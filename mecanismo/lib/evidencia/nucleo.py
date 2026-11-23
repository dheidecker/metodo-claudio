"""Piezas de evidencia que comparten `mecanismo verificar` y `hooks/stop-evidencia`.

CONTRATO §5 (evidencia) y §6 (mecanismo.yml y mapa). `stop-evidencia` solo usa la parte de
lectura (config, globs, vigencia): nunca verifica.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import signal
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path

from lib import comun

CONF = Path(".claude/mecanismo.yml")
MAPA = Path(".claude/mapa-funciones.yml")
EVIDENCIA = Path(".claude/evidencia")


# ---------------------------------------------------------------- configuración

class ConfInvalida(ValueError):
    """mecanismo.yml o mapa-funciones.yml no se puede leer como lo pide el contrato (§6)."""


def leer_bytes(p: Path) -> bytes | None:
    """Bytes del archivo, o None si no existe. `verificar` parsea y hashea estos mismos bytes,
    para que lo que se confió (lib.evidencia.confianza) sea exactamente lo que se ejecuta."""
    p = Path(p)
    if not p.is_file():
        return None
    return p.read_bytes()


def _yaml(datos: bytes, nombre: Path):
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:
        raise comun.SinPyYAML(str(e)) from e
    try:
        return yaml.safe_load(datos)
    except yaml.YAMLError as e:
        raise ConfInvalida(f"{nombre}: YAML inválido ({type(e).__name__})") from None


def conf_de(datos: bytes | None) -> dict | None:
    """mecanismo.yml ya leído → dict (None si el archivo no existe). Lanza SinPyYAML o ConfInvalida."""
    if datos is None:
        return None
    d = _yaml(datos, CONF) or {}
    if not isinstance(d, dict):
        raise ConfInvalida(f"{CONF} no es un mapping (es {type(d).__name__})")
    return d


def mapa_de(datos: bytes | None) -> list[dict]:
    if datos is None:
        return []
    d = _yaml(datos, MAPA) or {}
    if not isinstance(d, dict):
        raise ConfInvalida(f"{MAPA} no es un mapping (es {type(d).__name__})")
    fs = d.get("funciones") or []
    if not isinstance(fs, list):
        raise ConfInvalida(f"{MAPA}: `funciones` no es una lista")
    return [f for f in fs if isinstance(f, dict) and f.get("id")]


def leer_conf(raiz: Path) -> dict | None:
    """mecanismo.yml o None si el proyecto no lo tiene. Lanza comun.SinPyYAML o ConfInvalida."""
    return conf_de(leer_bytes(Path(raiz) / CONF))


def leer_mapa(raiz: Path) -> list[dict]:
    return mapa_de(leer_bytes(Path(raiz) / MAPA))


def via(funcion: dict) -> str:
    for v in ("mcp", "web", "test"):
        if v in funcion:
            return v
    return "?"


# ---------------------------------------------------------------- globs (CONTRATO §3)

def _variantes(glob: str) -> set[str]:
    """`**/` = cero o más carpetas: cada `**/` también se prueba quitado."""
    out = {glob}
    i = glob.find("**/")
    if i >= 0:
        for resto in _variantes(glob[i + 3:]):
            out.add(glob[:i + 3] + resto)
            out.add(glob[:i] + resto)
    return out


def casa(rel: str, globs: list[str]) -> bool:
    rel = rel.replace(os.sep, "/")
    return any(fnmatch.fnmatchcase(rel, v) for g in globs or [] for v in _variantes(g))


def relativa(raiz: Path, f: Path) -> str | None:
    try:
        return Path(f).resolve().relative_to(Path(raiz).resolve()).as_posix()
    except ValueError:
        return None


def funciones_de(rel: str, mapa: list[dict]) -> list[str]:
    return [f["id"] for f in mapa if casa(rel, f.get("globs") or [])]


# ---------------------------------------------------------------- evidencia

def evidencia_dir(raiz: Path) -> Path:
    d = Path(raiz) / EVIDENCIA
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():  # que la evidencia nunca cuente como "archivo cambiado" ni se commitee
        gi.write_text("*\n", encoding="utf-8")
    return d


def sello() -> tuple[str, str]:
    """(ts ISO con zona para el JSON, nombre de archivo ordenable)."""
    ahora = _dt.datetime.now().astimezone()
    return ahora.isoformat(timespec="seconds"), ahora.strftime("%Y%m%d-%H%M%S-%f")


def head(raiz: Path) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(raiz), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def evidencias(raiz: Path) -> list[dict]:
    """Todas las evidencias del proyecto, la más reciente primero."""
    d = Path(raiz) / EVIDENCIA
    out = []
    for p in sorted(d.glob("*.json"), reverse=True):
        try:
            e = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # una evidencia con forma rara (escrita a mano, cortada) se ignora: no tumba al hook
        if (isinstance(e, dict) and e.get("version") == 1 and isinstance(e.get("huellas"), dict)
                and isinstance(e.get("funciones"), list)):
            out.append(e)
    return out


def vigente(rel: str, sha: str, fid: str, evs: list[dict]) -> bool:
    """CONTRATO §5: la evidencia más reciente que tiene huellas[rel] == sha y verificó `fid`
    manda; vale solo si esa función dio ok: true. Una huella con otro hash no cuenta."""
    for e in evs:
        if (e.get("huellas") or {}).get(rel) != sha:
            continue
        for f in e.get("funciones") or []:
            if isinstance(f, dict) and f.get("id") == fid:
                return f.get("ok") is True
    return False


def faltantes(raiz: Path, cambiados: list[Path], mapa: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    """({función: [archivos sin evidencia vigente]}, [archivos fuera del mapa])."""
    evs = evidencias(raiz)
    falta: dict[str, list[str]] = {}
    sin_mapa: list[str] = []
    for f in cambiados:
        rel = relativa(raiz, f)
        if rel is None:
            continue
        fids = funciones_de(rel, mapa)
        if not fids:
            sin_mapa.append(rel)
            continue
        try:
            sha = comun.sha256_archivo(f)
        except OSError:
            continue
        for fid in fids:
            if not vigente(rel, sha, fid, evs):
                falta.setdefault(fid, []).append(rel)
    return falta, sin_mapa


def comando_verificar(fids) -> str:
    return "mecanismo verificar --funciones " + ",".join(fids)


# ---------------------------------------------------------------- arranque (mecanismo.yml `arranque`)

def _host_puerto(url: str) -> tuple[str, int] | None:
    u = urllib.parse.urlsplit(url)
    if not u.hostname:
        return None
    return u.hostname, u.port or (443 if u.scheme == "https" else 80)


def escucha(url: str, timeout: float = 0.5) -> bool:
    hp = _host_puerto(url)
    if not hp:
        return False
    try:
        with socket.create_connection(hp, timeout=timeout):
            return True
    except OSError:
        return False


class Arranque:
    """Levanta `arranque` si lo que se verifica no escucha ya, y lo mata (grupo entero) al salir."""

    def __init__(self, comando: str | None, url: str | None, raiz: Path, espera: float = 20.0):
        self.comando, self.url, self.raiz, self.espera = comando, url, raiz, espera
        self.proc: subprocess.Popen | None = None

    def __enter__(self):
        if not self.comando or not self.url or escucha(self.url):
            return self
        self.proc = subprocess.Popen(self.comando, shell=True, cwd=self.raiz, start_new_session=True,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        limite = time.time() + self.espera
        while time.time() < limite and self.proc.poll() is None:
            if escucha(self.url):
                break
            time.sleep(0.1)
        return self

    def __exit__(self, *exc):
        matar_grupo(self.proc)
        return False


def matar_grupo(proc: subprocess.Popen | None) -> None:
    """SIGTERM al grupo, espera, y SIGKILL al grupo por si algún hijo se quedó."""
    if proc is None:
        return
    for sig, espera in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=espera)
        except subprocess.TimeoutExpired:
            pass
