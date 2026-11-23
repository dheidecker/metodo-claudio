"""Frente D: ninguna regla allow propuesta casa con un irreversible conocido, y `rm` con ruta,
escapado o con envoltorio se clasifica igual que `rm`. Siempre sobre un ~/.claude falso."""
import random
import unittest
from unittest import mock

from lib.permisos import analisis, familias, propuestas, reglas
from lib.permisos.fuente import Decision
from tests.test_d_permisos import APROBADO, Entorno, sesion_sintetica

SIN_REGLAS = {"allow": [], "ask": []}


def aprobado(cmd: str, dia: str = "2026-11-10") -> Decision:
    return Decision("Bash", cmd, "accept", "user_temporary", "bashMiss:no-rule-match", None, "p", dia, False)


def allow_de(cmds: list[str]) -> list[str]:
    a = analisis.analizar([aprobado(c) for c in cmds], 90, False, SIN_REGLAS)
    return [p["contenido"]["regla"] for p in propuestas.generar(a, SIN_REGLAS) if p["tipo"] == "permiso-allow"]


# Comandos benignos que comparten prefijo con algún irreversible del corpus.
BENIGNOS = [
    "npm run build", "npm run test", "npm run lint", "npm run dev", "npm ci", "npm test", "npm ls",
    "pnpm install", "pnpm run build", "yarn test", "yarn run lint",
    "docker image ls", "docker image inspect img:1", "docker images", "docker ps", "docker compose ps",
    "docker compose logs api", "docker compose up -d", "docker compose config", "docker buildx ls",
    "docker build -t x .", "docker", "podman ps",
    "gcloud run jobs list", "gcloud run jobs describe j", "gcloud run services list", "gcloud builds list",
    "gcloud run revisions list", "gcloud app versions list", "gcloud functions list", "gcloud compute instances list",
    "git status", "git log --oneline", "git diff", "git fetch", "git pull", "git -C repo status", "git",
    "kubectl get pods", "kubectl describe pod x", "kubectl logs x", "kubectl -n x get svc",
    "terraform plan", "terraform fmt", "terraform validate", "terraform -chdir=infra plan",
    "gh pr view 3", "gh pr list", "gh pr checks 3", "gh run list",
    "rm a.txt", "rm -f b.log", "rm -r dir", "rm -i x", "/bin/rm x.tmp", "\\rm -f y.log", "rm -- -rf",
    "make build", "make test", "firebase emulators:start", "fly status", "vercel ls",
    "php artisan migrate:status", "python3 manage.py check", "bin/rails db:migrate:status",
]


class TestNormalizacion(unittest.TestCase):
    def test_rm_con_ruta_escapado_o_envuelto(self):
        for cmd in ("/bin/rm -rf build", "/usr/bin/rm -rf x", "\\rm -rf x", "command rm -rf x", "builtin rm -rf x",
                    "sudo rm -rf x", "sudo -u root rm -rf x", "env A=1 rm -rf x", "env -i A=1 B=2 rm -rf x",
                    "nice rm -rf x", "nice -n 5 rm -rf x", "A=1 /bin/rm -rf x", "timeout 5 \\rm -rf x",
                    "/usr/bin/sudo /usr/bin/env A=1 nice -n 5 command /bin/rm -rf x",
                    "cd x && /bin/rm -rf build", "echo $(\\rm -rf x)", "X=$(/bin/rm -rf x)", "X=$( /bin/rm -rf x )",
                    "(\\rm -rf x)", "if true; then /bin/rm -rf x; fi"):
            c = familias.clasificar(cmd)
            self.assertEqual((c.familia, c.irreversible), ("rm -rf", True), cmd)

    def test_rm_banderas_en_cualquier_orden(self):
        for cmd in ("rm -rf x", "rm -fr x", "rm -Rf x", "rm -fR x", "rm -r -f x", "rm -f -r x", "rm -R -f x",
                    "rm --recursive --force x", "rm --force --recursive x", "rm -r --force x", "rm --recursive -f x",
                    "rm x -rf", "rm -v -r x -f", "rm -rfv x"):
            self.assertTrue(familias.es_irreversible(cmd), cmd)
        for cmd in ("rm a.txt", "rm -f b.log", "rm -r dir", "rm -R dir", "rm -i x", "rm -- -rf", "/bin/rm x.tmp"):
            c = familias.clasificar(cmd)
            self.assertEqual((c.familia, c.irreversible), ("rm", False), cmd)

    def test_normalizacion_aplica_a_todas_las_familias(self):
        casos = {
            "/usr/bin/git push origin feat": "git push", "\\git push": "git push", "sudo docker push img": "docker push",
            "env NODE_ENV=x npm publish": "npm publish", "nice -n 5 terraform apply": "terraform apply",
            "/usr/local/bin/gcloud run deploy api": "gcloud run deploy", "command kubectl delete pod x":
            "kubectl apply/delete", "builtin \\gh pr merge 3": "gh pr merge", "sudo -u d /opt/bin/firebase deploy":
            "deploy", "/usr/bin/docker compose push": "docker push", "docker-compose push": "docker push",
            "docker buildx build --push -t x .": "docker push",
        }
        for cmd, fam in casos.items():
            self.assertEqual(familias.clasificar(cmd).familia, fam, cmd)
        self.assertEqual(familias.normalizar("sudo -u r env -i A=1 nice -n 5 /bin/rm -rf x"), "rm -rf x")
        self.assertEqual(familias.normalizar("command -v rm"), "command -v rm")    # consulta, no ejecución
        self.assertEqual(familias.nombre_generico("/usr/bin/ls -la"), "ls")
        self.assertEqual(familias.nombre_generico("\\ls"), "ls")


