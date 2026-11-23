"""`mecanismo juez [--ultimas N] [--negadas] [--json]`: las decisiones del juez de permisos."""
from __future__ import annotations

import argparse
import json

from lib.juez import auditoria


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="mecanismo juez", description="Decisiones del juez de permisos.")
    ap.add_argument("--ultimas", type=int, default=20, metavar="N", help="cuántas mostrar (20)")
    ap.add_argument("--negadas", action="store_true", help="solo las negadas")
    ap.add_argument("--json", action="store_true", help="una línea JSON por decisión")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    filas = [e for e in auditoria.leer() if not a.negadas or e.get("decision") == "negar"]
    filas = filas[-a.ultimas:] if a.ultimas > 0 else filas
    if not filas:
        print("juez: sin decisiones" + (" negadas" if a.negadas else "") + f" en {auditoria.dir_auditoria()}")
        return 0
    for e in filas:
        if a.json:
            print(json.dumps(e, ensure_ascii=False))
            continue
        dec = "PERMITE" if e.get("decision") == "permitir" else "NIEGA  "
        cmd = " ".join(str(e.get("comando", "")).split())
        print(f"{str(e.get('ts', ''))[:19]}  {dec} {e.get('via', '?'):<6} {e.get('riesgo', '?'):<5} "
              f"{e.get('duracion_ms', '?'):>6}ms  {e.get('familia', '')}  [{str(e.get('proyecto', '')).rsplit('/', 1)[-1]}]")
        print(f"    $ {cmd[:120]}{'…' if len(cmd) > 120 else ''}")
        print(f"    {e.get('motivo', '')}")
    return 0
