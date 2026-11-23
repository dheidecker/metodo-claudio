"""mecanismo permisos [--dias N] [--json] [--proponer] [--min N] [--subagentes]

Cuenta los diálogos de permiso de los transcripts por familia de comando, por reasonCode y por
regla de ~/.claude/settings.json (solo lectura). Con --proponer escribe propuestas (CONTRATO §4)
en comun.estado_dir()/propuestas/. Nunca toca settings.json.
"""
from __future__ import annotations

import argparse
import json
import sys

from lib import comun
from lib.permisos import analisis, propuestas, reglas as mreglas
from lib.permisos.fuente import iterar_decisiones

DEFINICION = ("diálogo = permissionDecision con source user_temporary o decision != accept "
              "(AskUserQuestion y ExitPlanMode aparte: son preguntas, no permisos); "
              "rechazo = decision != accept; familia = el subcomando más grave del compuesto")

MAX_FILAS = 25


def _args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="mecanismo permisos", description=__doc__.split("\n\n")[1])
    p.add_argument("--dias", type=int, default=30, help="ventana por mtime del transcript (30)")
    p.add_argument("--json", action="store_true", help="salida JSON")
    p.add_argument("--proponer", action="store_true", help="escribe propuestas en propuestas/")
    p.add_argument("--min", type=int, default=propuestas.MINIMO, help="aprobaciones o repeticiones para proponer (3)")
    p.add_argument("--subagentes", action="store_true", help="incluye los transcripts de subagentes")
    return p.parse_args(argv)


def _texto(a: analisis.Analisis, escritas: list[tuple[str, str]] | None, props: list[dict] | None) -> str:
    L = []
    alcance = "sesión principal y subagentes" if a.subagentes else "solo sesión principal"
    L.append(f"mecanismo permisos — últimos {a.dias} días ({alcance}): "
             f"{a.decisiones} decisiones, {a.dialogos} diálogos, {a.rechazos} rechazos")
    L.append(f"Definición: {DEFINICION}.")
    L.append("")
    L.append(f"{'Familia':<34}{'Diálogos':>9}{'Aprob.':>8}{'Rech.':>7}{'Por ask':>9}  Irrev.")
    fams = sorted(a.familias.values(), key=lambda g: (-g.dialogos, g.nombre))
    for g in fams[:MAX_FILAS]:
        L.append(f"{g.nombre[:33]:<34}{g.dialogos:>9}{g.aprobados:>8}{g.rechazados:>7}{g.por_regla:>9}  "
                 f"{'sí' if g.irreversible else ''}")
    if len(fams) > MAX_FILAS:
        resto = fams[MAX_FILAS:]
        L.append(f"… y {len(resto)} familias más con {sum(g.dialogos for g in resto)} diálogos (--json las lista)")
    push = a.familias.get("git push")
    if push and push.variantes:
        L.append("git push por destino: " + ", ".join(f"{k} {v}" for k, v in push.variantes.most_common()))
    if a.no_permiso:
        L.append("No cuentan (preguntas a la persona): " + ", ".join(f"{k} {v}" for k, v in a.no_permiso.items()))
    L.append("«Por ask» = reasonCode rule:* (el comando entero casó una regla ask).")
    L.append("")
    L.append("Por reasonCode                                     Diálogos  Rech.")
    for c, n in a.codigos.most_common():
        L.append(f"  {c[:48]:<48}{n:>9}{a.codigos_rech.get(c, 0):>7}")
    L.append("")
    L.append(f"Reglas de {mreglas.settings_path()} (solo lectura)")
    for lista in ("ask", "allow"):
        rs = a.reglas.get(lista, {})
        if not rs:
            L.append(f"  {lista:<6}(ninguna)")
        for r, n in rs.items():
            L.append(f"  {lista:<6}{r[:52]:<53}{n:>5} diálogos")
    if props is not None:
        L.append("")
        L.append(f"Propuestas ({len(props)}) en {comun.estado_dir() / 'propuestas'}:")
        estado = dict(escritas or [])
        for p in props:
            L.append(f"  [{estado.get(p['id'], '?')}] {p['tipo']:<19}{p['id']}")
            L.append(f"      {p['resumen']}")
        if props:
            L.append("  Nada se aplica solo: `mecanismo aprobar ID` imprime el comando jq.")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    try:
        args = _args(argv)
    except SystemExit as e:
        return int(e.code or 0) if e.code in (0, None) else 2
    if args.proponer:
        try:
            import yaml  # noqa: F401, PLC0415
        except ImportError:
            print("mecanismo permisos --proponer: instala python3-yaml", file=sys.stderr)
            return 4
    cfg = mreglas.leer_reglas()
    a = analisis.analizar(iterar_decisiones(args.dias, args.subagentes), args.dias, args.subagentes, cfg)
    props = escritas = None
    if args.proponer:
        props = propuestas.generar(a, cfg, args.min)
        escritas = propuestas.escribir(props)
    if args.json:
        d = analisis.a_dict(a)
        d["definicion"] = DEFINICION
        if props is not None:
            d["propuestas"] = [{"id": p["id"], "tipo": p["tipo"], "resumen": p["resumen"],
                                "estado_escritura": dict(escritas).get(p["id"])} for p in props]
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(_texto(a, escritas, props))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
