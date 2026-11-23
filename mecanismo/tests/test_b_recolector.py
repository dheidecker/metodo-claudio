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
        "CLAUDE_PROJECT_DIR", "FAKE_CLAUDE_LOG", "MECANISMO_PRESUPUESTO_USD", "MECANISMO_LOTE", "ANTHROPIC_API_KEY",
        "FAKE_CLAUDE_VARIANTE")


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

    def agregar_history(self, filas):
        """filas: [(texto, proyecto, sesion)] de hoy, al final de history.jsonl."""
        import time
        with open(self.tmp / "claude" / "history.jsonl", "a", encoding="utf-8") as f:
            for texto, proy, sesion in filas:
                f.write(json.dumps({"display": texto, "pastedContents": {}, "timestamp": int(time.time() * 1000),
                                    "project": str(self.proy / proy), "sessionId": sesion}, ensure_ascii=False) + "\n")

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

    def test_llamar_redacta_siempre_lo_que_envia(self):
        # el fake sale con 3 si ve CANARIO: que responda prueba que llegó redactado
        out = modelo.llamar("clasificar", {"tarea": "clasificar", "prompts": [
            {"i": 0, "proyecto": "x", "texto": "sk-ant-CANARIOxxxxxxxx"},
            {"i": 1, "proyecto": "x", "texto": "la base: postgres://u:CANARIO@db/prod"}]}, modelo.Presupuesto())
        self.assertEqual(len(out["items"]), 2)
        self.assertEqual(len(self.llamadas()), 1)

    def test_pem_largo_y_dsn_en_el_corte(self):
        """Redactar antes de cortar (CONTRATO §11): CANARIO no llega al fake, ni a la caché, ni a `ejemplos`."""
        from lib.recolector import fuentes
        pem = ("lanza agentes en paralelo con esta clave -----BEGIN RSA PRIVATE KEY-----\n"
               + "CANARIOabcdefghij+/\n" * 170 + "-----END RSA PRIVATE KEY-----")
        self.assertGreater(len(pem), 3000)
        dsn = "postgres://app:CANARIOclave"
        cabeza = "lanza agentes en paralelo, la base es"
        corte = cabeza + " " * (fuentes.MAX_TEXTO - len(cabeza) - len(dsn)) + dsn
        self.assertEqual(len(corte), fuentes.MAX_TEXTO)  # el corte cae justo antes de la @
        self.agregar_history([(pem, "sitio", "red-pem"), (corte + "@db.interno:5432/prod", "crm", "red-dsn")])
        code, r = self.recolectar_json()
        self.assertEqual(code, 0, r["errores"])  # el fake sale con 3 si ve CANARIO
        par = next(p for p in r["propuestas"] if "paralelo" in p["resumen"].lower())
        ej = par["evidencia"]["ejemplos"]
        self.assertIn("lanza agentes en paralelo con esta clave [REDACTADO:pem]", ej)
        self.assertIn("lanza agentes en paralelo, la base es [REDACTADO:dsn]", ej)
        self.sin_canario()  # propuestas y caché
        self.assertTrue(list((self.tmp / "mecanismo" / "cache").glob("*.json")))

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


