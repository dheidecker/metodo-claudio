"""Llamadas a `claude -p` con presupuesto, caché por sha256 y control de redacción.

Flags (comprobados con `claude --help`, Claude Code 2.1.330):
  -p --output-format json --no-session-persistence --json-schema <esquema> --model <m>
  --max-budget-usd <x> --system-prompt <prompt> --tools ""
  + `--bare` si hay ANTHROPIC_API_KEY (--bare no lee OAuth ni keychain: sin clave fallaría);
    si no, `--setting-sources project` y cwd en un directorio vacío, para no cargar los hooks del usuario.
El binario sale de MECANISMO_CLAUDE (o `claude`). Los datos van por stdin como JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from lib import comun

PROMPTS = comun.raiz_mecanismo() / "prompts"
TOPE_CORRIDA_USD = 2.0
POR_LLAMADA = {"clasificar": 0.25, "fusionar": 0.60, "trampas": 0.40}
MODELOS = {"clasificar": "haiku", "fusionar": "sonnet", "trampas": "sonnet"}
MINIMO_USD = 0.05


class ErrorModelo(RuntimeError):
    pass


class SinPresupuesto(ErrorModelo):
    pass


class Presupuesto:
    """El total por corrida nunca pasa de 2 USD: cada llamada lleva --max-budget-usd igual a
    lo que queda (o menos), así que la suma de topes no supera el total."""

    def __init__(self, total: float | None = None):
        env = os.environ.get("MECANISMO_PRESUPUESTO_USD")
        t = total if total is not None else (float(env) if env else TOPE_CORRIDA_USD)
        self.total = min(max(t, 0.0), TOPE_CORRIDA_USD)
        self.gastado = 0.0
        self.llamadas = 0

    def tope(self, tarea: str) -> float:
        queda = self.total - self.gastado
        if queda < MINIMO_USD:
            raise SinPresupuesto(f"presupuesto agotado ({self.gastado:.2f} de {self.total:.2f} USD)")
        return round(min(POR_LLAMADA.get(tarea, 0.25), queda), 2)


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def cache_dir() -> Path:
    d = comun.estado_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def version_prompt(tarea: str) -> str:
    """Cambia si cambian el prompt, el esquema o el modelo: invalida la caché de esa tarea."""
    return sha256((PROMPTS / f"{tarea}.md").read_text(encoding="utf-8")
                  + (PROMPTS / f"{tarea}.schema.json").read_text(encoding="utf-8") + modelo_de(tarea))[:12]


def modelo_de(tarea: str) -> str:
    return os.environ.get(f"MECANISMO_MODELO_{tarea.upper()}") or MODELOS[tarea]


def binario() -> str:
    """MECANISMO_CLAUDE o `claude`. Una ruta relativa se resuelve contra el cwd de quien llama
    (la llamada corre en otro cwd, un directorio vacío)."""
    b = os.environ.get("MECANISMO_CLAUDE") or "claude"
    return os.path.abspath(b) if os.sep in b and not os.path.isabs(b) else b


def _args(tarea: str, tope: float) -> list[str]:
    esquema = json.dumps(json.loads((PROMPTS / f"{tarea}.schema.json").read_text(encoding="utf-8")),
                         separators=(",", ":"))
    args = [binario(), "-p",
            "--output-format", "json", "--no-session-persistence",
            "--json-schema", esquema, "--model", modelo_de(tarea),
            "--max-budget-usd", f"{tope:.2f}",
            "--system-prompt", (PROMPTS / f"{tarea}.md").read_text(encoding="utf-8"),
            "--tools", ""]
    if os.environ.get("ANTHROPIC_API_KEY"):
        args.append("--bare")
    else:
        args += ["--setting-sources", "project"]
    return args


def _resultado(stdout: str) -> dict:
    try:
        out = json.loads(stdout)
    except ValueError as e:
        raise ErrorModelo(f"salida no es JSON: {stdout[:200]!r}") from e
    if isinstance(out, list):  # algunas versiones con --verbose devuelven la lista de mensajes
        out = next((m for m in reversed(out) if isinstance(m, dict) and m.get("type") == "result"), {})
    if not isinstance(out, dict):
        raise ErrorModelo("salida inesperada")
    return out


def _datos(out: dict) -> dict:
    d = out.get("structured_output")
    if isinstance(d, dict):
        return d
    r = out.get("result")
    if isinstance(r, str):
        r = r.strip()
        if r.startswith("```"):
            r = r.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            d = json.loads(r)
        except ValueError as e:
            raise ErrorModelo(f"result no es JSON: {r[:200]!r}") from e
    if not isinstance(d, dict):
        raise ErrorModelo("sin structured_output")
    return d


def redactado(x):
    """Copia de `x` con cada texto pasado por comun.redactar, campo a campo (en el JSON serializado
    un `\\n@app.route` parecería un correo)."""
    if isinstance(x, str):
        return comun.redactar(x)
    if isinstance(x, dict):
        return {k: redactado(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [redactado(v) for v in x]
    return x


def llamar(tarea: str, datos: dict, presupuesto: Presupuesto) -> dict:
    """Una llamada. `datos` debería venir ya redactado, pero lo que se ENVÍA se redacta siempre
    aquí, campo a campo: un texto cortado después de redactar puede dejar a la vista algo que
    redactar() todavía reconoce, y comprobar sin redactar tiraba el lote entero."""
    entrada = json.dumps(redactado(datos), ensure_ascii=False)
    tope = presupuesto.tope(tarea)
    cwd = comun.estado_dir() / "vacio"
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(_args(tarea, tope), input=entrada, capture_output=True, text=True,
                           cwd=cwd, timeout=int(os.environ.get("MECANISMO_TIMEOUT", "900")))
    except (OSError, subprocess.SubprocessError) as e:
        raise ErrorModelo(f"no se pudo correr claude: {e}") from e
    presupuesto.llamadas += 1
    if not r.stdout.strip():
        raise ErrorModelo(f"claude salió con {r.returncode}: {comun.redactar(r.stderr.strip())[:300]}")
    out = _resultado(r.stdout)
    try:
        presupuesto.gastado += float(out.get("total_cost_usd") or 0)
    except (TypeError, ValueError):
        pass
    if r.returncode != 0 or out.get("is_error") or (out.get("subtype") not in (None, "success")):
        raise ErrorModelo(f"claude: {out.get('subtype') or r.returncode} "
                          f"{comun.redactar(str(out.get('result') or r.stderr))[:200]}")
    return _datos(out)


# ---------------------------------------------------------------- caché

class Cache:
    """Un JSON por tarea en cache/: {sha256(entrada redactada): resultado}. Se guarda tras cada lote."""

    def __init__(self, tarea: str):
        self.path = cache_dir() / f"{tarea}-{version_prompt(tarea)}.json"
        try:
            self.d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.d = {}
        self.aciertos = 0

    def get(self, clave: str):
        v = self.d.get(clave)
        if v is not None:
            self.aciertos += 1
        return v

    def put(self, clave: str, valor) -> None:
        self.d[clave] = valor

    def guardar(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
