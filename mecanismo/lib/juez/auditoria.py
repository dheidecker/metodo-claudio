"""Auditoría del juez: una línea JSON por decisión en estado_dir()/juez/AAAA-MM.jsonl."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Iterator

from lib import comun


def dir_auditoria() -> Path:
    d = comun.estado_dir() / "juez"
    d.mkdir(parents=True, exist_ok=True)
    return d


def anotar(registro: dict) -> None:
    ahora = dt.datetime.now().astimezone()
    registro = {"ts": ahora.isoformat(timespec="seconds"), **registro}
    p = dir_auditoria() / f"{ahora:%Y-%m}.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def leer() -> Iterator[dict]:
    for p in sorted(dir_auditoria().glob("*.jsonl")):
        with open(p, encoding="utf-8", errors="replace") as f:
            for linea in f:
                try:
                    e = json.loads(linea)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    yield e
