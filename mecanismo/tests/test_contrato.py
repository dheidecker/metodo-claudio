"""F0: el contrato que los frentes A–E dan por hecho. Si esto falla, ningún frente arranca."""
import inspect
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from lib import comun

RAIZ = pathlib.Path(__file__).resolve().parent.parent


class Entorno(unittest.TestCase):
    """Cada test con su ~/.claude falso: nunca se escribe en el real."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._env = {k: os.environ.get(k) for k in ("CLAUDE_HOME", "MECANISMO_HOME", "MECANISMO_BITACORA", "CLAUDE_PROJECT_DIR")}
        os.environ["CLAUDE_HOME"] = str(self.tmp / "claude")
        os.environ.pop("MECANISMO_HOME", None)
        os.environ.pop("MECANISMO_BITACORA", None)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestFirmas(unittest.TestCase):
    def test_api_congelada(self):
        esperado = {
            "claude_home": [], "estado_dir": [], "bitacora_path": [], "raiz_mecanismo": [], "raiz_proyecto": ["cwd"],
            "bitacora": ["hook", "resultado", "proyecto"], "redactar": ["texto"],
            "marca_sesion": ["sid"], "desde_sesion": ["sid", "minutos_sin_marca"], "repos_de": ["base"],
            "archivos_cambiados": ["base", "desde"], "lineas_cambiadas": ["archivo"], "sha256_archivo": ["archivo"],
            "iterar_transcripts": ["dias", "proyecto"], "es_prompt_humano": ["e"], "texto_de": ["e"],
            "iterar_history": ["dias"], "leer_yaml": ["path"], "leer_stdin_json": [],
            "salida_hook": ["evento", "mensaje", "bloquear"], "exige_tty": ["accion"],
        }
        for nombre, params in esperado.items():
            self.assertEqual(list(inspect.signature(getattr(comun, nombre)).parameters), params, nombre)
        self.assertTrue(issubclass(comun.SinPyYAML, RuntimeError))
        self.assertEqual(comun.raiz_mecanismo(), RAIZ)


class TestBitacora(Entorno):
    def test_formato_compatible_con_informe_sh(self):
        comun.bitacora("trampas", "AVISO tx-con-llamada-externa x.go", proyecto="sepa-mcp")
        linea = comun.bitacora_path().read_text().splitlines()[-1]
        campos = linea.split(" | ")
        self.assertEqual(len(campos), 4, linea)
        time.strptime(campos[0], "%Y-%m-%d %H:%M:%S")
        self.assertEqual(len(campos[1]), 22)
        self.assertEqual(campos[1].strip(), "trampas")
        self.assertEqual(campos[2].strip(), "sepa-mcp")
        self.assertEqual(campos[3].split()[0], "AVISO")
        # informe.sh lo agrupa igual que las líneas de los hooks bash
        informe = RAIZ.parent / "hooks" / "informe.sh"
        env = dict(os.environ, HOME=str(self.tmp / "home"))
        (self.tmp / "home" / ".claude").mkdir(parents=True)
        (self.tmp / "home" / ".claude" / "metodo-claudio.log").write_text(comun.bitacora_path().read_text())
        out = subprocess.run(["bash", str(informe), "1"], capture_output=True, text=True, env=env).stdout
        self.assertIn("trampas · AVISO", out)

    def test_estado_dir_respeta_entorno(self):
        os.environ["MECANISMO_HOME"] = str(self.tmp / "m")
        self.assertEqual(comun.estado_dir(), self.tmp / "m")
        self.assertTrue((self.tmp / "m").is_dir())


class TestRedactar(unittest.TestCase):
    CASOS = {
        "jwt": "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJDQU5BUklPIn0.abcDEF_123 fin",
        "anthropic": "clave sk-ant-api03-CANARIOxxxxxxxxxxxx",
        "github": "ghp_CANARIO1234567890abcdef y github_pat_CANARIO_123456789",
        "bearer": "Authorization: Bearer CANARIOabc.def-123",
        "sanctum": "token 42|CANARIOabcdefghijklmnop",
        "dsn": "postgres://app:CANARIO-pass@db.interno:5432/sepa",
        "pem": "-----BEGIN PRIVATE KEY-----\nCANARIO\nMIIE\n-----END PRIVATE KEY-----",
        "correo": "escríbele a canario.CANARIO@ejemplo.cl mañana",
    }

    def test_ningun_canario_sobrevive(self):
        for tipo, txt in self.CASOS.items():
            r = comun.redactar(txt)
            self.assertNotIn("CANARIO", r, f"{tipo}: {r}")
            self.assertIn(f"[REDACTADO:{tipo}]", r, f"{tipo}: {r}")

    def test_idempotente_y_no_toca_texto_normal(self):
        t = "orquesta varios agentes en paralelo, 3 | 4 frentes, rama main"
        self.assertEqual(comun.redactar(t), t)
        r = comun.redactar(self.CASOS["jwt"])
        self.assertEqual(comun.redactar(r), r)


class TestCambios(Entorno):
    def _git(self, *a):
        subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)

    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")
        (self.repo / "a.txt").write_text("uno\ndos\ntres\ncuatro\n")
        self._git("add", "a.txt")
        self._git("commit", "-qm", "x")

    def test_lineas_cambiadas(self):
        f = self.repo / "a.txt"
        self.assertEqual(comun.lineas_cambiadas(f), set())
        f.write_text("uno\nDOS\ntres\ncuatro\ncinco\n")
        self.assertEqual(comun.lineas_cambiadas(f), {2, 5})
        nuevo = self.repo / "b.txt"
        nuevo.write_text("x\n")
        self.assertIsNone(comun.lineas_cambiadas(nuevo))
        fuera = self.tmp / "suelto.txt"
        fuera.write_text("x\n")
        self.assertIsNone(comun.lineas_cambiadas(fuera))

    def test_archivos_cambiados(self):
        corte = time.time() - 1
        (self.repo / "a.txt").write_text("cambiado\n")
        (self.repo / "nuevo.txt").write_text("x\n")
        got = [p.name for p in comun.archivos_cambiados(self.repo, corte)]
        self.assertEqual(got, ["a.txt", "nuevo.txt"])
        self.assertEqual(comun.archivos_cambiados(self.repo, time.time() + 60), [])
        # repos anidados a un nivel (caso tickets/)
        self.assertEqual([p.name for p in comun.archivos_cambiados(self.tmp, corte)], ["a.txt", "nuevo.txt"])

    def test_sin_git_usa_mtime(self):
        d = self.tmp / "plano"
        (d / "node_modules").mkdir(parents=True)
        (d / "node_modules" / "x.js").write_text("x")
        corte = time.time() - 1
        (d / "f.py").write_text("x")
        self.assertEqual([p.name for p in comun.archivos_cambiados(d, corte)], ["f.py"])

    def test_desde_sesion_sin_marca(self):
        t = comun.desde_sesion("no-existe-" + str(time.time()))
        self.assertAlmostEqual(t, time.time() - 1800, delta=5)


class TestTranscripts(Entorno):
    def test_prompts_humanos_y_history(self):
        p = comun.claude_home() / "projects" / "-home-x-Proyectos-demo"
        p.mkdir(parents=True)
        entradas = [
            {"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": "lanza en paralelo"}},
            {"type": "user", "origin": {"kind": "peer"}, "message": {"content": "<agent-message>"}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]},
             "permissionDecision": {"decision": "accept", "source": "user_temporary"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hola"}]}},
        ]
        (p / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in entradas) + "\nbasura no json\n")
        todas = [e for _, e in comun.iterar_transcripts()]
        self.assertEqual(len(todas), 4)
        humanos = [comun.texto_de(e) for e in todas if comun.es_prompt_humano(e)]
        self.assertEqual(humanos, ["lanza en paralelo"])
        self.assertEqual(comun.texto_de(entradas[3]), "hola")
        self.assertEqual(list(comun.iterar_transcripts(proyecto="otro")), [])
        h = comun.claude_home() / "history.jsonl"
        now = int(time.time() * 1000)
        h.write_text(json.dumps({"display": "viejo", "timestamp": now - 100 * 86400000, "project": "/p"}) + "\n" +
                     json.dumps({"display": "nuevo", "timestamp": now, "project": "/p"}) + "\n")
        self.assertEqual([e["display"] for e in comun.iterar_history(dias=30)], ["nuevo"])


class TestHooks(Entorno):
    def test_salida_hook(self):
        import contextlib, io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(comun.salida_hook("PostToolUse", None), 0)
            self.assertEqual(comun.salida_hook("PostToolUse", "ojo"), 0)
            self.assertEqual(comun.salida_hook("Stop", "para", bloquear=True), 2)
        j = json.loads(out.getvalue())
        self.assertEqual(j["hookSpecificOutput"]["additionalContext"], "ojo")
        self.assertIn("para", err.getvalue())

    def test_exige_tty_sin_terminal(self):
        r = subprocess.run([sys.executable, "-c", "from lib import comun; comun.exige_tty('aprobar')"],
                           cwd=RAIZ, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, MECANISMO_TTY_FALSO="1"))
        self.assertEqual(r.returncode, 3, r.stderr)

    def test_canario_anota_en_bitacora(self):
        ev = {"hook_event_name": "Notification", "notification_type": "permission_prompt", "cwd": "/x/demo"}
        r = subprocess.run([str(RAIZ / "hooks" / "canario-permisos")], input=json.dumps(ev),
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        linea = comun.bitacora_path().read_text().splitlines()[-1].split(" | ")
        self.assertEqual([c.strip() for c in linea[1:]], ["canario-permisos", "demo", "EVENTO Notification permission_prompt"])

    def test_leer_yaml(self):
        f = self.tmp / "t.yml"
        f.write_text("- id: a\n  nivel: aviso\n")
        self.assertEqual(comun.leer_yaml(f), [{"id": "a", "nivel": "aviso"}])


class TestEsquemas(unittest.TestCase):
    """Los esquemas existen, son JSON válido y los ejemplos de CONTRATO.md cumplen sus `required`."""

    def _req(self, esquema, doc):
        faltan = [k for k in esquema.get("required", []) if k not in doc]
        self.assertEqual(faltan, [], esquema["title"])

    def test_esquemas(self):
        import yaml
        e = {n: json.loads((RAIZ / "esquemas" / f"{n}.schema.json").read_text())
             for n in ("trampa", "propuesta", "evidencia", "mecanismo", "mapa")}
        trampa = yaml.safe_load((RAIZ / "PLAN.md").read_text().split("```yaml\n")[1].split("```")[0])
        self._req(e["trampa"], trampa)
        self.assertLessEqual(set(trampa), set(e["trampa"]["properties"]))
        bloques = (RAIZ / "CONTRATO.md").read_text().split("```")
        yamls = [yaml.safe_load(b[len("yaml\n"):]) for b in bloques if b.startswith("yaml\n")]
        jsons = [json.loads(b[len("json\n"):]) for b in bloques if b.startswith("json\n")]
        prop, mec, mapa = yamls
        self._req(e["propuesta"], prop)
        self._req(e["mecanismo"], mec)
        self._req(e["mapa"], mapa)
        for f in mapa["funciones"]:
            self.assertEqual(sum(k in f for k in ("mcp", "web", "test")), 1, f["id"])
        self._req(e["evidencia"], jsons[0])
        self.assertEqual(set(jsons[0]), set(e["evidencia"]["properties"]))


if __name__ == "__main__":
    unittest.main()
