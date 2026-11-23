"""Frente B: recolector de punta a punta con el `claude` falso (offline, sin cuota)."""
import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from lib import comun
from lib.recolector import cli, modelo, proponer
from tests.fixtures.recolector.armar import FAKE, armar

RAIZ = pathlib.Path(__file__).resolve().parent.parent
VARS = ("CLAUDE_HOME", "MECANISMO_HOME", "MECANISMO_BITACORA", "MECANISMO_CLAUDE", "MECANISMO_GH",
        "CLAUDE_PROJECT_DIR", "FAKE_CLAUDE_LOG", "MECANISMO_PRESUPUESTO_USD", "MECANISMO_LOTE", "ANTHROPIC_API_KEY")


def motor_falso():
    """lib.trampas.motor simulado (lo escribe el frente A): dispara debe casar, no_dispara no."""
    def probar_trampa(t):
        rx = re.compile(t["patron"])
        errores = []
        if not any(rx.search(l) for l in t["prueba"]["dispara"].splitlines()):
            errores.append("dispara no dispara")
        if any(rx.search(l) for l in t["prueba"]["no_dispara"].splitlines()):
            errores.append("no_dispara dispara")
        return errores
    m = types.ModuleType("lib.trampas.motor")
    m.probar_trampa = probar_trampa
    return {"lib.trampas": types.ModuleType("lib.trampas"), "lib.trampas.motor": m}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._env = {k: os.environ.get(k) for k in VARS}
        for k in VARS:
            os.environ.pop(k, None)
        self.env = armar(self.tmp)
        os.environ.update(self.env)
        os.environ["FAKE_CLAUDE_LOG"] = str(self.tmp / "fake.log")
        self.proy = self.tmp / "proyectos"

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

    def recolectar_json(self, *extra):
        code, out = self.correr("--fuente", "todas", "--dias", "60", "--json", *extra)
        return code, json.loads(out)

    def llamadas(self):
        p = self.tmp / "fake.log"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def sin_canario(self):
        rutas = [str(self.tmp / "mecanismo")] + [str(p) for p in self.proy.glob("*/.claude/trampas/propuestas")]
        r = subprocess.run(["grep", "-r", "CANARIO", *rutas], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout)


class TestAceptacion(Base):
    def test_paralelo_entre_las_tres_primeras_ya_documentada(self):
        with mock.patch.dict(sys.modules, motor_falso()):
            code, r = self.recolectar_json()
        self.assertEqual(code, 0, r["errores"])
        top = r["propuestas"][:3]
        par = [p for p in top if "paralelo" in p["resumen"].lower()]
        self.assertEqual(len(par), 1, [p["resumen"] for p in top])
        p = par[0]
        self.assertEqual((p["destino"], p["tipo"]), ("metodologia", "regla-metodologia"))
        self.assertEqual(p["nota"], "ya documentada en 9e12dd7; vigilar si se repite")
        ev = p["evidencia"]
        self.assertEqual((ev["ocurrencias"], len(ev["proyectos"]), ev["dias"]), (24, 9, 17))
        self.assertEqual(ev["puntuacion"], 24 * 9 * 17)
        self.assertLessEqual(len(ev["ejemplos"]), 3)
        self.assertTrue(pathlib.Path(p["ruta"]).is_relative_to(self.tmp / "mecanismo" / "propuestas"))
        self.sin_canario()

    def test_propuestas_cumplen_esquema(self):
        esquema = json.loads((RAIZ / "esquemas" / "propuesta.schema.json").read_text())
        trampa = json.loads((RAIZ / "esquemas" / "trampa.schema.json").read_text())
        _, r = self.recolectar_json()
        self.assertTrue(r["propuestas"])
        for p in r["propuestas"]:
            doc = comun.leer_yaml(p["ruta"])
            self.assertLessEqual(set(doc), set(esquema["properties"]), p["id"])
            self.assertEqual([k for k in esquema["required"] if k not in doc], [], p["id"])
            for k in ("estado", "origen", "tipo", "destino"):
                self.assertIn(doc[k], esquema["properties"][k]["enum"], (p["id"], k))
            self.assertLessEqual(set(doc["evidencia"]), set(esquema["properties"]["evidencia"]["properties"]))
            self.assertLessEqual(len(doc["evidencia"].get("ejemplos", [])), 3)
            self.assertRegex(doc["id"], r"^[a-z0-9-]+-[0-9a-f]{8}$")
            if "trampa" in doc["contenido"]:
                t = doc["contenido"]["trampa"]
                self.assertEqual(t["nivel"], "aviso")
                self.assertLessEqual(set(t), set(trampa["properties"]))
                self.assertEqual([k for k in trampa["required"] if k not in t], [])

    def test_tres_corridas_mismo_resultado_sin_duplicar(self):
        ids = []
        for _ in range(3):
            code, r = self.recolectar_json()
            self.assertEqual(code, 0, r["errores"])
            ids.append([p["id"] for p in r["propuestas"][:3]])
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ids[1], ids[2])
        self.assertTrue(all(p["accion"] == "actualizada" for p in r["propuestas"]))
        n_glob = len(list((self.tmp / "mecanismo" / "propuestas").glob("*.yml")))
        self.assertEqual(n_glob, sum(1 for p in r["propuestas"] if "/mecanismo/propuestas/" in p["ruta"]))
        # 2.ª y 3.ª corrida: todo desde caché, 0 llamadas nuevas
        self.assertEqual(len(self.llamadas()), 3)

    def test_decidida_no_se_reabre(self):
        _, r = self.recolectar_json()
        p = next(p for p in r["propuestas"] if "paralelo" in p["resumen"].lower())
        f = pathlib.Path(p["ruta"])
        f.write_text(f.read_text().replace("estado: pendiente", "estado: rechazada"))
        _, r = self.recolectar_json()
        q = next(x for x in r["propuestas"] if x["id"] == p["id"])
        self.assertEqual(q["estado"], "rechazada")


