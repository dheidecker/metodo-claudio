"""mecanismo propuestas [--todas] [--json] · propuestas ver ID · aprobar ID · rechazar ID

`aprobar` y `rechazar` exigen TTY (comun.exige_tty): Claude no se aprueba solo.
- aprobar una `trampa-nueva` / `subir-a-hook`: escribe la trampa (nivel aviso) en
  <proyecto>/.claude/trampas/<id>.yml y marca la propuesta `aprobada`.
- `subir-a-bloqueo` / `podar`: imprime el diff o el comando; el .yml lo cambias tú.
- destino metodologia / proyecto: imprime el diff de METODOLOGIA.md o del CLAUDE.md.
- destino permisos: imprime el comando jq. Nunca toca settings.json, METODOLOGIA.md ni CLAUDE.md.
Exit: 0 ok · 1 no se pudo (ya existe, no encontrada) · 2 uso · 3 sin TTY · 4 sin PyYAML.
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

from lib import comun

USO = "uso: mecanismo propuestas [--todas] [--json] | propuestas ver ID | aprobar ID | rechazar ID"


def _yaml():
    import yaml  # noqa: PLC0415
    return yaml


def listar(todas: bool, como_json: bool) -> int:
    from lib.propuestas import almacen  # noqa: PLC0415
    filas = [(f, p) for f, p in almacen.listar() if todas or p.get("estado") == "pendiente"]
    filas.sort(key=lambda fp: (-(fp[1].get("evidencia") or {}).get("puntuacion", 0), fp[1]["id"]))
    if como_json:
        print(json.dumps([dict(p, ruta=str(f)) for f, p in filas], ensure_ascii=False, indent=2, default=str))
        return 0
    if not filas:
        print("sin propuestas pendientes")
        return 0
    for f, p in filas:
        ev = p.get("evidencia") or {}
        print(f"{p['id']:<52} {p.get('tipo', '?'):<18} {p.get('destino', '?'):<11} "
              f"{ev.get('puntuacion', 0):>6}  {p.get('estado', '?'):<9} {p.get('resumen', '')}")
    return 0


def ver(pid: str) -> int:
    from lib.propuestas import almacen  # noqa: PLC0415
    r = almacen.buscar(pid)
    if not r:
        print(f"no encontré la propuesta {pid}", file=sys.stderr)
        return 1
    f, p = r
    print(f"# {f}")
    print(_yaml().safe_dump(p, allow_unicode=True, sort_keys=False, width=100), end="")
    return 0


def _diff_agregar(archivo: Path, texto: str) -> str:
    try:
        antes = archivo.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        antes = []
    if antes and not antes[-1].endswith("\n"):
        antes[-1] += "\n"
    despues = antes + (["\n"] if antes else []) + [l + "\n" for l in texto.rstrip("\n").split("\n")]
    return "".join(difflib.unified_diff(antes, despues, f"a/{archivo.name}", f"b/{archivo.name}"))


def _diff_nivel(archivo: Path, tid: str) -> str:
    """Cambia `nivel: aviso` -> `nivel: bloqueo` dentro del bloque de la trampa `tid` (solo para mostrar)."""
    try:
        antes = archivo.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return ""
    despues, dentro = [], False
    for l in antes:
        if re.match(r"^\s*-?\s*id:\s*['\"]?([a-z0-9-]+)", l):
            dentro = re.match(r"^\s*-?\s*id:\s*['\"]?([a-z0-9-]+)", l).group(1) == tid
        if dentro and re.match(r"^\s*-?\s*nivel:\s*aviso\b", l):
            l = l.replace("aviso", "bloqueo", 1)
            dentro = False
        despues.append(l)
    return "".join(difflib.unified_diff(antes, despues, f"a/{archivo.name}", f"b/{archivo.name}"))


def _aplicar(p: dict) -> tuple[int, str]:
    """Hace (o imprime) lo que pide la propuesta. Devuelve (exit, mensaje)."""
    tipo, c = p.get("tipo"), p.get("contenido") or {}
    if tipo in ("trampa-nueva", "subir-a-hook"):
        t = dict(c.get("trampa") or {})
        proyecto = Path(str(c.get("proyecto") or ""))
        if not t.get("id") or not proyecto.is_dir():
            return 1, f"falta la trampa o el proyecto no existe: {proyecto}"
        t["nivel"] = "aviso"
        destino = proyecto / ".claude" / "trampas" / f"{t['id']}.yml"
        if destino.exists():
            return 1, f"ya existe {destino}: no la piso"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(_yaml().safe_dump(t, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
        return 0, f"trampa escrita en {destino} (nivel aviso). Pruébala: mecanismo trampas --probar {proyecto}"
    if tipo == "subir-a-bloqueo":
        d = _diff_nivel(Path(c.get("archivo", "")), c.get("id", ""))
        return 0, (d or f"no encontré `nivel: aviso` de {c.get('id')} en {c.get('archivo')}") + \
            "\nAplícalo tú (no se toca el .yml desde aquí)."
    if tipo == "podar":
        return 0, (f"Para podar «{c.get('id')}» quita su entrada de {c.get('archivo')} "
                   f"(si es la única del archivo: git rm {c.get('archivo')}).")
    if p.get("destino") in ("metodologia", "proyecto"):
        archivo = Path(str(c.get("archivo") or ""))
        texto = c.get("diff") or _diff_agregar(archivo, str(c.get("texto") or p.get("resumen") or ""))
        return 0, texto + f"\nAplícalo tú en {archivo} (no se toca desde aquí)."
    if p.get("destino") == "permisos":
        return 0, (c.get("comando_jq") or json.dumps(c, ensure_ascii=False)) + \
            "\nCórrelo tú: settings.json no se toca desde aquí."
    return 1, f"tipo desconocido: {tipo}"


def decidir(pid: str, aprobar: bool) -> int:
    comun.exige_tty("aprobar" if aprobar else "rechazar")
    from lib.propuestas import almacen  # noqa: PLC0415
    r = almacen.buscar(pid)
    if not r:
        print(f"no encontré la propuesta {pid}", file=sys.stderr)
        return 1
    f, p = r
    if p.get("estado") != "pendiente":
        print(f"{p['id']} ya está {p.get('estado')}", file=sys.stderr)
        return 1
    if aprobar:
        code, msg = _aplicar(p)
        print(msg)
        if code:
            return code
    p["estado"] = "aprobada" if aprobar else "rechazada"
    almacen.guardar(p, f.parent)
    print(f"{p['id']}: {p['estado']}")
    return 0


def main(argv: list[str]) -> int:
    argv = list(argv)
    if argv[:1] == ["propuestas"]:
        argv = argv[1:]
    try:
        _yaml()
    except ImportError:
        print("mecanismo propuestas: instala python3-yaml", file=sys.stderr)
        return 4
    if not argv or argv[0].startswith("--"):
        extra = set(argv) - {"--todas", "--json"}
        if extra:
            print(USO, file=sys.stderr)
            return 2
        return listar("--todas" in argv, "--json" in argv)
    if len(argv) == 2 and argv[0] == "ver":
        return ver(argv[1])
    if len(argv) == 2 and argv[0] in ("aprobar", "rechazar"):
        return decidir(argv[1], argv[0] == "aprobar")
    print(USO, file=sys.stderr)
    return 2
