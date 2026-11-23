"""Frente C: vía web con la CLI chrome-devtools contra una página servida por http.server.

La página pide un CSS que da 404 y hace console.error('CANARIO-web'): `verificar` tiene que fallar
y nombrar los dos. Sin chrome-devtools en el PATH el test se salta con ese motivo.
"""
import os
import pathlib
import re
import subprocess
import sys
import unittest

from lib.evidencia.adaptadores import web
from tests.c_entorno import FIXTURES, EntornoC

SITIO = FIXTURES / "web" / "sitio"
PROYECTO = FIXTURES / "web" / "proyecto"


class EntornoWeb(EntornoC):
    def servir(self) -> str:
        p = self.lanzar([sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1",
                         "--directory", str(SITIO)], stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True)
        linea = p.stdout.readline()
        m = re.search(r"port (\d+)", linea)
        self.assertTrue(m, linea)
        return f"http://127.0.0.1:{m.group(1)}"


class TestWeb(EntornoWeb):
    def setUp(self):
        super().setUp()
        if not web.instalado():
            self.skipTest("chrome-devtools no instalado")
        self.cdt_antes = set(pathlib.Path("/tmp").glob("cdt*"))

    def tearDown(self):
        nuevos = set(pathlib.Path("/tmp").glob("cdt*")) - self.cdt_antes
        super().tearDown()
        self.assertEqual(nuevos, set(), "el adaptador web dejó su XDG_RUNTIME_DIR")

    def test_pagina_con_404_y_console_error_falla_y_nombra_ambos(self):
        p = self.proyecto(PROYECTO, subs={"@BASE@": self.servir()})
        r = self.verificar(p)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ev = self.ultima_evidencia(p)
        self.comprobar_esquema(ev)
        portada = next(f for f in ev["funciones"] if f["id"] == "portada")
        limpia = next(f for f in ev["funciones"] if f["id"] == "limpia")
        self.assertFalse(portada["ok"])
        self.assertRegex(portada["resumen"], r"404 GET http://127\.0\.0\.1:\d+/no-existe-CANARIO\.css")
        self.assertIn("console.error: CANARIO-web", portada["resumen"])
        self.assertTrue(limpia["ok"], limpia["resumen"])
        for f in (portada, limpia):
            self.assertEqual(len(f["capturas"]), 1)
            self.assertTrue((p / f["capturas"][0]).stat().st_size > 0)
        self.assertIn("404", r.stdout)
        self.assertIn("CANARIO-web", r.stdout)


class TestWebSinCLI(EntornoWeb):
    def test_sin_chrome_devtools_da_ok_false_con_el_motivo(self):
        p = self.proyecto(PROYECTO, subs={"@BASE@": "http://127.0.0.1:9"})
        env = dict(self.env, PATH=os.pathsep.join(d for d in ("/usr/bin", "/bin") if os.path.isdir(d)))
        r = self.verificar(p, "--funciones", "limpia", env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(self.ultima_evidencia(p)["funciones"][0]["resumen"], "chrome-devtools no instalado")


if __name__ == "__main__":
    unittest.main()
