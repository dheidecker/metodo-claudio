"""Vía `mcp`: cliente MCP en stdlib (HTTP streamable o stdio) contra goldens.

mecanismo.yml:
    mcp: {url: "http://host/mcp", token_env: MCP_TOKEN, golden: ".claude/verificacion/golden",
          ignorar: [query_id, request_id, firma]}            # o {comando: "python3 servidor.py"}
mapa-funciones.yml:
    - id: consultar
      mcp: {tool: consultar, casos: ".claude/verificacion/casos/consultar.yaml"}

Casos: el formato de mcp-sempat/testdata/golden/casos.yaml — `{"casos": [{nombre, descripcion,
mcp: <argumentos>, divergencias: [{clave, motivo}]}]}` (también vale `argumentos`, o una lista suelta).
Goldens: `<golden>/tools-list.json` y `<golden>/<tool>/<nombre>.json`.

Comparación: los campos de `ignorar` se quitan a cualquier profundidad (también dentro de un
`content[].text` que sea JSON); `tools/list` compara nombre, anotaciones y esquemas, sin orden;
una diferencia cuya ruta casa con la `clave` de una divergencia declarada (exacta o glob) se acepta.
"""
from __future__ import annotations

import difflib
import fnmatch
import json
import os
import queue
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from lib import comun
from lib.evidencia import nucleo

PROTOCOLO = "2025-06-18"
TIMEOUT = 30


class ErrorMCP(RuntimeError):
    pass


# ---------------------------------------------------------------- transportes

class _Base:
    def __init__(self):
        self._id = 0

    def _siguiente(self) -> int:
        self._id += 1
        return self._id

    def pedir(self, metodo: str, params: dict | None = None) -> dict:
        """Devuelve el objeto JSON-RPC de respuesta entero ({result} o {error})."""
        raise NotImplementedError

    def notificar(self, metodo: str, params: dict | None = None) -> None:
        raise NotImplementedError

    def cerrar(self) -> None:
        pass


