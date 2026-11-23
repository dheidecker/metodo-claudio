"""Clasificar (Haiku, por lotes) y fusionar (Sonnet) las instrucciones; puntuar los grupos.

Puntuación = ocurrencias × proyectos distintos × días distintos. Umbral: 3 ocurrencias.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field

from lib import comun
from lib.propuestas.almacen import norm
from lib.recolector.fuentes import Muestra, es_acuse
from lib.recolector.modelo import Cache, ErrorModelo, Presupuesto, SinPresupuesto, llamar, sha256

ALCANCES = ("metodologia", "proyecto", "ninguno")
UMBRAL = 3
MAX_FRASES = 1500
MAX_TEXTO_MODELO = 600


@dataclass
class Grupo:
    resumen: str
    alcance: str
    muestras: list[Muestra]
    regla: str = ""
    documentada_sha: str = ""
    documentada_en: str = ""
    existente: str = ""
    trampa: dict | None = None
    frases: list[str] = field(default_factory=list)

    @property
    def ocurrencias(self) -> int:
        return len(self.muestras)

    @property
    def proyectos(self) -> list[str]:
        return sorted({m.proyecto for m in self.muestras})

    @property
    def dias(self) -> int:
        return len({m.dia for m in self.muestras})

    @property
    def puntuacion(self) -> int:
        return self.ocurrencias * len(self.proyectos) * self.dias

    def proyecto_dominante(self) -> tuple[str, str | None]:
        nombre = Counter(m.proyecto for m in self.muestras).most_common(1)[0][0]
        ruta = next((m.ruta for m in self.muestras if m.proyecto == nombre and m.ruta), None)
        return nombre, ruta


@dataclass
class Stats:
    muestras: int = 0
    acuses: int = 0
    cache: int = 0
    enviadas: int = 0
    sin_clasificar: int = 0
    con_instruccion: int = 0
    frases: int = 0


# ---------------------------------------------------------------- clasificar

def clasificar(muestras: list[Muestra], pres: Presupuesto, errores: list[str], stats: Stats,
               sin_modelo: bool = False) -> dict[str, dict]:
    """{sha256(texto redactado): {"c": canónica, "a": alcance}}. Sin modelo, la canónica es el
    propio texto y el alcance queda "?" (se decide al agrupar)."""
    res: dict[str, dict] = {}
    pend: dict[str, Muestra] = {}
    cache = None if sin_modelo else Cache("clasificar")
    stats.muestras = len(muestras)
    for m in muestras:
        k = sha256(m.texto)
        if k in res or k in pend:
            continue
        if es_acuse(m.texto):
            res[k] = {"c": "", "a": "ninguno"}
            stats.acuses += 1
        elif sin_modelo:
            res[k] = {"c": m.texto.strip()[:160], "a": "?"}
        else:
            v = cache.get(k)
            if v is not None:
                res[k] = v
                stats.cache += 1
            else:
                pend[k] = m
    claves = sorted(pend)
    lote = max(1, int(os.environ.get("MECANISMO_LOTE") or 300))
    for ini in range(0, len(claves), lote):
        trozo = claves[ini:ini + lote]
        datos = {"tarea": "clasificar",
                 "prompts": [{"i": j, "proyecto": pend[k].proyecto, "texto": pend[k].texto[:MAX_TEXTO_MODELO]}
                             for j, k in enumerate(trozo)]}
        try:
            out = llamar("clasificar", datos, pres)
        except SinPresupuesto as e:
            errores.append(f"clasificar: {e}")
            break
        except ErrorModelo as e:
            errores.append(f"clasificar lote {ini // lote + 1}: {e}")
            continue
        stats.enviadas += len(trozo)
        por_i = {it.get("i"): it for it in out.get("items", []) if isinstance(it, dict)}
        for j, k in enumerate(trozo):
            it = por_i.get(j)
            if not it or it.get("alcance") not in ALCANCES:
                continue  # sin respuesta: se reintenta en la próxima corrida
            c = comun.redactar(str(it.get("canonica") or "").strip())[:160]
            a = it["alcance"] if c else "ninguno"
            v = {"c": c if a != "ninguno" else "", "a": a}
            cache.put(k, v)
            res[k] = v
        cache.guardar()
    stats.sin_clasificar = sum(1 for m in muestras if sha256(m.texto) not in res)
    return res


# ---------------------------------------------------------------- fusionar

def _frases(muestras: list[Muestra], clasif: dict[str, dict]) -> list[dict]:
    frases: dict[str, dict] = {}
    for m in muestras:
        v = clasif.get(sha256(m.texto))
        if not v or v["a"] == "ninguno" or not v["c"]:
            continue
        f = frases.setdefault(norm(v["c"]), {"frase": v["c"], "alc": Counter(), "ms": []})
        f["alc"][v["a"]] += 1
        f["ms"].append(m)
    return sorted(frases.values(), key=lambda f: (-len(f["ms"]), f["frase"]))[:MAX_FRASES]


def _alcance(f: dict) -> str:
    a = f["alc"].most_common(1)[0][0]
    if a in ("metodologia", "proyecto"):
        return a
    return "metodologia" if len({m.proyecto for m in f["ms"]}) >= 2 else "proyecto"


def documentado(docs: dict) -> tuple[list[str], set[str]]:
    """(shas del git log, títulos citables) para validar lo que diga el modelo."""
    shas = [l.split()[0] for l in docs.get("git_log", []) if l.split()]
    titulos = set(docs.get("metodologia", []))
    for grupo in ("claude_md", "trampas"):
        for lista in (docs.get(grupo) or {}).values():
            titulos.update(lista)
    return shas, titulos


def _sha_valido(sha: str, shas: list[str]) -> str:
    sha = (sha or "").strip()
    if len(sha) < 7:
        return ""
    return next((s for s in shas if s.startswith(sha) or sha.startswith(s)), "")


def agrupar(muestras: list[Muestra], clasif: dict[str, dict], docs: dict, existentes: list[dict],
            pres: Presupuesto, errores: list[str], stats: Stats, sin_modelo: bool = False) -> list[Grupo]:
    lista = _frases(muestras, clasif)
    stats.frases = len(lista)
    stats.con_instruccion = sum(len(f["ms"]) for f in lista)
    out = {"grupos": []}
    if not sin_modelo and lista:
        datos = {"tarea": "fusionar",
                 "frases": [{"i": i, "frase": f["frase"], "alcance": _alcance(f), "n": len(f["ms"]),
                             "proyectos": len({m.proyecto for m in f["ms"]})} for i, f in enumerate(lista)],
                 "documentado": docs}
        # `existentes` no entra en la clave: así la misma entrada da la misma salida entre corridas.
        clave = sha256(json.dumps(datos, sort_keys=True, ensure_ascii=False))
        cache = Cache("fusionar")
        cacheado = cache.get(clave)
        if cacheado is not None:
            out = cacheado
        else:
            try:
                out = llamar("fusionar", dict(datos, existentes=existentes), pres)
                cache.put(clave, out)
                cache.guardar()
            except ErrorModelo as e:
                errores.append(f"fusionar: {e}")
    shas, titulos = documentado(docs)
    usados: set[int] = set()
    grupos: list[Grupo] = []
    for g in out.get("grupos", []) if isinstance(out, dict) else []:
        if not isinstance(g, dict):
            continue
        miembros = [i for i in g.get("miembros") or [] if isinstance(i, int) and 0 <= i < len(lista) and i not in usados]
        if not miembros:
            continue
        usados.update(miembros)
        alc = g.get("alcance") if g.get("alcance") in ("metodologia", "proyecto") else _alcance(lista[miembros[0]])
        doc_en = g.get("documentada_en") or ""
        grupos.append(Grupo(
            resumen=comun.redactar(str(g.get("resumen") or lista[miembros[0]]["frase"]).strip())[:160],
            alcance=alc,
            muestras=[m for i in miembros for m in lista[i]["ms"]],
            regla=comun.redactar(str(g.get("regla") or "").strip())[:1200],
            documentada_sha=_sha_valido(g.get("documentada_sha") or "", shas),
            documentada_en=doc_en if doc_en in titulos else "",
            existente=str(g.get("existente") or ""),
            trampa=g.get("trampa") if g.get("mecanizable") and isinstance(g.get("trampa"), dict) else None,
            frases=[lista[i]["frase"] for i in miembros]))
    for i, f in enumerate(lista):
        if i not in usados:
            grupos.append(Grupo(resumen=f["frase"], alcance=_alcance(f), muestras=f["ms"], frases=[f["frase"]]))
    grupos.sort(key=lambda g: (-g.puntuacion, g.resumen))
    return grupos


# ---------------------------------------------------------------- trampas escritas -> regex

def trampas_de_docs(items: list[dict], pres: Presupuesto, errores: list[str], lote: int = 80) -> list[tuple[dict, dict]]:
    """[(ítem documentado, trampa sugerida)] solo para las mecanizables."""
    out = []
    cache = Cache("trampas")
    for ini in range(0, len(items), lote):
        trozo = items[ini:ini + lote]
        datos = {"tarea": "trampas",
                 "documentadas": [{"i": j, "proyecto": it["proyecto"], "titulo": it["titulo"], "cuerpo": it["cuerpo"]}
                                  for j, it in enumerate(trozo)]}
        clave = sha256(json.dumps(datos, sort_keys=True, ensure_ascii=False))
        r = cache.get(clave)
        if r is None:
            try:
                r = llamar("trampas", datos, pres)
            except SinPresupuesto as e:
                errores.append(f"trampas: {e}")
                break
            except ErrorModelo as e:
                errores.append(f"trampas lote {ini // lote + 1}: {e}")
                continue
            cache.put(clave, r)
            cache.guardar()
        for t in r.get("trampas", []) if isinstance(r, dict) else []:
            if isinstance(t, dict) and isinstance(t.get("i"), int) and 0 <= t["i"] < len(trozo):
                out.append((trozo[t["i"]], t))
    return out
