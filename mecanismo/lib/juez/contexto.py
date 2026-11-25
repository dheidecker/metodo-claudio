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
COMMITS_PUSH = 20
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


def _respuesta_a_pregunta(e: dict) -> str | None:
    """Las respuestas de la persona a un AskUserQuestion: son decisiones suyas, aunque lleguen como
    tool_result (`toolUseResult.answers` = {pregunta: respuesta}, `annotations` = {pregunta: {notes}})."""
    if e.get("type") != "user" or e.get("isSidechain"):
        return None
    r = e.get("toolUseResult")
    if not isinstance(r, dict) or not isinstance(r.get("answers"), dict) or not r["answers"]:
        return None
    notas = r.get("annotations") if isinstance(r.get("annotations"), dict) else {}
    partes = []
    for preg, resp in r["answers"].items():
        nota = (notas.get(preg) or {}).get("notes") if isinstance(notas.get(preg), dict) else None
        extra = f" (nota: {nota})" if nota else ""
        # la respuesta primero: si hay que cortar, se pierde la pregunta, no la decisión
        partes.append(f"Respondió «{resp}»{extra} a la pregunta del agente: «{str(preg)[:900]}»")
    return "\n".join(partes)


def transcript(path: str | None, n: int = 5) -> dict:
    humanos: collections.deque = collections.deque(maxlen=n)
    sin_origen: collections.deque = collections.deque(maxlen=n)
    asistente = ""
    if path:
        for e in _entradas(Path(path)):
            if comun.es_prompt_humano(e):
                humanos.append(comun.texto_de(e))
            elif (resp := _respuesta_a_pregunta(e)) is not None:
                humanos.append(resp)
            elif _prompt_sin_origen(e):
                sin_origen.append(comun.texto_de(e))
            elif e.get("type") == "assistant" and not e.get("isSidechain"):
                t = comun.texto_de(e).strip()
                if t:
                    asistente = t
    prompts = list(humanos) or list(sin_origen)
    return {"prompts_humanos": [cortar(p, TOPE_PROMPT) for p in prompts],
            "ultimo_asistente": cortar(asistente, TOPE_ASISTENTE)}


def push(destinos) -> list[dict]:
    """Por cada destino de un `git push` (reglas.Destino): los commits que van a subir (como mucho
    COMMITS_PUSH) y si el remoto va por delante. Sin fetch: según las referencias remotas locales."""
    out = []
    for d in destinos[:5]:
        remota = f"refs/remotes/{d.remoto}/{d.dst}"
        base = remota if _git(d.dir, "rev-parse", "--verify", "-q", remota).strip() else None
        if base is None and _git(d.dir, "rev-parse", "--verify", "-q", "@{u}").strip() and \
                _git(d.dir, "rev-parse", d.src).strip() == _git(d.dir, "rev-parse", "HEAD").strip():
            base = "@{u}"
        if base:
            rango = [f"{base}..{d.src}"]
            delante = _git(d.dir, "rev-list", "--count", f"{d.src}..{base}").strip()
        else:
            rango = [d.src, "--not", f"--remotes={d.remoto}"]
            delante = ""
        commits = _git(d.dir, "log", "--oneline", f"-{COMMITS_PUSH}", *rango).splitlines()
        total = _git(d.dir, "rev-list", "--count", *rango).strip()
        out.append({
            "repo": redactar(d.dir),
            "rama_local": _git(d.dir, "symbolic-ref", "--short", "-q", "HEAD").strip() or None,
            "commits_que_crea_el_comando": d.commits_antes,
            "remoto": d.remoto, "origen": d.src, "rama_destino": d.dst,
            "rama_remota_existe": base == remota,
            "commits_a_subir": [cortar(c, 200) for c in commits],
            "total_commits": int(total) if total.isdigit() else None,
            "remoto_por_delante": int(delante) if delante.isdigit() else None,
        })
    return out


def armar(comando: str, cwd: str, familias: list[str], nota: str, transcript_path: str | None,
          destinos_push=()) -> dict:
    t = transcript(transcript_path)
    datos = {
        "tarea": "juez",
        "comando": cortar(comando, TOPE_COMANDO),
        "cwd": redactar(cwd),
        "familias": familias,
        "nota_reglas": redactar(nota),
        "git": git(cwd),
        **t,
    }
    if destinos_push:
        datos["push"] = push(destinos_push)
    return datos
