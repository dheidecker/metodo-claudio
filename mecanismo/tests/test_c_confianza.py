"""Frente C: confianza de comandos del proyecto (CONTRATO §11, como `direnv allow`).

Un agente que edita `.claude/mapa-funciones.yml` y corre `mecanismo verificar` (que puede estar en la
lista allow) no debe poder ejecutar nada: sin `mecanismo confiar` de una persona, verificar no corre
ni el `arranque`, deja evidencia ok: false y sale con 1.
"""
import json
import subprocess
import sys
import unittest

from lib.evidencia import confianza
from tests.c_entorno import FIXTURES, SERVIDOR_MCP, EntornoC

OK = FIXTURES / "mcp" / "mcp-ok"
SUBS = {"@SERVIDOR@": str(SERVIDOR_MCP)}
CONF = ".claude/mecanismo.yml"
MAPA = ".claude/mapa-funciones.yml"


class TestConfianza(EntornoC):
    def armar(self, test='touch pwnec', extra_conf=""):
        d = self.tmp / "fuente"
        (d / ".claude").mkdir(parents=True)
        (d / "src").mkdir()
        (d / ".claude" / "mecanismo.yml").write_text("version: 1\ntipo: lib\npuerta: aviso\n" + extra_conf)
        (d / ".claude" / "mapa-funciones.yml").write_text(
            f'funciones:\n  - id: f\n    globs: ["src/**"]\n    test: "{test}"\n')
        (d / "src" / "a.py").write_text("a = 1\n")
        return self.proyecto(d)

    def assert_negado(self, p, r, testigos=("pwned",)):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("mecanismo confiar", r.stderr)
        self.assertIn("No se ejecutó nada", r.stderr)
        for t in testigos:
            self.assertFalse((p / t).exists(), f"se ejecutó un comando no confiado: {t}")
        ev = self.ultima_evidencia(p)
        self.comprobar_esquema(ev)
        self.assertFalse(ev["ok"])
        for f in ev["funciones"]:
            self.assertFalse(f["ok"])
            self.assertEqual(f["resumen"], "configuración no confiada: corre `mecanismo confiar`")
        self.assertRegex(self.bitacora(), r"\| verificar\s+\|.*\| AVISO no-confiada ")

    def test_sin_confiar_no_ejecuta_nada(self):
        p = self.armar(test="touch pwned")
        self.assert_negado(p, self.verificar(p))

    def test_confiado_ejecuta(self):
        """Control positivo: con la confianza, el mismo tipo de comando sí corre."""
        p = self.armar(test="touch hecho")
        self.confiar(p)
        r = self.verificar(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((p / "hecho").exists())
        self.assertIn("ok confiar ", self.bitacora())

    def test_una_letra_del_mapa_invalida_la_confianza(self):
        p = self.armar(test="touch pwnec")
        self.confiar(p)
        m = p / MAPA
        m.write_text(m.read_text().replace("pwnec", "pwned"))   # una letra
        self.assert_negado(p, self.verificar(p), testigos=("pwned", "pwnec"))

    def test_una_letra_de_mecanismo_yml_invalida_la_confianza(self):
        p = self.armar(test="touch pwned")
        self.confiar(p)
        c = p / CONF
        c.write_text(c.read_text().replace("puerta: aviso", "puerta: avisa"))
        self.assert_negado(p, self.verificar(p))
        self.assertFalse(confianza.es_confiable(p))

    def test_sin_confiar_no_corre_ni_el_arranque(self):
        """mcp por url (que sola no necesita confianza) pero con `arranque`: no corre nada."""
        p = self.armar(test="true", extra_conf='arranque: "touch pwned-arranque"\n'
                                                'mcp: {url: "http://127.0.0.1:9/mcp"}\n')
        m = p / MAPA
        m.write_text('funciones:\n  - id: f\n    globs: ["src/**"]\n    mcp: {tool: x}\n')
        self.assert_negado(p, self.verificar(p), testigos=("pwned-arranque",))

    def test_mcp_stdio_sin_confiar_no_lanza_el_servidor(self):
        p = self.proyecto(OK, subs={"@SERVIDOR@": "/no/existe.py"})
        c = p / CONF
        c.write_text(c.read_text().replace('comando: "python3 /no/existe.py --modo ok"', 'comando: "touch pwned"'))
        self.assert_negado(p, self.verificar(p))

    def test_mcp_por_url_sin_arranque_no_necesita_confianza(self):
        p = self.proyecto(OK, subs=SUBS)
        url = self.servidor_mcp_http("ok")
        self.editar_yml(p, CONF, comando=None, url=url)
        r = self.verificar(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("no-confiada", self.bitacora())

    def test_confianza_es_por_raiz(self):
        p = self.armar(test="touch pwned")
        self.confiar(p)
        with self.entorno_proceso():
            self.assertTrue(confianza.es_confiable(p))
        q = self.tmp / "copia"
        subprocess.run(["cp", "-a", str(p), str(q)], check=True)
        (q / "pwned").unlink(missing_ok=True)
        self.assert_negado(q, self.verificar(q))  # mismo contenido, otra raíz: no confiada

    def test_confiar_muestra_todos_los_comandos(self):
        p = self.armar(test="touch pwnec", extra_conf='arranque: "make servir"\nmcp: {comando: "python3 s.py"}\n')
        rc, out = self.confiar(p)
        self.assertEqual(rc, 0)
        for c in ("make servir", "python3 s.py", "touch pwnec", "test de f"):
            self.assertIn(c, out)

    def test_confiar_escapa_caracteres_de_control(self):
        p = self.armar(test="echo hola\\e[8m; touch pwned")   # \e[8m oculta texto en una terminal
        _, out = self.confiar(p)
        self.assertNotIn("\x1b", out)
        self.assertIn("touch pwned", out)

    def test_confiar_sin_si_no_guarda(self):
        p = self.armar()
        rc, _ = self.confiar(p, respuesta="no")
        self.assertEqual(rc, 1)
        with self.entorno_proceso():
            self.assertFalse(confianza.es_confiable(p))
        self.assert_negado(p, self.verificar(p))

    def test_confiar_si_el_yml_cambia_mientras_se_confirma_no_guarda(self):
        p = self.armar(test="touch pwnec")
        m = p / MAPA

        def cambiar_y_responder(_):
            m.write_text(m.read_text().replace("pwnec", "pwned"))
            return "sí"

        from unittest import mock
        with self.entorno_proceso(), mock.patch("lib.comun.exige_tty"), \
                mock.patch("builtins.input", side_effect=cambiar_y_responder), \
                mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(confianza.main([str(p)]), 1)
            self.assertFalse(confianza.es_confiable(p))

    def test_confiar_sin_tty_sale_3_y_no_guarda(self):
        """Sin parchear exige_tty: como lo correría un agente (sin TTY, o con CLAUDECODE)."""
        p = self.armar()
        for env in (dict(self.env, CLAUDECODE="1"), {k: v for k, v in self.env.items() if k != "CLAUDECODE"}):
            r = subprocess.run([sys.executable, "-m", "lib.evidencia.confianza", str(p)], input="sí\n",
                               env=env, cwd=str(p), capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            self.assertIn("touch pwnec", r.stdout)   # muestra lo que se confiaría antes de negarse
        self.assertFalse((self.tmp / "mecanismo" / "confianza.json").exists())
        self.assert_negado(p, self.verificar(p), testigos=("pwnec",))

    def test_registro_corrupto_no_es_confiable(self):
        p = self.armar()
        self.confiar(p)
        reg = self.tmp / "mecanismo" / "confianza.json"
        d = json.loads(reg.read_text())
        self.assertEqual(set(d[str(p.resolve())]), {"sha256", "fecha"})
        reg.write_text("{no es json")
        with self.entorno_proceso():
            self.assertFalse(confianza.es_confiable(p))
        self.confiar(p)   # confiar sobre un registro corrupto lo rehace
        with self.entorno_proceso():
            self.assertTrue(confianza.es_confiable(p))

    def test_huella_archivo_ausente_cuenta_como_vacio(self):
        p = self.armar()
        (p / MAPA).unlink()
        self.assertEqual(confianza.huella_de(p), confianza.huella((p / CONF).read_bytes(), b""))
        self.assertNotEqual(confianza.huella(b"a", b""), confianza.huella(b"", b"a"))


if __name__ == "__main__":
    unittest.main()
