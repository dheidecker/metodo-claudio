"""Frente C: hooks/stop-evidencia alimentado por stdin. Solo lee evidencia: nunca verifica."""
import json
import unittest

from tests.c_entorno import FIXTURES, SERVIDOR_MCP, EntornoC

OK = FIXTURES / "mcp" / "mcp-ok"
ROTO = FIXTURES / "mcp" / "mcp-roto"
SUBS = {"@SERVIDOR@": str(SERVIDOR_MCP)}
CMD_SUMAR = "mecanismo verificar --funciones sumar"


class TestStopEvidencia(EntornoC):
    def entrada(self, p, **kw):
        return {"session_id": self.sid, "cwd": str(p), "hook_event_name": "Stop", **kw}

    def puerta(self, p, valor):
        conf = p / ".claude" / "mecanismo.yml"
        conf.write_text(conf.read_text().replace("puerta: aviso", f"puerta: {valor}"))

    def assert_aviso(self, r, comando=CMD_SUMAR):
        self.assertEqual(r.returncode, 0, r.stderr)
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertIn(comando, msg)
        return msg

    def test_stop_hook_active_sale_0(self):
        p = self.proyecto(OK, subs=SUBS)
        self.tocar(p / "src" / "sumar.py")
        r = self.hook(self.entrada(p, stop_hook_active=True))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_sin_mecanismo_yml_sale_0_en_silencio(self):
        d = self.tmp / "otro"
        d.mkdir()
        self.git(d, "init", "-q")
        (d / "x.py").write_text("x = 1\n")
        r = self.hook(self.entrada(d))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.bitacora(), "")

    def test_aviso_sale_0_con_el_comando(self):
        p = self.proyecto(OK, subs=SUBS)
        self.tocar(p / "src" / "sumar.py")
        msg = self.assert_aviso(self.hook(self.entrada(p)))
        self.assertIn("src/sumar.py", msg)
        self.assertNotIn("saludar", msg)
        self.assertIn("AVISO sumar", self.bitacora())

    def test_bloqueo_sale_2_con_el_comando_exacto(self):
        p = self.proyecto(OK, subs=SUBS)
        self.puerta(p, "bloqueo")
        self.tocar(p / "src" / "sumar.py")
        self.tocar(p / "src" / "saludar" / "hola.py")
        r = self.hook(self.entrada(p))
        self.assertEqual(r.returncode, 2)
        self.assertIn("mecanismo verificar --funciones saludar,sumar", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("BLOQUEO saludar,sumar", self.bitacora())

    def test_vigente_sale_0_y_hash_cambiado_vuelve_a_avisar(self):
        p = self.proyecto(OK, subs=SUBS)
        self.puerta(p, "bloqueo")
        self.git(p, "commit", "-qam", "puerta bloqueo")
        self.tocar(p / "src" / "sumar.py")
        self.assertEqual(self.hook(self.entrada(p)).returncode, 2)
        v = self.verificar(p)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        r = self.hook(self.entrada(p))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertIn("ok evidencia vigente", self.bitacora())
        # otro cambio: la huella vieja ya no vale
        self.tocar(p / "src" / "sumar.py", "# otro cambio\n")
        r = self.hook(self.entrada(p))
        self.assertEqual(r.returncode, 2)
        self.assertIn(CMD_SUMAR, r.stderr)

    def test_hash_cambiado_en_modo_aviso(self):
        p = self.proyecto(OK, subs=SUBS)
        self.tocar(p / "src" / "sumar.py")
        self.assertEqual(self.verificar(p).returncode, 0)
        r = self.hook(self.entrada(p))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.tocar(p / "src" / "sumar.py", "# otro\n")
        self.assert_aviso(self.hook(self.entrada(p)))

    def test_evidencia_con_ok_false_no_vale(self):
        p = self.proyecto(ROTO, subs=SUBS)
        self.tocar(p / "src" / "sumar.py")
        self.tocar(p / "src" / "saludar" / "hola.py")
        self.assertEqual(self.verificar(p).returncode, 1)
        msg = self.assert_aviso(self.hook(self.entrada(p)))
        self.assertNotIn("saludar", msg)  # saludar sí quedó ok con la misma huella

    def test_archivos_fuera_del_mapa_no_exigen_pero_se_anotan(self):
        p = self.proyecto(OK, subs=SUBS)
        self.tocar(p / "LEEME.txt", "cambio\n")
        (p / "nuevo.txt").write_text("sin seguimiento\n")
        r = self.hook(self.entrada(p))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertRegex(self.bitacora(), r"stop-evidencia\s+\|.*\| silencio sin-mapa 2 ")

    def test_sin_pyyaml_sale_0_y_lo_anota(self):
        p = self.proyecto(OK, subs=SUBS)
        self.tocar(p / "src" / "sumar.py")
        falso = self.tmp / "sin-yaml"
        falso.mkdir()
        (falso / "yaml.py").write_text("raise ImportError('PyYAML ausente (test)')\n")
        env = dict(self.env, PYTHONPATH=f"{falso}")
        r = self.hook(self.entrada(p), env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertIn("sin-pyyaml", self.bitacora())

    def test_no_verifica_nunca(self):
        """El hook no arranca el servidor ni escribe evidencia: solo lee."""
        p = self.proyecto(OK, subs={"@SERVIDOR@": "/no/existe.py"})
        self.tocar(p / "src" / "sumar.py")
        self.assert_aviso(self.hook(self.entrada(p)))
        self.assertFalse((p / ".claude" / "evidencia").exists())


if __name__ == "__main__":
    unittest.main()
