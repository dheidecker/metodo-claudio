"""Agrega las decisiones en familias, reasonCodes, reglas y formas compuestas."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from lib import comun
from lib.permisos import familias, reglas as mreglas
from lib.permisos.fuente import NO_PERMISO, Decision

MAX_EJEMPLO = 160
_FILTROS = {"grep", "egrep", "head", "tail", "sort", "uniq", "tr", "cut", "sed", "awk", "wc", "jq", "tee", "cat",
            "column", "less", "fmt", "nl", "rev", "paste"}


def ejemplo(cmd: str | None) -> str:
    """Comando listo para mostrarse: redactado, en una línea y recortado."""
    t = comun.redactar((cmd or "").strip()).replace("\n", " ⏎ ")
    return t if len(t) <= MAX_EJEMPLO else t[:MAX_EJEMPLO - 1] + "…"


@dataclass
class Grupo:
    nombre: str
    irreversible: bool = False
    herramienta: str = "Bash"
    dialogos: int = 0
    aprobados: int = 0
    rechazados: int = 0
    por_regla: int = 0            # reasonCode rule:* : el comando entero casó una regla ask
    simples_aprobados: int = 0    # aprobados que no eran compuestos ni too-complex (los que un allow quitaría)
    variantes: Counter = field(default_factory=Counter)
    comandos: Counter = field(default_factory=Counter)   # comando exacto de cada aprobado simple (en memoria;
    #                                                      solo se escribe si pasa a regla exacta y no lleva secretos)
    proyectos: set = field(default_factory=set)
    dias: set = field(default_factory=set)
    ejemplos: list = field(default_factory=list)

    def anotar(self, d: Decision, cmd_ejemplo: str | None) -> None:
        self.dialogos += 1
        if d.es_rechazo:
            self.rechazados += 1
        else:
            self.aprobados += 1
        if (d.reason_code or "").startswith("rule:"):
            self.por_regla += 1
        self.proyectos.add(d.proyecto)
        if d.dia:
            self.dias.add(d.dia)
        if cmd_ejemplo is not None and len(self.ejemplos) < 3:
            ej = ejemplo(cmd_ejemplo)
            if ej and ej not in self.ejemplos:
                self.ejemplos.append(ej)

    def evidencia(self) -> dict:
        p, dd = sorted(self.proyectos), len(self.dias)
        return {"ocurrencias": self.dialogos, "proyectos": p, "dias": dd,
                "puntuacion": self.dialogos * max(len(p), 1) * max(dd, 1), "ejemplos": self.ejemplos[:3]}


def forma(cmd: str) -> str:
    """Firma de un compuesto: sus comandos en orden, sin triviales (cd, echo...), sin filtros de
    texto (grep, tail, jq...) y sin repeticiones seguidas. `cd x && a | grep y && b` -> `a + b`."""
    nombres: list[str] = []
    for pieza in familias.partir(cmd):
        n = familias.nombre_generico(pieza)
        if not n or n in _FILTROS:
            continue
        if not nombres or nombres[-1] != n:
            nombres.append(n)
    return " + ".join(nombres) or "(vacío)"


@dataclass
class Analisis:
    dias: int | None
    subagentes: bool
    decisiones: int = 0
    dialogos: int = 0
    rechazos: int = 0
    familias: dict = field(default_factory=dict)       # nombre -> Grupo
    codigos: Counter = field(default_factory=Counter)  # reasonCode -> diálogos
    codigos_rech: Counter = field(default_factory=Counter)
    no_permiso: Counter = field(default_factory=Counter)
    complejos: dict = field(default_factory=dict)      # forma -> Grupo (solo too-complex)
    reglas: dict = field(default_factory=dict)         # {"ask": {regla: n}, "allow": {...}}
    decisiones_por_familia: Counter = field(default_factory=Counter)


def analizar(decisiones: Iterable[Decision], dias: int | None, subagentes: bool,
             reglas_cfg: dict[str, list[str]] | None = None) -> Analisis:
    reglas_cfg = reglas_cfg if reglas_cfg is not None else mreglas.leer_reglas()
    a = Analisis(dias=dias, subagentes=subagentes)
    a.reglas = {k: {r: 0 for r in reglas_cfg.get(k, [])} for k in ("ask", "allow")}
    for d in decisiones:
        a.decisiones += 1
        if d.herramienta in NO_PERMISO:
            if d.es_dialogo:
                a.no_permiso[d.herramienta] += 1
            continue
        if d.herramienta == "Bash":
            c = familias.clasificar(d.comando or "")
            nombre, irrev = c.familia, c.irreversible
        else:
            c, nombre, irrev = None, d.herramienta, False
        a.decisiones_por_familia[nombre] += 1
        if not d.es_dialogo:
            continue
        a.dialogos += 1
        a.rechazos += d.es_rechazo
        a.codigos[d.codigo] += 1
        if d.es_rechazo:
            a.codigos_rech[d.codigo] += 1
        g = a.familias.setdefault(nombre, Grupo(nombre, irreversible=irrev, herramienta=d.herramienta))
        g.anotar(d, d.comando)
        too_complex = "too-complex" in (d.reason_code or "")
        if c is not None:
            if c.variante:
                g.variantes[c.variante] += 1
            if not d.es_rechazo and not c.compuesto and not too_complex:
                g.simples_aprobados += 1
                g.comandos[(d.comando or "").strip()] += 1
            if too_complex:
                f = forma(d.comando or "")
                gc = a.complejos.setdefault(f, Grupo(f))
                gc.irreversible = gc.irreversible or irrev
                gc.anotar(d, d.comando)
        elif not d.es_rechazo:
            g.simples_aprobados += 1
        for lista in ("ask", "allow"):
            for r in a.reglas[lista]:
                if mreglas.casa(r, d.herramienta, d.comando):
                    a.reglas[lista][r] += 1
    return a


def a_dict(a: Analisis) -> dict:
    fam = sorted(a.familias.values(), key=lambda g: (-g.dialogos, g.nombre))
    return {
        "dias": a.dias, "subagentes": a.subagentes,
        "decisiones": a.decisiones, "dialogos": a.dialogos, "rechazos": a.rechazos,
        "familias": [{"familia": g.nombre, "dialogos": g.dialogos, "aprobados": g.aprobados,
                      "rechazados": g.rechazados, "por_regla_ask": g.por_regla, "irreversible": g.irreversible,
                      "variantes": dict(g.variantes), "proyectos": sorted(g.proyectos), "ejemplos": g.ejemplos}
                     for g in fam],
        "reason_codes": dict(a.codigos.most_common()),
        "reason_codes_rechazos": dict(a.codigos_rech.most_common()),
        "reglas": a.reglas,
        "no_permiso": dict(a.no_permiso),
        "compuestos_too_complex": [{"forma": g.nombre, "dialogos": g.dialogos, "rechazados": g.rechazados,
                                    "irreversible": g.irreversible}
                                   for g in sorted(a.complejos.values(), key=lambda g: -g.dialogos)],
    }
