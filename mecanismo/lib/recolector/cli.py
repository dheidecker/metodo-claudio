"""mecanismo recolectar --fuente history|transcripts|bitacora|gh|claudemd|todas --dias N [--sin-modelo] [--json]

Lee lo que se repite (prompts, comentarios de PR, bitácora, trampas escritas) y escribe
propuestas pendientes. Nada se activa: eso es `mecanismo aprobar ID` (con TTY).
Exit: 0 ok · 1 alguna llamada al modelo falló (las propuestas escritas quedan) · 2 uso · 4 sin PyYAML.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib import comun

FUENTES = ("history", "transcripts", "bitacora", "gh", "claudemd", "todas")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mecanismo recolectar", description=__doc__.split("\n\n")[1])
    p.add_argument("--fuente", choices=FUENTES, default="todas")
    p.add_argument("--dias", type=int, default=60)
    p.add_argument("--sin-modelo", action="store_true", help="agrupa por texto idéntico, sin llamar a claude")
    p.add_argument("--json", action="store_true")
    p.add_argument("--proyecto", action="append", default=[], help="carpeta de proyecto extra (repetible)")
    p.add_argument("--top", type=int, default=5, help="cuántas propuestas mostrar")
    return p


def _docs(rutas: dict[str, Path], items_doc: list[dict], metodo: Path) -> dict:
    from lib.recolector import fuentes  # noqa: PLC0415
    trampas: dict[str, list[str]] = {}
    for it in items_doc:
        lista = trampas.setdefault(it["proyecto"], [])
        if len(lista) < 40:
            lista.append(it["titulo"])
    return {"metodologia": fuentes.encabezados(metodo / "METODOLOGIA.md", (1, 2, 3), 120),
            "claude_md": {n: h for n, r in sorted(rutas.items()) if (h := fuentes.encabezados(r / "CLAUDE.md", (2, 3), 60))},
            "trampas": trampas,
            "git_log": fuentes.git_log(metodo, 60)}


def main(argv: list[str]) -> int:
    argv = list(argv)
    if argv[:1] == ["recolectar"]:
        argv = argv[1:]
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    try:
        import yaml  # noqa: F401, PLC0415
    except ImportError:
        print("mecanismo recolectar: instala python3-yaml", file=sys.stderr)
        return 4

    from lib.propuestas import almacen  # noqa: PLC0415
    from lib.recolector import agrupar, bitacora, fuentes, proponer  # noqa: PLC0415
    from lib.recolector.modelo import Presupuesto  # noqa: PLC0415

    quiero = set(FUENTES[:-1]) if args.fuente == "todas" else {args.fuente}
    metodo = comun.raiz_mecanismo().parent
    conocidos = almacen.proyectos_conocidos(args.proyecto, con_cwd=False)
    errores: list[str] = []
    descartes: list[str] = []
    pres = Presupuesto()
    stats = agrupar.Stats()

    muestras = []
    if "history" in quiero:
        muestras += fuentes.de_history(args.dias)
    if "transcripts" in quiero:
        muestras += fuentes.de_transcripts(args.dias)
    if "gh" in quiero:
        muestras += fuentes.de_gh([str(p) for p in conocidos], args.dias)
    muestras = fuentes.sin_duplicados(muestras)

    rutas = {p.name: p for p in conocidos}
    for m in muestras:
        if m.ruta and Path(m.ruta).is_dir():
            rutas.setdefault(m.proyecto, Path(m.ruta))
    items_doc = fuentes.trampas_documentadas(sorted(set(rutas.values())))

    nuevas: list[tuple[dict, Path]] = []
    grupos = []
    if muestras:
        clasif = agrupar.clasificar(muestras, pres, errores, stats, args.sin_modelo)
        con_algo = {m.proyecto for m in muestras if clasif.get(agrupar.sha256(m.texto), {}).get("a") not in (None, "ninguno")}
        docs = _docs({n: r for n, r in rutas.items() if n in con_algo},
                     [it for it in items_doc if it["proyecto"] in con_algo], metodo)
        previas = almacen.en_carpeta(almacen.dir_global())
        # Ids estables (CONTRATO §11): la fusión ve las propuestas vigentes, también las ya decididas,
        # para devolver en `existente` la que es el mismo grupo aunque cambie la redacción.
        existentes = [{"id": pid, "resumen": p.get("resumen", ""), "estado": p.get("estado", "")}
                      for pid, p in sorted(previas.items()) if p.get("origen") == "recolector"]
        grupos = agrupar.agrupar(muestras, clasif, docs, existentes, pres, errores, stats, args.sin_modelo)
        tomados: set[str] = set()
        for g in grupos:
            r = proponer.de_grupo(g, metodo, previas, tomados)
            if r:
                nuevas.append(r)
    if "claudemd" in quiero and items_doc and not args.sin_modelo:
        for item, sugerida in agrupar.trampas_de_docs(items_doc, pres, errores):
            prop, carpeta, motivo = proponer.de_trampa_documentada(item, sugerida)
            if prop:
                nuevas.append((prop, carpeta))
            else:
                descartes.append(motivo)
    if "bitacora" in quiero:
        nuevas += bitacora.propuestas(fuentes.de_bitacora(args.dias), sorted(set(rutas.values())), args.dias)

    escritas = []
    for prop, carpeta in nuevas:
        ruta, accion = almacen.fusionar(prop, carpeta)
        escritas.append({"ruta": str(ruta), "accion": accion, **almacen.leer(ruta)})
    escritas.sort(key=lambda p: (-p["evidencia"].get("puntuacion", 0), p["id"]))

    resumen = {"muestras": stats.muestras, "acuses": stats.acuses, "cache": stats.cache, "enviadas": stats.enviadas,
               "sin_clasificar": stats.sin_clasificar, "con_instruccion": stats.con_instruccion,
               "frases": stats.frases, "grupos_umbral": sum(1 for g in grupos if g.ocurrencias >= agrupar.UMBRAL),
               "llamadas": pres.llamadas, "usd": round(pres.gastado, 4), "errores": errores,
               "descartadas": descartes, "propuestas": escritas}
    if args.json:
        print(json.dumps(resumen, ensure_ascii=False, indent=2, default=str))
    else:
        _imprimir(resumen, args.top)
    return 1 if errores else 0


def _imprimir(r: dict, top: int) -> None:
    print(f"recolectar: {r['muestras']} muestras · {r['con_instruccion']} con instrucción en {r['frases']} frases · "
          f"{r['grupos_umbral']} grupos con ≥3 · {r['llamadas']} llamadas, {r['usd']:.2f} USD · "
          f"caché {r['cache']} · sin clasificar {r['sin_clasificar']}")
    for e in r["errores"]:
        print(f"  error: {e}", file=sys.stderr)
    for d in r["descartadas"]:
        print(f"  descartada: {d}")
    props = r["propuestas"]
    print(f"Propuestas (top {min(top, len(props))} de {len(props)}):")
    for n, p in enumerate(props[:top], 1):
        ev = p["evidencia"]
        print(f"  {n}. {p['id']}  [{p['tipo']} → {p['destino']}]  {p['estado']}  ({p['accion']})")
        print(f"     {p['resumen']}")
        print(f"     {ev.get('ocurrencias', 0)} veces · {len(ev.get('proyectos', []))} proyectos · "
              f"{ev.get('dias', 0)} días = {ev.get('puntuacion', 0)}")
        if p.get("nota"):
            print(f"     nota: {p['nota']}")
