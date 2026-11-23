"""`mecanismo init --tipo mcp|web|lib [dir]` (frente E, CONTRATO §2 y §6).

Deja en un proyecto lo mínimo para que mecanismo funcione: mecanismo.yml, un mapa de
ejemplo, las carpetas de trampas y verificación, los dos shims y `.claude/evidencia/` en
el .gitignore. Idempotente: nunca pisa un archivo existente (lo dice y lo deja).
NO toca el settings.json del proyecto: imprime el comando jq que lo engancha.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from lib import comun

TIPOS = ("mcp", "web", "lib")
SHIMS = ("mecanismo-trampas.sh", "stop-evidencia.sh")
IGNORAR = ".claude/evidencia/"

_MECANISMO_YML = {
    "mcp": """\
# mecanismo.yml — CONTRATO §6. La puerta nace en aviso: pasa a bloqueo cuando confíes en ella.
version: 1
tipo: mcp
puerta: aviso
# arranque: "make servir-falso"     # cómo se levanta lo que se verifica
mcp:
  url: "http://localhost:8080/mcp"   # o, para stdio: comando: "python3 servidor.py"
  token_env: "MCP_TOKEN"
  golden: ".claude/verificacion/golden"
  ignorar: [query_id, request_id]
""",
    "web": """\
# mecanismo.yml — CONTRATO §6. La puerta nace en aviso: pasa a bloqueo cuando confíes en ella.
version: 1
tipo: web
puerta: aviso
# arranque: "php artisan serve"     # cómo se levanta lo que se verifica
web:
  base_url: "http://localhost:8000"
""",
    "lib": """\
# mecanismo.yml — CONTRATO §6. La puerta nace en aviso: pasa a bloqueo cuando confíes en ella.
version: 1
tipo: lib
puerta: aviso
lib:
  tests: "python3 -m unittest"
""",
}

_MAPA_YML = {
    "mcp": """\
# mapa-funciones.yml — CONTRATO §6. EJEMPLO: cambia id, globs y caso por los de tu proyecto.
# Cada función lleva exactamente una vía: mcp, web o test.
funciones:
  - id: ejemplo
    globs: ["internal/ejemplo/**"]
    mcp: {tool: ejemplo, casos: ".claude/verificacion/casos/ejemplo.yaml"}
""",
    "web": """\
# mapa-funciones.yml — CONTRATO §6. EJEMPLO: cambia id, globs, url y pasos por los de tu proyecto.
# Cada función lleva exactamente una vía: mcp, web o test.
funciones:
  - id: login
    globs: ["resources/views/auth/**"]
    web: {url: "/login", pasos: ["fill #email x", "click button[type=submit]"]}
""",
    "lib": """\
# mapa-funciones.yml — CONTRATO §6. EJEMPLO: cambia id, globs y test por los de tu proyecto.
# Cada función lleva exactamente una vía: mcp, web o test.
funciones:
  - id: parser
    globs: ["src/parser/**"]
    test: "python3 -m unittest tests.test_parser"