class TestRedaccion(Base):
    def test_fake_falla_con_canario(self):
        datos = json.dumps({"tarea": "clasificar", "prompts": [{"i": 0, "proyecto": "x", "texto": "ghp_CANARIO123456789"}]})
        args = [str(FAKE), "-p", "--output-format", "json", "--json-schema", "{}", "--model", "haiku", "--max-budget-usd", "0.1"]
        r = subprocess.run(args, input=datos, capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stderr)
        r = subprocess.run(args + ["--system-prompt", "CANARIO"], input="{}", capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)

    def test_llamar_no_envia_sin_redactar(self):
        with self.assertRaises(modelo.ErrorModelo):
            modelo.llamar("clasificar", {"tarea": "clasificar", "prompts": [{"i": 0, "texto": "sk-ant-CANARIOxxxxxxxx"}]},
                          modelo.Presupuesto())
        self.assertEqual(self.llamadas(), [])

    def test_decorador_no_es_correo(self):
        # en el JSON serializado "\n@app.route" parecería un correo: el control va campo a campo
        out = modelo.llamar("clasificar", {"tarea": "clasificar", "prompts": [{"i": 0, "proyecto": "x",
                                                                            "texto": "mira\n@app.route('/x')"}]},
                            modelo.Presupuesto())
        self.assertEqual(len(out["items"]), 1)

    def test_canario_en_todo_lo_escrito(self):
        self.recolectar_json()
        self.sin_canario()
        for c in (self.tmp / "mecanismo" / "cache").glob("*.json"):
            self.assertNotIn("CANARIO", c.read_text())


class TestPresupuesto(Base):
    def test_flags_y_topes(self):
        os.environ["MECANISMO_LOTE"] = "10"
        code, r = self.recolectar_json()
        self.assertEqual(code, 0, r["errores"])
        ll = self.llamadas()
        clasif = [l for l in ll if l["tarea"] == "clasificar"]
        self.assertEqual(len(clasif), 4)  # 38 prompts distintos en lotes de 10
        self.assertTrue(all(l["modelo"] == "haiku" for l in clasif))
        self.assertTrue(all(l["modelo"] == "sonnet" for l in ll if l["tarea"] != "clasificar"))
        self.assertTrue(all(l["tools"] == "" for l in ll))
        self.assertTrue(all(0 < l["tope"] <= modelo.POR_LLAMADA[l["tarea"]] for l in ll))
        self.assertLessEqual(sum(l["tope"] for l in ll), 2.0)
        self.assertFalse(any(l["bare"] for l in ll))

    def test_bare_solo_con_api_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "x"
        self.recolectar_json()
        self.assertTrue(all(l["bare"] for l in self.llamadas()))

    def test_tope_por_corrida(self):
        self.assertEqual(modelo.Presupuesto(50).total, 2.0)
        p = modelo.Presupuesto(1.0)
        p.gastado = 0.9
        self.assertEqual(p.tope("fusionar"), 0.1)
        p.gastado = 0.97
        with self.assertRaises(modelo.SinPresupuesto):
            p.tope("clasificar")

    def test_sin_presupuesto_no_llama_y_sale_1(self):
        os.environ["MECANISMO_PRESUPUESTO_USD"] = "0.04"
        code, r = self.recolectar_json()
        self.assertEqual(code, 1)
        self.assertEqual(self.llamadas(), [])
        self.assertTrue(any("presupuesto" in e for e in r["errores"]))
        # lo que no depende del modelo (bitácora) sí sale
        self.assertIn("subir-a-bloqueo", {p["tipo"] for p in r["propuestas"]})


