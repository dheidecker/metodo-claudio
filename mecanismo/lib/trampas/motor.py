"""Motor de trampas (CONTRATO.md §3). Solo stdlib; PyYAML entra por comun.leer_yaml.

API que importa el frente B (no cambiar las firmas sin pasar por el contrato):
    cargar_trampas(dir_proyecto) -> list[dict]
    aciertos(trampas, archivo, texto, lineas) -> list[(archivo, línea, id)]
    probar_trampa(trampa) -> list[str]        # errores; vacía = ok
"""
from __future__ import annotations

import fnmatch
import functools
import itertools
import os
import re
from pathlib import Path

from lib import comun

MAX_POR_DEFECTO = 3
OBLIGATORIOS = ("id", "nivel", "globs", "patron", "mensaje", "origen", "prueba")
CAMPOS = set(OBLIGATORIOS) | {"excepto", "bloque", "max"}
NIVELES = ("aviso", "bloqueo")
_SLUG = re.compile(r"^[a-z0-9-]+$")
# Un archivo más grande que esto no es código que se edite a mano: no se mira.
TAM_MAX = 2 * 1024 * 1024

Acierto = tuple  # (archivo: str, línea: int, id: str)


# ---------------------------------------------------------------- carga

def dir_trampas(dir_proyecto: str | os.PathLike) -> Path:
    return Path(dir_proyecto) / ".claude" / "trampas"


