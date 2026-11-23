"""Frente C: vía `test` (adaptador lib) y piezas de núcleo (globs, vigencia)."""
import sys
import unittest

from lib.evidencia import nucleo
from tests.c_entorno import EntornoC

MAPA = """funciones:
  - id: pasa
    globs: ["src/pasa/**"]
    test: "{py} -c \\"print('linea-1'); print('todo bien')\\""
  - id: falla
    globs: ["src/falla.py"]
    test: "{py} -c \\"import sys; print('CANARIO-cola'); sys.exit(3)\\""
  - id: lenta
    globs: ["src/lenta.py"]
    test: "{py} -c \\"import time; time.sleep(30)\\""
"""


class TestViaTest(EntornoC):
    def armar(self, timeout=None):
        d = self.tmp / "fuente"
        (d / ".claude").mkdir(parents=True)
        (d / "src" / "pasa").mkdir(parents=True)
        (d / ".claude" / "mecanismo.yml").write_text(
            "version: 1\ntipo: lib\npuerta: aviso\n" + (f"lib: {{timeout: {timeout}}}\n" if timeout else ""))
        (d / ".claude" / "mapa-funciones.yml").write_text(MAPA.format(py=sys.executable))
        (d / "src" / "pasa" / "a.py").write_text("a = 1\n")
        (d / "src" / "falla.py").write_text("b = 1\n")
        (d / "src" / "lenta.py").write_text("c = 1\n")
        p = self.proyecto(d)
        self.confiar(p)
        return p

    def test_pasa_y_guarda_la_cola(self):
        p = self.armar()
        r = self.verificar(p, "--funciones", "pasa")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ev = self.ultima_evidencia(p)
        self.comprobar_esquema(ev)
        f = ev["funciones"][0]
        self.assertEqual(f["resumen"], "exit 0: todo bien")
        self.assertIn("todo bien", (p / f["capturas"][0]).read_text())
        self.assertEqual(ev["tipo"], "lib")

    def test_falla_con_exit_1_y_la_cola_en_el_diff(self):
        p = self.armar()
        r = self.verificar(p, "--funciones", "falla")
        self.assertEqual(r.returncode, 1)
        f = self.ultima_evidencia(p)["funciones"][0]
        self.assertFalse(f["ok"])
        self.assertIn("exit 3", f["resumen"])
        self.assertIn("CANARIO-cola", f["diffs"][0])

    def test_timeout(self):
        p = self.armar(timeout=1)
        r = self.verificar(p, "--funciones", "lenta")
        self.assertEqual(r.returncode, 1)
        self.assertIn("timeout tras 1 s", self.ultima_evidencia(p)["funciones"][0]["resumen"])

    def test_sin_cambios_verifica_todas(self):
        p = self.armar(timeout=1)
        self.verificar(p)
        self.assertEqual([f["id"] for f in self.ultima_evidencia(p)["funciones"]], ["pasa", "falla", "lenta"])


class TestNucleo(unittest.TestCase):
    def test_globs_doble_asterisco(self):
        self.assertTrue(nucleo.casa("src/sumar.py", ["src/**/sumar.py"]))
        self.assertTrue(nucleo.casa("src/a/b/sumar.py", ["src/**/sumar.py"]))
        self.assertTrue(nucleo.casa("internal/consultar/x/y.go", ["internal/consultar/**"]))
        self.assertTrue(nucleo.casa("a.sql", ["**/*.sql"]))
        self.assertFalse(nucleo.casa("internal/otro/y.go", ["internal/consultar/**"]))

    def test_vigente_exige_hash_y_ok(self):
        evs = [  # la más reciente primero
            {"huellas": {"a.go": "h2"}, "funciones": [{"id": "f", "ok": False}]},
            {"huellas": {"a.go": "h1"}, "funciones": [{"id": "f", "ok": True}]},
        ]
        self.assertTrue(nucleo.vigente("a.go", "h1", "f", evs))
        self.assertFalse(nucleo.vigente("a.go", "h2", "f", evs))   # ok: false no vale
        self.assertFalse(nucleo.vigente("a.go", "h3", "f", evs))   # otro hash no vale
        self.assertFalse(nucleo.vigente("a.go", "h1", "g", evs))   # otra función no cubre


if __name__ == "__main__":
    unittest.main()
