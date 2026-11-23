"""Frente E: dispatcher (bin/mecanismo), `mecanismo init`, shims y plantilla.

La prueba del instalador en sí (instalar.sh / desinstalar.sh con un HOME falso) está en
tests/instalar.sh; aquí solo se comprueba que existe y pasa `bash -n`.
"""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest

import yaml

RAIZ = pathlib.Path(__file__).resolve().parent.parent          # mecanismo/
REPO = RAIZ.parent                                              # metodo-claudio/
BIN = RAIZ / "bin" / "mecanismo"
PLANTILLA = REPO / "plantilla-proyecto" / ".claude"
SHIMS = ("mecanismo-trampas.sh", "stop-evidencia.sh")


class Base(unittest.TestCase):
    """Cada test con su ~/.claude y su HOME falsos: nada toca el real."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.env = dict(os.environ)
        self.env.update(HOME=str(self.tmp / "home"), CLAUDE_HOME=str(self.tmp / "claude"),
                        MECANISMO_BITACORA=str(self.tmp / "bitacora.log"))
        for k in ("CLAUDE_PROJECT_DIR", "MECANISMO_HOME", "PYTHONPATH"):
            self.env.pop(k, None)
        (self.tmp / "home").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_(self, args, cwd=None, entrada="", bin_=BIN, env=None):
        return subprocess.run([str(bin_), *args], cwd=cwd or self.tmp, input=entrada, text=True,
                              capture_output=True, env=env or self.env, timeout=60)

    def copia_minima(self):
        """Un mecanismo/ falso con solo bin/ y lib/comun.py: para probar el dispatcher
        sin depender de qué paquetes de otros frentes ya estén integrados."""
        m = self.tmp / "clon" / "mecanismo"
        (m / "bin").mkdir(parents=True)
        (m / "lib").mkdir()
        (m / "hooks").mkdir()
        shutil.copy2(BIN, m / "bin" / "mecanismo")
        shutil.copy2(RAIZ / "lib" / "__init__.py", m / "lib" / "__init__.py")
        shutil.copy2(RAIZ / "lib" / "comun.py", m / "lib" / "comun.py")
        return m


class TestDispatcher(Base):
    def test_help_y_version(self):
        r = self.run_(["--help"])
        self.assertEqual(r.returncode, 0)
        for sub in ("trampas", "recolectar", "propuestas", "aprobar", "verificar", "confiar", "permisos",
                    "init", "hook"):
            self.assertIn(sub, r.stdout)
        r = self.run_(["version"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("contrato v1", r.stdout)

    def test_sin_args_y_desconocido_salen_2(self):
        self.assertEqual(self.run_([]).returncode, 2)
        r = self.run_(["nada-de-esto"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("desconocido", r.stderr)

    def test_paquete_inexistente_sale_2_sin_traceback(self):
        m = self.copia_minima()
        for sub in ("trampas", "recolectar", "propuestas", "aprobar", "rechazar", "verificar", "confiar",
                    "permisos", "init"):
            r = self.run_([sub], bin_=m / "bin" / "mecanismo")
            self.assertEqual(r.returncode, 2, sub)
            self.assertIn("todavía no existe", r.stderr, sub)
            self.assertNotIn("Traceback", r.stderr, sub)

    def test_despacha_a_cli_main_con_argv(self):
        m = self.copia_minima()
        for pkg in ("propuestas", "trampas"):
            (m / "lib" / pkg).mkdir()
            (m / "lib" / pkg / "__init__.py").write_text("")
            (m / "lib" / pkg / "cli.py").write_text(
                "import json\ndef main(argv):\n    print(json.dumps(argv))\n    return 7\n")
        b = m / "bin" / "mecanismo"
        r = self.run_(["trampas", "--probar", "x y"], bin_=b)
        self.assertEqual((r.returncode, json.loads(r.stdout)), (7, ["--probar", "x y"]))
        r = self.run_(["propuestas"], bin_=b)
        self.assertEqual(json.loads(r.stdout), [])
        r = self.run_(["propuestas", "ver", "abc"], bin_=b)
        self.assertEqual(json.loads(r.stdout), ["ver", "abc"])
        r = self.run_(["aprobar", "abc"], bin_=b)
        self.assertEqual(json.loads(r.stdout), ["aprobar", "abc"])
        r = self.run_(["rechazar", "abc"], bin_=b)
        self.assertEqual(json.loads(r.stdout), ["rechazar", "abc"])

    def test_confiar_despacha_a_evidencia_confianza(self):
        # CONTRATO §11: `confiar` -> lib.evidencia.confianza.main(argv), no lib.evidencia.cli.
        m = self.copia_minima()
        ev = m / "lib" / "evidencia"
        ev.mkdir()
        (ev / "__init__.py").write_text("")
        (ev / "cli.py").write_text("def main(argv):\n    print('cli')\n    return 0\n")
        b = m / "bin" / "mecanismo"
        # con lib/evidencia/cli.py pero sin confianza.py: «todavía no existe», exit 2
        r = self.run_(["confiar"], bin_=b)
        self.assertEqual(r.returncode, 2)
        self.assertIn("todavía no existe", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        (ev / "confianza.py").write_text(
            "import json\ndef main(argv):\n    print(json.dumps(['confianza', *argv]))\n    return 5\n")
        r = self.run_(["confiar", "/x y"], bin_=b)
        self.assertEqual((r.returncode, json.loads(r.stdout)), (5, ["confianza", "/x y"]))
        # `verificar` sigue yendo a cli.py, y un `mod` del entorno no cambia el módulo
        r = self.run_(["verificar"], bin_=b, env=dict(self.env, mod="confianza"))
        self.assertEqual(r.stdout.strip(), "cli")

    def test_enlace_simbolico_resuelve_la_raiz_real(self):
        enlace = self.tmp / "home" / "mecanismo"
        enlace.symlink_to(BIN)
        r = self.run_(["version"], bin_=enlace)
        self.assertEqual(r.returncode, 0)
        self.assertIn(str(RAIZ), r.stdout)

    def test_lib_del_proyecto_no_tapa_el_nuestro(self):
        # Trampa: python3 -c antepone el cwd a sys.path; un proyecto con lib/__init__.py
        # taparía `from lib import comun`. El dispatcher corre con -P.
        p = self.tmp / "proy"
        (p / "lib").mkdir(parents=True)
        (p / "lib" / "__init__.py").write_text("raise ImportError('lib del proyecto')\n")
        r = self.run_(["init", "--tipo", "lib", "."], cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((p / ".claude" / "mecanismo.yml").is_file())

    def test_sin_pyyaml_sale_4(self):
        falso = self.tmp / "sin-yaml"
        falso.mkdir()
        (falso / "yaml.py").write_text("raise ImportError('sin PyYAML (test)')\n")
        env = dict(self.env, PYTHONPATH=str(falso))
        r = self.run_(["init", "--tipo", "mcp", str(self.tmp)], env=env)
        self.assertEqual(r.returncode, 4)
        self.assertIn("python3-yaml", r.stderr)

    def test_hook_pasa_stdin_y_args_intactos(self):
        m = self.copia_minima()
        eco = m / "hooks" / "eco"
        eco.write_text("import sys, json\nprint(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}))\n")
        entrada = '{"tool_input": {"file_path": "/x/ñ y.php"}}\n'
        r = self.run_(["hook", "eco", "--stop", "a b"], entrada=entrada, bin_=m / "bin" / "mecanismo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"argv": ["--stop", "a b"], "stdin": entrada})

    def test_hook_inexistente_no_rompe_la_sesion(self):
        m = self.copia_minima()
        r = self.run_(["hook", "trampas"], entrada="{}", bin_=m / "bin" / "mecanismo")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertIn("error falta mecanismo/hooks/trampas", (self.tmp / "bitacora.log").read_text())

    def test_hook_nombre_invalido(self):
        self.assertEqual(self.run_(["hook", "../bin/mecanismo"]).returncode, 2)


class TestInit(Base):
    def init(self, tipo, d, *extra):
        return self.run_(["init", "--tipo", tipo, str(d), *extra])

    def foto(self, d):
        out = {}
        for p in sorted(d.rglob("*")):
            st = p.lstat()
            out[str(p.relative_to(d))] = (stat.S_IMODE(st.st_mode), p.read_bytes() if p.is_file() else None)
        return out

    def test_crea_todo_y_es_idempotente(self):
        for tipo in ("mcp", "web", "lib"):
            d = self.tmp / tipo
            d.mkdir()
            r = self.init(tipo, d)
            self.assertEqual(r.returncode, 0, r.stderr)
            c = d / ".claude"
            for rel in ("mecanismo.yml", "mapa-funciones.yml", "trampas", "trampas/propuestas",
                        "verificacion/casos", "verificacion/golden"):
                self.assertTrue((c / rel).exists(), rel)
            for s in SHIMS:
                self.assertTrue(os.access(c / "hooks" / s, os.X_OK), s)
                self.assertEqual((c / "hooks" / s).read_text(), (PLANTILLA / "hooks" / s).read_text())
            self.assertIn(".claude/evidencia/", (d / ".gitignore").read_text().splitlines())
            self.assertFalse((c / "settings.json").exists(), "init no crea ni toca settings.json")
            antes = self.foto(d)
            r2 = self.init(tipo, d)
            self.assertEqual(r2.returncode, 0)
            self.assertIn("sin cambios", r2.stdout)
            self.assertEqual(self.foto(d), antes, f"la segunda corrida cambió algo ({tipo})")

    def test_yml_cumplen_esquemas(self):
        esq = {n: json.loads((RAIZ / "esquemas" / f"{n}.schema.json").read_text()) for n in ("mecanismo", "mapa")}
        for tipo in ("mcp", "web", "lib"):
            d = self.tmp / tipo
            d.mkdir()
            self.init(tipo, d)
            mec = yaml.safe_load((d / ".claude" / "mecanismo.yml").read_text())
            self.assertEqual(mec["tipo"], tipo)
            self.assertEqual(mec["puerta"], "aviso")
            self.assertEqual(mec["version"], 1)
            self.assertLessEqual(set(mec), set(esq["mecanismo"]["properties"]))
            self.assertIn(tipo, mec)
            mapa = yaml.safe_load((d / ".claude" / "mapa-funciones.yml").read_text())
            self.assertTrue(mapa["funciones"])
            for f in mapa["funciones"]:
                self.assertLessEqual(set(f), set(esq["mapa"]["properties"]["funciones"]["items"]["properties"]))
                self.assertEqual(sum(k in f for k in ("mcp", "web", "test")), 1)
                self.assertIn({"mcp": "mcp", "web": "web", "lib": "test"}[tipo], f)

    def test_nunca_pisa_lo_existente(self):
        d = self.tmp / "p"
        (d / ".claude" / "hooks").mkdir(parents=True)
        (d / ".claude" / "mecanismo.yml").write_text("mio: true\n")
        (d / ".claude" / "hooks" / "stop-evidencia.sh").write_text("# mio\n")
        (d / ".gitignore").write_text("vendor/\n/.claude/evidencia")   # sin \n final, variante con /
        r = self.init("web", d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((d / ".claude" / "mecanismo.yml").read_text(), "mio: true\n")
        self.assertEqual((d / ".claude" / "hooks" / "stop-evidencia.sh").read_text(), "# mio\n")
        self.assertEqual((d / ".gitignore").read_text(), "vendor/\n/.claude/evidencia")
        self.assertIn("no se toca", r.stdout)

    def test_gitignore_sin_salto_final(self):
        d = self.tmp / "p"
        d.mkdir()
        (d / ".gitignore").write_text("vendor/")
        self.init("lib", d)
        self.assertEqual((d / ".gitignore").read_text().splitlines()[0], "vendor/")
        self.assertIn(".claude/evidencia/", (d / ".gitignore").read_text().splitlines())

    def test_uso_incorrecto(self):
        self.assertEqual(self.run_(["init"]).returncode, 2)
        self.assertEqual(self.run_(["init", "--tipo", "php"]).returncode, 2)
        self.assertEqual(self.run_(["init", "--tipo", "mcp", str(self.tmp / "no-existe")]).returncode, 2)

    def test_dir_por_defecto_es_la_raiz_git(self):
        d = self.tmp / "repo"
        (d / "sub").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        r = self.run_(["init", "--tipo", "lib"], cwd=d / "sub")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((d / ".claude" / "mecanismo.yml").is_file())
        self.assertFalse((d / "sub" / ".claude").exists())

    @unittest.skipUnless(shutil.which("jq"), "sin jq")
    def test_comando_jq_engancha_sin_pisar_y_es_idempotente(self):
        d = self.tmp / "p"
        (d / ".claude").mkdir(parents=True)
        previo = {"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "otro.sh"}]}],
                            "Stop": [{"hooks": [{"type": "command", "command": "stop-lint.sh"}]}]},
                  "permissions": {"allow": ["Bash(ls*)"]}}
        s = d / ".claude" / "settings.json"
        s.write_text(json.dumps(previo))
        r = self.init("mcp", d)
        cmd = next(l.strip() for l in r.stdout.splitlines() if l.strip().startswith("f="))
        for _ in range(2):
            subprocess.run(["bash", "-c", cmd], check=True, env=self.env)
        nuevo = json.loads(s.read_text())
        self.assertEqual(nuevo["permissions"], previo["permissions"])
        cmds = [h["command"] for ev in ("PostToolUse", "Stop") for e in nuevo["hooks"][ev] for h in e["hooks"]]
        self.assertEqual(cmds.count("otro.sh"), 1)
        self.assertEqual(cmds.count("stop-lint.sh"), 1)
        self.assertEqual(sum(c.endswith("mecanismo-trampas.sh") for c in cmds), 1)
        self.assertEqual(sum(c.endswith("mecanismo-trampas.sh --stop") for c in cmds), 1)
        self.assertEqual(sum(c.endswith("stop-evidencia.sh") for c in cmds), 1)
        r = self.init("mcp", d)
        self.assertIn("ya llama a los dos shims", r.stdout)

    @unittest.skipUnless(shutil.which("jq"), "sin jq")
    def test_comando_jq_sin_settings_previo(self):
        d = self.tmp / "p"
        d.mkdir()
        r = self.init("lib", d)
        cmd = next(l.strip() for l in r.stdout.splitlines() if l.strip().startswith("f="))
        subprocess.run(["bash", "-c", cmd], check=True, env=self.env)
        self.assertIn("Stop", json.loads((d / ".claude" / "settings.json").read_text())["hooks"])


class TestShimsYPlantilla(Base):
    def test_shim_sin_mecanismo_sale_0_en_silencio(self):
        env = dict(self.env, PATH="/usr/bin:/bin")
        self.assertIsNone(shutil.which("mecanismo", path=env["PATH"]))
        for s in SHIMS:
            for args in ([], ["--stop"]):
                r = subprocess.run([str(PLANTILLA / "hooks" / s), *args], input='{"session_id":"x"}',
                                   text=True, capture_output=True, env=env, timeout=10)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), s)

    def test_shim_con_mecanismo_despacha_al_hook(self):
        m = self.copia_minima()
        (m / "hooks" / "trampas").write_text("import sys\nprint('trampas', *sys.argv[1:], sys.stdin.read())\n")
        (m / "hooks" / "stop-evidencia").write_text("import sys\nprint('evidencia', *sys.argv[1:])\n")
        binp = self.tmp / "binp"
        binp.mkdir()
        (binp / "mecanismo").symlink_to(m / "bin" / "mecanismo")
        env = dict(self.env, PATH=f"{binp}:/usr/bin:/bin")
        r = subprocess.run([str(PLANTILLA / "hooks" / "mecanismo-trampas.sh"), "--stop"], input="{}",
                           text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(r.stdout.strip(), "trampas --stop {}")
        r = subprocess.run([str(PLANTILLA / "hooks" / "stop-evidencia.sh")], input="{}",
                           text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(r.stdout.strip(), "evidencia")

    def test_plantilla_settings_engancha_shims_y_conserva_lo_previo(self):
        d = json.loads((PLANTILLA / "settings.json").read_text())
        cmds = {ev: [h["command"] for e in d["hooks"][ev] for h in e["hooks"]] for ev in d["hooks"]}
        C = "${CLAUDE_PROJECT_DIR}/.claude/hooks/"
        for previo in ("session-marca.sh",):
            self.assertIn(C + previo, cmds["SessionStart"])
        for previo in ("lint-editado.sh", "blade-trampas.sh", "mecanismo-trampas.sh"):
            self.assertIn(C + previo, cmds["PostToolUse"])
        for previo in ("stop-lint.sh", "mecanismo-trampas.sh --stop", "stop-evidencia.sh"):
            self.assertIn(C + previo, cmds["Stop"])
        pt = [e for e in d["hooks"]["PostToolUse"] if C + "mecanismo-trampas.sh" in [h["command"] for h in e["hooks"]]]
        self.assertEqual(pt[0]["matcher"], "Edit|Write")
        for s in SHIMS:
            p = PLANTILLA / "hooks" / s
            self.assertTrue(os.access(p, os.X_OK), s)
            self.assertIn("command -v mecanismo", p.read_text())

    def test_bash_n_y_sin_rutas_a_mano(self):
        scripts = [BIN, REPO / "instalar.sh", REPO / "desinstalar.sh", RAIZ / "tests" / "instalar.sh",
                   *(PLANTILLA / "hooks" / s for s in SHIMS)]
        for s in scripts:
            r = subprocess.run(["bash", "-n", str(s)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{s}: {r.stderr}")
        for s in [*scripts[:3], *scripts[4:], *(RAIZ / "lib" / "init").glob("*.py")]:
            t = s.read_text()
            self.assertNotRegex(t, r"/home/[a-z]", str(s))
            self.assertNotRegex(t, r"/Users/[A-Za-z]", str(s))


if __name__ == "__main__":
    unittest.main()
