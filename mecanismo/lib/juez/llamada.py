"""La llamada al juez modelo: `claude -p` con Sonnet, esquema JSON, tope 0,10 USD y 45 s.

Imita los flags de lib.recolector.modelo (y reutiliza sus ayudantes de salida y redacción), pero no
su `llamar()`: el juez lleva su propio modelo, tope y timeout, y sobre todo MECANISMO_JUEZ_ANIDADO=1
en el entorno, para que el `claude` anidado no vuelva a entrar en este hook (recursión).
"""
from __future__ import annotations

import json
import os
import subprocess

from lib import comun
from lib.recolector import modelo as M

MODELO = "sonnet"
TOPE_USD = 0.10
TIMEOUT_S = 45
DECISIONES = ("permitir", "negar")
RIESGOS = ("bajo", "medio", "alto")


class ErrorJuez(RuntimeError):
    def __init__(self, tipo: str, detalle: str = ""):
        super().__init__(f"{tipo} {detalle}".strip())
        self.tipo = tipo


def _args() -> list[str]:
    P = comun.raiz_mecanismo() / "prompts"
    esquema = json.dumps(json.loads((P / "juez.schema.json").read_text(encoding="utf-8")), separators=(",", ":"))
    args = [M.binario(), "-p", "--output-format", "json", "--no-session-persistence",
            "--json-schema", esquema, "--model", os.environ.get("MECANISMO_MODELO_JUEZ") or MODELO,
            "--max-budget-usd", f"{TOPE_USD:.2f}",
            "--system-prompt", (P / "juez.md").read_text(encoding="utf-8"),
            "--tools", ""]
    if os.environ.get("ANTHROPIC_API_KEY"):
        args.append("--bare")
    else:
        args += ["--setting-sources", "project"]
    return args


def juzgar(datos: dict) -> dict:
    """{decision, motivo, riesgo, costo_usd}. Lanza ErrorJuez(tipo) ante cualquier fallo."""
    entrada = json.dumps(M.redactado(datos), ensure_ascii=False)
    cwd = comun.estado_dir() / "vacio"
    cwd.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, MECANISMO_JUEZ_ANIDADO="1")
    env.pop("CLAUDE_PROJECT_DIR", None)
    timeout = float(os.environ.get("MECANISMO_JUEZ_TIMEOUT") or TIMEOUT_S)
    try:
        r = subprocess.run(_args(), input=entrada, capture_output=True, text=True, cwd=cwd, env=env,
                           timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ErrorJuez("timeout", f"{timeout:g}s") from e
    except FileNotFoundError as e:
        raise ErrorJuez("sin-claude", M.binario()) from e
    except (OSError, subprocess.SubprocessError) as e:
        raise ErrorJuez("no-corre", type(e).__name__) from e
    if not r.stdout.strip():
        raise ErrorJuez("salida-vacia", f"rc={r.returncode}")
    try:
        out = M._resultado(r.stdout)
    except M.ErrorModelo as e:
        raise ErrorJuez("json-invalido") from e
    if r.returncode != 0 or out.get("is_error") or out.get("subtype") not in (None, "success"):
        raise ErrorJuez("modelo", str(out.get("subtype") or r.returncode))
    try:
        d = M._datos(out)
    except M.ErrorModelo as e:
        raise ErrorJuez("json-invalido") from e
    decision, motivo, riesgo = d.get("decision"), d.get("motivo"), d.get("riesgo")
    if decision not in DECISIONES or riesgo not in RIESGOS or not isinstance(motivo, str) or not motivo.strip():
        raise ErrorJuez("json-invalido", "fuera del esquema")
    try:
        costo = float(out.get("total_cost_usd") or 0)
    except (TypeError, ValueError):
        costo = 0.0
    return {"decision": decision, "motivo": comun.redactar(motivo.strip())[:200], "riesgo": riesgo,
            "costo_usd": costo}
