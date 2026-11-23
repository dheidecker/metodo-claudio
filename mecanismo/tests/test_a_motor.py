"""Frente A: motor de trampas (CONTRATO §3) sin hooks ni git."""
import pathlib
import tempfile
import unittest

import yaml

from lib.trampas import motor

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FIX = RAIZ / "tests" / "fixtures" / "blade"


def trampa(**kw):
    t = {"id": "t", "nivel": "aviso", "globs": ["**/*.txt"], "patron": "MAL", "mensaje": "m", "origen": "o",
         "prueba": {"dispara": "MAL", "no_dispara": "bien"}}
    t.update(kw)
    return t


def lineas(t, texto, cambiadas=None):
    return [n for _, n, _ in motor.aciertos([t], "a.txt", texto, cambiadas)]


class TestGlobs(unittest.TestCase):
    def test_doble_asterisco_es_cero_o_mas_carpetas(self):
        g = "**/*.blade.php"
        for r in ("x.blade.php", "resources/views/x.blade.php", "a/b/c/x.blade.php"):
            self.assertTrue(motor.casa_glob(r, g), r)
        self.assertFalse(motor.casa_glob("x.php", g))
        g = "**/database/migrations/*.php"
        self.assertTrue(motor.casa_glob("database/migrations/2026_x.php", g))
        self.assertTrue(motor.casa_glob("backend/database/migrations/2026_x.php", g))
        self.assertTrue(motor.casa_glob("/abs/ruta/database/migrations/2026_x.php", g))
        self.assertFalse(motor.casa_glob("app/Servicio.php", g))
        self.assertTrue(motor.casa_glob("internal/x.go", "internal/**/*.go"))
        self.assertTrue(motor.casa_glob("internal/a/b/x.go", "internal/**/*.go"))

    def test_relativa(self):
        self.assertEqual(motor.relativa("/r/a/b.txt", "/r"), "a/b.txt")
        self.assertEqual(motor.relativa("/otro/b.txt", "/r"), "/otro/b.txt")

    def test_glob_que_no_casa_no_mira(self):
        self.assertEqual(motor.aciertos([trampa()], "a.php", "MAL", None), [])


class TestSemantica(unittest.TestCase):
    def test_patron_excepto_y_max_despues_de_filtrar(self):
        t = trampa(excepto="ok")
        self.assertEqual(lineas(t, "MAL\nMAL ok\nbien\nMAL\nMAL\nMAL"), [1, 4, 5])  # max 3
        # max cuenta DESPUÉS de filtrar: el 4.º acierto cambiado sí sale (el original lo perdía)
        self.assertEqual(lineas(t, "MAL\nMAL\nMAL\nMAL\nMAL", {4, 5}), [4, 5])
        self.assertEqual(lineas(trampa(max=1), "MAL\nMAL"), [1])
        self.assertEqual(lineas(t, "MAL", set()), [])  # seguido y sin cambios

    def test_bloque(self):
        t = trampa(bloque={"abre": "ABRE", "cierra": "CIERRA"})
        # fuera de bloque no cuenta; un acierto por bloque; la línea de abre y la de cierra cuentan
        self.assertEqual(lineas(t, "MAL\nABRE\nMAL\nMAL\nCIERRA\nMAL"), [3])
        self.assertEqual(lineas(t, "ABRE MAL\nMAL\nCIERRA"), [1])
        self.assertEqual(lineas(t, "ABRE\nx\nMAL CIERRA\nMAL"), [3])
        # un abre dentro de un bloque lo reinicia
        self.assertEqual(lineas(t, "ABRE\nMAL\nABRE\nMAL\nCIERRA"), [2, 4])
        # abre y cierra en la misma línea: bloque de una línea
        self.assertEqual(lineas(t, "ABRE MAL CIERRA\nMAL"), [1])
        # el primer acierto consume el bloque aunque no esté entre las líneas cambiadas
        self.assertEqual(lineas(t, "ABRE\nMAL\nMAL\nCIERRA", {3}), [])

    def test_ejemplo_del_plan(self):
        doc = (RAIZ / "PLAN.md").read_text().split("```yaml\n")[1].split("```")[0]
        self.assertEqual(motor.probar_trampa(yaml.safe_load(doc)), [])


