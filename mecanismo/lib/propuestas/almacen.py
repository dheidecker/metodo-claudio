"""Almacén de propuestas (CONTRATO §4): dónde viven, cómo se leen, se escriben y se fusionan.

Globales: comun.estado_dir()/propuestas/<id>.yml.
Trampa de un proyecto: <proyecto>/.claude/trampas/propuestas/<id>.yml.
El id es `slug + 8 hex de sha256(texto canónico)`: estable entre corridas.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import unicodedata
from pathlib import Path

from lib import comun

CAMPOS = ("id", "estado", "creada", "origen", "tipo", "destino", "resumen", "evidencia", "contenido", "nota")
ESTADOS = ("pendiente", "aprobada", "rechazada")


def norm(texto: str) -> str:
    """Minúsculas, sin tildes ni puntuación, espacios colapsados: para comparar frases."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ ]+", " ", t)).strip()


def slug(texto: str, largo: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", norm(texto).replace("ñ", "n")).strip("-")
    if len(s) > largo:
        s = s[:largo].rsplit("-", 1)[0] or s[:largo]
    return s or "propuesta"


def sha8(texto: str) -> str:
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()[:8]


def id_de(canonico: str, base: str | None = None) -> str:
    return f"{slug(base or canonico)}-{sha8(canonico)}"


def ahora_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def dir_global() -> Path:
    return comun.estado_dir() / "propuestas"


def dir_proyecto(proyecto: str | os.PathLike) -> Path:
    return Path(proyecto) / ".claude" / "trampas" / "propuestas"


def proyectos_conocidos(extra: list[str] | None = None, con_cwd: bool = True) -> list[Path]:
    """Carpetas de proyecto que existen: las de history.jsonl (todas las fechas), más `extra`
    y (con_cwd) la raíz del proyecto actual."""
    vistos: dict[str, Path] = {}
    for e in comun.iterar_history(None):
        p = e.get("project")
        if p and p not in vistos:
            vistos[p] = Path(p)
    for p in extra or []:
        vistos[str(p)] = Path(p)
    if con_cwd:
        try:
            r = comun.raiz_proyecto()
            vistos.setdefault(str(r), r)
        except Exception:  # noqa: BLE001 — cwd borrado, etc.
            pass
    return [p for p in vistos.values() if p.is_dir()]


def carpetas(proyectos: list[Path] | None = None) -> list[Path]:
    out = [dir_global()]
    for p in proyectos if proyectos is not None else proyectos_conocidos():
        d = dir_proyecto(p)
        if d.is_dir() and d not in out:
            out.append(d)
    return out


def leer(path: Path) -> dict | None:
    try:
        d = comun.leer_yaml(path)
    except comun.SinPyYAML:
        raise
    except Exception:  # noqa: BLE001 — un YAML roto no tumba el listado
        return None
    return d if isinstance(d, dict) and d.get("id") else None


def guardar(prop: dict, carpeta: Path) -> Path:
    import yaml  # noqa: PLC0415
    carpeta.mkdir(parents=True, exist_ok=True)
    limpio = {k: prop[k] for k in CAMPOS if k in prop and prop[k] is not None}
    destino = carpeta / f"{limpio['id']}.yml"
    tmp = destino.with_suffix(".yml.tmp")
    tmp.write_text(yaml.safe_dump(limpio, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
    os.replace(tmp, destino)
    return destino


def listar(proyectos: list[Path] | None = None) -> list[tuple[Path, dict]]:
    out = []
    for d in carpetas(proyectos):
        for f in sorted(d.glob("*.yml")):
            p = leer(f)
            if p:
                out.append((f, p))
    return out


def en_carpeta(carpeta: Path) -> dict[str, dict]:
    out = {}
    if carpeta.is_dir():
        for f in carpeta.glob("*.yml"):
            p = leer(f)
            if p:
                out[p["id"]] = p
    return out


def buscar(pid: str, proyectos: list[Path] | None = None) -> tuple[Path, dict] | None:
    """Por id exacto o por prefijo único."""
    todas = listar(proyectos)
    for f, p in todas:
        if p["id"] == pid:
            return f, p
    cand = [(f, p) for f, p in todas if p["id"].startswith(pid)]
    return cand[0] if len(cand) == 1 else None


def fusionar(nueva: dict, carpeta: Path) -> tuple[Path, str]:
    """Escribe `nueva`; si ya existe una con su id, conserva id, estado y `creada`, y actualiza
    evidencia (y el resto solo si sigue pendiente). Devuelve (ruta, 'nueva'|'actualizada')."""
    previa = None
    f = carpeta / f"{nueva['id']}.yml"
    if f.exists():
        previa = leer(f)
    if not previa:
        nueva.setdefault("estado", "pendiente")
        nueva.setdefault("creada", ahora_iso())
        return guardar(nueva, carpeta), "nueva"
    mezcla = dict(previa)
    mezcla["evidencia"] = nueva.get("evidencia", previa.get("evidencia"))
    if previa.get("estado") == "pendiente":
        for k in ("resumen", "contenido", "tipo", "destino"):
            if nueva.get(k) is not None:
                mezcla[k] = nueva[k]
        if nueva.get("nota"):
            mezcla["nota"] = nueva["nota"]
    return guardar(mezcla, carpeta), "actualizada"
