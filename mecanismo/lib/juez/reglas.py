"""Qué juzga el juez y las reglas deterministas de `rm -rf` (antes del modelo).

La clasificación reutiliza lib.permisos.familias (partir, normalizar, familias_de...). Lo único
propio es conservar el texto crudo de cada subcomando: `familias.partir` enmascara las comillas
(`"…"`), y para resolver los objetivos de un `rm` hacen falta las rutas tal cual.
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from lib.permisos import familias as F

FAMILIAS_POR_DEFECTO = ("gcloud run deploy", "gcloud builds submit", "rm -rf")
EFIMEROS = frozenset({"build", "dist", "node_modules", "__pycache__", ".cache", "tmp", ".pytest_cache",
                      "coverage", "target", ".next"})

PERMITE, MODELO, NIEGA = "permitir", "modelo", "negar"
_GRAVEDAD = {PERMITE: 0, MODELO: 1, NIEGA: 2}

_RX_CITA = re.compile(r"\\.|'[^']*'|\"(?:\\.|[^\"\\])*\"", re.S)
_RX_MARCA = re.compile("\x00(\\d+)\x00")
_RX_VARIABLE = re.compile(r"\$(?:[A-Za-z_{(]|[0-9@*#?!$-])|`")
_RX_GLOB = re.compile(r"[*?\[]")
_RX_REDIRECCION = re.compile(r"^\d*(?:>>?|<|&>|>&)")


@dataclass
class Pieza:
    enmascarada: str     # comillas como `"…"` (lo que espera familias)
    cruda: str           # el texto original del subcomando
    familias: list[str] = field(default_factory=list)


@dataclass
class Veredicto:
    decision: str        # permitir | modelo | negar
    motivo: str


def piezas(cmd: str) -> list[Pieza]:
    """Subcomandos de `cmd` (mismo corte que familias.partir) con su texto crudo y sus familias."""
    s = F.quitar_heredocs(cmd or "")
    citas: list[str] = []

    def marcar(m: re.Match) -> str:
        if m.group(0).startswith("\\"):
            return m.group(0)
        citas.append(m.group(0))
        return f"\x00{len(citas) - 1}\x00"

    marcado = _RX_CITA.sub(marcar, s)
    out = []
    for p in F.partir(marcado):
        cruda = _RX_MARCA.sub(lambda m: citas[int(m.group(1))], p)
        enm = _RX_MARCA.sub(lambda m: citas[int(m.group(1))][0] + "…" + citas[int(m.group(1))][0], p)
        out.append(Pieza(enm, cruda, F.familias_de(enm)))
    return out


def familias_presentes(cmd: str, ps: list[Pieza] | None = None) -> list[str]:
    """Todas las familias especiales del comando (no solo la más grave), en orden de gravedad."""
    ps = piezas(cmd) if ps is None else ps
    hallas = []
    for p in ps:
        hallas += [f for f in p.familias if f not in hallas]
    if "DROP/TRUNCATE" not in hallas and (F._RX_SQL.search(F.quitar_heredocs(cmd or "")) or F._RX_SQL.search(cmd or "")):
        hallas.append("DROP/TRUNCATE")
    return sorted(hallas, key=F._ORDEN.__getitem__)


# ------------------------------------------------------------------------------- rm -rf

def _dentro(a: str, b: str) -> bool:
    """a está estrictamente dentro de b."""
    return a != b and (a.startswith(b.rstrip("/") + "/"))


def _expandir(tok: str, home: str) -> str | None:
    """`~` y `$HOME`/`${HOME}` expandidos; None si queda alguna variable o sustitución sin expandir."""
    if tok == "~" or tok.startswith("~/"):
        tok = home + tok[1:]
    elif tok.startswith("~"):
        return None                                   # ~usuario
    tok = re.sub(r"\$\{HOME\}|\$HOME(?![A-Za-z0-9_])", lambda _: home, tok)
    return None if _RX_VARIABLE.search(tok) else tok


def _objetivos(cruda: str) -> list[str] | None:
    """Operandos de un `rm` (sin opciones ni redirecciones). None si no se puede leer."""
    norm = F.normalizar(cruda)
    try:
        t = shlex.split(norm, posix=True)
    except ValueError:
        return None
    if not t or t[0] != "rm":
        return None
    out, opciones, saltar = [], True, False
    for x in t[1:]:
        if saltar:
            saltar = False
            continue
        if opciones and x == "--":
            opciones = False
            continue
        if opciones and x.startswith("-") and x != "-":
            continue
        m = _RX_REDIRECCION.match(x)
        if m:
            saltar = m.end() == len(x)                 # `> archivo`: el siguiente es el destino
            continue
        out.append(x.rstrip(")`") or x)
    return out


class _Ctx:
    def __init__(self, raiz: str):
        self.home = os.path.normpath(str(Path.home()))
        self.claudes = {os.path.normpath(os.path.join(self.home, ".claude"))}
        try:
            from lib import comun
            self.claudes.add(os.path.normpath(str(comun.claude_home())))
        except Exception:
            pass
        self.raices = {os.path.normpath(raiz), os.path.realpath(raiz)}
        self.tmps = {"/tmp", os.path.realpath("/tmp")}


def _evaluar(p: str, ctx: _Ctx, patron: str | None) -> Veredicto:
    """Una ruta absoluta normalizada. `patron`: el componente con glob cuyo contenido se borra en p."""
    if p == "/":
        return Veredicto(NIEGA, "glob en la raíz (/*)" if patron else "borra /")
    if p == ctx.home:
        return Veredicto(NIEGA, "glob en $HOME (~/*)" if patron else "borra $HOME")
    for c in ctx.claudes:
        if p == c or _dentro(p, c):
            return Veredicto(NIEGA, "toca ~/.claude")
    if ".git" in Path(p).parts:
        return Veredicto(NIEGA, "toca .git")
    for raiz in ctx.raices:
        if _dentro(raiz, p):
            return Veredicto(NIEGA, f"borra un ancestro del proyecto: {p}")
        if p == raiz:
            if patron is None:
                return Veredicto(NIEGA, "borra la raíz del proyecto")
            if re.fullmatch(r"[*.]+", patron):
                return Veredicto(NIEGA, f"vacía la raíz del proyecto ({patron})")
            return Veredicto(MODELO, f"glob {patron} en la raíz del proyecto")
    for raiz in ctx.raices:
        if _dentro(p, raiz):
            rel = Path(p).relative_to(raiz).parts
            if any(x in EFIMEROS for x in rel):
                return Veredicto(PERMITE, "efímero dentro del proyecto")
            return Veredicto(MODELO, f"dentro del proyecto, no efímero: {'/'.join(rel)}")
    if any(_dentro(p, t) for t in ctx.tmps):
        return Veredicto(PERMITE, "bajo /tmp")
    return Veredicto(NIEGA, f"fuera del proyecto: {p}")


def _evaluar_objetivo(tok: str, cwd: str | None, ctx: _Ctx) -> Veredicto:
    exp = _expandir(tok, ctx.home)
    if exp is None:
        return Veredicto(NIEGA, f"variable sin expandir en {tok}")
    if not os.path.isabs(exp) and cwd is None:
        return Veredicto(MODELO, f"cwd desconocido tras un cd: {tok}")
    ruta = os.path.join(cwd or "/", exp)
    patron = None
    if _RX_GLOB.search(ruta):
        partes = Path(ruta).parts
        i = next(k for k, x in enumerate(partes) if _RX_GLOB.search(x))
        patron = partes[i]
        ruta = str(Path(*partes[:i])) if i else "/"
    lex = os.path.normpath(ruta)
    peor = Veredicto(PERMITE, "")
    for p in (lex, os.path.realpath(lex)):
        v = _evaluar(p, ctx, patron)
        if _GRAVEDAD[v.decision] > _GRAVEDAD[peor.decision]:
            peor = v
        elif not peor.motivo:
            peor.motivo = v.motivo
    return peor


def reglas_rm(ps: list[Pieza], cwd: str, raiz: str) -> Veredicto:
    """NIEGA si algún objetivo de algún `rm -rf` es peligroso; PERMITE si todo el comando son `rm -rf`
    de efímeros del proyecto o de /tmp (más `cd` y triviales); si no, MODELO."""
    ctx = _Ctx(raiz)
    actual: str | None = os.path.normpath(cwd)
    resultado = Veredicto(PERMITE, "")
    motivos: list[str] = []
    hubo_rm = False

    def peor(v: Veredicto):
        nonlocal resultado
        if _GRAVEDAD[v.decision] > _GRAVEDAD[resultado.decision]:
            resultado = v

    for p in ps:
        norm = F.normalizar(p.enmascarada)
        cabeza = norm.split()[0] if norm.split() else ""
        if cabeza in ("cd", "pushd"):
            try:
                t = shlex.split(F.normalizar(p.cruda), posix=True)
            except ValueError:
                t = []
            destino = t[1] if len(t) > 1 else "~"
            exp = _expandir(destino, ctx.home) if destino != "-" else None
            if exp is None:
                actual = None
            elif os.path.isabs(exp):
                actual = os.path.normpath(exp)
            elif actual is not None:
                actual = os.path.normpath(os.path.join(actual, exp))
            continue
        if "rm -rf" in p.familias:
            objetivos = _objetivos(p.cruda)
            if not objetivos:
                peor(Veredicto(MODELO, "rm -rf sin objetivos legibles"))
                continue
            hubo_rm = True
            for o in objetivos:
                v = _evaluar_objetivo(o, actual, ctx)
                if v.decision == NIEGA:
                    return v
                peor(v)
                if v.motivo and v.motivo not in motivos:
                    motivos.append(v.motivo)
            continue
        if F.nombre_generico(p.enmascarada) is not None or re.search(r"\$\(|`", p.enmascarada):
            peor(Veredicto(MODELO, f"el comando incluye además: {norm[:60]}"))
    if not hubo_rm and resultado.decision == PERMITE:
        return Veredicto(MODELO, "sin rm -rf que evaluar")
    if resultado.decision == PERMITE:
        return Veredicto(PERMITE, "; ".join(motivos) or "efímeros")
    return resultado
