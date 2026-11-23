"""Adaptadores de verificación: uno por vía del mapa (`mcp`, `web`, `test`).

Cada adaptador expone `verificar(funcion, conf, raiz, ctx) -> dict` con
`{ok: bool, resumen: str, capturas: [str], diffs: [str]}`. Nunca lanzan: un error es `ok: false`
con el motivo en `resumen`. Son el contrato de entrada de un futuro `mecanismo evaluar`.
"""
from __future__ import annotations

from pathlib import Path


class Contexto:
    """Estado de una corrida de `verificar`: dónde dejar capturas y recursos que se comparten
    entre funciones (la sesión MCP se abre una vez). `cerrar()` libera todo."""

    def __init__(self, raiz: Path, dir_evidencia: Path, prefijo: str, grabar: bool = False):
        self.raiz = Path(raiz)
        self.dir_evidencia = Path(dir_evidencia)
        self.prefijo = prefijo
        self.grabar = grabar
        self.recursos: dict = {}

    def cerrar(self) -> None:
        for r in list(self.recursos.values()):
            cerrar = getattr(r, "cerrar", None)
            if cerrar:
                try:
                    cerrar()
                except Exception:  # noqa: BLE001 — cerrar nunca rompe la entrega
                    pass
        self.recursos.clear()


def verificar(funcion: dict, conf: dict, raiz: Path, ctx: Contexto) -> dict:
    from . import lib as _lib, mcp as _mcp, web as _web  # noqa: PLC0415
    try:
        if "mcp" in funcion:
            r = _mcp.verificar(funcion, conf, raiz, ctx)
        elif "web" in funcion:
            r = _web.verificar(funcion, conf, raiz, ctx)
        elif "test" in funcion:
            r = _lib.verificar(funcion, conf, raiz, ctx)
        else:
            r = {"ok": False, "resumen": "la función no declara vía (mcp, web o test)"}
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "resumen": f"error del adaptador: {type(e).__name__}: {e}"}
    r.setdefault("capturas", [])
    r.setdefault("diffs", [])
    return r