class TestCasadoClaude(unittest.TestCase):
    def test_semantica_de_prefijo(self):
        c = reglas.casa_claude
        self.assertTrue(c("Bash(npm run *)", "npm run deploy"))
        self.assertTrue(c("Bash(npm run *)", "npm run"))
        self.assertFalse(c("Bash(npm run *)", "npm runner"))
        self.assertTrue(c("Bash(npm run*)", "npm runner"))
        self.assertTrue(c("Bash(npm run:*)", "npm run deploy"))
        self.assertTrue(c("Bash(npm run build)", "npm run build"))
        self.assertFalse(c("Bash(npm run build)", "npm run build --x"))
        self.assertTrue(c("Bash(npm run *)", "cd x && npm run deploy"))         # cada subcomando cuenta
        self.assertFalse(c("Bash(npm run build)", "npm run deploy"))
        self.assertTrue(c("Bash(rm *.log)", "rm -rf x.log"))                       # `*` en medio es comodín
        self.assertTrue(c("Bash", "git push"))

    def test_corpus_cubre_cada_irreversible(self):
        for fam in familias.FAMILIAS_IRREVERSIBLES:
            self.assertTrue(familias.CORPUS.get(fam), fam)
            for cmd in familias.CORPUS[fam]:
                c = familias.clasificar(cmd)
                self.assertEqual((c.familia, c.irreversible), (fam, True), cmd)
        for fam in familias.NUNCA_ALLOW:
            self.assertTrue(any(c.startswith(fam + " ") for c in familias.CORPUS_NUNCA_ALLOW), fam)


class TestReglaNoCasaIrreversibles(Entorno):
    def test_ejemplo_de_la_revision(self):
        anchas = {"Bash(npm run *)": "npm run deploy", "Bash(docker image *)": "docker image push img:1",
                  "Bash(gcloud run jobs *)": "gcloud run jobs execute j", "Bash(docker compose *)": "docker compose push"}
        for regla, irrev in anchas.items():
            self.assertTrue(reglas.casa_claude(regla, irrev), regla)
            self.assertFalse(propuestas.regla_segura(regla), regla)
        sesion_sintetica(self.home, [(c, APROBADO) for c in
                                     ["npm run build"] * 3 + ["docker image ls"] * 3 + ["gcloud run jobs list"] * 3
                                     + ["docker compose ps"] * 2 + ["docker compose logs api"] + ["npm test"] * 3])
        rc, _ = self.correr("--dias", "90", "--proponer")
        self.assertEqual(rc, 0)
        ps = [p for p in self.propuestas_escritas().values() if p["tipo"] == "permiso-allow"]
        self.assertEqual(sorted(p["contenido"]["regla"] for p in ps),
                         ["Bash(docker compose ps)", "Bash(docker image ls)", "Bash(gcloud run jobs list)",
                          "Bash(npm run build)", "Bash(npm test *)"])
        for p in ps:
            self.assertIsNone(reglas.casa_corpus(p["contenido"]["regla"]), p["contenido"]["regla"])
            if "*" not in p["contenido"]["regla"]:
                self.assertIn("Estrechada", p["nota"])

    def test_rm_nunca_con_comodin(self):
        for r in ("Bash(rm *)", "Bash(rm*)", "Bash(rm:*)", "Bash(rm -i *)", "Bash(rm -f *)", "Bash(/bin/rm *)"):
            self.assertFalse(propuestas.regla_segura(r), r)
        reglas_rm = allow_de(["rm a.txt", "rm -f b.log", "/bin/rm -rf build"] * 3)
        self.assertNotIn("Bash(rm *)", reglas_rm)
        self.assertEqual(reglas_rm, ["Bash(rm a.txt)"])                  # estrechada al exacto más frecuente
        self.assertEqual(allow_de(["rm *.tmp"] * 5), [])                 # el exacto lleva comodín: se descarta

    def test_si_ni_el_exacto_es_seguro_se_descarta(self):
        self.assertEqual(allow_de(["docker compose ps --format '(x)'"] * 4), [])
        self.assertEqual(allow_de(["npm run build:*"] * 4), [])

    def test_defensa_final_sobre_la_regla(self):
        falsa = propuestas._base("permiso-allow", "npm run", "x", "x", {}, {
            "lista": "allow", "accion": "agregar", "regla": "Bash(npm run *)", "comando_jq": "jq"}, None)
        a = analisis.analizar([], 90, False, SIN_REGLAS)
        with mock.patch.object(propuestas, "_permiso_allow", return_value=[falsa]):
            self.assertEqual(propuestas.generar(a, SIN_REGLAS), [])

    def test_propiedad_ninguna_regla_casa_con_el_corpus(self):
        for cmd in BENIGNOS:
            self.assertFalse(familias.es_irreversible(cmd), cmd)
        rnd = random.Random(20261123)
        anchas = exactas = 0
        for _ in range(120):
            elegidos = rnd.sample(BENIGNOS, rnd.randint(1, 8))
            cmds = [c for c in elegidos for _ in range(rnd.randint(1, 6))]
            rnd.shuffle(cmds)
            for regla in allow_de(cmds):
                self.assertIsNone(reglas.casa_corpus(regla), (regla, elegidos))
                self.assertTrue(any(reglas.casa_claude(regla, c) for c in cmds), regla)
                anchas += "*" in regla
                exactas += "*" not in regla
        self.assertGreater(anchas, 0)      # la prueba no es vacía: salen reglas de los dos tipos
        self.assertGreater(exactas, 0)


if __name__ == "__main__":
    unittest.main()
