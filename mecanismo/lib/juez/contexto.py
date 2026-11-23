"""Contexto para el juez modelo: git, transcript y redacción (siempre antes de cortar)."""
from __future__ import annotations

import collections
import json
import re
import subprocess
from pathlib import Path

from lib import comun

# comun.redactar no ve `KEY=valor` sin prefijo conocido, y un deploy suele llevar los secretos en
# `--set-env-vars`. Esto va ANTES de comun.redactar; se conservan los nombres, nunca los valores.
_RX_FLAG_ENV = re.compile(
    r"(--(?:set|update|remove)?-?(?:build-)?(?:env-vars|secrets|env)(?:-file)?)(=|\s+)"
    r"(\"(?:\\.|[^\"\\])*\"|'[^']*'|\S+)")
_RX_ASIG_SECRETA = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:pass(?:word|wd)?|secret|token|api[_-]?key|private[_-]?key|credential|pwd|"
    r"auth)[A-Za-z0-9_]*)=(\"(?:\\.|[^\"\\])*\"|'[^']*'|[^\s,;&|]+)")
_RX_OPCION_SECRETA = re.compile(r"(?i)(--[\w-]*(?:password|token|secret|api-key)[\w-]*)(=|\s+)(\S+)")

TOPE_PROMPT = 1500
TOPE_ASISTENTE = 2000
TOPE_COMANDO = 4000
LINEAS_STATUS = 30
COLA_TRANSCRIPT = 8 << 20      # solo los últimos 8 MB: un transcript largo no debe frenar el hook


def redactar(texto: str) -> str:
    if not texto:
        return texto or ""

    def flag_env(m: re.Match) -> str:
        nombres = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", m.group(3))
        valor = ",".join(f"{n}=[REDACTADO:env]" for n in nombres) or "[REDACTADO:env]"
        return f"{m.group(1)}{m.group(2)}{valor}"

    texto = _RX_FLAG_ENV.sub(flag_env, texto)
    texto = _RX_ASIG_SECRETA.sub(lambda m: f"{m.group(1)}=[REDACTADO:env]", texto)
    texto = _RX_OPCION_SECRETA.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTADO:opcion]", texto)
    return comun.redactar(texto)


def cortar(texto: str, n: int) -> str:
    """Redacta y DESPUÉS corta (CONTRATO §11)."""
    t = redactar(texto)
    return t if len(t) <= n else t[:n] + "…"


def _git(cwd: str, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def git(cwd: str) -> dict:
    status = [redactar(x) for x in _git(cwd, "status", "--short").splitlines()]
    return {
        "rama": _git(cwd, "rev-parse", "--abbrev-ref", "HEAD").strip() or None,
        "status": status[:LINEAS_STATUS] + ([f"… y {len(status) - LINEAS_STATUS} más"]
                                           if len(status) > LINEAS_STATUS else []),
        "commits": [cortar(x, 200) for x in _git(cwd, "log", "-5", "--format=%s").splitlines()],
    }


def _entradas(path: Path):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            f.seek(max(0, tam - COLA_TRANSCRIPT))
            datos = f.read()
    except OSError:
        return
    if tam > COLA_TRANSCRIPT:
        datos = datos.split(b"\n", 1)[-1]
    for linea in datos.decode("utf-8", "replace").splitlines():
        try:
            e = json.loads(linea)
        except ValueError:
            continue
        if isinstance(e, dict):
            yield e


def _prompt_sin_origen(e: dict) -> bool:
    """Respaldo para sesiones `claude -p`, cuyo prompt puede no traer `origin`: entrada user que no es
    tool_result, ni meta, ni de un subagente, ni una etiqueta del harness (<command-…>, <system-…>)."""
    if e.get("type") != "user" or e.get("origin") or e.get("isMeta") or e.get("isSidechain"):
        return False
    if e.get("toolUseResult") is not None:
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return False
    t = comun.texto_de(e).strip()
    return bool(t) and not t.startswith("<")


def transcript(path: str | None, n: int = 5) -> dict:
    humanos: collections.deque = collections.deque(maxlen=n)
    sin_origen: collections.deque = collections.deque(maxlen=n)
    asistente = ""
    if path:
        for e in _entradas(Path(path)):
            if comun.es_prompt_humano(e):
                humanos.append(comun.texto_de(e))
            elif _prompt_sin_origen(e):
                sin_origen.append(comun.texto_de(e))
            elif e.get("type") == "assistant" and not e.get("isSidechain"):
                t = comun.texto_de(e).strip()
                if t:
                    asistente = t
    prompts = list(humanos) or list(sin_origen)
    return {"prompts_humanos": [cortar(p, TOPE_PROMPT) for p in prompts],
            "ultimo_asistente": cortar(asistente, TOPE_ASISTENTE)}


def armar(comando: str, cwd: str, familias: list[str], nota: str, transcript_path: str | None) -> dict:
    t = transcript(transcript_path)
    return {
        "tarea": "juez",
        "comando": cortar(comando, TOPE_COMANDO),
        "cwd": redactar(cwd),
        "familias": familias,
        "nota_reglas": redactar(nota),
        "git": git(cwd),
        **t,
    }
