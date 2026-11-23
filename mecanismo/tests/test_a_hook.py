"""Frente A: hooks/trampas (PostToolUse y --stop) y la CLI `trampas`, contra repos git en tmp."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import yaml

RAIZ = pathlib.Path(__file__).resolve().parent.parent
HOOK = RAIZ / "hooks" / "trampas"
FIX = RAIZ / "tests" / "fixtures" / "blade"

BLOQUEO = {"id": "sin-debug", "nivel": "bloqueo", "globs": ["**/*.py"], "patron": r"breakpoint\(\)",
           "mensaje": "quita el breakpoint", "origen": "test", "prueba": {"dispara": "breakpoint()", "no_dispara": "x"}}


class Base(unittest.TestCase):
    """~/.claude falso y un repo git en tmp con las trampas de blade más una de bloqueo."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._env = {k: os.environ.get(k) for k in
                     ("HOME", "CLAUDE_HOME", "MECANISMO_HOME", "MECANISMO_BITACORA", "CLAUDE_PROJECT_DIR")}
        os.environ["HOME"] = str(self.tmp / "home")
        os.environ["CLAUDE_HOME"] = str(self.tmp / "home" / ".claude")
        os.environ["MECANISMO_HOME"] = str(self.tmp / "mecanismo")
        os.environ["MECANISMO_BITACORA"] = str(self.tmp / "bitacora.log")
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.p = self.tmp / "proyecto"
        tr = self.p / ".claude" / "trampas"
        tr.mkdir(parents=True)
        shutil.copy(FIX / "blade.yml", tr / "blade.yml")
        (tr / "bloqueo.yml").write_text(yaml.safe_dump(BLOQUEO))
        self.git("init", "-q")
        self.vista = self.p / "resources" / "views" / "v.blade.php"
        self.vista.parent.mkdir(parents=True)
        self.vista.write_text('<div x-init="a(); b()">\n<p>x</p>\n')
        self.git("add", str(self.vista))
        self.git("commit", "-qm", "base")

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def git(self, *a):
        subprocess.run(["git", "-C", str(self.p), "-c", "user.email=t@t", "-c", "user.name=t",
                        "-c", "commit.gpgsign=false", *a], check=True, capture_output=True)

    def hook(self, d, *args, env=None):
        return subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps(d), capture_output=True,
                              text=True, cwd=self.p, env=env or dict(os.environ))

    def post(self, f, **kw):
        return self.hook({"tool_input": {"file_path": str(f)}, "cwd": str(self.p)}, **kw)

    def bitacora(self):
        try:
            txt = pathlib.Path(os.environ["MECANISMO_BITACORA"]).read_text()
        except OSError:
            return []
        return [[c.strip() for c in l.split(" | ")[1:]] for l in txt.splitlines()]


