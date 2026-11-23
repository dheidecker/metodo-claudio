"""`mecanismo confiar [dir]`: confianza en los comandos del proyecto, como `direnv allow` (CONTRATO §11).

`verificar` ejecuta con shell lo que dice el yml del proyecto (`arranque`, `mcp.comando`, cada `test`).
Solo lo hace si el sha256 de `.claude/mecanismo.yml` + `.claude/mapa-funciones.yml` está registrado
para esa raíz en `~/.claude/mecanismo/confianza.json`. Lo registra una persona, en su terminal:
`confiar` muestra todos los comandos, exige TTY (`comun.exige_tty`) y pide teclear «sí».
Cambiar una letra de cualquiera de los dos archivos invalida la confianza.

Exit: 0 confiado · 1 cancelado o la configuración cambió mientras se confirmaba · 2 uso ·
3 falta TTY · 4 falta PyYAML.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from lib import comun
from lib.evidencia import nucleo

ARCHIVO = "confianza.json"
# Separa los dos archivos dentro del hash. YAML no admite NUL, así que no puede aparecer dentro.
SEPARADOR = b"\n\x00mapa-funciones.yml\x00\n"
MENSAJE = "configuración no confiada: corre `mecanismo confiar`"


# ---------------------------------------------------------------- hash y registro

def leer(raiz: Path) -> tuple[bytes | None, bytes | None]:
    """(bytes de mecanismo.yml, bytes de mapa-funciones.yml); None si falta el archivo."""
    raiz = Path(raiz)
    return nucleo.leer_bytes(raiz / nucleo.CONF), nucleo.leer_bytes(raiz / nucleo.MAPA)


def huella(conf: bytes | None, mapa: bytes | None) -> str:
    """sha256(mecanismo.yml + separador + mapa-funciones.yml); un archivo ausente cuenta como vacío."""
    return hashlib.sha256((conf or b"") + SEPARADOR + (mapa or b"")).hexdigest()


def huella_de(raiz: Path) -> str:
    return huella(*leer(raiz))


def _clave(raiz: Path) -> str:
    return str(Path(raiz).resolve())


def _ruta() -> Path:
    return comun.estado_dir() / ARCHIVO


def _registro() -> dict:
    try:
        d = json.loads(_ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def es_confiable(raiz: Path, huella_actual: str | None = None) -> bool:
    """¿La configuración actual de `raiz` (o `huella_actual`, si se da) es la que una persona confió?"""
    h = huella_actual if huella_actual is not None else huella_de(raiz)
    e = _registro().get(_clave(raiz))
    return isinstance(e, dict) and e.get("sha256") == h


def _guardar(raiz: Path, h: str) -> None:
    d = _registro()
    d[_clave(raiz)] = {"sha256": h, "fecha": _dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    ruta = _ruta()
    fd, tmp = tempfile.mkstemp(prefix=".confianza-", dir=ruta.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- qué se ejecutaría

def _mconf(conf: dict) -> dict:
    m = conf.get("mcp")
    return m if isinstance(m, dict) else {}


def necesita(conf: dict, funciones: list[dict]) -> bool:
    """¿Verificar estas funciones ejecutaría algún comando del yml? `arranque` siempre cuenta;
    una función `test` también; una `mcp` solo si mecanismo.yml declara `mcp.comando` (stdio).
    Una `mcp` por `url` o una `web` sin `arranque` no ejecutan nada local."""
    if conf.get("arranque"):
        return True
    for f in funciones:
        if "test" in f:
            return True
        if "mcp" in f and _mconf(conf).get("comando"):
            return True
    return False


def comandos(conf: dict, mapa: list[dict]) -> list[tuple[str, str]]:
    """[(de dónde sale, comando)]: todo lo que `verificar` podría ejecutar con shell."""
    out = []
    if conf.get("arranque"):
        out.append(("arranque (mecanismo.yml)", str(conf["arranque"])))
    if _mconf(conf).get("comando"):
        out.append(("mcp.comando (mecanismo.yml)", str(_mconf(conf)["comando"])))
    for f in mapa:
        if "test" in f:
            out.append((f"test de {f['id']} (mapa-funciones.yml)", str(f["test"])))
    return out


def _visible(s: str) -> str:
    """Escapa caracteres de control: que una secuencia ANSI no esconda parte del comando."""
    return "".join(c if c.isprintable() or c == " " else repr(c)[1:-1] for c in s)


# ---------------------------------------------------------------- CLI

def _args(argv):
    p = argparse.ArgumentParser(prog="mecanismo confiar",
                                description="Confía en los comandos del yml del proyecto (solo una persona, con TTY).")
    p.add_argument("dir", nargs="?", help="raíz del proyecto (por defecto la de cwd)")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        a = _args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    raiz = Path(a.dir).resolve() if a.dir else comun.raiz_proyecto()
    conf_b, mapa_b = leer(raiz)
    try:
        conf = nucleo.conf_de(conf_b)
        if conf is None:
            print(f"confiar: {raiz} no tiene {nucleo.CONF}", file=sys.stderr)
            return 2
        mapa = nucleo.mapa_de(mapa_b)
    except comun.SinPyYAML:
        print("confiar: instala python3-yaml", file=sys.stderr)
        return 4
    except nucleo.ConfInvalida as e:
        print(f"confiar: {e}", file=sys.stderr)
        return 2
    h = huella(conf_b, mapa_b)

    print(f"Proyecto: {raiz}")
    print(f"Huella de {nucleo.CONF} + {nucleo.MAPA}: {h[:16]}…")
    cmds = comandos(conf, mapa)
    if cmds:
        print(f"`mecanismo verificar` podrá ejecutar con shell, en {raiz}, estos {len(cmds)} comando(s):")
        for origen, c in cmds:
            print(f"  - {origen}:\n      {_visible(c)}")
    else:
        print("La configuración no declara comandos locales (arranque, mcp.comando ni test).")
    if es_confiable(raiz, h):
        print("(ya estaba confiada con esta misma huella)")

    try:
        comun.exige_tty("confiar")
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 3
    try:
        r = input("Si los revisaste y confías en ellos, escribe «sí»: ")
    except (EOFError, KeyboardInterrupt):
        print("\nconfiar: cancelado, no se guardó nada.", file=sys.stderr)
        return 1
    if r.strip().lower() not in ("sí", "si"):
        print("confiar: cancelado, no se guardó nada.", file=sys.stderr)
        return 1
    # Lo confiado es lo que se mostró: si el yml cambió mientras se leía, no vale.
    if huella_de(raiz) != h:
        print("confiar: la configuración cambió mientras confirmabas; no se guardó. Vuelve a correrlo.",
              file=sys.stderr)
        return 1
    _guardar(raiz, h)
    comun.bitacora("verificar", f"ok confiar {h[:12]}", proyecto=raiz.name)
    print(f"Confiado. Cualquier cambio en {nucleo.CONF} o {nucleo.MAPA} pedirá confiar de nuevo.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