class HTTP(_Base):
    def __init__(self, url: str, token: str | None = None, timeout: float = TIMEOUT):
        super().__init__()
        self.url, self.token, self.timeout = url, token, timeout
        self.sesion: str | None = None
        self.protocolo: str | None = None

    def _post(self, cuerpo: dict):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.sesion:
            h["Mcp-Session-Id"] = self.sesion
        if self.protocolo:
            h["MCP-Protocol-Version"] = self.protocolo
        req = urllib.request.Request(self.url, data=json.dumps(cuerpo).encode(), headers=h, method="POST")
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)  # noqa: S310 — url declarada por el proyecto
        except urllib.error.HTTPError as e:
            pista = " (¿falta el token de token_env?)" if e.code in (401, 403) else ""
            raise ErrorMCP(f"HTTP {e.code} en {cuerpo.get('method')}{pista}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ErrorMCP(f"no conecta con {self.url}: {getattr(e, 'reason', e)}") from None

    def pedir(self, metodo, params=None):
        mid = self._siguiente()
        with self._post({"jsonrpc": "2.0", "id": mid, "method": metodo, "params": params or {}}) as r:
            if r.headers.get("Mcp-Session-Id"):
                self.sesion = r.headers["Mcp-Session-Id"]
            tipo = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            if tipo == "text/event-stream":
                return _de_sse(r, mid)
            try:
                d = json.loads(r.read().decode("utf-8") or "null")
            except ValueError as e:
                raise ErrorMCP(f"respuesta no JSON a {metodo}: {e}") from None
        if isinstance(d, list):  # lote
            d = next((x for x in d if isinstance(x, dict) and x.get("id") == mid), None)
        if not isinstance(d, dict):
            raise ErrorMCP(f"respuesta vacía a {metodo}")
        return d

    def notificar(self, metodo, params=None):
        cuerpo = {"jsonrpc": "2.0", "method": metodo}
        if params:
            cuerpo["params"] = params
        with self._post(cuerpo) as r:
            r.read()


def _de_sse(r, mid: int) -> dict:
    """Lee eventos SSE hasta la respuesta con id == mid (ignora notificaciones intermedias)."""
    datos: list[str] = []
    for crudo in r:
        linea = crudo.decode("utf-8", errors="replace").rstrip("\r\n")
        if linea.startswith("data:"):
            datos.append(linea[5:].lstrip(" "))
            continue
        if linea == "" and datos:
            try:
                d = json.loads("\n".join(datos))
            except ValueError:
                d = None
            datos = []
            if isinstance(d, dict) and d.get("id") == mid and ("result" in d or "error" in d):
                return d
    raise ErrorMCP(f"el stream SSE terminó sin respuesta al id {mid}")


class Stdio(_Base):
    def __init__(self, comando: str, cwd: Path, timeout: float = TIMEOUT):
        super().__init__()
        self.timeout = timeout
        self.err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(comando, shell=True, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.err, start_new_session=True)
        self.cola: queue.Queue = queue.Queue()
        threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self):
        for linea in self.proc.stdout:
            self.cola.put(linea)
        self.cola.put(None)

    def _escribir(self, d: dict):
        try:
            self.proc.stdin.write((json.dumps(d) + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise ErrorMCP("el servidor stdio se cerró" + self._stderr()) from None

    def _stderr(self) -> str:
        try:
            self.err.seek(0)
            t = self.err.read().decode("utf-8", errors="replace").strip().splitlines()[-3:]
            return (": " + " | ".join(t)) if t else ""
        except OSError:
            return ""

    def pedir(self, metodo, params=None):
        mid = self._siguiente()
        self._escribir({"jsonrpc": "2.0", "id": mid, "method": metodo, "params": params or {}})
        while True:
            try:
                linea = self.cola.get(timeout=self.timeout)
            except queue.Empty:
                raise ErrorMCP(f"sin respuesta a {metodo} en {self.timeout:.0f} s") from None
            if linea is None:
                raise ErrorMCP(f"el servidor stdio terminó antes de responder a {metodo}" + self._stderr())
            try:
                d = json.loads(linea)
            except ValueError:
                continue  # el servidor ensució stdout: no es JSON-RPC
            if isinstance(d, dict) and d.get("id") == mid and ("result" in d or "error" in d):
                return d

    def notificar(self, metodo, params=None):
        cuerpo = {"jsonrpc": "2.0", "method": metodo}
        if params:
            cuerpo["params"] = params
        self._escribir(cuerpo)

    def cerrar(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        nucleo.matar_grupo(self.proc)
        self.err.close()


# ---------------------------------------------------------------- sesión

class Sesion:
    """initialize → notifications/initialized; tools/list se pide una vez por corrida."""

    def __init__(self, transporte: _Base):
        self.t = transporte
        r = self.t.pedir("initialize", {"protocolVersion": PROTOCOLO, "capabilities": {},
                                        "clientInfo": {"name": "mecanismo", "version": "1"}})
        if "error" in r:
            raise ErrorMCP(f"initialize falló: {r['error']}")
        if isinstance(self.t, HTTP):
            self.t.protocolo = (r.get("result") or {}).get("protocolVersion") or PROTOCOLO
        self.t.notificar("notifications/initialized")
        self._tools: list | None = None

    def tools(self) -> list:
        if self._tools is None:
            todas, cursor = [], None
            while True:
                r = self.t.pedir("tools/list", {"cursor": cursor} if cursor else {})
                if "error" in r:
                    raise ErrorMCP(f"tools/list falló: {r['error']}")
                res = r.get("result") or {}
                todas += res.get("tools") or []
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            self._tools = todas
        return self._tools

    def llamar(self, tool: str, args: dict) -> dict:
        r = self.t.pedir("tools/call", {"name": tool, "arguments": args or {}})
        return {"error": r["error"]} if "error" in r else (r.get("result") or {})

    def cerrar(self):
        self.t.cerrar()


def abrir(mconf: dict, raiz: Path) -> Sesion:
    if mconf.get("url"):
        tok = os.environ.get(mconf["token_env"]) if mconf.get("token_env") else None
        return Sesion(HTTP(mconf["url"], tok, float(mconf.get("timeout") or TIMEOUT)))
    if mconf.get("comando"):
        return Sesion(Stdio(mconf["comando"], raiz, float(mconf.get("timeout") or TIMEOUT)))
    raise ErrorMCP("mecanismo.yml: mcp necesita `url` o `comando`")


# ---------------------------------------------------------------- normalización y diff

def _texto_json(v):
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def normalizar(v, ignorar: set[str]):
    """Quita las claves volátiles a cualquier profundidad y abre los `text` que son JSON."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k in ignorar:
                continue
            if k == "text":
                x = _texto_json(x)
            out[k] = normalizar(x, ignorar)
        return out
    if isinstance(v, list):
        return [normalizar(x, ignorar) for x in v]
    return v


def normalizar_tools(tools: list, ignorar: set[str]) -> dict:
    """{nombre: {annotations, inputSchema, outputSchema}}: sin orden y sin descripciones."""
    out = {}
    for t in tools or []:
        if not isinstance(t, dict) or "name" not in t:
            continue
        d = {k: t[k] for k in ("annotations", "inputSchema", "outputSchema") if k in t}
        out[t["name"]] = _ordenar_required(normalizar(d, ignorar))
    return out


def _ordenar_required(v):
    if isinstance(v, dict):
        return {k: (sorted(x) if k == "required" and isinstance(x, list) and all(isinstance(i, str) for i in x)
                    else _ordenar_required(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [_ordenar_required(x) for x in v]
    return v


def aplanar(v, ruta: str = "") -> dict[str, str]:
    """{"content/0/text/resultado": "5", ...}; contenedores vacíos cuentan como hoja."""
    if isinstance(v, dict) and v:
        out = {}
        for k in v:
            out.update(aplanar(v[k], f"{ruta}/{k}" if ruta else str(k)))
        return out
    if isinstance(v, list) and v:
        out = {}
        for i, x in enumerate(v):
            out.update(aplanar(x, f"{ruta}/{i}" if ruta else str(i)))
        return out
    return {ruta or "/": json.dumps(v, ensure_ascii=False, sort_keys=True)}


def comparar(golden, actual, divergencias: list | None, nombre_g: str, nombre_a: str) -> str | None:
    """None si coinciden (salvo divergencias declaradas); si no, el diff unificado."""
    claves = [str(d.get("clave")) for d in divergencias or [] if isinstance(d, dict) and d.get("clave")]
    g, a = aplanar(golden), aplanar(actual)

    def aceptada(r):
        return any(r == c or fnmatch.fnmatchcase(r, c) or r.startswith(c.rstrip("/") + "/") for c in claves)

    distintas = [r for r in set(g) | set(a) if g.get(r) != a.get(r) and not aceptada(r)]
    if not distintas:
        return None
    lg = [f"{r} = {g[r]}" for r in sorted(g) if not aceptada(r)]
    la = [f"{r} = {a[r]}" for r in sorted(a) if not aceptada(r)]
    return "\n".join(difflib.unified_diff(lg, la, nombre_g, nombre_a, lineterm="", n=2))


# ---------------------------------------------------------------- casos y goldens

def leer_casos(p: Path) -> list[dict]:
    d = comun.leer_yaml(p)
    casos = d.get("casos") if isinstance(d, dict) else d
    return [c for c in casos or [] if isinstance(c, dict) and c.get("nombre")]


def _leer_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _grabar_json(p: Path, v) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verificar(funcion: dict, conf: dict, raiz: Path, ctx) -> dict:
    mconf = conf.get("mcp") or {}
    fconf = funcion["mcp"] or {}
    tool = fconf.get("tool") or funcion["id"]
    ignorar = set(mconf.get("ignorar") or [])
    golden = raiz / (mconf.get("golden") or ".claude/verificacion/golden")
    diffs: list[str] = []
    problemas: list[str] = []

    try:
        s = ctx.recursos.get("mcp")
        if s is None:
            s = ctx.recursos["mcp"] = abrir(mconf, raiz)
        tools_actual = normalizar_tools(s.tools(), ignorar)
    except ErrorMCP as e:
        return {"ok": False, "resumen": comun.redactar(str(e))}

    # tools/list: se compara entero, sin orden
    pg = golden / "tools-list.json"
    if ctx.grabar:
        _grabar_json(pg, tools_actual)
    tg = _leer_json(pg)
    if tg is None:
        problemas.append("falta golden tools-list.json")
    else:
        d = comparar(tg, tools_actual, None, "golden/tools-list.json", "actual/tools/list")
        if d:
            problemas.append("tools/list difiere")
            diffs.append(d)
    if tool not in tools_actual:
        problemas.append(f"el servidor no expone la tool {tool}")

    # casos
    casos_p = raiz / fconf["casos"] if fconf.get("casos") else None
    casos = leer_casos(casos_p) if casos_p and casos_p.is_file() else []
    if casos_p and not casos:
        problemas.append(f"sin casos en {fconf['casos']}")
    rotos: list[str] = []
    for c in casos:
        args = c.get("argumentos", c.get("mcp")) or {}
        t = c.get("tool") or tool
        try:
            actual = normalizar(s.llamar(t, args), ignorar)
        except ErrorMCP as e:
            rotos.append(c["nombre"])
            diffs.append(f"caso {c['nombre']}: {e}")
            continue
        pc = golden / t / f"{c['nombre']}.json"
        if ctx.grabar:
            _grabar_json(pc, actual)
        esperado = _leer_json(pc)
        if esperado is None:
            rotos.append(c["nombre"])
            diffs.append(f"caso {c['nombre']}: falta golden {os.path.relpath(pc, raiz)}")
            continue
        d = comparar(esperado, actual, c.get("divergencias"),
                     f"golden/{t}/{c['nombre']}.json", f"actual/{t}/{c['nombre']}")
        if d:
            rotos.append(c["nombre"])
            diffs.append(d)

    if rotos:
        problemas.insert(0, f"{len(rotos)} de {len(casos)} casos difiere: {', '.join(rotos)}")
    resumen = "; ".join(problemas) if problemas else f"{len(casos)} casos y tools/list coinciden con el golden"
    return {"ok": not problemas, "resumen": comun.redactar(resumen),
            "diffs": [comun.redactar(d) for d in diffs]}