class TestPostToolUse(Base):
    def test_aviso_solo_en_lineas_cambiadas(self):
        r = self.post(self.vista)
        self.assertEqual((r.returncode, r.stdout), (0, ""))  # seguido y sin cambios
        self.assertEqual(self.bitacora()[-1], ["trampas", "proyecto", "silencio v.blade.php"])
        self.vista.write_text('<div x-init="a(); b()">\n<p>x</p>\n<div x-init="c(); d()">\n')
        r = self.post(self.vista)
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        self.assertIn("- x-init-con-bloque (líneas 3):", j["systemMessage"])
        self.assertEqual(j["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(self.bitacora()[-1], ["trampas", "proyecto", "AVISO x-init-con-bloque v.blade.php"])

    def test_sin_seguimiento_mira_todo_y_tool_response(self):
        f = self.p / "nuevo.blade.php"
        f.write_text('<div x-init="a(); b()">\n    // @push("x")\n')
        r = self.hook({"tool_response": {"filePath": str(f)}, "cwd": str(self.p)})
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertIn("x-init-con-bloque (líneas 1)", msg)
        self.assertIn("directiva-en-comentario-js (líneas 2)", msg)
        self.assertEqual(len([l for l in self.bitacora() if l[2].startswith("AVISO")]), 2)

    def test_bloqueo_sale_con_2(self):
        f = self.p / "app.py"
        f.write_text("x = 1\nbreakpoint()\n")
        r = self.post(f)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertIn("sin-debug [bloqueo] (líneas 2)", r.stderr)
        self.assertEqual(self.bitacora()[-1], ["trampas", "proyecto", "BLOQUEO sin-debug app.py"])

    def test_sin_trampas_no_anota_y_entradas_raras(self):
        otro = self.tmp / "otro"
        otro.mkdir()
        (otro / "a.blade.php").write_text('<div x-init="a(); b()">\n')
        r = self.hook({"tool_input": {"file_path": str(otro / "a.blade.php")}, "cwd": str(otro)})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        for d in ({}, {"tool_input": {"file_path": "/no/existe"}}, {"tool_input": "raro"}):
            self.assertEqual(self.hook(d).returncode, 0)
        self.assertEqual(self.bitacora(), [])
        r = subprocess.run([sys.executable, str(HOOK)], input="no es json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_trampa_rota_se_anota_y_no_rompe(self):
        (self.p / ".claude" / "trampas" / "rota.yml").write_text(yaml.safe_dump({"id": "rota", "patron": "(["}))
        f = self.p / "app.py"
        f.write_text("breakpoint()\n")
        r = self.post(f)
        self.assertEqual(r.returncode, 2)
        self.assertTrue(any(l[2].startswith("error trampa-invalida rota") for l in self.bitacora()))

    def test_sin_pyyaml(self):
        falso = self.tmp / "sinyaml"
        falso.mkdir()
        (falso / "yaml.py").write_text("raise ImportError('sin PyYAML (test)')\n")
        env = dict(os.environ, PYTHONPATH=str(falso))
        r = self.post(self.vista, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.bitacora()[-1][2], "sin-pyyaml")
        r = subprocess.run([sys.executable, "-m", "lib.trampas.cli", "--probar", str(FIX)], cwd=RAIZ,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 4)
        self.assertIn("python3-yaml", r.stderr)


class TestStop(Base):
    def test_arbol_cambiado(self):
        sid = "test-%d" % time.time_ns()
        marca = pathlib.Path(f"/tmp/lint-marca-{sid}")
        marca.touch()
        self.addCleanup(marca.unlink, True)
        os.utime(marca, (time.time() - 10, time.time() - 10))
        self.vista.write_text('<div x-init="a(); b()">\n<div x-init="c(); d()">\n')  # sed/heredoc: sin PostToolUse
        mig = self.p / "database" / "migrations" / "2026_x.php"
        mig.parent.mkdir(parents=True)
        mig.write_text("$table->timestamp('a');\n")
        d = {"session_id": sid, "cwd": str(self.p), "stop_hook_active": False}
        r = self.hook(d, "--stop")
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        self.assertEqual(set(j), {"systemMessage"})
        self.assertIn("resources/views/v.blade.php:", j["systemMessage"])
        self.assertIn("x-init-con-bloque (líneas 2)", j["systemMessage"])
        self.assertIn("timestamp-sin-nullable (líneas 1)", j["systemMessage"])
        self.assertEqual(sorted(l[2] for l in self.bitacora() if l[0] == "trampas-stop"),
                         ["AVISO timestamp-sin-nullable 2026_x.php", "AVISO x-init-con-bloque v.blade.php"])
        # un bloqueo en Stop solo avisa
        (self.p / "app.py").write_text("breakpoint()\n")
        r = self.hook(d, "--stop")
        self.assertEqual(r.returncode, 0)
        self.assertIn("sin-debug", json.loads(r.stdout)["systemMessage"])
        # respeta stop_hook_active
        r = self.hook(dict(d, stop_hook_active=True), "--stop")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        # la CLI --arbol ve lo mismo
        r = subprocess.run([sys.executable, "-c", "import sys; from lib.trampas.cli import main; "
                            "sys.exit(main(sys.argv[1:]))", "--arbol", "--sid", sid],
                           cwd=RAIZ, capture_output=True, text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.p)))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("resources/views/v.blade.php:2:x-init-con-bloque", r.stdout.splitlines())

    def test_stop_silencio(self):
        r = self.hook({"session_id": "nadie", "cwd": str(self.p)}, "--stop")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.bitacora()[-1], ["trampas-stop", "proyecto", "silencio"])


class TestCli(unittest.TestCase):
    def cli(self, *a, cwd=RAIZ):
        return subprocess.run([sys.executable, "-m", "lib.trampas.cli", *a], cwd=cwd, capture_output=True, text=True,
                              env=dict(os.environ, PYTHONPATH=str(RAIZ)))

    def test_probar(self):
        r = self.cli("--probar", str(FIX))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("5 trampas, 0 fallan", r.stdout)
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "mala.yml").write_text(yaml.safe_dump([dict(BLOQUEO, prueba={"dispara": "x", "no_dispara": "y"}),
                                                    BLOQUEO]))
        r = self.cli("--probar", str(d))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no dispara", r.stdout)
        self.assertIn("`id` repetido", r.stdout)

    def test_archivo_y_uso(self):
        f = FIX / "resources" / "views" / "x-init.blade.php"
        r = self.cli("--trampas", str(FIX), "--archivo", str(f))
        self.assertEqual(r.returncode, 1)
        self.assertEqual([l.rsplit(":", 2)[1:] for l in r.stdout.splitlines()],
                         [["2", "x-init-con-bloque"], ["3", "x-init-con-bloque"], ["5", "x-init-con-bloque"]])
        r = self.cli("--trampas", str(FIX), "--archivo", str(FIX / "resources" / "views" / "parciales" / "limpio.blade.php"))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli("--archivo", "x", "--sid", "s").returncode, 2)
        self.assertEqual(self.cli("--archivo", "/no/existe").returncode, 2)


@unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "la paridad necesita jq y bash")
class TestParidad(unittest.TestCase):
    def test_migracion_blade(self):
        r = subprocess.run(["bash", str(RAIZ / "tests" / "migracion_blade.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("migracion_blade: OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
