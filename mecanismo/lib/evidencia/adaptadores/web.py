"""Vía `web`: la CLI `chrome-devtools` (paquete chrome-devtools-mcp) en un daemon propio.

mecanismo.yml:  web: {base_url: "http://localhost:8000", ignorar_red: ["/favicon\\.ico$"]}
mapa:           web: {url: "/login", pasos: ["fill #email x", "click button[type=submit]", "esperar 500"]}

Pasos (selectores CSS, se ejecutan con evaluate_script):
    fill <selector> <valor>   ·  click <selector>  ·  esperar <ms>  ·  ir <url-relativa-o-absoluta>

Falla si alguna respuesta de red es 4xx/5xx (salvo `ignorar_red`, regex sobre la URL) o hay algún
console.error, y nombra cada uno. Deja una captura en .claude/evidencia/.

Aislamiento: el daemon de la CLI se ubica por XDG_RUNTIME_DIR; se le da uno propio y corto en /tmp
(el socket UNIX no admite rutas largas) y un --userDataDir dentro, así nunca se toca el daemon del
usuario y al final se mata todo lo que lleve esa ruta en su línea de comandos.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from lib import comun

CLI = "chrome-devtools"
IGNORAR_RED = [r"/favicon\.ico$"]


def instalado() -> str | None:
    return shutil.which(CLI)


class Navegador:
    def __init__(self, exe: str, timeout: float = 60):
        self.exe, self.timeout = exe, timeout
        self.rt = tempfile.mkdtemp(prefix="cdt", dir="/tmp")
        self.env = dict(os.environ, XDG_RUNTIME_DIR=self.rt)

    def cmd(self, *args: str, json_out: bool = False) -> str:
        a = [self.exe, *args] + (["--output-format", "json"] if json_out else [])
        r = subprocess.run(a, env=self.env, capture_output=True, text=True, timeout=self.timeout,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            err = (r.stderr or r.stdout).strip().splitlines()
            err = [x for x in err if "Update available" not in x and "npm install" not in x]
            raise RuntimeError(f"{CLI} {args[0]} falló: {' '.join(err[-2:])[:300]}")
        return r.stdout

    def json(self, *args: str):
        out = self.cmd(*args, json_out=True)
        i = out.find("{")
        if i < 0:
            return {}
        try:
            return json.loads(out[i:])
        except ValueError:
            return {}

    def arrancar(self):
        self.cmd("start", "--headless", "--userDataDir", os.path.join(self.rt, "perfil"), "--no-usage-statistics")

    def cerrar(self):
        try:
            subprocess.run([self.exe, "stop"], env=self.env, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
        _matar_con(self.rt)
        shutil.rmtree(self.rt, ignore_errors=True)


def _matar_con(marca: str) -> None:
    """SIGKILL a todo proceso del usuario cuya línea de comandos contenga `marca` (daemon y Chrome)."""
    mio = os.getpid()
    for _ in range(3):
        vivos = []
        for p in Path("/proc").iterdir():
            if not p.name.isdigit() or int(p.name) == mio:
                continue
            try:
                if marca.encode() in (p / "cmdline").read_bytes():
                    vivos.append(int(p.name))
            except OSError:
                continue
        if not vivos:
            return
        for pid in vivos:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        time.sleep(0.3)


def _js(texto: str) -> str:
    return json.dumps(texto)


def _paso(nav: Navegador, paso: str, base: str) -> None:
    partes = paso.strip().split(" ", 2)
    verbo = partes[0]
    if verbo == "fill" and len(partes) == 3:
        f = ("() => { const e = document.querySelector(%s); if (!e) throw new Error('no existe ' + %s);"
             " e.focus(); e.value = %s; e.dispatchEvent(new Event('input', {bubbles: true}));"
             " e.dispatchEvent(new Event('change', {bubbles: true})); return true; }"
             % (_js(partes[1]), _js(partes[1]), _js(partes[2])))
        nav.cmd("evaluate_script", f)
    elif verbo == "click" and len(partes) >= 2:
        sel = paso.strip()[len("click"):].strip()
        f = ("() => { const e = document.querySelector(%s); if (!e) throw new Error('no existe ' + %s);"
             " e.click(); return true; }" % (_js(sel), _js(sel)))
        nav.cmd("evaluate_script", f)
    elif verbo == "esperar" and len(partes) == 2:
        time.sleep(int(partes[1]) / 1000)
    elif verbo == "ir" and len(partes) == 2:
        nav.cmd("navigate_page", "--type", "url", "--url", urllib.parse.urljoin(base, partes[1]))
    else:
        raise RuntimeError(f"paso no reconocido: {paso!r}")


def verificar(funcion: dict, conf: dict, raiz: Path, ctx) -> dict:
    exe = instalado()
    if not exe:
        return {"ok": False, "resumen": "chrome-devtools no instalado"}
    wconf = conf.get("web") or {}
    fconf = funcion["web"] or {}
    base = wconf.get("base_url") or ""
    url = urllib.parse.urljoin(base.rstrip("/") + "/", str(fconf.get("url") or "/").lstrip("/")) if base \
        else str(fconf.get("url"))
    ignorar = [re.compile(x) for x in (wconf.get("ignorar_red", IGNORAR_RED) or [])]
    captura = ctx.dir_evidencia / f"{ctx.prefijo}-{funcion['id']}.png"
    problemas: list[str] = []
    capturas: list[str] = []

    nav = Navegador(exe, float(wconf.get("timeout") or 60))
    try:
        nav.arrancar()
        nav.cmd("new_page", url)
        for p in fconf.get("pasos") or []:
            _paso(nav, p, url)
        time.sleep(float(wconf.get("espera_ms") or 300) / 1000)  # que terminen los recursos tardíos
        red = nav.json("list_network_requests", "--includePreservedRequests", "true").get("networkRequests") or []
        for r in red:
            try:
                st = int(str(r.get("status") or "0").split()[0])
            except ValueError:
                continue
            u = str(r.get("url") or "")
            if st >= 400 and not any(rx.search(u) for rx in ignorar):
                problemas.append(f"{st} {r.get('method') or 'GET'} {u}")
        con = nav.json("list_console_messages", "--includePreservedMessages", "true").get("consoleMessages") or []
        for m in con:
            texto = str(m.get("text") or "")
            if m.get("type") != "error" or texto.startswith("Failed to load resource"):
                continue  # los "Failed to load resource" ya salen, con su URL, en la lista de red
            problemas.append(f"console.error: {texto[:200]}")
        try:
            nav.cmd("take_screenshot", "--filePath", str(captura))
            if captura.exists():
                capturas.append(os.path.relpath(captura, raiz))
        except RuntimeError as e:
            problemas.append(f"sin captura: {e}")
    except (RuntimeError, subprocess.SubprocessError) as e:
        problemas.append(str(e))
    finally:
        nav.cerrar()

    resumen = (f"{len(problemas)} problema(s): " + "; ".join(problemas)) if problemas else f"{url} sin errores de red ni de consola"
    return {"ok": not problemas, "resumen": comun.redactar(resumen[:1000]), "capturas": capturas,
            "diffs": [comun.redactar("\n".join(problemas))] if problemas else []}
