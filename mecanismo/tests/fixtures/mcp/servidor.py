#!/usr/bin/env python3
"""Servidor MCP de prueba (stdlib) para el adaptador mcp del frente C.

    servidor.py [--modo ok|roto] [--http [--puerto N]]

- stdio por defecto (JSON-RPC por líneas); con --http, POST /mcp en 127.0.0.1 (puerto 0 = libre),
  e imprime `PUERTO <n>` en stdout al quedar escuchando.
- HTTP: tools/call responde como SSE y lo demás como JSON (cubre las dos formas del transporte).
  Si FIXTURE_MCP_TOKEN está definido exige `Authorization: Bearer <token>` (401 si no).
- Tools: `saludar` y `sumar`. Cada respuesta lleva campos volátiles (query_id, request_id).
- Modo `roto`: sumar(2, 3) devuelve 6.
"""
import argparse
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = [
    {"name": "saludar", "description": "Saluda por nombre.",
     "inputSchema": {"type": "object", "properties": {"nombre": {"type": "string"}}, "required": ["nombre"]},
     "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}},
    {"name": "sumar", "description": "Suma dos enteros.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"},
                                                      "version_nueva": {"type": "boolean"}},
                     "required": ["a", "b"]},
     "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}},
]

MODO = "ok"


def _texto(obj) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}], "isError": False}


def llamar(nombre: str, args: dict) -> dict:
    if nombre == "saludar":
        return _texto({"saludo": f"hola {args.get('nombre', '')}", "query_id": str(uuid.uuid4())})
    if nombre == "sumar":
        a, b = int(args.get("a", 0)), int(args.get("b", 0))
        r = a + b + (1 if MODO == "roto" and (a, b) == (2, 3) else 0)
        return _texto({"resultado": r, "query_id": str(uuid.uuid4()),
                       "meta": {"request_id": uuid.uuid4().hex, "version": "2" if args.get("version_nueva") else "1"}})
    return {"content": [{"type": "text", "text": f"tool desconocida: {nombre}"}], "isError": True}


def responder(msg: dict) -> dict | None:
    """None para notificaciones."""
    if "id" not in msg:
        return None
    m, p, mid = msg.get("method"), msg.get("params") or {}, msg["id"]
    if m == "initialize":
        res = {"protocolVersion": p.get("protocolVersion") or "2025-06-18",
               "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture-mcp", "version": "1"}}
    elif m == "tools/list":
        res = {"tools": TOOLS}
    elif m == "tools/call":
        res = llamar(p.get("name"), p.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"método {m}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def stdio():
    for linea in sys.stdin:
        try:
            msg = json.loads(linea)
        except ValueError:
            continue
        r = responder(msg)
        if r is not None:
            sys.stdout.write(json.dumps(r) + "\n")
            sys.stdout.flush()


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        tok = os.environ.get("FIXTURE_MCP_TOKEN")
        if tok and self.headers.get("Authorization") != f"Bearer {tok}":
            self.send_response(401)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            msg = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        r = responder(msg)
        if r is None:
            self.send_response(202)
            self.end_headers()
            return
        if msg.get("method") == "tools/call":
            # SSE: una notificación de progreso antes de la respuesta, como un servidor real
            ruido = json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}})
            cuerpo = f"event: message\ndata: {ruido}\n\nevent: message\ndata: {json.dumps(r)}\n\n".encode()
            tipo = "text/event-stream"
        else:
            cuerpo, tipo = json.dumps(r).encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        if msg.get("method") == "initialize":
            self.send_header("Mcp-Session-Id", uuid.uuid4().hex)
        self.end_headers()
        self.wfile.write(cuerpo)


def main():
    global MODO
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["ok", "roto"], default="ok")
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--puerto", type=int, default=0)
    a = ap.parse_args()
    MODO = a.modo
    if not a.http:
        stdio()
        return
    srv = ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador)
    print(f"PUERTO {srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
