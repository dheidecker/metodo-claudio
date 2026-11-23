"""Fuentes del recolector. Todo texto sale de aquí YA redactado (comun.redactar).
Regla (CONTRATO §11): redactar ANTES de cortar, nunca `redactar(t[:n])`: un corte deja un PEM sin
`-----END` o una DSN sin su `@`, y la redacción ya no los reconoce.

- history.jsonl (`display`, sin comandos de barra ni `exit`).
- Transcripts: solo prompts humanos (comun.es_prompt_humano) que no sean notificaciones inyectadas.
- Bitácora de disparos (para subir-a-bloqueo y podar).
- `gh api repos/{o}/{r}/pulls/comments` si el proyecto tiene remoto en GitHub y gh responde.
- Trampas escritas en Markdown: secciones cuyo encabezado dice «trampa», en tres formas reales:
  sub-encabezados (`### 10.N. Título`), viñetas (`- **Título.** …`) y lista numerada (`7. …`).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lib import comun
from lib.propuestas.almacen import norm

PREFIJOS_INYECTADOS = ("<task-notification", "<agent-message", "<system-reminder", "<command-",
                       "<local-command", "<bash-", "<user-prompt-submit-hook")
COMANDOS_SUELTOS = {"exit", "quit", "clear", "salir", "q"}
ACUSES = {"si", "sí", "ok", "dale", "listo", "gracias", "sigue", "continua", "continúa", "yes", "no", "va"}
MAX_TEXTO = 2000


@dataclass
class Muestra:
    texto: str              # redactado
    proyecto: str           # nombre corto (basename)
    ruta: str | None        # ruta del proyecto, si se sabe
    dia: str                # YYYY-MM-DD local
    fuente: str             # history | transcripts | gh
    sesion: str | None = None
    extra: dict = field(default_factory=dict)


def descartable(texto: str) -> bool:
    t = (texto or "").strip()
    if not t or t.startswith(("/", "!")) or t.lower() in COMANDOS_SUELTOS:
        return True
    return t.startswith(PREFIJOS_INYECTADOS)


def es_acuse(texto: str) -> bool:
    """Respuestas de una o dos palabras sin instrucción: se clasifican `ninguno` sin modelo."""
    n = norm(texto)
    return len(n) < 4 or n in {norm(a) for a in ACUSES}


def _dia_ms(ms) -> str | None:
    try:
        return _dt.datetime.fromtimestamp(float(ms) / 1000).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _dia_iso(ts) -> str | None:
    if not isinstance(ts, str):
        return None
    try:
        d = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d.astimezone() if d.tzinfo else d).date().isoformat()


def _corte(dias: int | None) -> str | None:
    return (_dt.date.today() - _dt.timedelta(days=dias)).isoformat() if dias else None


def de_history(dias: int | None) -> list[Muestra]:
    out = []
    for e in comun.iterar_history(dias):
        t = e.get("display")
        if not isinstance(t, str) or descartable(t):
            continue
        dia = _dia_ms(e.get("timestamp"))
        if not dia:
            continue
        ruta = e.get("project") or None
        out.append(Muestra(comun.redactar(t)[:MAX_TEXTO], Path(ruta).name if ruta else "?", ruta, dia,
                           "history", e.get("sessionId")))
    return out


def _proyecto_de_carpeta(nombre: str) -> str:
    # -home-derek-Proyectos-sempat -> sempat (aproximado: sin cwd no hay forma exacta)
    return nombre.rsplit("-", 1)[-1] or nombre


def de_transcripts(dias: int | None) -> list[Muestra]:
    corte = _corte(dias)
    out = []
    for path, e in comun.iterar_transcripts(dias):
        if not comun.es_prompt_humano(e):
            continue
        t = comun.texto_de(e)
        if descartable(t):
            continue
        dia = _dia_iso(e.get("timestamp")) or _dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
        if corte and dia < corte:
            continue
        cwd = e.get("cwd")
        out.append(Muestra(comun.redactar(t)[:MAX_TEXTO],
                           Path(cwd).name if cwd else _proyecto_de_carpeta(path.parent.name),
                           cwd, dia, "transcripts", e.get("sessionId")))
    return out


def sin_duplicados(muestras: list[Muestra]) -> list[Muestra]:
    """El mismo prompt llega por history y por el transcript de su sesión: se cuenta una vez."""
    vistos, out = set(), []
    for m in muestras:
        k = (m.sesion, norm(m.texto)) if m.sesion else (id(m),)
        if k in vistos:
            continue
        vistos.add(k)
        out.append(m)
    return out


# ---------------------------------------------------------------- bitácora

@dataclass
class LineaBitacora:
    fecha: str      # "YYYY-MM-DD HH:MM:SS"
    hook: str
    proyecto: str
    categoria: str
    detalle: list[str]


def de_bitacora(dias: int | None) -> list[LineaBitacora]:
    corte = _corte(dias)
    out = []
    try:
        lineas = comun.bitacora_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for l in lineas:
        partes = l.split(" | ", 3)
        if len(partes) != 4:
            continue
        fecha, hook, proy, res = (p.strip() for p in partes)
        if corte and fecha[:10] < corte:
            continue
        toks = res.split()
        if not toks:
            continue
        out.append(LineaBitacora(fecha, hook, proy, toks[0], toks[1:]))
    return out


# ---------------------------------------------------------------- GitHub

def _ejecutar(args: list[str], cwd: str | None = None, timeout: int = 30) -> str | None:
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def repo_github(ruta: str) -> str | None:
    url = (_ejecutar(["git", "-C", ruta, "remote", "get-url", "origin"], timeout=10) or "").strip()
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def de_gh(rutas: list[str], dias: int | None) -> list[Muestra]:
    """Comentarios de revisión en PRs. Sin gh, sin remoto o sin respuesta: se salta en silencio."""
    gh = os.environ.get("MECANISMO_GH") or "gh"
    if not shutil.which(gh):
        return []
    corte = _corte(dias)
    out, hechos = [], set()
    for ruta in rutas:
        repo = repo_github(ruta)
        if not repo or repo in hechos:
            continue
        hechos.add(repo)
        txt = _ejecutar([gh, "api", f"repos/{repo}/pulls/comments?per_page=100&sort=created&direction=desc"])
        try:
            comentarios = json.loads(txt) if txt else []
        except ValueError:
            continue
        for c in comentarios if isinstance(comentarios, list) else []:
            cuerpo, dia = c.get("body"), (c.get("created_at") or "")[:10]
            if not isinstance(cuerpo, str) or not dia or (corte and dia < corte):
                continue
            out.append(Muestra(comun.redactar(cuerpo)[:MAX_TEXTO], Path(ruta).name, ruta, dia, "gh",
                               f"gh:{repo}:{c.get('pull_request_url', '')}"))
    return out


# ---------------------------------------------------------------- trampas escritas en Markdown

_ENC = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_NUMERACION = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)")
_VINETA_NEGRITA = re.compile(r"^[-*]\s+\*\*(.+?)\*\*")
_VINETA = re.compile(r"^[-*]\s+(\S.*)")
_NUMERADA = re.compile(r"^\d+[.)]\s+(\S.*)")


def _limpio(t: str) -> str:
    t = re.sub(r"\*\*|__", "", t).strip().rstrip(":")
    return comun.redactar(t)[:200]


def trampas_en_markdown(path: Path) -> list[dict]:
    """Ítems de las secciones cuyo encabezado contiene «trampa». Devuelve
    [{titulo, cuerpo, linea, archivo}] ya redactados."""
    try:
        lineas = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    items: list[dict] = []
    nivel = None           # nivel del encabezado «Trampas» activo
    con_sub = False        # la sección usa sub-encabezados: las viñetas son cuerpo, no ítems
    cerca = False
    actual = None
    for n, l in enumerate(lineas, 1):
        if l.lstrip().startswith("```"):
            cerca = not cerca
        if cerca:
            if actual is not None:
                actual["_c"].append(l)
            continue
        m = _ENC.match(l)
        if m:
            k, titulo = len(m.group(1)), m.group(2)
            if nivel is not None and k <= nivel:
                nivel, con_sub, actual = None, False, None
            if nivel is None:
                if "trampa" in titulo.lower():
                    nivel = k
                continue
            con_sub = True
            actual = {"titulo": _limpio(_NUMERACION.sub("", titulo)), "linea": n, "_c": []}
            items.append(actual)
            continue
        if nivel is None:
            continue
        if not con_sub and not l.startswith((" ", "\t")):
            m = _VINETA_NEGRITA.match(l) or _NUMERADA.match(l) or _VINETA.match(l)
            if m:
                actual = {"titulo": _limpio(m.group(1)), "linea": n, "_c": [l]}
                items.append(actual)
                continue
        if actual is not None:
            actual["_c"].append(l)
    for it in items:
        it["cuerpo"] = comun.redactar("\n".join(it.pop("_c")).strip())[:600]
        it["archivo"] = str(path)
    return [it for it in items if it["titulo"]]


def archivos_markdown(proyecto: Path) -> list[Path]:
    """Donde suele haber trampas escritas: CLAUDE.md, los .md de la raíz y docs/**."""
    vistos, out = set(), []
    for patron in ("CLAUDE.md", ".claude/CLAUDE.md", "*.md", "docs/**/*.md"):
        for f in sorted(proyecto.glob(patron)):
            if f.is_file() and f not in vistos and len(out) < 200:
                vistos.add(f)
                out.append(f)
    return out


def trampas_documentadas(proyectos: list[Path]) -> list[dict]:
    out = []
    for p in proyectos:
        for f in archivos_markdown(p):
            for it in trampas_en_markdown(f):
                it["proyecto"] = p.name
                it["ruta"] = str(p)
                out.append(it)
    return out


def encabezados(path: Path, niveles=(1, 2, 3), maximo: int = 80) -> list[str]:
    try:
        lineas = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out, cerca = [], False
    for l in lineas:
        if l.lstrip().startswith("```"):
            cerca = not cerca
            continue
        m = None if cerca else _ENC.match(l)
        if m and len(m.group(1)) in niveles:
            out.append(comun.redactar(m.group(2))[:160])
    return out[:maximo]


def git_log(repo: Path, n: int = 60) -> list[str]:
    txt = _ejecutar(["git", "-C", str(repo), "log", "--oneline", f"-{n}"], timeout=10) or ""
    return [comun.redactar(l) for l in txt.splitlines() if l.strip()]
