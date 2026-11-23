"""Arma un ~/.claude falso con la forma real (CONTRATO §9) para probar el recolector offline.

    python3 tests/fixtures/recolector/armar.py DIR   # imprime los `export` para una corrida a mano

Deja en DIR: proyectos/<9 proyectos> (con las trampas escritas en los tres formatos reales),
claude/history.jsonl, claude/projects/<sesión>.jsonl, bitacora.log y el MECANISMO_HOME vacío.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import time
from pathlib import Path

import yaml

FX = Path(__file__).resolve().parent
FAKE = FX.parent / "fake-claude"
PROYECTOS = ["sempat", "mcp-sempat", "sepa-mcp", "demo-web", "tickets", "crm", "metodo-x", "sitio", "informes"]


def _ms(d: dt.datetime) -> int:
    return int(d.timestamp() * 1000)


def armar(base: Path) -> dict[str, str]:
    base = Path(base)
    hoy = dt.date.today()
    proy = base / "proyectos"
    shutil.copytree(FX / "proyectos", proy, dirs_exist_ok=True)
    for n in PROYECTOS:
        (proy / n).mkdir(exist_ok=True)
    claude = base / "claude"
    claude.mkdir(parents=True, exist_ok=True)

    filas = yaml.safe_load((FX / "prompts.yml").read_text(encoding="utf-8"))
    with open(claude / "history.jsonl", "w", encoding="utf-8") as f:
        for k, r in enumerate(filas):
            cuando = dt.datetime.combine(hoy - dt.timedelta(days=r["hace"]), dt.time(10, k % 60))
            f.write(json.dumps({"display": r["texto"], "pastedContents": {}, "timestamp": _ms(cuando),
                                "project": str(proy / r["proyecto"]), "sessionId": r["sesion"]},
                               ensure_ascii=False) + "\n")
        f.write("línea rota que no es json\n")

    def iso(dias: int) -> str:
        return dt.datetime.combine(hoy - dt.timedelta(days=dias), dt.time(11, 0)).astimezone().isoformat()

    sesion = claude / "projects" / ("-tmp-" + proy.name + "-sempat")
    sesion.mkdir(parents=True, exist_ok=True)
    entradas = [
        # duplicado del history (misma sesión): cuenta una vez
        {"type": "user", "origin": {"kind": "human"}, "sessionId": "esp-0", "cwd": str(proy / "demo-web"),
         "timestamp": iso(3), "message": {"role": "user", "content": "responde en español por favor"}},
        {"type": "user", "origin": {"kind": "human"}, "sessionId": "tr-1", "cwd": str(proy / "sempat"),
         "timestamp": iso(4), "message": {"role": "user", "content": [
             {"type": "text", "text": "muestra la salida de las pruebas; el secreto es ghp_CANARIOabcdef12345"}]}},
        {"type": "user", "origin": {"kind": "human"}, "sessionId": "tr-1", "cwd": str(proy / "sempat"),
         "timestamp": iso(4), "message": {"content": "<task-notification>el agente en paralelo terminó</task-notification>"}},
        {"type": "user", "origin": {"kind": "human"}, "sessionId": "tr-1", "cwd": str(proy / "sempat"),
         "timestamp": iso(4), "message": {"content": "<command-name>/agents</command-name>"}},
        {"type": "user", "origin": {"kind": "peer"}, "sessionId": "tr-1", "cwd": str(proy / "sempat"),
         "timestamp": iso(4), "message": {"content": "<agent-message>lanza en paralelo</agent-message>"}},
        {"type": "user", "sessionId": "tr-1", "timestamp": iso(4),
         "message": {"content": [{"type": "tool_result", "content": "en paralelo"}]},
         "permissionDecision": {"decision": "accept", "source": "config"}},
        {"type": "assistant", "sessionId": "tr-1", "timestamp": iso(4),
         "message": {"content": [{"type": "text", "text": "lo hago en paralelo"}]}},
    ]
    (sesion / "tr-1.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entradas) + "\n",
                                       encoding="utf-8")

    def linea(fecha: str, hook: str, proyecto: str, res: str) -> str:
        return "%s | %-22s | %-32s | %s\n" % (fecha, hook, proyecto, res)

    lineas = []
    for d in (9, 6, 2):
        dia = (hoy - dt.timedelta(days=d)).isoformat()
        for i in range(2):  # 6 avisos de blade-sin-escapar, cada uno seguido de una pasada limpia
            lineas.append(linea(f"{dia} 10:0{i}:00", "trampas", "demo-web", "AVISO blade-sin-escapar a.blade.php"))
            lineas.append(linea(f"{dia} 10:0{i}:30", "trampas", "demo-web", "silencio a.blade.php"))
    for d in (8, 7, 5, 4, 1):  # 5 avisos que nadie corrigió: no sube a bloqueo
        dia = (hoy - dt.timedelta(days=d)).isoformat()
        lineas.append(linea(f"{dia} 12:00:00", "trampas", "demo-web", "AVISO otra-no-corregida b.php"))
    lineas.append(linea(f"{hoy.isoformat()} 09:00:00", "precommit-credenciales", "demo-web", "ok"))
    (base / "bitacora.log").write_text("".join(lineas), encoding="utf-8")

    viejo = time.time() - 100 * 86400
    os.utime(proy / "demo-web" / ".claude" / "trampas" / "blade.yml", (viejo, viejo))
    (base / "cwd").mkdir(exist_ok=True)
    return {"CLAUDE_HOME": str(claude), "MECANISMO_HOME": str(base / "mecanismo"),
            "MECANISMO_BITACORA": str(base / "bitacora.log"), "MECANISMO_CLAUDE": str(FAKE),
            "MECANISMO_GH": str(base / "sin-gh"), "CLAUDE_PROJECT_DIR": str(base / "cwd")}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("uso: armar.py DIR")
    for k, v in armar(Path(sys.argv[1])).items():
        print(f"export {k}={v}")
