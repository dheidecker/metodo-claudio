"""`mecanismo trampas` (CONTRATO.md §2–3).

  --probar [DIR]          corre prueba.dispara / prueba.no_dispara de cada trampa. DIR es un proyecto
                          (usa .claude/trampas) o una carpeta de *.yml; por defecto el proyecto actual.
  --archivo F             aciertos de F, `archivo:línea:id`. Mira el archivo entero salvo --cambiadas.
  --arbol [--sid S]       aciertos sobre comun.archivos_cambiados (desde la marca de la sesión S, si se da),
                          solo en las líneas cambiadas, como el hook --stop.
  --trampas DIR           de dónde salen las trampas (por defecto, el proyecto de cwd).

Exit: 0 ok / sin aciertos · 1 una prueba falla o hay aciertos · 2 uso · 4 falta PyYAML.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lib import comun
from lib.trampas import motor


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mecanismo trampas", description="Trampas como datos (CONTRATO §3).")
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--probar", nargs="?", const="", metavar="DIR")
    m.add_argument("--archivo", metavar="F")
    m.add_argument("--arbol", action="store_true")
    p.add_argument("--sid", metavar="S")
    p.add_argument("--trampas", metavar="DIR")
    p.add_argument("--cambiadas", action="store_true", help="con --archivo: solo líneas cambiadas respecto a HEAD")
    return p


def _probar(d: Path) -> int:
    errores: list[str] = []
    trampas = motor.cargar_desde(d, errores)
    fallos = 0
    for e in errores:
        print(f"FALLA {e}")
        fallos += 1
    vistos: set[str] = set()
    for t in trampas:
        i = t.get("id", "?") if isinstance(t, dict) else "?"
        err = motor.probar_trampa(t)
        if i in vistos:
            err.append("`id` repetido")
        vistos.add(i)
        if err:
            fallos += 1
            print(f"FALLA {i}: " + "; ".join(err))
        else:
            print(f"ok    {i}")
    print(f"{len(trampas)} trampas, {fallos} fallan ({d})")
    return 1 if fallos else 0


def _imprimir(hits) -> int:
    for a, n, i in hits:
        print(f"{a}:{n}:{i}")
    return 1 if hits else 0


def main(argv: list[str]) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    if args.sid and not args.arbol:
        print("--sid solo va con --arbol", file=sys.stderr)
        return 2
    raiz = comun.raiz_proyecto(os.getcwd())
    try:
        if args.probar is not None:
            return _probar(Path(args.probar or args.trampas or raiz))
        trampas = [t for t in motor.cargar_desde(Path(args.trampas or raiz)) if not motor.validar(t)]
        if args.archivo is not None:
            f = Path(args.archivo)
            texto = motor.leer_texto(f)
            if texto is None:
                print(f"no se puede leer {f}", file=sys.stderr)
                return 2
            lineas = comun.lineas_cambiadas(f) if args.cambiadas else None
            hits = motor.aciertos(trampas, motor.relativa(f, raiz), texto, lineas)
            return _imprimir([(args.archivo, n, i) for _, n, i in hits])
        desde = comun.desde_sesion(args.sid) if args.sid else None
        hits = []
        for f in comun.archivos_cambiados(raiz, desde):
            rel = motor.relativa(f, raiz)
            if not any(motor.aplica(t, rel) for t in trampas):
                continue
            texto = motor.leer_texto(f)
            if texto is not None:
                hits += motor.aciertos(trampas, rel, texto, comun.lineas_cambiadas(f))
        return _imprimir(hits)
    except comun.SinPyYAML:
        print("mecanismo trampas: instala python3-yaml (PyYAML)", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