class TestIdsEstables(Base):
    """En tres corridas reales «orquesta varios agentes en paralelo» salió con tres ids distintos:
    el mismo grupo con otra redacción tiene que actualizar la propuesta existente (CONTRATO §11)."""

    def paralelas(self):
        out = {}
        for f in (self.tmp / "mecanismo" / "propuestas").glob("*.yml"):
            p = comun.leer_yaml(f)
            if "paralel" in p["resumen"].lower():
                out[p["id"]] = p
        return out

    def dos_corridas(self, variante):
        code, r = self.recolectar_json()
        self.assertEqual(code, 0, r["errores"])
        antes = self.paralelas()
        self.assertEqual(len(antes), 1)
        shutil.rmtree(self.tmp / "mecanismo" / "cache")  # que el modelo vuelva a redactarlo todo
        os.environ["FAKE_CLAUDE_VARIANTE"] = variante
        code, r = self.recolectar_json()
        self.assertEqual(code, 0, r["errores"])
        fus = [l for l in self.llamadas() if l["tarea"] == "fusionar"]
        self.assertEqual(len(fus), 2)
        despues = self.paralelas()
        self.assertEqual(list(despues), list(antes))  # una sola propuesta, mismo id
        p = next(iter(despues.values()))
        self.assertEqual(p["resumen"], "Paraleliza el trabajo entre agentes")  # se actualizó la existente
        self.assertEqual(next(x for x in r["propuestas"] if x["id"] == p["id"])["accion"], "actualizada")

    def test_fusion_devuelve_el_existente(self):
        self.dos_corridas("1")

    def test_sin_existente_la_reconoce_por_sus_ejemplos(self):
        self.dos_corridas("2")

    def test_un_id_existente_no_lo_toman_dos_grupos(self):
        g = lambda r, txt: types.SimpleNamespace(existente="x-1", resumen=r, muestras=[types.SimpleNamespace(texto=txt)])
        existentes = {"x-1": {"origen": "recolector", "resumen": "algo", "evidencia": {"ejemplos": []}}}
        tomados = set()
        a = proponer._id_estable(g("uno", "a"), existentes, tomados)
        tomados.add(a)
        b = proponer._id_estable(g("dos", "b"), existentes, tomados)
        self.assertEqual(a, "x-1")
        self.assertNotEqual(b, "x-1")


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

    def test_en_el_repo_solo_ejemplos_del_proyecto(self):
        """Una propuesta que se escribe en <proyecto>/.claude/trampas/propuestas/ (versionable) no lleva
        prompts de otro proyecto en `ejemplos`."""
        self.agregar_history([("otra vez EXCLUDED en el upsert de tickets-secreto", "tickets", "exc-t")])
        with mock.patch.dict(sys.modules, motor_falso()):
            code, r = self.recolectar_json()
        self.assertEqual(code, 0, r["errores"])
        hook = next(p for p in r["propuestas"] if p["tipo"] == "subir-a-hook")
        self.assertEqual(pathlib.Path(hook["ruta"]).parent, self.proy / "sepa-mcp" / ".claude" / "trampas" / "propuestas")
        self.assertEqual(hook["evidencia"]["ocurrencias"], 5)  # cuenta todas
        self.assertEqual(hook["evidencia"]["ejemplos"], ["otra vez EXCLUDED en el upsert, usa parámetros"])
        for f in (self.proy / "sepa-mcp" / ".claude" / "trampas" / "propuestas").glob("*.yml"):
            self.assertNotIn("tickets-secreto", f.read_text())

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


