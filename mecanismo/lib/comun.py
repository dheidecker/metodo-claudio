"""Piezas compartidas de mecanismo. CONGELADO desde F0: los frentes lo usan, no lo editan.

Si un frente necesita algo más, lo escribe en su propio paquete; si es de verdad común,
lo pide al orquestador, que lo añade en la integración. Ver CONTRATO.md §8.

Solo stdlib. PyYAML se importa perezoso en leer_yaml() para que un hook sin PyYAML
pueda salir con exit 0 y anotar `sin-pyyaml` en vez de romper la sesión.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

VERSION_CONTRATO = 1

# ---------------------------------------------------------------- rutas
# Todas sobreescribibles por entorno: los tests NUNCA escriben en el ~/.claude real.

def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def estado_dir() -> Path:
    """Estado agregado y caché de mecanismo (~/.claude/mecanismo). Se crea al pedirlo."""
    d = Path(os.environ.get("MECANISMO_HOME") or claude_home() / "mecanismo")
    d.mkdir(parents=True, exist_ok=True)
    return d


def bitacora_path() -> Path:
    return Path(os.environ.get("MECANISMO_BITACORA") or claude_home() / "metodo-claudio.log")


def raiz_mecanismo() -> Path:
    """La carpeta metodo-claudio/mecanismo de este clon (deriva de este archivo, nunca escrita a mano)."""
    return Path(__file__).resolve().parent.parent


def raiz_proyecto(cwd: str | os.PathLike | None = None) -> Path:
    """CLAUDE_PROJECT_DIR, si no la raíz git de cwd, si no cwd."""
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(os.environ["CLAUDE_PROJECT_DIR"])
    base = Path(cwd or os.getcwd())
    r = _git(base, "rev-parse", "--show-toplevel")
    return Path(r.strip()) if r else base


# ---------------------------------------------------------------- bitácora
# Mismo formato que los hooks bash (hooks/informe.sh lo parte por " | "):
#   2026-11-23 11:04:05 | <hook 22>               | <proyecto 32>                    | <RESULTADO> <detalle>
# El primer token del resultado es la categoría: ok, silencio, AVISO, BLOQUEO, inicio, sin-pyyaml, error, EVENTO.

def bitacora(hook: str, resultado: str, proyecto: str | None = None) -> None:
    if proyecto is None:
        proyecto = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).name
    linea = "%s | %-22s | %-32s | %s\n" % (
        _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), hook, proyecto, resultado.replace("\n", " "))
    try:
        p = bitacora_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(linea)
    except OSError:
        pass


# ---------------------------------------------------------------- redacción
# Se aplica ANTES de cachear, enviar a un modelo o escribir una propuesta. Orden importa:
# PEM y DSN primero (contienen cosas que otras reglas partirían a medias).
_REDACCIONES: list[tuple[str, re.Pattern]] = [
    ("pem", re.compile(r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----", re.S)),
    ("dsn", re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@[^\s]+")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-|]{8,}")),
    ("anthropic", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")),
    ("github", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})")),
    ("sanctum", re.compile(r"\b\d+\|[A-Za-z0-9]{16,}")),
    ("correo", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
]


def redactar(texto: str) -> str:
    """Sustituye secretos y correos por [REDACTADO:<tipo>]. Idempotente."""
    if not texto:
        return texto
    for tipo, rx in _REDACCIONES:
        texto = rx.sub(f"[REDACTADO:{tipo}]", texto)
    return texto


# ---------------------------------------------------------------- sesión y cambios

def marca_sesion(sid: str | None) -> Path:
    """La marca que deja session-marca.sh al arrancar: /tmp/lint-marca-<sid>."""
    return Path(f"/tmp/lint-marca-{sid or 'sin-sesion'}")


def desde_sesion(sid: str | None, minutos_sin_marca: int = 30) -> float:
    """mtime de corte: la marca de la sesión o, si no hay, ahora - 30 min (igual que stop-lint.sh)."""
    m = marca_sesion(sid)
    try:
        return m.stat().st_mtime
    except OSError:
        return time.time() - minutos_sin_marca * 60


def _git(cwd: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def repos_de(base: Path) -> list[Path]:
    """base si es repo; si no, los repos anidados a un nivel (caso tickets/{backend,crm,...})."""
    base = Path(base)
    if (base / ".git").exists():
        return [base]
    return sorted(p.parent for p in base.glob("*/.git"))


_IGNORAR_SIN_GIT = {".git", "node_modules", "vendor", "__pycache__", ".venv", ".claude"}


def archivos_cambiados(base: str | os.PathLike, desde: float | None = None) -> list[Path]:
    """Archivos que cambiaron en el árbol: sucios en git (diff HEAD + sin seguimiento) y, si se da
    `desde`, con mtime > desde. Sin ningún repo: recorre el árbol con mtime > desde (find -newer).
    Devuelve rutas absolutas, ordenadas, solo archivos que existen."""
    base = Path(base).resolve()
    repos = repos_de(base)
    out: set[Path] = set()
    if repos:
        for d in repos:
            txt = (_git(d, "diff", "--name-only", "HEAD") or "") + (
                _git(d, "ls-files", "--others", "--exclude-standard") or "")
            for rel in filter(None, txt.splitlines()):
                f = d / rel
                if f.is_file() and (desde is None or f.stat().st_mtime > desde):
                    out.add(f.resolve())
    else:
        if desde is None:
            return []
        for raiz, dirs, archivos in os.walk(base):
            dirs[:] = [x for x in dirs if x not in _IGNORAR_SIN_GIT]
            for a in archivos:
                f = Path(raiz) / a
                try:
                    if f.stat().st_mtime > desde:
                        out.add(f.resolve())
                except OSError:
                    pass
    return sorted(out)


def lineas_cambiadas(archivo: str | os.PathLike) -> set[int] | None:
    """Líneas (1-based) añadidas o cambiadas respecto a HEAD.
    None  -> mirar el archivo entero (sin seguimiento o fuera de un repo).
    set() -> seguido y sin cambios: no hay nada que avisar.
    Misma lógica que blade-trampas.sh (git diff -U0 HEAD, hunks +a,b)."""
    f = Path(archivo).resolve()
    d = f.parent
    if _git(d, "rev-parse", "--is-inside-work-tree") is None:
        return None
    if _git(d, "ls-files", "--error-unmatch", str(f)) is None:
        return None
    diff = _git(d, "diff", "-U0", "HEAD", "--", str(f)) or ""
    lineas: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        a, b = int(m.group(1)), int(m.group(2) or 1)
        lineas.update(range(a, a + b))
    return lineas


def sha256_archivo(archivo: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(archivo, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


# ---------------------------------------------------------------- transcripts e historial

def _jsonl(path: Path) -> Iterator[dict]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for linea in f:
                try:
                    e = json.loads(linea)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    yield e
    except OSError:
        return


def iterar_transcripts(dias: int | None = None, proyecto: str | None = None) -> Iterator[tuple[Path, dict]]:
    """(ruta, entrada) de ~/.claude/projects/*/*.jsonl (solo el nivel de sesión, no subagentes).
    `dias` filtra por mtime del archivo; `proyecto` es una subcadena del nombre de la carpeta."""
    corte = time.time() - dias * 86400 if dias else None
    raiz = claude_home() / "projects"
    for path in sorted(raiz.glob("*/*.jsonl")):
        if proyecto and proyecto not in path.parent.name:
            continue
        try:
            if corte and path.stat().st_mtime < corte:
                continue
        except OSError:
            continue
        for e in _jsonl(path):
            yield path, e


