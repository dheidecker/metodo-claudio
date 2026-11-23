"""Frente F: juez de permisos (hook PermissionRequest). Offline: el modelo es tests/fixtures/fake-claude.

Ningún test borra nada: el hook solo decide. HOME, CLAUDE_HOME, MECANISMO_HOME y MECANISMO_BITACORA
van a un tmp, así que `~` y `~/.claude` de las reglas son los del tmp, nunca los reales.
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

from lib.juez import contexto, reglas

RAIZ = pathlib.Path(__file__).resolve().parent.parent
HOOK = RAIZ / "hooks" / "juez-permisos"
FAKE = RAIZ / "tests" / "fixtures" / "fake-claude"
LIMPIAR = ("CLAUDE_PROJECT_DIR", "MECANISMO_JUEZ_ANIDADO", "ANTHROPIC_API_KEY", "FAKE_CLAUDE_JUEZ",
           "FAKE_CLAUDE_ENTRADA", "FAKE_CLAUDE_LOG", "MECANISMO_JUEZ_TIMEOUT", "MECANISMO_MODELO_JUEZ",
           "FAKE_CLAUDE_VARIANTE", "CLAUDECODE")


class Base(unittest.TestCase):
    def setUp(self):
        # /var/tmp y no /tmp: las reglas permiten todo lo que esté bajo /tmp, y aquí hace falta un
        # «fuera del proyecto» relativo (../vecino) que no lo esté.
        base = "/var/tmp" if os.access("/var/tmp", os.W_OK) else None
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="mecanismo-f-", dir=base))
        self.home = self.tmp / "home"
        self.proy = self.home / "trabajo" / "proy"
        for d in ("build", "src", "vendor/bin", ".git-no"):
            (self.proy / d).mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "principal", str(self.proy)], check=True)
        subprocess.run(["git", "-C", str(self.proy), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "feat: primer commit"], check=True)
        self.env = {k: v for k, v in os.environ.items() if k not in LIMPIAR}
        self.env.update(HOME=str(self.home), CLAUDE_HOME=str(self.home / ".claude"),
                        MECANISMO_HOME=str(self.tmp / "mh"), MECANISMO_BITACORA=str(self.tmp / "bitacora.log"),
                        MECANISMO_CLAUDE=str(FAKE), FAKE_CLAUDE_LOG=str(self.tmp / "fake.log"),
                        FAKE_CLAUDE_ENTRADA=str(self.tmp / "entrada.json"), PYTHONPATH=str(RAIZ))
        self.cwd = str(self.proy)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hook(self, cmd, tool="Bash", cwd=None, transcript=None, **env):
        ev = {"hook_event_name": "PermissionRequest", "tool_name": tool, "tool_input": {"command": cmd},
              "cwd": self.cwd if cwd is None else cwd, "session_id": "s-f", "transcript_path": transcript}
        t0 = time.monotonic()
        r = subprocess.run([str(HOOK)], input=json.dumps(ev), capture_output=True, text=True,
                           env={**self.env, **env}, timeout=60)
        r.ms = (time.monotonic() - t0) * 1000
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        r.json = json.loads(r.stdout) if r.stdout.strip() else None
        return r

    def decision(self, r):
        return r.json["hookSpecificOutput"]["decision"] if r.json else None

    def auditoria(self):
        d = self.tmp / "mh" / "juez"
        return [json.loads(l) for p in sorted(d.glob("*.jsonl")) for l in p.read_text().splitlines()] if d.exists() else []

    def bitacora(self):
        p = self.tmp / "bitacora.log"
        return [l.split(" | ")[-1].strip() for l in p.read_text().splitlines()] if p.exists() else []

    def fake_log(self):
        p = self.tmp / "fake.log"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


class TestReglasRm(Base):
    NIEGA = {
        "rm -rf $X": "variable sin expandir",
        "rm -rf ${X}/build": "variable sin expandir",
        "rm -rf build/$(date)": "variable sin expandir",
        "rm -rf /*": "glob en la raíz",
        "rm -rf ~/*": "glob en $HOME",
        "rm -rf $HOME/*": "glob en $HOME",
        "rm -rf /": "borra /",
        "sudo rm -r -f /": "borra /",
        "rm -rf $HOME": "borra $HOME",
        'rm -rf "${HOME}"': "borra $HOME",
        "rm -rf ~": "borra $HOME",
        "rm -rf ~/.claude": "toca ~/.claude",
        "rm x -rf ~/.claude/projects": "toca ~/.claude",
        "rm -rf .git": "toca .git",
        "rm -rf src/.git/objects": "toca .git",
        "rm -rf .": "borra la raíz del proyecto",
        "rm -rf *": "vacía la raíz del proyecto",
        "rm -rf ..": "ancestro del proyecto",
        "rm -rf ../../..": "ancestro del proyecto",
        "rm -rf ../..": "borra $HOME",
        "rm -rf /srv/otro": "fuera del proyecto",
        "rm -rf ../vecino": "fuera del proyecto",
        "\\rm -fr /opt/app": "fuera del proyecto",
        "rm -rf /tmp": "fuera del proyecto",
        "rm -rf /tmp/*": "fuera del proyecto",
        "rm -rf build && rm -rf /etc/x": "fuera del proyecto",
        "rm -rf build && git push": None,          # ver test_otra_irreversible
    }
    PERMITE = ["rm -rf build", "rm -rf dist node_modules", "rm -rf __pycache__ .cache tmp .pytest_cache",
               "rm -rf coverage target .next", "rm -rf src/__pycache__", "rm -rf build/*", "rm -rf ./build/",
               "\\rm -fr build", "/bin/rm build -rf", "sudo rm --recursive --force dist",
               "cd build && rm -rf x", "rm -rf /tmp/algo", "rm -rf /tmp/a/*", 'rm -rf "build" 2>/dev/null',
               "rm -rf build; echo listo"]

    def test_niega(self):
        for cmd, motivo in self.NIEGA.items():
            if motivo is None or (cmd == "rm -rf ../vecino" and str(self.tmp).startswith("/tmp/")):
                continue
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                d = self.decision(r)
                self.assertEqual(d and d["behavior"], "deny", r.stdout)
                self.assertIn(motivo, d["message"])
                self.assertTrue(d["message"].startswith("Juez de permisos: "))
                self.assertTrue(d["message"].endswith("Si es correcto, explica por qué o pídeselo a la persona."))
                self.assertIs(d["interrupt"], False)
        self.assertEqual(self.fake_log(), [], "las reglas deterministas no llaman al modelo")

    def test_permite(self):
        for cmd in self.PERMITE:
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(self.decision(r), {"behavior": "allow"}, r.stdout)
                self.assertTrue(r.json["systemMessage"].startswith("juez: permitido — "))
        self.assertEqual(self.fake_log(), [])
        self.assertTrue(all(e["via"] == "regla" and e["decision"] == "permitir" for e in self.auditoria()))
        self.assertTrue(all(l == "PERMITE rm -rf regla" for l in self.bitacora()), self.bitacora())

    def test_lo_demas_va_al_modelo(self):
        for cmd in ("rm -rf src", "rm -rf vendor/bin", "rm -rf build && curl -s x", "rm -rf src/*.log",
                    "find . -name x | xargs rm -rf"):
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(self.decision(r), {"behavior": "allow"}, r.stdout)
        self.assertEqual(len(self.fake_log()), 5)
        self.assertTrue(all(e["via"] == "modelo" for e in self.auditoria()))

    def test_reglas_en_menos_de_300_ms(self):
        tiempos = []
        for cmd in ("rm -rf build", "rm -rf /srv/otro", "rm -rf $X", "cd build && rm -rf x"):
            r = self.hook(cmd)
            self.assertIsNotNone(r.json)
            tiempos.append(r.ms)
        internos = [e["duracion_ms"] for e in self.auditoria()]
        self.assertTrue(all(ms < 300 for ms in internos), internos)
        self.assertLess(max(tiempos), 300, f"pared (proceso entero): {tiempos}")

    def test_cwd_desde_el_subdirectorio(self):
        r = self.hook("rm -rf ../build", cwd=str(self.proy / "src"))
        self.assertEqual(self.decision(r), {"behavior": "allow"})

    def test_piezas_conservan_el_texto_crudo(self):
        ps = reglas.piezas("""rm -rf "mi dir" 'b;c' && echo "x; rm -rf /" """)
        self.assertEqual([p.cruda for p in ps], ['rm -rf "mi dir" \'b;c\'', 'echo "x; rm -rf /"'])
        self.assertEqual([p.familias for p in ps], [["rm -rf"], []])


class TestJuezModelo(Base):
    DEPLOY = "gcloud run deploy api --image gcr.io/p/api --region us-central1 --project mi-proy"

    def transcript(self, extra_asistente="Voy a desplegar api a us-central1.", prompts=None):
        t = self.tmp / "sesion.jsonl"
        filas = []
        for i, p in enumerate(prompts or [f"prompt viejo {i}" for i in range(6)]):
            filas.append({"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": p}})
            filas.append({"type": "assistant", "message": {"content": [{"type": "text", "text": f"respuesta {i}"}]}})
        filas.append({"type": "user", "origin": {"kind": "peer"}, "message": {"content": "soy otro agente"}})
        filas.append({"type": "user", "toolUseResult": {}, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "salida"}]}})
        filas.append({"type": "assistant", "message": {"content": [{"type": "text", "text": extra_asistente}]}})
        filas.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": self.DEPLOY}}]}})
        t.write_text("\n".join(json.dumps(f) for f in filas) + "\n")
        return str(t)

    def test_deploy_permitido(self):
        r = self.hook(self.DEPLOY, transcript=self.transcript())
        self.assertEqual(self.decision(r), {"behavior": "allow"})
        self.assertEqual(r.json["systemMessage"], "juez: permitido — la persona pidió desplegar api a us-central1")
        log = self.fake_log()
        self.assertEqual(len(log), 1)
        self.assertEqual((log[0]["modelo"], log[0]["tope"], log[0]["tools"], log[0]["anidado"]),
                         ("sonnet", 0.10, "", "1"))
        self.assertEqual(log[0]["setting_sources"], "project")
        self.assertEqual(log[0]["cwd"], str(self.tmp / "mh" / "vacio"))
        e = json.loads((self.tmp / "entrada.json").read_text())
        self.assertEqual(e["comando"], self.DEPLOY)
        self.assertEqual(e["prompts_humanos"], [f"prompt viejo {i}" for i in range(1, 6)])
        self.assertEqual(e["ultimo_asistente"], "Voy a desplegar api a us-central1.")
        self.assertEqual(e["git"]["rama"], "principal")
        self.assertEqual(e["git"]["commits"], ["feat: primer commit"])
        self.assertEqual(e["familias"], ["gcloud run deploy"])
        self.assertIn("PERMITE gcloud run deploy modelo", self.bitacora())

    def test_deploy_negado(self):
        r = self.hook(self.DEPLOY + " && gcloud builds submit --tag x .", transcript=self.transcript(),
                      FAKE_CLAUDE_JUEZ="negar")
        d = self.decision(r)
        self.assertEqual(d, {"behavior": "deny", "interrupt": False, "message":
                             "Juez de permisos: la persona pidió desplegar web, no api. "
                             "Si es correcto, explica por qué o pídeselo a la persona."})
        a = self.auditoria()[-1]
        self.assertEqual((a["familia"], a["via"], a["decision"], a["riesgo"]),
                         ("gcloud run deploy+gcloud builds submit", "modelo", "negar", "alto"))
        self.assertTrue(any(l.startswith("NIEGA gcloud run deploy+gcloud builds submit") for l in self.bitacora()))

    def test_fallos_del_modelo_devuelven_el_dialogo(self):
        casos = [({"FAKE_CLAUDE_JUEZ": "dormir", "MECANISMO_JUEZ_TIMEOUT": "1"}, "error timeout"),
                 ({"MECANISMO_CLAUDE": str(self.tmp / "no-existe")}, "error sin-claude"),
                 ({"FAKE_CLAUDE_JUEZ": "basura"}, "error json-invalido"),
                 ({"FAKE_CLAUDE_JUEZ": "fuera-de-esquema"}, "error json-invalido")]
        for env, linea in casos:
            with self.subTest(linea=linea, env=env):
                r = self.hook(self.DEPLOY, **env)
                self.assertEqual(r.stdout, "")
                self.assertEqual(self.bitacora()[-1], linea)
        self.assertEqual(self.auditoria(), [])

    def test_timeout_no_espera_al_modelo(self):
        r = self.hook(self.DEPLOY, FAKE_CLAUDE_JUEZ="dormir", MECANISMO_JUEZ_TIMEOUT="1")
        self.assertEqual(r.stdout, "")
        self.assertLess(r.ms, 10000)

    def test_canario_de_redaccion(self):
        cmd = (self.DEPLOY + " --set-env-vars DB_PASS=CANARIO1,MODO=CANARIO2 --update-env-vars=X=CANARIO3"
               " && TOKEN=CANARIO4 echo ok")
        prompts = ["despliega api; la clave es sk-CANARIO5abcdefgh", "usa Bearer CANARIO6abcdefgh12 y PASSWORD=CANARIO7"]
        subprocess.run(["git", "-C", self.cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "fix: rota api_key=CANARIO8"], check=True)
        r = self.hook(cmd, transcript=self.transcript("con postgres://u:CANARIO9@h/db", prompts))
        # el fake sale con 3 si ve CANARIO: una decisión «allow» prueba que no llegó ninguno
        self.assertEqual(self.decision(r), {"behavior": "allow"}, self.bitacora())
        entrada = (self.tmp / "entrada.json").read_text()
        self.assertNotIn("CANARIO", entrada)
        self.assertIn("DB_PASS=[REDACTADO:env],MODO=[REDACTADO:env]", entrada)
        self.assertIn("--region us-central1", entrada)          # lo que el juez necesita ver, sigue ahí
        self.assertNotIn("CANARIO", json.dumps(self.auditoria()))
        self.assertNotIn("CANARIO", (self.tmp / "bitacora.log").read_text())

    def test_auditoria_y_cli(self):
        self.hook(self.DEPLOY)
        self.hook("rm -rf /srv/otro")
        a = self.auditoria()
        self.assertEqual(len(a), 2)
        for e in a:
            self.assertEqual(set(e) - {"costo_usd"}, {"ts", "proyecto", "cwd", "comando", "familia", "via",
                                                      "decision", "motivo", "riesgo", "duracion_ms"})
            self.assertEqual(e["proyecto"], str(self.proy))
        self.assertRegex(a[0]["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertTrue((self.tmp / "mh" / "juez" / (a[0]["ts"][:7] + ".jsonl")).exists())
        from lib.juez import cli
        viejo = {k: os.environ.get(k) for k in ("MECANISMO_HOME",)}
        os.environ["MECANISMO_HOME"] = str(self.tmp / "mh")
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["--negadas"]), 0)
            self.assertIn("NIEGA", out.getvalue())
            self.assertIn("/srv/otro", out.getvalue())
            self.assertNotIn("gcloud", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["--ultimas", "1", "--json"]), 0)
            self.assertEqual(json.loads(out.getvalue())["decision"], "negar")
            self.assertEqual(cli.main(["--nada"]), 2)
        finally:
            for k, v in viejo.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class TestGuardas(Base):
    def test_guarda_anidada(self):
        r = self.hook("rm -rf /", MECANISMO_JUEZ_ANIDADO="1")
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.bitacora(), [])

    def test_no_bash_y_no_juzgados(self):
        self.assertEqual(self.hook("rm -rf /", tool="Write").stdout, "")
        for cmd in ("ls -la", "git push origin main", 'echo "rm -rf /"', "rm -f x", "npm run deploy",
                    "gcloud run services list"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.hook(cmd).stdout, "")
        self.assertEqual(self.bitacora(), [])
        self.assertEqual(self.fake_log(), [])

    def test_otra_irreversible_vuelve_al_dialogo(self):
        r = self.hook("rm -rf build && git push")
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.bitacora(), ["silencio fuera-de-juez git push"])
        # ...pero una regla NIEGA sigue mandando
        self.assertEqual(self.decision(self.hook("rm -rf / && git push"))["behavior"], "deny")

    def test_config_juez_yml(self):
        (self.tmp / "mh").mkdir(exist_ok=True)
        (self.tmp / "mh" / "juez.yml").write_text("familias: [git push]\n")
        self.assertEqual(self.hook("rm -rf /").stdout, "")
        self.assertEqual(self.decision(self.hook("git push origin main"))["behavior"], "allow")
        self.assertEqual(self.fake_log()[0]["tarea"], "juez")
        (self.tmp / "mh" / "juez.yml").write_text("familias: rm -rf\n")
        self.assertEqual(self.hook("rm -rf build").stdout, "")
        self.assertEqual(self.bitacora()[-1], "error config-invalida")

    def test_sin_pyyaml(self):
        (self.tmp / "mh").mkdir(exist_ok=True)
        (self.tmp / "mh" / "juez.yml").write_text("familias: [rm -rf]\n")
        sin = self.tmp / "sin-yaml"
        sin.mkdir()
        (sin / "yaml.py").write_text("raise ImportError('PyYAML simulado ausente')\n")
        r = self.hook("rm -rf build", PYTHONPATH=f"{sin}:{RAIZ}")
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.bitacora()[-1], "error sin-pyyaml")
        # sin juez.yml no hace falta PyYAML
        (self.tmp / "mh" / "juez.yml").unlink()
        self.assertEqual(self.decision(self.hook("rm -rf build", PYTHONPATH=f"{sin}:{RAIZ}")), {"behavior": "allow"})

    def test_excepcion_sin_traceback(self):
        r = self.hook("rm -rf build", cwd=12)
        self.assertEqual(r.stdout, "")
        self.assertTrue(self.bitacora()[-1].startswith("error excepcion"), self.bitacora())

    def test_entrada_rota(self):
        r = subprocess.run([str(HOOK)], input="no es json", capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_por_el_dispatcher(self):
        r = subprocess.run([str(RAIZ / "bin" / "mecanismo"), "hook", "juez-permisos"], capture_output=True, text=True,
                           input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf build"},
                                             "cwd": self.cwd}), env=self.env)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        r = subprocess.run([str(RAIZ / "bin" / "mecanismo"), "--help"], capture_output=True, text=True, env=self.env)
        self.assertRegex(r.stdout, r"\n  juez ")


class TestRedaccion(unittest.TestCase):
    def test_redactar_env_y_opciones(self):
        t = contexto.redactar("x --set-env-vars 'A=1,B=dos' --set-secrets=K=s:1 --db-password hunter2 GH_TOKEN=abc")
        for secreto in ("=1", "dos", "s:1", "hunter2", "abc"):
            self.assertNotIn(secreto, t)
        self.assertIn("A=[REDACTADO:env],B=[REDACTADO:env]", t)

    def test_redactar_antes_de_cortar(self):
        pem = "-----BEGIN PRIVATE KEY-----\n" + "A" * 3000 + "\n-----END PRIVATE KEY-----"
        self.assertEqual(contexto.cortar(pem, 50), "[REDACTADO:pem]")


if __name__ == "__main__":
    unittest.main()
