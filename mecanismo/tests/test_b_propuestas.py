"""Frente B: `mecanismo propuestas | ver | aprobar | rechazar`."""
import contextlib
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

from lib import comun
from lib.propuestas import almacen, cli

RAIZ = pathlib.Path(__file__).resolve().parent.parent
VARS = ("CLAUDE_HOME", "MECANISMO_HOME", "MECANISMO_BITACORA", "CLAUDE_PROJECT_DIR")


def propuesta(pid, tipo, destino, contenido, puntuacion=10):
    return {"id": pid, "estado": "pendiente", "creada": "2026-11-23T11:00:00-03:00", "origen": "recolector",
            "tipo": tipo, "destino": destino, "resumen": f"resumen de {pid}",
            "evidencia": {"ocurrencias": 3, "proyectos": ["demo"], "dias": 2, "puntuacion": puntuacion, "ejemplos": []},
            "contenido": contenido}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._env = {k: os.environ.get(k) for k in VARS}
        for k in VARS:
            os.environ.pop(k, None)
        os.environ["CLAUDE_HOME"] = str(self.tmp / "claude")
        os.environ["MECANISMO_HOME"] = str(self.tmp / "mecanismo")
        self.proy = self.tmp / "demo"
        (self.proy / ".claude" / "trampas").mkdir(parents=True)
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.proy)
        self.trampa = {"id": "upsert-excluded", "nivel": "bloqueo", "globs": ["**/*.sql"], "patron": r"EXCLUDED\.",
                       "mensaje": "usa parámetros", "origen": "test",
                       "prueba": {"dispara": "SET n = EXCLUDED.n", "no_dispara": "SET n = $2"}}
        self.metodologia = RAIZ.parent / "METODOLOGIA.md"
        g = almacen.dir_global()
        almacen.guardar(propuesta("regla-paralelo-aaaa1111", "regla-metodologia", "metodologia",
                                  {"archivo": str(self.metodologia), "texto": "Orquesta agentes en paralelo."}, 3672), g)
        almacen.guardar(propuesta("permiso-push-bbbb2222", "permiso-allow", "permisos",
                                  {"lista": "allow", "accion": "agregar", "regla": "Bash(git push origin feat*)",
                                   "comando_jq": "jq '.permissions.allow += [\"Bash(git push origin feat*)\"]' settings.json"}), g)
        almacen.guardar(propuesta("trampa-excluded-cccc3333", "trampa-nueva", "trampa",
                                  {"trampa": self.trampa, "proyecto": str(self.proy)}, 5), almacen.dir_proyecto(self.proy))
        (self.proy / ".claude" / "trampas" / "blade.yml").write_text(
            "- id: blade-sin-escapar\n  nivel: aviso\n  patron: x\n- id: otra\n  nivel: aviso\n  patron: y\n")
        almacen.guardar(propuesta("bloqueo-blade-dddd4444", "subir-a-bloqueo", "trampa",
                                  {"archivo": str(self.proy / ".claude/trampas/blade.yml"), "id": "blade-sin-escapar",
                                   "disparos": 6, "dias": 3}), almacen.dir_proyecto(self.proy))

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def correr(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        self.err = err.getvalue()
        return code, out.getvalue()


class TestListar(Base):
    def test_lista_pendientes_por_puntuacion(self):
        code, out = self.correr()
        self.assertEqual(code, 0)
        ids = [l.split()[0] for l in out.splitlines()]
        self.assertEqual(ids[0], "regla-paralelo-aaaa1111")
        self.assertIn("trampa-excluded-cccc3333", ids)  # la del proyecto actual también
        self.assertEqual(self.correr("propuestas", "--json")[0], 0)

    def test_ver_por_prefijo(self):
        code, out = self.correr("ver", "permiso-push")
        self.assertEqual(code, 0)
        self.assertIn("comando_jq", out)
        self.assertEqual(self.correr("ver", "no-existe")[0], 1)

    def test_uso(self):
        self.assertEqual(self.correr("borrar", "x")[0], 2)
        self.assertEqual(self.correr("--raro")[0], 2)


class TestDecidir(Base):
    """Sin bypass por entorno (CONTRATO §11): se parchea exige_tty y se simula lo que teclea la persona."""

    def setUp(self):
        super().setUp()
        self.tecleado = None  # None = teclea el id pedido
        for p in (mock.patch("lib.comun.exige_tty"),
                  mock.patch("builtins.input", side_effect=self._teclear)):
            p.start()
            self.addCleanup(p.stop)

    def _teclear(self, pregunta):
        if isinstance(self.tecleado, BaseException):
            raise self.tecleado
        if self.tecleado is not None:
            return self.tecleado
        return pregunta.rsplit("(", 1)[1].rstrip("): ")

    def test_sin_tty_sale_3_y_no_cambia_nada(self):
        env = dict(os.environ, PYTHONPATH=str(RAIZ))
        for accion in ("aprobar", "rechazar"):
            r = subprocess.run([sys.executable, "-c", "import sys; from lib.propuestas.cli import main; sys.exit(main(sys.argv[1:]))",
                                accion, "regla-paralelo-aaaa1111"], cwd=RAIZ, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(almacen.buscar("regla-paralelo")[1]["estado"], "pendiente")

    def test_aprobar_trampa_la_escribe_en_aviso(self):
        code, out = self.correr("aprobar", "trampa-excluded-cccc3333")
        self.assertEqual(code, 0, self.err)
        t = yaml.safe_load((self.proy / ".claude" / "trampas" / "upsert-excluded.yml").read_text())
        self.assertEqual(t["nivel"], "aviso")
        self.assertEqual(t["patron"], r"EXCLUDED\.")
        self.assertEqual(almacen.buscar("trampa-excluded")[1]["estado"], "aprobada")
        self.assertEqual(self.correr("aprobar", "trampa-excluded-cccc3333")[0], 1)  # ya decidida

    def test_aprobar_exige_teclear_el_id(self):
        destino = self.proy / ".claude" / "trampas" / "upsert-excluded.yml"
        for tecleado in ("trampa-excluded", "otra cosa", "", EOFError()):
            self.tecleado = tecleado
            code, out = self.correr("aprobar", "trampa-excluded-cccc3333")
            self.assertEqual(code, 1, tecleado)
            self.assertIn("no coincide", self.err)
            self.assertFalse(destino.exists())
            self.assertEqual(almacen.buscar("trampa-excluded")[1]["estado"], "pendiente")
        self.tecleado = "  trampa-excluded-cccc3333\n"
        self.assertEqual(self.correr("aprobar", "trampa-excluded")[0], 0)  # por prefijo; se teclea el id completo
        self.assertTrue(destino.exists())

    def test_rechazar_no_pide_id(self):
        self.tecleado = "no coincide"
        self.assertEqual(self.correr("rechazar", "trampa-excluded-cccc3333")[0], 0)

    def test_aprobar_subir_puerta_solo_imprime_diff(self):
        conf = self.proy / ".claude" / "mecanismo.yml"
        conf.write_text("version: 1\ntipo: lib\npuerta: aviso   # nace aviso\nlib: {tests: x}\n")
        antes = conf.read_text()
        almacen.guardar(propuesta("puerta-bloqueo-demo-eeee5555", "subir-puerta", "proyecto",
                                  {"archivo": str(conf), "diff": "viejo"}), almacen.dir_global())
        code, out = self.correr("aprobar", "puerta-bloqueo-demo")
        self.assertEqual(code, 0, self.err)
        self.assertIn("-puerta: aviso   # nace aviso", out)
        self.assertIn("+puerta: bloqueo   # nace aviso", out)
        self.assertIn("Aplícalo tú", out)
        self.assertEqual(conf.read_text(), antes)
        self.assertEqual(almacen.buscar("puerta-bloqueo-demo")[1]["estado"], "aprobada")

    def test_subir_puerta_ya_en_bloqueo_no_se_aprueba(self):
        conf = self.proy / ".claude" / "mecanismo.yml"
        conf.write_text("version: 1\npuerta: bloqueo\n")
        almacen.guardar(propuesta("puerta-bloqueo-demo-eeee5555", "subir-puerta", "proyecto",
                                  {"archivo": str(conf), "diff": "viejo"}), almacen.dir_global())
        self.assertEqual(self.correr("aprobar", "puerta-bloqueo-demo")[0], 1)
        self.assertEqual(almacen.buscar("puerta-bloqueo-demo")[1]["estado"], "pendiente")

    def test_aprobar_trampa_no_pisa(self):
        (self.proy / ".claude" / "trampas" / "upsert-excluded.yml").write_text("id: upsert-excluded\n")
        self.assertEqual(self.correr("aprobar", "trampa-excluded-cccc3333")[0], 1)
        self.assertEqual(almacen.buscar("trampa-excluded")[1]["estado"], "pendiente")

    def test_aprobar_metodologia_solo_imprime_diff(self):
        antes = comun.sha256_archivo(self.metodologia)
        code, out = self.correr("aprobar", "regla-paralelo-aaaa1111")
        self.assertEqual(code, 0)
        self.assertIn("+Orquesta agentes en paralelo.", out)
        self.assertIn("--- a/METODOLOGIA.md", out)
        self.assertEqual(comun.sha256_archivo(self.metodologia), antes)
        self.assertEqual(almacen.buscar("regla-paralelo")[1]["estado"], "aprobada")

    def test_aprobar_permiso_imprime_jq(self):
        code, out = self.correr("aprobar", "permiso-push-bbbb2222")
        self.assertEqual(code, 0)
        self.assertIn("jq '.permissions.allow", out)
        self.assertIn("settings.json no se toca", out)

    def test_subir_a_bloqueo_imprime_diff_sin_tocar(self):
        f = self.proy / ".claude" / "trampas" / "blade.yml"
        antes = f.read_text()
        code, out = self.correr("aprobar", "bloqueo-blade-dddd4444")
        self.assertEqual(code, 0)
        self.assertIn("+  nivel: bloqueo", out)
        self.assertEqual(out.count("+  nivel: bloqueo"), 1)  # solo la de esa trampa
        self.assertEqual(f.read_text(), antes)

    def test_rechazar(self):
        self.assertEqual(self.correr("rechazar", "permiso-push-bbbb2222")[0], 0)
        self.assertEqual(almacen.buscar("permiso-push")[1]["estado"], "rechazada")
        code, out = self.correr()
        self.assertNotIn("permiso-push", out)


class TestAlmacen(Base):
    def test_id_estable_y_slug(self):
        self.assertEqual(almacen.id_de("Orquesta varios agentes en paralelo"),
                         almacen.id_de("Orquesta varios agentes en paralelo"))
        self.assertRegex(almacen.id_de("¿Ñandú — en paralelo?"), r"^[a-z0-9-]+-[0-9a-f]{8}$")

    def test_fusionar_conserva_estado_y_creada(self):
        g = almacen.dir_global()
        p = dict(almacen.buscar("regla-paralelo")[1], estado="rechazada")
        almacen.guardar(p, g)
        nueva = propuesta("regla-paralelo-aaaa1111", "regla-metodologia", "metodologia", {}, 9999)
        nueva["creada"] = "otra"
        _, accion = almacen.fusionar(nueva, g)
        q = almacen.buscar("regla-paralelo")[1]
        self.assertEqual((accion, q["estado"], q["creada"]), ("actualizada", "rechazada", "2026-11-23T11:00:00-03:00"))
        self.assertEqual(q["evidencia"]["puntuacion"], 9999)

    def test_cumple_esquema(self):
        import json
        esquema = json.loads((RAIZ / "esquemas" / "propuesta.schema.json").read_text())
        for f, p in almacen.listar():
            self.assertLessEqual(set(p), set(esquema["properties"]), f)
            self.assertEqual([k for k in esquema["required"] if k not in p], [], f)


if __name__ == "__main__":
    unittest.main()