def cargar_dir(d: str | os.PathLike, errores: list[str] | None = None) -> list[dict]:
    """Trampas de `d/*.yml` (no baja a subcarpetas: `propuestas/` queda fuera).
    Un archivo es una trampa (mapping) o una lista. Lanza comun.SinPyYAML si hace falta y no está.
    Un archivo ilegible o que no es YAML se salta y se anota en `errores`."""
    out: list[dict] = []
    for f in sorted(Path(d).glob("*.yml")):
        if not f.is_file():
            continue
        try:
            datos = comun.leer_yaml(f)
        except comun.SinPyYAML:
            raise
        except Exception as e:  # yaml.YAMLError, OSError, UnicodeError
            if errores is not None:
                errores.append(f"{f.name}: {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
            continue
        if datos is None:
            continue
        items = datos if isinstance(datos, list) else [datos]
        for t in items:
            if isinstance(t, dict):
                out.append(t)
            elif errores is not None:
                errores.append(f"{f.name}: una entrada no es un mapping")
    return out


def cargar_trampas(dir_proyecto: str | os.PathLike, errores: list[str] | None = None) -> list[dict]:
    """Trampas activas de un proyecto: `<proyecto>/.claude/trampas/*.yml` (no `propuestas/`)."""
    d = dir_trampas(dir_proyecto)
    return cargar_dir(d, errores) if d.is_dir() else []


def cargar_desde(d: str | os.PathLike, errores: list[str] | None = None) -> list[dict]:
    """Para la CLI: `d` es un proyecto (tiene .claude/trampas) o una carpeta de *.yml suelta."""
    return cargar_trampas(d, errores) if dir_trampas(d).is_dir() else cargar_dir(d, errores)


# ---------------------------------------------------------------- globs

def _variantes(glob: str) -> set[str]:
    """`**/` = cero o más carpetas: además del glob tal cual (fnmatch ya cruza `/` con `*`),
    cada combinación de `**/` quitados. `**/*.blade.php` casa también `x.blade.php` en la raíz."""
    partes = glob.split("**/")
    if len(partes) == 1:
        return {glob}
    out = set()
    for quitar in itertools.product((False, True), repeat=len(partes) - 1):
        s = partes[0]
        for q, p in zip(quitar, partes[1:]):
            s += ("" if q else "**/") + p
        out.add(s)
    return out


@functools.lru_cache(maxsize=512)
def _rx_glob(glob: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{fnmatch.translate(v)})" for v in sorted(_variantes(glob))))


def casa_glob(ruta: str, glob: str) -> bool:
    return _rx_glob(glob).match(ruta.replace(os.sep, "/")) is not None


def aplica(trampa: dict, ruta: str) -> bool:
    globs = trampa.get("globs") or []
    return isinstance(globs, list) and any(isinstance(g, str) and casa_glob(ruta, g) for g in globs)


def relativa(archivo: str | os.PathLike, raiz: str | os.PathLike) -> str:
    """Ruta posix relativa a la raíz; si el archivo queda fuera, la absoluta (los `**/` la casan igual)."""
    a = Path(archivo).resolve()
    try:
        return a.relative_to(Path(raiz).resolve()).as_posix()
    except ValueError:
        return a.as_posix()


# ---------------------------------------------------------------- validación

@functools.lru_cache(maxsize=1024)
def _rx(patron: str) -> re.Pattern:
    return re.compile(patron)


def validar(t) -> list[str]:
    """Forma de la trampa (esquemas/trampa.schema.json) y regex que compilan. No corre la prueba."""
    if not isinstance(t, dict):
        return ["no es un mapping"]
    err = [f"falta `{k}`" for k in OBLIGATORIOS if k not in t]
    err += [f"campo desconocido `{k}`" for k in sorted(set(t) - CAMPOS)]
    if "id" in t and not (isinstance(t["id"], str) and _SLUG.match(t["id"])):
        err.append("`id` no es un slug [a-z0-9-]+")
    if "nivel" in t and t["nivel"] not in NIVELES:
        err.append("`nivel` debe ser aviso o bloqueo")
    if "globs" in t and not (isinstance(t["globs"], list) and t["globs"] and all(isinstance(g, str) for g in t["globs"])):
        err.append("`globs` debe ser una lista de textos no vacía")
    for k in ("mensaje", "origen"):
        if k in t and not (isinstance(t[k], str) and t[k].strip()):
            err.append(f"`{k}` debe ser un texto no vacío")
    regexes = [("patron", t.get("patron")), ("excepto", t.get("excepto"))]
    if "bloque" in t:
        b = t["bloque"]
        if not (isinstance(b, dict) and set(b) == {"abre", "cierra"}):
            err.append("`bloque` debe ser {abre, cierra}")
        else:
            regexes += [("bloque.abre", b["abre"]), ("bloque.cierra", b["cierra"])]
    for nombre, rx in regexes:
        if rx is None and nombre == "excepto":
            continue
        if not isinstance(rx, str):
            if nombre != "patron" or "patron" in t:
                err.append(f"`{nombre}` debe ser un texto")
            continue
        try:
            _rx(rx)
        except re.error as e:
            err.append(f"`{nombre}` no compila: {e}")
    if "prueba" in t:
        p = t["prueba"]
        if not (isinstance(p, dict) and set(p) == {"dispara", "no_dispara"}
                and all(isinstance(v, str) for v in p.values())):
            err.append("`prueba` debe ser {dispara: texto, no_dispara: texto}")
    if "max" in t and not (isinstance(t["max"], int) and not isinstance(t["max"], bool) and t["max"] >= 1):
        err.append("`max` debe ser un entero >= 1")
    return err


# ---------------------------------------------------------------- motor

def lineas_de(trampa: dict, lineas_texto: list[str], lineas: set[int] | None) -> list[int]:
    """Líneas (1-based) donde acierta una trampa ya validada. Globs aparte.
    `bloque`: abre en la línea que casa `abre` (incluida), cierra tras la que casa `cierra`
    (incluida), un acierto por bloque, un `abre` dentro lo reinicia. El primer acierto de un bloque
    lo consume aunque luego se filtre por líneas cambiadas (igual que el awk original).
    `max` se cuenta después de filtrar."""
    rx = _rx(trampa["patron"])
    ex = _rx(trampa["excepto"]) if trampa.get("excepto") else None
    b = trampa.get("bloque")
    abre, cierra = (_rx(b["abre"]), _rx(b["cierra"])) if b else (None, None)
    maximo = trampa.get("max") or MAX_POR_DEFECTO
    out: list[int] = []
    dentro = consumido = False
    for n, linea in enumerate(lineas_texto, 1):
        if abre is not None and abre.search(linea):
            dentro, consumido = True, False
        cuenta = (dentro and not consumido) if abre is not None else True
        if cuenta and rx.search(linea) and not (ex is not None and ex.search(linea)):
            if abre is not None:
                consumido = True
            if lineas is None or n in lineas:
                out.append(n)
                if len(out) >= maximo:
                    break
        if dentro and cierra.search(linea):
            dentro = False
    return out


def aciertos(trampas: list[dict], archivo: str | os.PathLike, texto: str,
             lineas: set[int] | None = None) -> list[Acierto]:
    """(archivo, línea, id) de cada trampa cuyo glob casa `archivo` (ruta relativa a la raíz del
    proyecto, o absoluta). `lineas` = comun.lineas_cambiadas(); None = todo el archivo.
    Las trampas que no validan se saltan en silencio (el hook las anota aparte)."""
    ruta = str(archivo).replace(os.sep, "/")
    if lineas is not None and not lineas:
        return []
    out: list[Acierto] = []
    partes = None
    for t in trampas:
        if not aplica(t, ruta) or validar(t):
            continue
        if partes is None:
            partes = texto.split("\n")
        out += [(str(archivo), n, t["id"]) for n in lineas_de(t, partes, lineas)]
    return out


def probar_trampa(trampa: dict) -> list[str]:
    """Errores de forma + su propia prueba: `dispara` debe dar ≥1 y `no_dispara` 0. Vacía = ok."""
    err = validar(trampa)
    if err:
        return err
    p = trampa["prueba"]
    if not lineas_de(trampa, p["dispara"].split("\n"), None):
        err.append("`prueba.dispara` no dispara")
    n = lineas_de(trampa, p["no_dispara"].split("\n"), None)
    if n:
        err.append(f"`prueba.no_dispara` dispara (líneas {','.join(map(str, n))})")
    return err


def leer_texto(archivo: str | os.PathLike) -> str | None:
    try:
        if os.path.getsize(archivo) > TAM_MAX:
            return None
        with open(archivo, encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------- mensajes

def agrupar(hits: list[Acierto]) -> dict[str, list[int]]:
    """id -> líneas, en el orden en que aparecen."""
    g: dict[str, list[int]] = {}
    for _, n, i in hits:
        g.setdefault(i, []).append(n)
    return g


def renglones(hits: list[Acierto], por_id: dict[str, dict]) -> list[str]:
    """`- <id> (líneas 3,7): <mensaje>`: el id va siempre, es lo que se poda y se sube de nivel."""
    out = []
    for i, ns in agrupar(hits).items():
        t = por_id.get(i, {})
        marca = " [bloqueo]" if t.get("nivel") == "bloqueo" else ""
        out.append(f"- {i}{marca} (líneas {','.join(map(str, ns))}): {t.get('mensaje', '').strip()}")
    return out