class TestSubirPuerta(Base):
    """`subir-puerta` (CONTRATO §11) con una bitácora sintética de stop-evidencia y verificar."""

    def setUp(self):
        super().setUp()
        import datetime as dt
        self.hoy = dt.date.today()
        self.dt = dt
        for n in ("demo-web", "tickets", "crm", "sempat"):
            c = self.proy / n / ".claude"
            c.mkdir(parents=True, exist_ok=True)
            (c / "mecanismo.yml").write_text("version: 1\ntipo: lib\npuerta: aviso\nlib: {tests: x}\n")

    def dia(self, d):
        return (self.hoy - self.dt.timedelta(days=d)).isoformat()

    def escribir(self, lineas):
        txt = "".join("%s | %-22s | %-32s | %s\n" % l for l in lineas)
        with open(self.tmp / "bitacora.log", "a", encoding="utf-8") as f:
            f.write(txt)

    def test_propone_solo_si_todos_los_avisos_se_atendieron(self):
        ls = []
        for d in range(1, 15):  # 14 días
            ls += [(f"{self.dia(d)} 10:00:00", "stop-evidencia", "demo-web", "AVISO consultar,parser"),
                   (f"{self.dia(d)} 10:05:00", "verificar", "demo-web", "ok consultar"),
                   (f"{self.dia(d)} 10:06:00", "verificar", "demo-web", "ok parser"),
                   # tickets: igual, pero un día el verificar no cubre todas las funciones del aviso
                   (f"{self.dia(d)} 11:00:00", "stop-evidencia", "tickets", "AVISO a,b"),
                   (f"{self.dia(d)} 11:05:00", "verificar", "tickets", "ok a" if d == 7 else "ok a,b"),
                   # sempat: un día el verificar llega al día siguiente
                   (f"{self.dia(d)} 23:00:00", "stop-evidencia", "sempat", "AVISO x")]
            if d != 3:
                ls.append((f"{self.dia(d)} 23:30:00", "verificar", "sempat", "ok x"))
            else:
                ls.append((f"{self.dia(d - 1)} 00:10:00", "verificar", "sempat", "ok x"))
        for d in range(1, 14):  # crm: 13 días, todos atendidos: aún no
            ls += [(f"{self.dia(d)} 12:00:00", "stop-evidencia", "crm", "AVISO f"),
                   (f"{self.dia(d)} 12:01:00", "verificar", "crm", "AVISO f"),  # falló: no cuenta…
                   (f"{self.dia(d)} 12:02:00", "verificar", "crm", "ok f")]     # …este sí
        self.escribir(ls)
        conf = self.proy / "demo-web" / ".claude" / "mecanismo.yml"
        antes = conf.read_text()
        code, out = self.correr("--fuente", "bitacora", "--dias", "60", "--json")
        self.assertEqual(code, 0)
        ps = [p for p in json.loads(out)["propuestas"] if p["tipo"] == "subir-puerta"]
        self.assertEqual([p["evidencia"]["proyectos"] for p in ps], [["demo-web"]])
        p = ps[0]
        self.assertEqual((p["destino"], p["origen"]), ("proyecto", "bitacora"))
        self.assertEqual((p["evidencia"]["ocurrencias"], p["evidencia"]["dias"]), (14, 14))
        self.assertEqual(p["contenido"]["archivo"], str(conf))
        self.assertIn("-puerta: aviso\n+puerta: bloqueo", p["contenido"]["diff"])
        self.assertTrue(pathlib.Path(p["ruta"]).is_relative_to(self.tmp / "mecanismo" / "propuestas"))
        self.assertEqual(conf.read_text(), antes)
        esquema = json.loads((RAIZ / "esquemas" / "propuesta.schema.json").read_text())
        doc = comun.leer_yaml(p["ruta"])
        self.assertLessEqual(set(doc), set(esquema["properties"]))
        self.assertEqual(self.llamadas(), [])

    def test_un_aviso_sin_atender_o_puerta_ya_en_bloqueo(self):
        ls = []
        for d in range(1, 16):
            ls += [(f"{self.dia(d)} 10:00:00", "stop-evidencia", "demo-web", "AVISO f"),
                   (f"{self.dia(d)} 10:05:00", "verificar", "demo-web", "ok f")]
        ls.append((f"{self.dia(0)} 09:00:00", "stop-evidencia", "demo-web", "AVISO f"))  # hoy, sin verificar
        self.escribir(ls)
        _, out = self.correr("--fuente", "bitacora", "--dias", "60", "--json")
        self.assertNotIn("subir-puerta", {p["tipo"] for p in json.loads(out)["propuestas"]})
        self.escribir([(f"{self.dia(0)} 09:10:00", "verificar", "demo-web", "ok f")])
        _, out = self.correr("--fuente", "bitacora", "--dias", "60", "--json")
        self.assertIn("subir-puerta", {p["tipo"] for p in json.loads(out)["propuestas"]})
        conf = self.proy / "demo-web" / ".claude" / "mecanismo.yml"
        conf.write_text(conf.read_text().replace("puerta: aviso", "puerta: bloqueo"))
        shutil.rmtree(self.tmp / "mecanismo" / "propuestas")
        _, out = self.correr("--fuente", "bitacora", "--dias", "60", "--json")
        self.assertNotIn("subir-puerta", {p["tipo"] for p in json.loads(out)["propuestas"]})


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
