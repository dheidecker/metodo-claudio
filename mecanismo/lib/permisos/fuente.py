"""De los transcripts a decisiones de permiso con su comando.

El `permissionDecision` vive en la entrada `user` que trae el `tool_result` (CONTRATO §9). El
comando está en el bloque `tool_use` de una entrada `assistant` anterior del mismo archivo: se une
por `message.content[].tool_use_id` y, si no aparece, por `sourceToolAssistantUUID`.

Se lee línea a línea (comun.iterar_transcripts) y solo se guarda, por archivo, el mapa
tool_use_id -> (herramienta, comando): nunca un archivo entero.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from lib import comun

# Herramientas cuyo «diálogo» es la persona contestando, no un permiso: no cuentan.
NO_PERMISO = frozenset({"AskUserQuestion", "ExitPlanMode"})


@dataclass(frozen=True)
class Decision:
    herramienta: str
    comando: str | None        # input.command en Bash; None en las demás
    decision: str              # accept | reject | ...
    source: str | None         # config | user_temporary | user_reject | hook ...
    reason_code: str | None
    reason_type: str | None
    proyecto: str              # basename del cwd de la entrada
    dia: str                   # YYYY-MM-DD del timestamp
    subagente: bool

    @property
    def es_dialogo(self) -> bool:
        """Definición elegida (ver cli.DEFINICION): la persona tuvo que contestar
        (source user_temporary) o la herramienta no se ejecutó (decision != accept)."""
        return self.source == "user_temporary" or self.decision != "accept"

    @property
    def es_rechazo(self) -> bool:
        return self.decision != "accept"

    @property
    def codigo(self) -> str:
        """reasonCode, o `(sin código) <reasonType|source>` si la versión de Claude Code no lo trae."""
        return self.reason_code or f"(sin código) {self.reason_type or self.source or '?'}"


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


def _subagentes(dias: int | None) -> Iterator[tuple[Path, dict]]:
    """Transcripts de subagentes (<proyecto>/<sesión>/subagents/*.jsonl), que comun no recorre."""
    corte = time.time() - dias * 86400 if dias else None
    for path in sorted((comun.claude_home() / "projects").glob("*/*/subagents/*.jsonl")):
        try:
            if corte and path.stat().st_mtime < corte:
                continue
        except OSError:
            continue
        for e in _jsonl(path):
            yield path, e


def iterar_decisiones(dias: int | None = None, subagentes: bool = False) -> Iterator[Decision]:
    fuentes = [comun.iterar_transcripts(dias)]
    if subagentes:
        fuentes.append(_subagentes(dias))
    for fuente in fuentes:
        actual: Path | None = None
        usos: dict[str, tuple[str, str | None]] = {}
        por_uuid: dict[str, tuple[str, str | None]] = {}
        for path, e in fuente:
            if path != actual:
                actual, usos, por_uuid = path, {}, {}
            tipo = e.get("type")
            msg = e.get("message") if isinstance(e.get("message"), dict) else {}
            contenido = msg.get("content") if isinstance(msg.get("content"), list) else []
            if tipo == "assistant":
                for b in contenido:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        cmd = inp.get("command") if b.get("name") == "Bash" else None
                        par = (b.get("name") or "?", cmd if isinstance(cmd, str) else None)
                        usos[b.get("id")] = par
                        if e.get("uuid"):
                            por_uuid.setdefault(e["uuid"], par)
                continue
            pd = e.get("permissionDecision")
            if tipo != "user" or not isinstance(pd, dict):
                continue
            par = None
            for b in contenido:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in usos:
                    par = usos[b["tool_use_id"]]
                    break
            if par is None:
                par = por_uuid.get(e.get("sourceToolAssistantUUID") or "", ("?", None))
            yield Decision(
                herramienta=par[0], comando=par[1],
                decision=str(pd.get("decision") or "?"), source=pd.get("source"),
                reason_code=pd.get("reasonCode"), reason_type=pd.get("reasonType"),
                proyecto=Path(e.get("cwd") or path.parent.name).name,
                dia=str(e.get("timestamp") or "")[:10],
                subagente="subagents" in path.parts,
            )
