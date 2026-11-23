"""Vía `test`: corre el comando de tests de la función en la raíz del proyecto."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from lib import comun
from lib.evidencia import nucleo

COLA = 40  # líneas de salida que se guardan


def verificar(funcion: dict, conf: dict, raiz: Path, ctx) -> dict:
    cmd = funcion["test"]
    timeout = int(((conf.get("lib") or {}).get("timeout")) or 900)
    with tempfile.TemporaryFile() as salida:
        proc = subprocess.Popen(cmd, shell=True, cwd=raiz, stdin=subprocess.DEVNULL, stdout=salida,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = proc.wait(timeout=timeout)
            vencido = False
        except subprocess.TimeoutExpired:
            nucleo.matar_grupo(proc)
            rc, vencido = None, True
        salida.seek(0)
        texto = salida.read().decode("utf-8", errors="replace")
    cola = comun.redactar("\n".join(texto.splitlines()[-COLA:]))
    log = ctx.dir_evidencia / f"{ctx.prefijo}-{funcion['id']}.log"
    log.write_text(f"$ {cmd}\n{cola}\n", encoding="utf-8")
    ultima = next((ln.strip() for ln in reversed(cola.splitlines()) if ln.strip()), "")
    if vencido:
        resumen = f"timeout tras {timeout} s: {cmd}"
    else:
        resumen = f"exit {rc}" + (f": {ultima}" if ultima else "")
    return {"ok": rc == 0, "resumen": resumen[:300],
            "capturas": [os.path.relpath(log, raiz)], "diffs": [] if rc == 0 else [cola]}
