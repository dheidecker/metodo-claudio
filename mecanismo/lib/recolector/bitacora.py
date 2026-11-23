"""Propuestas que salen de la bitácora de disparos: `subir-a-bloqueo` y `podar`.

Aproximación de «corregido» (la bitácora no dice si Claude arregló el aviso):
- Las líneas `hook=trampas|trampas-stop` del mismo (proyecto, archivo) y el mismo segundo son
  UNA pasada del hook (el hook escribe una línea por trampa acertada, o `silencio <archivo>`).
- Un `AVISO <id> <archivo>` cuenta como corregido si hay una pasada POSTERIOR sobre el mismo
  archivo en la que `<id>` ya no aparece (un `silencio` u otros avisos). Si el archivo no se
  vuelve a tocar, no consta como corregido.
- subir-a-bloqueo: ≥ UMBRAL_AVISOS avisos de esa trampa en la ventana y todos corregidos, y la
  trampa sigue en `aviso` en `.claude/trampas/`.
- podar: una trampa activa con 0 AVISO/BLOQUEO en la ventana y cuyo .yml tiene más de N días
  (si no, aún no tuvo tiempo de disparar).
"""
from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from lib import comun
from lib.propuestas import almacen
from lib.propuestas.almacen import id_de
from lib.recolector.fuentes import LineaBitacora

UMBRAL_AVISOS = 5
HOOKS = ("trampas", "trampas-stop")


def trampas_activas(rutas: list[Path]) -> list[tuple[Path, Path, dict]]:
    """[(proyecto, archivo .yml, trampa)] de <proyecto>/.claude/trampas/*.yml (sin propuestas/)."""
    out = []
    for ruta in rutas:
        for f in sorted((Path(ruta) / ".claude" / "trampas").glob("*.yml")):
            try:
                d = comun.leer_yaml(f)
            except comun.SinPyYAML:
                raise
            except Exception:  # noqa: BLE001
                continue
            for t in d if isinstance(d, list) else [d]:
                if isinstance(t, dict) and t.get("id"):
                    out.append((Path(ruta), f, t))
    return out


def _pasadas(lineas: list[LineaBitacora]) -> dict[tuple[str, str], list[tuple[str, set[str]]]]:
    """{(proyecto, archivo): [(fecha, {ids que avisaron})...]} en orden."""
    crudo: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(dict)
    for l in lineas:
        if l.hook not in HOOKS or not l.detalle:
            continue
        archivo = l.detalle[-1]
        ids = crudo[(l.proyecto, archivo)].setdefault(l.fecha, set())
        if l.categoria in ("AVISO", "BLOQUEO") and len(l.detalle) >= 2:
            ids.add(l.detalle[0])
    return {k: sorted(v.items()) for k, v in crudo.items()}


def disparos(lineas: list[LineaBitacora]) -> dict[tuple[str, str], dict]:
    """{(proyecto, id): {avisos, corregidos, dias:set, archivos:set}} solo de AVISO."""
    st: dict[tuple[str, str], dict] = defaultdict(lambda: {"avisos": 0, "corregidos": 0, "bloqueos": 0,
                                                           "dias": set(), "archivos": set()})
    avisos_por_pasada = defaultdict(set)
    for l in lineas:
        if l.hook in HOOKS and l.categoria in ("AVISO", "BLOQUEO") and len(l.detalle) >= 2:
            avisos_por_pasada[(l.proyecto, l.detalle[-1], l.fecha)].add((l.categoria, l.detalle[0]))
    for (proy, archivo), pasadas in _pasadas(lineas).items():
        for k, (fecha, _ids) in enumerate(pasadas):
            for cat, tid in avisos_por_pasada.get((proy, archivo, fecha), ()):
                s = st[(proy, tid)]
                if cat == "BLOQUEO":
                    s["bloqueos"] += 1
                    continue
                s["avisos"] += 1
                s["dias"].add(fecha[:10])
                s["archivos"].add(archivo)
                if any(tid not in ids for _f, ids in pasadas[k + 1:]):
                    s["corregidos"] += 1
    return st


def propuestas(lineas: list[LineaBitacora], rutas: list[Path], dias: int) -> list[tuple[dict, Path]]:
    st = disparos(lineas)
    activas = trampas_activas(rutas)
    out = []
    corte = time.time() - dias * 86400
    for ruta, archivo, t in activas:
        tid, proy = t["id"], ruta.name
        s = st.get((proy, tid))
        if s and t.get("nivel", "aviso") == "aviso" and s["avisos"] >= UMBRAL_AVISOS and s["corregidos"] == s["avisos"]:
            n, nd = s["avisos"], len(s["dias"])
            out.append(({
                "id": id_de(f"subir-a-bloqueo:{ruta}:{tid}", base=f"bloqueo-{tid}"),
                "estado": "pendiente", "origen": "bitacora", "tipo": "subir-a-bloqueo", "destino": "trampa",
                "resumen": f"Subir «{tid}» de aviso a bloqueo: {n} avisos en {nd} días, todos corregidos",
                "evidencia": {"ocurrencias": n, "proyectos": [proy], "dias": nd, "puntuacion": n * nd,
                              "ejemplos": sorted(s["archivos"])[:3]},
                "contenido": {"archivo": str(archivo), "id": tid, "disparos": n, "dias": nd},
                "nota": "corregido = una pasada posterior del hook sobre el mismo archivo ya no trae el aviso",
            }, almacen.dir_proyecto(ruta)))
        total = (s["avisos"] + s["bloqueos"]) if s else 0
        try:
            vieja = archivo.stat().st_mtime < corte
        except OSError:
            vieja = False
        if total == 0 and vieja:
            out.append(({
                "id": id_de(f"podar:{ruta}:{tid}", base=f"podar-{tid}"),
                "estado": "pendiente", "origen": "bitacora", "tipo": "podar", "destino": "trampa",
                "resumen": f"Podar «{tid}»: 0 disparos en {dias} días",
                "evidencia": {"ocurrencias": 0, "proyectos": [proy], "dias": dias, "puntuacion": 0, "ejemplos": []},
                "contenido": {"archivo": str(archivo), "id": tid, "disparos": 0, "dias": dias},
            }, almacen.dir_proyecto(ruta)))
    return out