def es_prompt_humano(e: dict) -> bool:
    """Entrada `user` escrita por la persona: origin.kind == "human". Descarta tool_result,
    mensajes de otros agentes (peer), task-notification y system-reminder."""
    o = e.get("origin")
    return e.get("type") == "user" and isinstance(o, dict) and o.get("kind") == "human"


def texto_de(e: dict) -> str:
    """Texto plano del mensaje de una entrada user/assistant (concatena bloques type=text)."""
    m = e.get("message") or {}
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def iterar_history(dias: int | None = None) -> Iterator[dict]:
    """Entradas de ~/.claude/history.jsonl: {display, project, timestamp(ms), sessionId, ...}."""
    corte_ms = (time.time() - dias * 86400) * 1000 if dias else None
    for e in _jsonl(claude_home() / "history.jsonl"):
        if corte_ms and (e.get("timestamp") or 0) < corte_ms:
            continue
        yield e


# ---------------------------------------------------------------- YAML, hooks, TTY

class SinPyYAML(RuntimeError):
    pass


def leer_yaml(path: str | os.PathLike):
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:
        raise SinPyYAML(str(e)) from e
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def leer_stdin_json() -> dict:
    try:
        d = json.loads(sys.stdin.read() or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def salida_hook(evento: str, mensaje: str | None, bloquear: bool = False) -> int:
    """Responde a un hook y devuelve el exit code que hay que usar.
    bloquear -> mensaje a stderr, 2.  aviso -> JSON systemMessage+additionalContext, 0.  None -> 0."""
    if not mensaje:
        return 0
    if bloquear:
        print(mensaje, file=sys.stderr)
        return 2
    print(json.dumps({"systemMessage": mensaje,
                      "hookSpecificOutput": {"hookEventName": evento, "additionalContext": mensaje}},
                     ensure_ascii=False))
    return 0


def exige_tty(accion: str) -> None:
    """`mecanismo aprobar` y similares: solo una persona en una terminal. Claude no se aprueba solo.
    MECANISMO_TTY_FALSO=1 existe SOLO para tests y lo ignora si no corre bajo unittest."""
    if os.environ.get("MECANISMO_TTY_FALSO") == "1" and "unittest" in sys.modules:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f"{accion}: exige una terminal interactiva (TTY). Córrelo tú, no un agente.", file=sys.stderr)
        raise SystemExit(3)
