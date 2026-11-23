"""Entorno común de los tests del frente C (no es un módulo de tests: no empieza por test_).

- ~/.claude falso: CLAUDE_HOME, MECANISMO_HOME y MECANISMO_BITACORA en un tmp.
- Los proyectos de fixture se copian a tmp y se les hace `git init` + commit antes de usarlos.
- Todo proceso que se arranca se registra y se mata en tearDown.
"""
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

RAIZ = pathlib.Path(__file__).resolve().parent.parent          # mecanismo/
FIXTURES = RAIZ / "tests" / "fixtures"
SERVIDOR_MCP = FIXTURES / "mcp" / "servidor.py"
HOOK = RAIZ / "hooks" / "stop-evidencia"


class EntornoC(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="mecanismo-c-"))
        self.procs: list[subprocess.Popen] = []
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_SESSION_ID", "FIXTURE_MCP_TOKEN")}
        self.env.update(CLAUDE_HOME=str(self.tmp / "claude"), MECANISMO_HOME=str(self.tmp / "mecanismo"),
                        MECANISMO_BITACORA=str(self.tmp / "bitacora.log"), PYTHONPATH=str(RAIZ))
        self.sid = "test-c-" + uuid.uuid4().hex  # sin marca en /tmp: corte = ahora - 30 min

    def tearDown(self):
        for p in self.procs:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                try:
                    p.wait(timeout=3)
                    break
                except subprocess.TimeoutExpired:
                    continue
            for f in (p.stdout, p.stderr):
                if f:
                    f.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ proyectos

    def proyecto(self, origen: pathlib.Path, nombre: str = "p", subs: dict | None = None) -> pathlib.Path:
        destino = self.tmp / nombre
        shutil.copytree(origen, destino)
        conf = destino / ".claude" / "mecanismo.yml"
        if conf.exists() and subs:
            t = conf.read_text()
            for k, v in subs.items():
                t = t.replace(k, v)
            conf.write_text(t)
        self.git(destino, "init", "-q")
        self.git(destino, "add", "-A")
        self.git(destino, "commit", "-q", "-m", "fixture")
        return destino

    def git(self, d, *args) -> str:
        r = subprocess.run(["git", "-C", str(d), "-c", "user.name=test", "-c", "user.email=test@ejemplo.invalid",
                            "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True)
        return r.stdout

    def editar_yml(self, raiz: pathlib.Path, rel: str, **cambios_mcp):
        """Cambia claves de la sección mcp de mecanismo.yml (para pasar de stdio a HTTP)."""
        import yaml
        p = raiz / rel
        d = yaml.safe_load(p.read_text())
        for k, v in cambios_mcp.items():
            if v is None:
                d["mcp"].pop(k, None)
            else:
                d["mcp"][k] = v
        p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False))

    def tocar(self, f: pathlib.Path, extra: str = "# cambio\n"):
        with open(f, "a") as h:
            h.write(extra)

    # ------------------------------------------------------------ procesos

    def lanzar(self, args, **kw) -> subprocess.Popen:
        p = subprocess.Popen(args, start_new_session=True, env=kw.pop("env", self.env), **kw)
        self.procs.append(p)
        return p

    def servidor_mcp_http(self, modo="ok", token=None) -> str:
        env = dict(self.env)
        if token:
            env["FIXTURE_MCP_TOKEN"] = token
        p = self.lanzar([sys.executable, str(SERVIDOR_MCP), "--http", "--modo", modo],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        linea = p.stdout.readline()
        m = re.match(r"PUERTO (\d+)", linea)
        self.assertTrue(m, f"el servidor no anunció su puerto: {linea!r}")
        return f"http://127.0.0.1:{m.group(1)}/mcp"

    def verificar(self, raiz, *args, env=None):
        return subprocess.run([sys.executable, "-c",
                               "import sys; from lib.evidencia.cli import main; sys.exit(main(sys.argv[1:]))",
                               "--dir", str(raiz), "--sid", self.sid, *args],
                              cwd=raiz, env=env or self.env, capture_output=True, text=True, timeout=180)

    def hook(self, entrada: dict, env=None):
        return subprocess.run([str(HOOK)], input=json.dumps(entrada), env=env or self.env,
                              cwd=entrada.get("cwd") or str(self.tmp), capture_output=True, text=True, timeout=60)

    # ------------------------------------------------------------ evidencia y bitácora

    def ultima_evidencia(self, raiz) -> dict:
        evs = sorted((pathlib.Path(raiz) / ".claude" / "evidencia").glob("*.json"))
        self.assertTrue(evs, "no se escribió evidencia")
        return json.loads(evs[-1].read_text())

    def comprobar_esquema(self, ev: dict):
        """Validación mínima contra esquemas/evidencia.schema.json (sin jsonschema: solo stdlib)."""
        esq = json.loads((RAIZ / "esquemas" / "evidencia.schema.json").read_text())
        self.assertEqual(set(ev), set(esq["properties"]))
        for k in esq["required"]:
            self.assertIn(k, ev)
        item = esq["properties"]["funciones"]["items"]
        for f in ev["funciones"]:
            self.assertTrue(set(item["required"]) <= set(f) <= set(item["properties"]), f)
            self.assertIsInstance(f["ok"], bool)
            self.assertIsInstance(f["duracion_ms"], int)
        self.assertEqual(ev["version"], 1)
        self.assertIn(ev["tipo"], esq["properties"]["tipo"]["enum"])
        for v in ev["huellas"].values():
            self.assertRegex(v, r"^[0-9a-f]{64}$")

    def bitacora(self) -> str:
        p = pathlib.Path(self.env["MECANISMO_BITACORA"])
        return p.read_text() if p.exists() else ""

    def esperar(self, cond, segundos=10):
        fin = time.time() + segundos
        while time.time() < fin:
            if cond():
                return True
            time.sleep(0.1)
        return False