""",
}

# Carpetas que deben existir. Las hojas llevan .gitkeep para que viajen vacías con el repo
# (trampas/ no: ya contiene propuestas/, y el motor solo lee *.yml).
_CARPETAS = (
    (".claude/trampas", False),
    (".claude/trampas/propuestas", True),
    (".claude/verificacion/casos", True),
    (".claude/verificacion/golden", True),
)

# Lo que el comando jq engancha en el settings.json del proyecto (mismo bloque que la plantilla).
_C = "${CLAUDE_PROJECT_DIR}/.claude/hooks/"
HOOKS = {
    "PostToolUse": {"matcher": "Edit|Write", "hooks": [
        {"type": "command", "command": _C + "mecanismo-trampas.sh", "timeout": 15}]},
    "Stop": {"hooks": [
        {"type": "command", "command": _C + "mecanismo-trampas.sh --stop", "timeout": 30},
        {"type": "command", "command": _C + "stop-evidencia.sh", "timeout": 30}]},
}


def plantilla_hooks() -> Path:
    """Los shims viven una sola vez, en la plantilla del repo; init los copia de ahí."""
    return comun.raiz_mecanismo().parent / "plantilla-proyecto" / ".claude" / "hooks"


def _rel(p: Path, raiz: Path) -> str:
    return str(p.relative_to(raiz))


class _Init:
    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.creados: list[str] = []
        self.existentes: list[str] = []

    def archivo(self, rel: str, texto: str, ejecutable: bool = False) -> None:
        p = self.raiz / rel
        if p.exists() or p.is_symlink():
            self.existentes.append(rel)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8")
        if ejecutable:
            p.chmod(0o755)
        self.creados.append(rel)

    def carpeta(self, rel: str, gitkeep: bool) -> None:
        p = self.raiz / rel
        if p.is_dir():
            return
        p.mkdir(parents=True, exist_ok=True)
        self.creados.append(rel + "/")
        if gitkeep:  # solo en la carpeta recién creada; si ya existía, no se toca
            (p / ".gitkeep").touch()

    def gitignore(self) -> None:
        p = self.raiz / ".gitignore"
        lineas = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        ya = {l.strip().lstrip("/").rstrip("/") for l in lineas}
        if IGNORAR.rstrip("/") in ya:
            self.existentes.append(".gitignore (ya ignora .claude/evidencia/)")
            return
        previo = p.read_text(encoding="utf-8") if p.exists() else ""
        sep = "" if (not previo or previo.endswith("\n")) else "\n"
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{sep}# mecanismo: evidencia local de verificación, no se versiona\n{IGNORAR}\n")
        self.creados.append(".gitignore (+ .claude/evidencia/)")


def _enganchados(settings: Path) -> bool:
    """¿El settings.json ya llama a los dos shims? Lectura pura: nunca se escribe."""
    try:
        d = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    cmds = [h.get("command", "")
            for ev in ("PostToolUse", "Stop")
            for e in (d.get("hooks", {}).get(ev) or [])
            for h in (e.get("hooks") or [])]
    return (any(c.endswith("mecanismo-trampas.sh") for c in cmds)
            and any(c.endswith("mecanismo-trampas.sh --stop") for c in cmds)
            and any(c.endswith("stop-evidencia.sh") for c in cmds))


def comando_jq(settings: Path) -> str:
    """Comando listo para pegar. Idempotente: quita antes cualquier entrada que ya llame a
    los shims de mecanismo y añade las nuevas; el resto de hooks queda igual."""
    filtro = (
        "def sin_mecanismo: map(select([.hooks[]?.command // \"\"] "
        "| any(test(\"mecanismo-trampas.sh|stop-evidencia.sh\")) | not)); "
        f".hooks.PostToolUse = (((.hooks.PostToolUse // []) | sin_mecanismo) + [{json.dumps(HOOKS['PostToolUse'])}]) "
        f"| .hooks.Stop = (((.hooks.Stop // []) | sin_mecanismo) + [{json.dumps(HOOKS['Stop'])}])"
    )
    s = shlex.quote(str(settings))
    return (f"f={s}; t=$(mktemp); {{ cat \"$f\" 2>/dev/null || echo '{{}}'; }} "
            f"| jq {shlex.quote(filtro)} > \"$t\" && mkdir -p \"$(dirname \"$f\")\" && mv \"$t\" \"$f\"")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="mecanismo init",
                                 description="Deja en un proyecto lo que mecanismo necesita. No pisa nada.")
    ap.add_argument("--tipo", required=True, choices=TIPOS)
    ap.add_argument("dir", nargs="?", help="raíz del proyecto (por defecto, la raíz git del directorio actual)")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    if a.dir:
        raiz = Path(a.dir).resolve()
        if not raiz.is_dir():
            print(f"mecanismo init: {a.dir} no es una carpeta", file=sys.stderr)
            return 2
    else:
        raiz = comun.raiz_proyecto(os.getcwd()).resolve()

    origen = plantilla_hooks()
    faltan = [s for s in SHIMS if not (origen / s).is_file()]
    if faltan:
        print(f"mecanismo init: faltan los shims {faltan} en {origen}", file=sys.stderr)
        return 2

    print(f"mecanismo init --tipo {a.tipo} en {raiz}")
    i = _Init(raiz)
    i.archivo(".claude/mecanismo.yml", _MECANISMO_YML[a.tipo])
    i.archivo(".claude/mapa-funciones.yml", _MAPA_YML[a.tipo])
    for c, gk in _CARPETAS:
        i.carpeta(c, gk)
    for s in SHIMS:
        i.archivo(f".claude/hooks/{s}", (origen / s).read_text(encoding="utf-8"), ejecutable=True)
    i.gitignore()

    for r in i.creados:
        print(f"  creado:          {r}")
    for r in i.existentes:
        print(f"  ya estaba, no se toca: {r}")
    if not i.creados:
        print("  sin cambios")

    tipo_actual = None
    try:
        d = comun.leer_yaml(raiz / ".claude" / "mecanismo.yml") or {}
        tipo_actual = d.get("tipo") if isinstance(d, dict) else None
    except comun.SinPyYAML:
        pass
    except Exception:  # noqa: BLE001 — un yml roto del usuario no impide terminar init
        print("  aviso: .claude/mecanismo.yml no se pudo leer como YAML; revísalo a mano")
    if tipo_actual and tipo_actual != a.tipo:
        print(f"  aviso: .claude/mecanismo.yml ya existía con tipo {tipo_actual}; no se cambió a {a.tipo}")

    settings = raiz / ".claude" / "settings.json"
    print()
    if _enganchados(settings):
        print(f"Hooks: {_rel(settings, raiz)} ya llama a los dos shims. Nada que añadir.")
    else:
        print(f"Hooks: falta engancharlos en {_rel(settings, raiz)}. Lo aplicas tú (init no lo toca):")
        print("  " + comando_jq(settings))
        if not shutil.which("jq"):
            print("  (no hay jq en el PATH: instálalo o copia el bloque de plantilla-proyecto/.claude/settings.json)")
    print("Después, chat nuevo: los hooks se leen al arrancar la sesión.")
    return 0