class TestTrampas(Base):
    def test_descarta_la_que_no_dispara(self):
        with mock.patch.dict(sys.modules, motor_falso()):
            code, r = self.recolectar_json()
        tipos = {(p["tipo"], p["contenido"].get("trampa", {}).get("id")) for p in r["propuestas"]}
        self.assertIn(("trampa-nueva", "excluded-en-upsert"), tipos)
        self.assertIn(("subir-a-hook", "upsert-excluded"), tipos)
        self.assertNotIn(("trampa-nueva", "tx-con-llamada-externa"), tipos)
        self.assertTrue(any("tx-con-llamada-externa" in d for d in r["descartadas"]))
        hook = next(p for p in r["propuestas"] if p["tipo"] == "subir-a-hook")
        self.assertTrue(hook["nota"].startswith("ya documentada en «Upsert"))
        self.assertEqual(hook["contenido"]["trampa"]["nivel"], "aviso")
        self.assertEqual(pathlib.Path(hook["ruta"]).parent, self.proy / "sepa-mcp" / ".claude" / "trampas" / "propuestas")

    def test_sin_motor_queda_sin_validar(self):
        with mock.patch.object(proponer, "_probar", return_value=None):
            _, r = self.recolectar_json()
        tx = next(p for p in r["propuestas"] if p["contenido"].get("trampa", {}).get("id") == "tx-con-llamada-externa")
        self.assertIn("sin validar", tx["nota"])


class TestBitacora(Base):
    def test_subir_a_bloqueo_y_podar(self):
        code, out = self.correr("--fuente", "bitacora", "--dias", "60", "--json")
        r = json.loads(out)
        self.assertEqual(code, 0)
        por_tipo = {p["tipo"]: p for p in r["propuestas"]}
        self.assertEqual(set(por_tipo), {"subir-a-bloqueo", "podar"})
        b = por_tipo["subir-a-bloqueo"]
        self.assertEqual(b["contenido"]["id"], "blade-sin-escapar")
        self.assertEqual((b["contenido"]["disparos"], b["contenido"]["dias"]), (6, 3))
        self.assertEqual(por_tipo["podar"]["contenido"]["id"], "vieja-sin-uso")
        self.assertEqual(self.llamadas(), [])  # la bitácora no gasta modelo

    def test_trampa_nueva_no_se_poda(self):
        os.utime(self.proy / "demo-web" / ".claude" / "trampas" / "blade.yml")
        _, out = self.correr("--fuente", "bitacora", "--dias", "60", "--json")
        self.assertNotIn("podar", {p["tipo"] for p in json.loads(out)["propuestas"]})


class TestSinModelo(Base):
    def test_agrupa_por_texto_identico(self):
        code, r = self.recolectar_json("--sin-modelo")
        self.assertEqual(code, 0)
        self.assertEqual(self.llamadas(), [])
        res = {p["resumen"]: p for p in r["propuestas"]}
        self.assertIn("responde en español por favor", res)
        self.assertEqual(res["responde en español por favor"]["destino"], "metodologia")
        self.assertEqual(res["otra vez EXCLUDED en el upsert, usa parámetros"]["destino"], "proyecto")
        self.assertNotIn("haz el commit más corto", res)  # 2 < umbral


class TestUso(Base):
    def test_uso_incorrecto(self):
        self.assertEqual(self.correr("--fuente", "nada")[0], 2)
        self.assertEqual(self.correr("--help")[0], 0)

    def test_sin_binario_claude_falla_limpio(self):
        os.environ["MECANISMO_CLAUDE"] = str(self.tmp / "no-existe")
        code, out = self.correr("--fuente", "history", "--dias", "60")
        self.assertEqual(code, 1)
        self.assertIn("no se pudo correr claude", self.err)

    def test_binario_relativo_al_cwd(self):
        os.environ["MECANISMO_CLAUDE"] = os.path.relpath(FAKE)
        code, r = self.recolectar_json()
        self.assertEqual(code, 0, r["errores"])
        self.assertGreater(len(self.llamadas()), 0)

    def test_subproceso_como_lo_llama_el_dispatcher(self):
        r = subprocess.run([sys.executable, "-c", "import sys; from lib.recolector.cli import main; sys.exit(main(sys.argv[1:]))",
                            "--fuente", "history", "--dias", "60", "--top", "3"],
                           cwd=RAIZ, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(RAIZ)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ya documentada en 9e12dd7", r.stdout)


if __name__ == "__main__":
    unittest.main()
