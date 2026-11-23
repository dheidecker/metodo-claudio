"""`mecanismo verificar [--funciones a,b] [--dir P] [--sid S] [--grabar-golden]`

Verifica funciones del mapa y escribe `.claude/evidencia/<ts>.json` (CONTRATO §5).
Sin `--funciones`: las que cubren archivos cambiados en la sesión; si no cubre ninguna, todas.
Comandos del yml (`arranque`, `mcp.comando`, `test`) solo si la configuración está confiada
(`mecanismo confiar`, CONTRATO §11); si no, no ejecuta nada y deja evidencia con ok: false.
Exit: 0 todo ok · 1 alguna falló o configuración no confiada · 2 uso · 4 falta PyYAML.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from lib import comun
from lib.evidencia import confianza, nucleo
from lib.evidencia.adaptadores import Contexto, verificar as verificar_funcion


def _args(argv):
    p = argparse.ArgumentParser(prog="mecanismo verificar", description=__doc__.splitlines()[0])
    p.add_argument("--funciones", help="ids separados por coma")
    p.add_argument("--dir", help="raíz del proyecto (por defecto la de cwd)")
    p.add_argument("--sid", help="session_id para el corte de 'cambiados' (por defecto CLAUDE_SESSION_ID)")
    p.add_argument("--grabar-golden", action="store_true",
                   help="mcp: escribe los goldens con la salida actual antes de comparar (revísalos con git diff)")
    p.add_argument("--json", action="store_true", help="imprime la evidencia en vez del resumen")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        a = _args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    raiz = Path(a.dir).resolve() if a.dir else comun.raiz_proyecto()
    # Se leen los bytes una vez: lo que se parsea es lo mismo que se compara con lo confiado.
    conf_b, mapa_b = confianza.leer(raiz)
    try:
        conf = nucleo.conf_de(conf_b)
        if conf is None:
            print(f"verificar: {raiz} no tiene {nucleo.CONF} (mecanismo init --tipo mcp|web|lib)", file=sys.stderr)
            return 2
        mapa = nucleo.mapa_de(mapa_b)
    except comun.SinPyYAML:
        print("verificar: instala python3-yaml", file=sys.stderr)
        return 4
    except nucleo.ConfInvalida as e:
        print(f"verificar: {e}", file=sys.stderr)
        return 2
    if not mapa:
        print(f"verificar: {nucleo.MAPA} no declara funciones", file=sys.stderr)
        return 2
    por_id = {f["id"]: f for f in mapa}
    sid = a.sid or os.environ.get("CLAUDE_SESSION_ID")
    desde = comun.desde_sesion(sid)

    if a.funciones:
        ids = [x.strip() for x in a.funciones.split(",") if x.strip()]
        desconocidas = [x for x in ids if x not in por_id]
        if desconocidas:
            print(f"verificar: funciones fuera del mapa: {', '.join(desconocidas)} "
                  f"(hay: {', '.join(por_id)})", file=sys.stderr)
            return 2
    else:
        tocadas = set()
        for f in comun.archivos_cambiados(raiz, desde):
            rel = nucleo.relativa(raiz, f)
            if rel:
                tocadas.update(nucleo.funciones_de(rel, mapa))
        ids = [f["id"] for f in mapa if f["id"] in tocadas] or list(por_id)

    ts, nombre = nucleo.sello()
    dir_ev = nucleo.evidencia_dir(raiz)
    ctx = Contexto(raiz, dir_ev, nombre, grabar=a.grabar_golden)
    funciones = []
    # CONTRATO §11: nada del yml se ejecuta (ni el arranque) sin la confianza de una persona.
    no_confiada = (confianza.necesita(conf, [por_id[i] for i in ids])
                   and not confianza.es_confiable(raiz, confianza.huella(conf_b, mapa_b)))
    if no_confiada:
        funciones = [{"id": fid, "ok": False, "comando": nucleo.comando_verificar([fid]),
                      "resumen": confianza.MENSAJE, "capturas": [], "diffs": [], "duracion_ms": 0}
                     for fid in ids]
        destino = "" if raiz == comun.raiz_proyecto() else f" {raiz}"
        print(f"verificar: configuración no confiada: corre `mecanismo confiar{destino}` tú, en tu terminal "
              f"(muestra los comandos del yml y pide confirmarlos). No se ejecutó nada.", file=sys.stderr)
    else:
        try:
            with nucleo.Arranque(conf.get("arranque"), _url_vigilada(conf), raiz):
                for fid in ids:
                    t0 = time.monotonic()
                    r = verificar_funcion(por_id[fid], conf, raiz, ctx)
                    funciones.append({
                        "id": fid, "ok": bool(r["ok"]), "comando": nucleo.comando_verificar([fid]),
                        "resumen": r.get("resumen") or "", "capturas": list(r.get("capturas") or []),
                        "diffs": list(r.get("diffs") or []), "duracion_ms": int((time.monotonic() - t0) * 1000)})
        finally:
            ctx.cerrar()

    # Huellas: archivos cambiados (en git sin corte de tiempo, más los de la sesión) que el mapa
    # asigna a alguna función verificada en esta corrida.
    verificadas = set(ids)
    huellas = {}
    for f in sorted(set(comun.archivos_cambiados(raiz, None)) | set(comun.archivos_cambiados(raiz, desde))):
        rel = nucleo.relativa(raiz, f)
        if rel and verificadas & set(nucleo.funciones_de(rel, mapa)):
            try:
                huellas[rel] = comun.sha256_archivo(f)
            except OSError:
                pass

    ok = all(f["ok"] for f in funciones)
    ev = {"version": 1, "ts": ts, "proyecto": str(raiz), "head": nucleo.head(raiz),
          "tipo": conf.get("tipo") or "lib", "ok": ok, "funciones": funciones, "huellas": huellas}
    ruta = dir_ev / f"{nombre}.json"
    ruta.write_text(json.dumps(ev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    malas = [f["id"] for f in funciones if not f["ok"]]
    if no_confiada:
        comun.bitacora("verificar", "AVISO no-confiada " + ",".join(ids), proyecto=raiz.name)
    else:
        comun.bitacora("verificar", ("ok " + ",".join(ids)) if ok else ("AVISO " + ",".join(malas)),
                       proyecto=raiz.name)

    if a.json:
        print(json.dumps(ev, ensure_ascii=False, indent=2))
    else:
        for f in funciones:
            print(f"{'ok   ' if f['ok'] else 'FALLA'} {f['id']}: {f['resumen']}")
            for d in f["diffs"] if not f["ok"] else []:
                print("  " + d.replace("\n", "\n  "))
        print(f"evidencia: {os.path.relpath(ruta, raiz)}")
    return 0 if ok else 1


def _url_vigilada(conf: dict) -> str | None:
    """Qué tiene que escuchar para no lanzar `arranque`: la url MCP o la base web."""
    if not conf.get("arranque"):
        return None
    m, w = conf.get("mcp"), conf.get("web")
    return (m.get("url") if isinstance(m, dict) else None) or (w.get("base_url") if isinstance(w, dict) else None)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
