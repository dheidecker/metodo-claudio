"""Frente D: mecanismo permisos. Siempre sobre un ~/.claude falso (CLAUDE_HOME y MECANISMO_HOME en tmp)."""
import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import time
import unittest

import yaml

from lib.permisos import analisis, cli, familias, propuestas, reglas
from lib.permisos.fuente import iterar_decisiones

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures" / "permisos"
VARS = ("CLAUDE_HOME", "MECANISMO_HOME", "MECANISMO_BITACORA", "CLAUDE_PROJECT_DIR")


class Entorno(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._env = {k: os.environ.get(k) for k in VARS}
        self.home = self.tmp / "claude"
        self.home.mkdir()
        os.environ["CLAUDE_HOME"] = str(self.home)
        os.environ["MECANISMO_HOME"] = str(self.tmp / "mecanismo")
        os.environ["MECANISMO_BITACORA"] = str(self.tmp / "bitacora.log")
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def con_fixture(self):
        shutil.copytree(FIXTURES / "projects", self.home / "projects", copy_function=shutil.copy)
        shutil.copy(FIXTURES / "settings.json", self.home / "settings.json")
        ahora = time.time()
        for f in (self.home / "projects").rglob("*.jsonl"):
            os.utime(f, (ahora, ahora))      # el filtro --dias va por mtime

    def correr(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(list(argv))
        return rc, out.getvalue()

    def propuestas_escritas(self) -> dict[str, dict]:
        d = pathlib.Path(os.environ["MECANISMO_HOME"]) / "propuestas"
        return {f.stem: yaml.safe_load(f.read_text()) for f in sorted(d.glob("*.yml"))} if d.exists() else {}


def sesion_sintetica(home: pathlib.Path, comandos: list[tuple[str, dict]], proyecto="-home-x-Proyectos-p") -> None:
    """Un transcript con la forma real: assistant(tool_use) -> user(tool_result + permissionDecision)."""
    d = home / "projects" / proyecto
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"s{len(list(d.glob('*.jsonl')))}.jsonl", "w") as f:
        for i, (cmd, pd) in enumerate(comandos):
            a = {"type": "assistant", "uuid": f"a{i}", "timestamp": f"2026-11-{10 + i % 10:02d}T10:00:00Z",
                 "cwd": "/home/x/Proyectos/p",
                 "message": {"role": "assistant", "content": [
                     {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": cmd}}]}}
            u = {"type": "user", "uuid": f"u{i}", "timestamp": f"2026-11-{10 + i % 10:02d}T10:00:01Z",
                 "cwd": "/home/x/Proyectos/p", "sourceToolAssistantUUID": f"a{i}",
                 "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": ""}]},
                 "toolUseResult": {"stdout": ""}, "permissionDecision": pd}
            f.write(json.dumps(a) + "\n" + json.dumps(u) + "\n")


APROBADO = {"decision": "accept", "source": "user_temporary", "reasonCode": "bashMiss:no-rule-match"}


class TestFamilias(unittest.TestCase):
    def test_compuesto_va_a_su_subcomando_mas_grave(self):
        casos = {
            "cd x && git push origin feat": "git push",
            "git -C /repo push": "git push",
            "TAG=$(date) && gcloud builds submit --tag t . && gcloud run deploy s --image t": "gcloud run deploy",
            "E=$(gcloud run jobs execute j | grep x)": "gcloud run jobs execute",
            "ls; rm -rf build | tail": "rm -rf",
            "rm -fr x": "rm -rf",
            "rm -r -f x": "rm -rf",
            "psql -c \"DROP TABLE clientes\"": "DROP/TRUNCATE",
            "php artisan migrate --force": "migrate prod",
            "php artisan migrate:fresh": "migrate prod",
            "kubectl -n x delete pod y": "kubectl apply/delete",
            "terraform apply -auto-approve": "terraform apply",
            "pnpm publish": "npm publish",
            "gh pr merge 12 --squash": "gh pr merge",
            "gh release create v1": "gh release",
            "docker push img:1": "docker push",
            "./deploy.sh prod": "deploy",
            "npm run deploy:prod": "deploy",
            "firebase deploy": "deploy",
            "bq --project_id=p query 'select 1'": "bq query",
        }
        for cmd, fam in casos.items():
            self.assertEqual(familias.clasificar(cmd).familia, fam, cmd)

    def test_comillas_y_heredoc_no_cuentan(self):
        self.assertEqual(familias.clasificar('git commit -m "no hagas git push; rm -rf"').familia, "git commit")
        self.assertEqual(familias.clasificar("cat <<'EOF' > n.md\ngit push origin main\nEOF").familia, "cat")
        self.assertEqual(familias.clasificar("grep x <<< \"$v\"\ngit push").familia, "git push")
        self.assertEqual(familias.clasificar("cat deploy.yaml").familia, "cat")
        self.assertEqual(familias.clasificar("rm -f x.tmp").familia, "rm")

    def test_variante_push(self):
        v = lambda c: familias.clasificar(c).variante  # noqa: E731
        self.assertEqual(v("git push -u origin feat/x"), "rama")
        self.assertEqual(v("git push origin main"), "main")
        self.assertEqual(v("git push origin HEAD:master"), "main")
        self.assertEqual(v("git push --force-with-lease origin feat"), "force")
        self.assertEqual(v("git push -f"), "force")
        self.assertEqual(v("git push origin +feat"), "force")
        self.assertEqual(v("git push"), "sin-destino")

    def test_lista_fija(self):
        for fam in ("git push", "gcloud run deploy", "gcloud builds submit", "deploy", "migrate prod",
                    "DROP/TRUNCATE", "rm -rf", "kubectl apply/delete", "terraform apply", "npm publish",
                    "gh pr merge", "gh release", "docker push"):
            self.assertIn(fam, familias.FAMILIAS_IRREVERSIBLES)


class TestReglas(Entorno):
    def test_casa_por_subcomando(self):
        self.assertTrue(reglas.casa("Bash(git push*)", "Bash", "cd x && git push origin a"))
        self.assertTrue(reglas.casa("Bash(git status:*)", "Bash", "git status --short"))
        self.assertTrue(reglas.casa("Bash(gcloud run jobs execute*)", "Bash", "E=$(gcloud run jobs execute j)"))
        self.assertFalse(reglas.casa("Bash(git push*)", "Bash", "git commit -m 'git push'"))
        self.assertFalse(reglas.casa("Bash(git push*)", "Write", None))

    def test_protegidas(self):
        for r in ("Bash(git push*)", "Bash(rm -rf*)", "Bash(bq query*)", "Bash(gcloud run deploy*)",
                  "Bash(gcloud builds submit*)", "Bash(php artisan migrate --force*)", "Bash(gcloud run jobs execute*)"):
            self.assertTrue(reglas.es_protegida(r), r)
        self.assertFalse(reglas.es_protegida("Bash(npm audit*)"))

    def test_lee_claude_home_sin_escribir(self):
        shutil.copy(FIXTURES / "settings.json", self.home / "settings.json")
        antes = (self.home / "settings.json").read_bytes()
        r = reglas.leer_reglas()
        self.assertIn("Bash(git push*)", r["ask"])
        self.assertEqual(r["allow"], ["Bash(ls *)"])
        self.assertEqual((self.home / "settings.json").read_bytes(), antes)

    def test_sin_settings(self):
        self.assertEqual(reglas.leer_reglas(), {"allow": [], "ask": [], "deny": []})


class TestInforme(Entorno):
    def test_fixture(self):
        self.con_fixture()
        rc, out = self.correr("--dias", "90", "--json")
        self.assertEqual(rc, 0)
        d = json.loads(out)
        fam = {f["familia"]: f for f in d["familias"]}
        self.assertEqual(fam["git push"]["dialogos"], 5)
        self.assertEqual(fam["git push"]["por_regla_ask"], 4)
        self.assertEqual(fam["git push"]["variantes"], {"rama": 3, "main": 1, "sin-destino": 1})
        self.assertEqual(fam["gcloud run deploy"]["dialogos"], 1)
        self.assertEqual((fam["rm -rf"]["dialogos"], fam["rm -rf"]["rechazados"]), (1, 1))
        self.assertEqual(fam["npm test"]["aprobados"], 3)
        self.assertEqual(fam["git log"]["dialogos"], 1)          # unido por sourceToolAssistantUUID
        self.assertEqual(fam["curl"]["rechazados"], 1)             # rechazo del clasificador
        self.assertNotIn("ls", fam)                                # aprobado por config: no es diálogo
        self.assertEqual(d["no_permiso"], {"AskUserQuestion": 1})
        self.assertEqual(d["reason_codes"]["rule:userSettings"], 5)
        self.assertEqual(d["reason_codes"]["(sin código) user_temporary"], 1)
        self.assertEqual(d["reglas"]["ask"]["Bash(git push*)"], 5)
        self.assertEqual(d["reglas"]["ask"]["Bash(bq query*)"], 0)
        self.assertEqual(d["reglas"]["allow"], {"Bash(ls *)": 0})
        self.assertEqual(d["dialogos"], 15)
        self.assertNotIn("CANARIO", out)
        self.assertNotIn("abcdefghijklmnop", out)

    def test_subagentes_aparte(self):
        self.con_fixture()
        _, sin = self.correr("--dias", "90", "--json")
        _, con = self.correr("--dias", "90", "--json", "--subagentes")
        g = lambda o: {f["familia"]: f for f in json.loads(o)["familias"]}["git push"]["dialogos"]  # noqa: E731
        self.assertEqual((g(sin), g(con)), (5, 6))

    def test_texto(self):
        self.con_fixture()
        rc, out = self.correr("--dias", "90")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"git push\s+5\s+5\s+0\s+4\s+sí")
        self.assertIn("bashMiss:too-complex", out)
        self.assertIn("Bash(git push*)", out)

    def test_ventana_por_mtime(self):
        self.con_fixture()
        viejo = time.time() - 200 * 86400
        for f in (self.home / "projects").rglob("*.jsonl"):
            os.utime(f, (viejo, viejo))
        d = json.loads(self.correr("--dias", "90", "--json")[1])
        self.assertEqual(d["dialogos"], 0)

    def test_uso_incorrecto(self):
        self.assertEqual(self.correr("--dias", "x")[0], 2)


class TestPropuestas(Entorno):
    def test_fixture_tres_tipos(self):
        self.con_fixture()
        antes = (self.home / "settings.json").read_bytes()
        rc, _ = self.correr("--dias", "90", "--proponer")
        self.assertEqual(rc, 0)
        ps = self.propuestas_escritas()
        tipos = {(p["tipo"], p["contenido"]["regla"]) for p in ps.values()}
        self.assertIn(("permiso-allow", "Bash(npm test *)"), tipos)
        self.assertIn(("permiso-quitar-ask", "Bash(npm audit*)"), tipos)
        self.assertIn(("envolver-script", "Bash(git-push-rama *)"), tipos)
        self.assertIn(("envolver-script", "Bash(bq query*)"), tipos)
        self.assertIn(("envolver-script", "Bash(secreto-leer-gcloud-compute-ssh *)"), tipos)
        # nunca se quitan de ask los protegidos, aunque tengan 0 diálogos
        self.assertNotIn(("permiso-quitar-ask", "Bash(bq query*)"), tipos)
        for p in ps.values():
            self.assertEqual((p["origen"], p["destino"], p["estado"]), ("permisos", "permisos", "pendiente"))
            self.assertRegex(p["id"], r"^[a-z0-9-]+-[0-9a-f]{8}$")
            self.assertIn("jq", p["contenido"]["comando_jq"])
            self.assertLessEqual(len(p["evidencia"]["ejemplos"]), 3)
        self.assertEqual((self.home / "settings.json").read_bytes(), antes)   # nunca se toca
        crudo = "".join(f.read_text() for f in (pathlib.Path(os.environ["MECANISMO_HOME"]) / "propuestas").glob("*"))
        self.assertNotIn("CANARIO", crudo)
        self.assertIn("[REDACTADO:anthropic]", crudo)

    def test_cumple_el_esquema(self):
        self.con_fixture()
        self.correr("--dias", "90", "--proponer")
        esquema = json.loads((RAIZ / "esquemas" / "propuesta.schema.json").read_text())
        for p in self.propuestas_escritas().values():
            for k in esquema["required"]:
                self.assertIn(k, p)
            self.assertFalse(set(p) - set(esquema["properties"]))
            self.assertFalse(set(p["evidencia"]) - set(esquema["properties"]["evidencia"]["properties"]))
            self.assertIn(p["tipo"], esquema["properties"]["tipo"]["enum"])
            self.assertTrue({"lista", "accion", "regla", "comando_jq"} <= set(p["contenido"]))

    def test_id_estable_y_respeta_decididas(self):
        self.con_fixture()
        self.correr("--dias", "90", "--proponer")
        primera = self.propuestas_escritas()
        d = pathlib.Path(os.environ["MECANISMO_HOME"]) / "propuestas"
        pid = next(k for k, p in primera.items() if p["tipo"] == "permiso-allow")
        f = d / f"{pid}.yml"
        f.write_text(f.read_text().replace("estado: pendiente", "estado: rechazada"))
        time.sleep(1.1)
        _, out = self.correr("--dias", "90", "--proponer")
        segunda = self.propuestas_escritas()
        self.assertEqual(set(primera), set(segunda))
        self.assertEqual(segunda[pid]["estado"], "rechazada")
        for k in primera:
            self.assertEqual(primera[k]["creada"], segunda[k]["creada"], k)
        self.assertIn("[decidida]", out)

    def test_nunca_allow_para_irreversibles(self):
        """100 aprobaciones y 0 rechazos de cada irreversible de la lista: ninguna permiso-allow para ellos."""
        irreversibles = [
            "git push origin main", "git push --force origin feat", "git push -f", "git push --force-with-lease",
            "git push origin feat",
            "gcloud run deploy api --image x", "gcloud builds submit --tag x .", "gcloud run jobs execute j",
            "./deploy.sh prod", "firebase deploy", "npm run deploy",
            "rm -rf build", "php artisan migrate --force", "python manage.py migrate --settings=prod",
            "psql -c 'DROP TABLE t'", "psql -c 'TRUNCATE TABLE t'", "dropdb prod",
            "kubectl apply -f x.yml", "kubectl delete pod y", "terraform apply", "terraform destroy",
            "npm publish", "gh pr merge 3", "gh release create v1", "docker push img:1",
        ]
        cmds = []
        for c in irreversibles:
            self.assertTrue(familias.es_irreversible(c), c)
            cmds += [(c, APROBADO)] * 100
        cmds += [("npm test", APROBADO)] * 5           # control: este sí sale
        sesion_sintetica(self.home, cmds)
        rc, _ = self.correr("--dias", "90", "--proponer", "--json")
        self.assertEqual(rc, 0)
        allow = [p["contenido"]["regla"] for p in self.propuestas_escritas().values() if p["tipo"] == "permiso-allow"]
        self.assertEqual(allow, ["Bash(npm test *)"])
        # y la barrera sigue aunque el análisis venga trucado (grupo marcado como no irreversible)
        a = analisis.analizar(iterar_decisiones(90), 90, False, {"allow": [], "ask": []})
        for c in irreversibles:
            g = a.familias[familias.clasificar(c).familia]
            g.irreversible = False
        self.assertEqual([p["contenido"]["regla"] for p in propuestas.generar(a, {"allow": [], "ask": []})
                          if p["tipo"] == "permiso-allow"], ["Bash(npm test *)"])

    def test_interpretes_y_rechazos_no_van_a_allow(self):
        sesion_sintetica(self.home, [("python3 x.py", APROBADO)] * 10 + [("curl https://x", APROBADO)] * 10
                         + [("bash -c 'make x'", APROBADO)] * 10
                         + [("gcloud logging read q", APROBADO)] * 9
                         + [("gcloud logging read q", {"decision": "reject", "source": "user_reject"})])
        self.correr("--dias", "90", "--proponer")
        self.assertEqual([p for p in self.propuestas_escritas().values() if p["tipo"] == "permiso-allow"], [])

    def test_compuesto_con_irreversible_no_se_envuelve(self):
        tc = {"decision": "accept", "source": "user_temporary", "reasonCode": "bashMiss:too-complex"}
        sesion_sintetica(self.home, [("git add . && git commit -m x && docker push img", tc)] * 5
                         + [("ls x && wc -l y && git status", tc)] * 5)
        self.correr("--dias", "90", "--proponer")
        env = [p["contenido"]["script"]["forma"] for p in self.propuestas_escritas().values()
               if p["tipo"] == "envolver-script" and "forma" in p["contenido"].get("script", {})]
        self.assertEqual(env, ["ls + git status"])

    def test_sin_pyyaml_sale_con_4(self):
        import builtins
        real = builtins.__import__

        def falso(name, *a, **k):
            if name == "yaml":
                raise ImportError("sin yaml")
            return real(name, *a, **k)
        builtins.__import__ = falso
        try:
            self.assertEqual(self.correr("--proponer")[0], 4)
        finally:
            builtins.__import__ = real


if __name__ == "__main__":
    unittest.main()