class TestProbar(unittest.TestCase):
    def test_fixture_blade_pasa(self):
        ts = motor.cargar_dir(FIX)
        self.assertEqual(len(ts), 5)
        for t in ts:
            self.assertEqual(motor.probar_trampa(t), [], t["id"])
            self.assertTrue(t["origen"])

    def test_errores(self):
        self.assertEqual(motor.probar_trampa(trampa()), [])
        self.assertIn("`prueba.dispara` no dispara", motor.probar_trampa(trampa(prueba={"dispara": "x", "no_dispara": "y"})))
        self.assertTrue(any("no_dispara` dispara" in e for e in
                            motor.probar_trampa(trampa(prueba={"dispara": "MAL", "no_dispara": "MAL"}))))
        self.assertTrue(any("no compila" in e for e in motor.probar_trampa(trampa(patron="(["))))
        t = trampa()
        del t["origen"]
        self.assertIn("falta `origen`", motor.probar_trampa(t))
        self.assertTrue(motor.probar_trampa(trampa(id="Con Espacios")))
        self.assertTrue(motor.probar_trampa(trampa(nivel="grave")))
        self.assertTrue(motor.probar_trampa(trampa(otro=1)))
        self.assertTrue(motor.probar_trampa(trampa(max=0)))
        self.assertTrue(motor.probar_trampa(trampa(bloque={"abre": "x"})))
        # una trampa inválida no rompe aciertos(): se salta
        self.assertEqual(motor.aciertos([trampa(patron="(["), trampa(id="b")], "a.txt", "MAL", None),
                         [("a.txt", 1, "b")])


class TestCarga(unittest.TestCase):
    def test_mapping_lista_y_propuestas(self):
        d = pathlib.Path(tempfile.mkdtemp())
        tr = d / ".claude" / "trampas"
        (tr / "propuestas").mkdir(parents=True)
        (tr / "una.yml").write_text(yaml.safe_dump(trampa(id="una")))
        (tr / "varias.yml").write_text(yaml.safe_dump([trampa(id="dos"), trampa(id="tres")]))
        (tr / "vacio.yml").write_text("")
        (tr / "otra.yaml").write_text(yaml.safe_dump(trampa(id="no-yml")))
        (tr / "propuestas" / "p.yml").write_text(yaml.safe_dump(trampa(id="propuesta")))
        (tr / "rota.yml").write_text("- id: [\n")
        errores = []
        self.assertEqual(sorted(t["id"] for t in motor.cargar_trampas(d, errores)), ["dos", "tres", "una"])
        self.assertEqual(len(errores), 1)
        self.assertIn("rota.yml", errores[0])
        self.assertEqual(motor.cargar_trampas(d / "no-existe"), [])


class TestDiferenciasIntencionales(unittest.TestCase):
    """Donde el contrato se aparta a propósito de blade-trampas.sh (fuera de la paridad)."""

    def wire(self):
        return {t["id"]: t for t in motor.cargar_dir(FIX)}["wire-model-sin-live"]

    def test_excepto_no_consume_el_bloque(self):
        # El awk original: la línea con wire:model=" y .live «consume» el bloque y la 3 no sale.
        # Contrato: esa línea solo no cuenta; el bloque sigue abierto y la 3 sí sale.
        texto = '<select\n  wire:model="a" wire:model.live="b"\n  wire:model="c">\n</select>'
        self.assertEqual(lineas(dict(self.wire(), globs=["**/*.txt"]), texto), [3])

    def test_cuarto_acierto_cambiado_sale(self):
        t = {t["id"]: t for t in motor.cargar_dir(FIX)}["x-init-con-bloque"]
        texto = "\n".join(['<div x-init="a(); b()">'] * 4)
        hits = motor.aciertos([t], "v.blade.php", texto, {4})
        self.assertEqual(hits, [("v.blade.php", 4, "x-init-con-bloque")])  # el original: nada


if __name__ == "__main__":
    unittest.main()
