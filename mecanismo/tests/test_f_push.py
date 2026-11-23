"""Juez de permisos: `git push`, `gcloud run jobs execute` y `docker push` (CONTRATO §12).

Cada regla de push corre en repos git temporales con un remoto bare local (en /var/tmp), para que
`@{u}` exista. El hook solo decide: nunca se ejecuta un push. El modelo es tests/fixtures/fake-claude.
"""
import json
import subprocess
import unittest

from lib.juez import reglas
from lib.permisos import familias as F
from tests.test_f_juez import Base


def git(*args, cwd=None):
    subprocess.run(["git", *(["-C", str(cwd)] if cwd else []), "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], check=True, capture_output=True)


class BasePush(Base):
    def setUp(self):
        super().setUp()
        self.remoto = self.tmp / "remoto.git"
        git("init", "-q", "--bare", "-b", "main", str(self.remoto))
        self.repo = self.home / "trabajo" / "repo"
        git("clone", "-q", str(self.remoto), str(self.repo))
        git("checkout", "-q", "-b", "main", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "feat: base", cwd=self.repo)
        git("push", "-q", "-u", "origin", "main", cwd=self.repo)          # local, al bare de tmp
        git("checkout", "-q", "-b", "feat", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "feat: trabajo de la sesión", cwd=self.repo)
        git("push", "-q", "-u", "origin", "feat", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "fix: lo que falta subir", cwd=self.repo)
        git("tag", "v1.2.0", cwd=self.repo)
        self.cwd = str(self.repo)


class TestFamiliasPorDefecto(unittest.TestCase):
    def test_por_defecto(self):
        self.assertEqual(set(reglas.FAMILIAS_POR_DEFECTO),
                         {"gcloud run deploy", "gcloud builds submit", "rm -rf", "gcloud run jobs execute",
                          "docker push", "git push"})
        self.assertTrue(set(reglas.FAMILIAS_POR_DEFECTO) <= F.FAMILIAS_IRREVERSIBLES)


class TestPushNiega(BasePush):
    NIEGA = {
        "git push --force origin feat": "--force",
        "git push -f origin feat": "-f",
        "git push -uf origin feat": "-f",
        "git push --force-with-lease origin feat": "--force-with-lease",
        "git push --force-with-lease=feat:abc origin feat": "--force-with-lease",
        "git push --mirror origin": "--mirror",
        "git push origin +feat": "refspec con +",
        "git push origin +feat:main": "refspec con +",
        "git push origin --delete feat": "--delete",
        "git push -d origin feat": "-d",
        "git push origin :vieja": "borra la rama remota vieja",
        "git push --prune origin": "--prune",
        "git push noexiste feat": "el remoto noexiste no existe",
        "git add -A && git push --force": "--force",
        "git -C ../repo push -f": "-f",
    }

    def test_niega(self):
        for cmd, motivo in self.NIEGA.items():
            with self.subTest(cmd=cmd):
                d = self.decision(self.hook(cmd))
                self.assertEqual(d and d["behavior"], "deny", cmd)
                self.assertIn(motivo, d["message"])
        self.assertEqual(self.fake_log(), [], "las reglas deterministas no llaman al modelo")
        self.assertTrue(all(e["via"] == "regla" and e["familia"] == "git push" for e in self.auditoria()))

    def test_remoto_de_la_rama_inexistente(self):
        git("config", "branch.feat.pushRemote", "fantasma", cwd=self.repo)
        d = self.decision(self.hook("git push"))
        self.assertEqual(d["behavior"], "deny")
        self.assertIn("el remoto fantasma no existe", d["message"])

    def test_remote_add_en_el_mismo_comando_va_al_modelo(self):
        r = self.hook("git remote add nuevo /var/tmp/x.git && git push -u nuevo feat")
        self.assertEqual(self.decision(r), {"behavior": "allow"})
        self.assertEqual(self.auditoria()[-1]["via"], "modelo")


class TestPushPermite(BasePush):
    PERMITE = [
        "git push origin feat",
        "git push -u origin feat",
        "git push --set-upstream origin feat",
        "git push",
        "git push origin",
        "git push origin HEAD",
        "git push origin HEAD:feat",
        "git push origin feat:refs/heads/otra",
        "git push -v --no-verify origin feat",
        "git push origin feat 2>&1 | tail -3",
        "git add -A && git commit -m 'x' && git push origin feat",
        "git commit -m \"$(cat <<'EOF'\nfeat: algo\n\nCo-Authored-By: x\nEOF\n)\" && git push",
        "git status && git push origin feat; echo listo",
    ]

    def test_permite_sin_modelo(self):
        for cmd in self.PERMITE:
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(self.decision(r), {"behavior": "allow"}, r.stdout + str(self.bitacora()[-1:]))
                self.assertIn("git push de ", r.json["systemMessage"])
        self.assertEqual(self.fake_log(), [])
        self.assertTrue(all(e["via"] == "regla" for e in self.auditoria()))
        self.assertTrue(all(l == "PERMITE git push regla" for l in self.bitacora()), self.bitacora())

    def test_arbol_sucio_no_importa(self):
        (self.repo / "nuevo.txt").write_text("x")
        self.assertEqual(self.decision(self.hook("git push origin feat")), {"behavior": "allow"})
        self.assertEqual(self.fake_log(), [])

    def test_desde_otro_cwd(self):
        otro = str(self.proy)
        for cmd in (f"cd {self.repo} && git push origin feat", f"git -C {self.repo} push origin feat",
                    "cd ../repo && git push", "(cd ../repo && git push origin feat)"):
            with self.subTest(cmd=cmd):
                r = self.hook(cmd, cwd=otro)
                self.assertEqual(self.decision(r), {"behavior": "allow"}, r.stdout)
        self.assertEqual(self.fake_log(), [])

    def test_reglas_en_menos_de_300_ms(self):
        cmds = ["git push origin feat", "git push", "git push --force origin feat", "git push origin :vieja",
                "git add -A && git commit -m x && git push -u origin feat"]
        tiempos = []
        for cmd in cmds:
            r = self.hook(cmd)
            self.assertIsNotNone(r.json)
            tiempos.append(round(r.ms))
        internos = [e["duracion_ms"] for e in self.auditoria()]
        print(f"\n  tiempos push (pared ms): {tiempos}; internos (ms): {internos}")
        self.assertTrue(all(ms < 300 for ms in internos), internos)
        self.assertLess(max(tiempos), 300, f"pared (proceso entero): {tiempos}")
        self.assertEqual(self.fake_log(), [])


class TestPushAlModelo(BasePush):
    MODELO = ["git push origin main", "git push origin master", "git push origin feat:main",
              "git push origin HEAD:refs/heads/main", "git push origin production", "git push origin prod-eu",
              "git push origin release-1.2", "git push --tags", "git push origin --tags", "git push origin v1.2.0",
              "git push origin refs/tags/v1.2.0", "git push --all origin", "git push --follow-tags",
              "git push origin feat && curl -s x", "git push origin $(git branch --show-current)",
              "git -c remote.origin.url=x push origin feat", "git push -o ci.skip origin feat",
              "xargs git push origin < ramas.txt"]

    def test_van_al_modelo(self):
        for cmd in self.MODELO:
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(self.decision(r), {"behavior": "allow"}, cmd)
                self.assertEqual(self.auditoria()[-1]["via"], "modelo", cmd)
        self.assertEqual(len(self.fake_log()), len(self.MODELO))

    def test_rama_main_sin_destino(self):
        git("checkout", "-q", "main", cwd=self.repo)
        r = self.hook("git push")
        self.assertEqual(self.auditoria()[-1]["via"], "modelo")
        e = json.loads((self.tmp / "entrada.json").read_text())
        self.assertIn("rama protegida main", e["nota_reglas"])

    def test_contexto_del_modelo(self):
        git("checkout", "-q", "main", cwd=self.repo)
        for i in range(25):
            git("commit", "-q", "--allow-empty", "-m", f"chore: paso {i}", cwd=self.repo)
        # otro clon adelanta el remoto: el push a main tiene el remoto por delante
        otro = self.tmp / "otro"
        git("clone", "-q", str(self.remoto), str(otro))
        git("commit", "-q", "--allow-empty", "-m", "feat: ajeno", cwd=otro)
        git("push", "-q", "origin", "main", cwd=otro)
        git("fetch", "-q", "origin", cwd=self.repo)
        r = self.hook("git push origin main", transcript=None)
        self.assertEqual(self.decision(r), {"behavior": "allow"})
        e = json.loads((self.tmp / "entrada.json").read_text())
        self.assertEqual(e["familias"], ["git push"])
        self.assertIn("rama protegida main", e["nota_reglas"])
        p, = e["push"]
        self.assertEqual((p["remoto"], p["rama_destino"], p["rama_remota_existe"]), ("origin", "main", True))
        self.assertEqual(len(p["commits_a_subir"]), 20)
        self.assertEqual(p["total_commits"], 25)
        self.assertIn("chore: paso 24", p["commits_a_subir"][0])
        self.assertEqual(p["remoto_por_delante"], 1)

    def test_contexto_con_upstream(self):
        git("checkout", "-q", "main", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "feat: subir a main", cwd=self.repo)
        self.hook("git push")
        p, = json.loads((self.tmp / "entrada.json").read_text())["push"]
        self.assertEqual([c.split(" ", 1)[1] for c in p["commits_a_subir"]], ["feat: subir a main"])
        self.assertEqual(p["remoto_por_delante"], 0)

    def test_negado_por_el_modelo(self):
        d = self.decision(self.hook("git push origin main", FAKE_CLAUDE_JUEZ="negar"))
        self.assertEqual(d["behavior"], "deny")
        self.assertTrue(any(l.startswith("NIEGA git push ") for l in self.bitacora()))

    def test_redaccion_de_commits(self):
        git("checkout", "-q", "main", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "fix: rota api_key=CANARIO1", cwd=self.repo)
        r = self.hook("git push origin main")
        self.assertEqual(self.decision(r), {"behavior": "allow"}, self.bitacora())   # el fake sale con 3 si ve CANARIO
        self.assertNotIn("CANARIO", (self.tmp / "entrada.json").read_text())


class TestJobsYDocker(Base):
    JOB = "gcloud run jobs execute migrar --region us-central1 --project mi-proy --wait"
    DOCKER = "docker push us-central1-docker.pkg.dev/mi-proy/apps/api:1.4"

    def test_siempre_al_modelo(self):
        for cmd, fam in ((self.JOB, "gcloud run jobs execute"), (self.DOCKER, "docker push"),
                         ("docker buildx build --push -t x .", "docker push"),
                         ("docker build -t x . && docker push x", "docker push")):
            with self.subTest(cmd=cmd):
                r = self.hook(cmd)
                self.assertEqual(self.decision(r), {"behavior": "allow"})
                a = self.auditoria()[-1]
                self.assertEqual((a["familia"], a["via"]), (fam, "modelo"))
                e = json.loads((self.tmp / "entrada.json").read_text())
                self.assertEqual((e["comando"], e["familias"]), (cmd, [fam]))
                self.assertNotIn("push", e)
                self.assertIn(f"PERMITE {fam} modelo", self.bitacora())
        self.assertEqual(len(self.fake_log()), 4)

    def test_negados(self):
        for cmd, fam in ((self.JOB, "gcloud run jobs execute"), (self.DOCKER, "docker push")):
            with self.subTest(cmd=cmd):
                d = self.decision(self.hook(cmd, FAKE_CLAUDE_JUEZ="negar"))
                self.assertEqual(d["behavior"], "deny")
                self.assertEqual(self.auditoria()[-1]["decision"], "negar")
                self.assertTrue(self.bitacora()[-1].startswith(f"NIEGA {fam} "))

    def test_compuestos(self):
        # dos familias del juez: una sola llamada al modelo con las dos
        self.hook("docker push x && " + self.JOB)
        self.assertEqual(self.auditoria()[-1]["familia"], "gcloud run jobs execute+docker push")
        # una irreversible fuera del juez sigue devolviendo el diálogo
        self.assertEqual(self.hook("docker push x && kubectl apply -f k.yml").stdout, "")
        self.assertEqual(self.bitacora()[-1], "silencio fuera-de-juez kubectl apply/delete")
        self.assertEqual(self.hook("docker push x && npm publish").stdout, "")
        # y un rm -rf peligroso manda aunque haya un docker push
        self.assertEqual(self.decision(self.hook("docker push x && rm -rf /"))["behavior"], "deny")


class TestPushJuntoARmYDeploy(BasePush):
    def test_rm_y_deploy_siguen_igual(self):
        self.assertEqual(self.decision(self.hook("rm -rf build")), {"behavior": "allow"})
        self.assertEqual(self.decision(self.hook("rm -rf /srv/x"))["behavior"], "deny")
        self.assertEqual(self.fake_log(), [])
        self.hook("gcloud run deploy api --image x --region us-central1")
        self.assertEqual(self.auditoria()[-1]["via"], "modelo")

    def test_rm_y_push_juntos(self):
        # cada regla deja PERMITE para su parte, pero cada una ve a la otra como «además»: al modelo
        r = self.hook("rm -rf build && git push origin feat")
        self.assertEqual(self.auditoria()[-1]["via"], "modelo")
        self.assertEqual(self.auditoria()[-1]["familia"], "git push+rm -rf")
        # un NIEGA de cualquiera de las dos manda
        self.assertIn("-f (force)", self.decision(self.hook("rm -rf build && git push -f"))["message"])
        self.assertIn("borra /", self.decision(self.hook("rm -rf / && git push origin feat"))["message"])

    def test_push_fuera_de_la_config(self):
        (self.tmp / "mh").mkdir(exist_ok=True)
        (self.tmp / "mh" / "juez.yml").write_text("familias: [rm -rf]\n")
        self.assertEqual(self.hook("git push origin feat").stdout, "")
        self.assertEqual(self.hook("rm -rf build && git push origin feat").stdout, "")
        self.assertEqual(self.bitacora()[-1], "silencio fuera-de-juez git push")


if __name__ == "__main__":
    unittest.main()
