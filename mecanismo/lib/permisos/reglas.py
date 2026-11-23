"""Reglas `ask` / `allow` / `deny` de ~/.claude/settings.json, en SOLO LECTURA.

Este módulo nunca escribe settings.json: las propuestas imprimen un `comando_jq` que aplica una
persona. La ruta sale de comun.claude_home(), así que CLAUDE_HOME la sobreescribe en los tests.
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from lib import comun
from lib.permisos import familias


def settings_path() -> Path:
    return comun.claude_home() / "settings.json"


def leer_reglas() -> dict[str, list[str]]:
    try:
        d = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    p = d.get("permissions") if isinstance(d, dict) else None
    p = p if isinstance(p, dict) else {}
    return {k: [r for r in (p.get(k) or []) if isinstance(r, str)] for k in ("allow", "ask", "deny")}


def partes(regla: str) -> tuple[str, str | None]:
    """`Bash(git push*)` -> ("Bash", "git push*"); `WebFetch` -> ("WebFetch", None)."""
    m = re.fullmatch(r"\s*([^()\s]+)\s*(?:\((.*)\))?\s*", regla, re.S)
    if not m:
        return regla, None
    return m.group(1), m.group(2)


def _rx_patron(pat: str) -> re.Pattern:
    if pat.endswith(":*"):              # sintaxis antigua: prefijo
        pat = pat[:-2] + "*"
    return re.compile(".*".join(re.escape(x) for x in pat.split("*")), re.S)


def prefijo(regla: str) -> str:
    """Parte fija de un patrón Bash (`git push*` -> `git push`), para clasificarla."""
    _, pat = partes(regla)
    return (pat or "").replace(":*", "").split("*")[0].strip()


def casa(regla: str, herramienta: str, comando: str | None) -> bool:
    """¿La regla cubre esta llamada? En Bash se prueba contra cada subcomando (sin asignaciones
    ni prefijos) y contra el comando entero. En otras herramientas con patrón (`WebFetch(domain:x)`)
    no se tiene el input a mano: se aproxima por el nombre de la herramienta."""
    tool, pat = partes(regla)
    if tool != herramienta:
        return False
    if pat is None or herramienta != "Bash":
        return True
    rx = _rx_patron(pat)
    cmd = comando or ""
    if rx.fullmatch(cmd.strip()):
        return True
    for pieza, _ in familias.partir_con_ops(cmd):
        t = familias._tokens(pieza)
        if t and rx.fullmatch(" ".join(t)):
            return True
    return False


def _rx_claude(pat: str) -> re.Pattern:
    """El patrón de una regla Bash como lo casa Claude Code, por el lado ancho: `x *` casa con `x` y con
    todo lo que empiece por `x `; `x:*` (sintaxis antigua) y `x*` con todo lo que empiece por `x`;
    `x` solo con `x`; un `*` en medio casa con cualquier cosa."""
    if pat.endswith(":*"):
        return re.compile(re.escape(pat[:-2]) + ".*", re.S)
    if pat.endswith(" *"):
        base = pat[:-2]
        return re.compile(".*".join(re.escape(x) for x in base.split("*")) + r"(?:\s.*)?", re.S)
    return re.compile(".*".join(re.escape(x) for x in pat.split("*")), re.S)


def casa_claude(regla: str, comando: str) -> bool:
    """¿Claude Code dejaría pasar `comando` con esta regla allow? Se prueba el comando entero (con los
    espacios colapsados) y cada subcomando; una regla `Bash` sin patrón casa con todo."""
    tool, pat = partes(regla)
    if tool != "Bash":
        return False
    if pat is None or not pat.strip():
        return True
    rx = _rx_claude(pat.strip())
    candidatos = [comando.strip(), " ".join(comando.split())]
    for pieza, _ in familias.partir_con_ops(comando):
        candidatos += [pieza, " ".join(familias._tokens(pieza))]
    return any(rx.fullmatch(c) for c in candidatos if c)


def casa_corpus(regla: str) -> str | None:
    """El primer comando del corpus de irreversibles (familias.CORPUS) que la regla dejaría pasar, o None."""
    return next((c for c in familias.CORPUS_NUNCA_ALLOW if casa_claude(regla, c)), None)


def es_protegida(regla: str) -> bool:
    """La regla cubre un irreversible o un sensible: nunca se propone quitarla de ask."""
    tool, _ = partes(regla)
    if tool != "Bash":
        return False
    c = familias.clasificar(prefijo(regla))
    return c.irreversible or c.familia in familias.FAMILIAS_SENSIBLES


def comando_jq(agregar: dict[str, list[str]] | None = None, quitar: dict[str, list[str]] | None = None) -> str:
    """El comando que aplicaría el cambio. Se IMPRIME; mecanismo nunca lo ejecuta."""
    ops = []
    for lista, reglas in (agregar or {}).items():
        ops.append(f".permissions.{lista} = ((.permissions.{lista} // []) + {json.dumps(reglas, ensure_ascii=False)} | unique)")
    for lista, reglas in (quitar or {}).items():
        ops.append(f".permissions.{lista} = ((.permissions.{lista} // []) - {json.dumps(reglas, ensure_ascii=False)})")
    prog = " | ".join(ops) or "."
    s = "~/.claude/settings.json"
    return (f"cp {s} {s}.bak && t=$(mktemp) && jq {shlex.quote(prog)} {s} > \"$t\" && mv \"$t\" {s}")
