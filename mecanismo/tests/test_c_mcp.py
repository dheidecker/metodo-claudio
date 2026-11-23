"""Frente C: `mecanismo verificar` con la vía mcp (stdio y HTTP) contra el servidor de fixture."""
import json
import socket
import sys
import unittest

from lib import comun
from lib.evidencia.adaptadores import mcp
from tests.c_entorno import FIXTURES, SERVIDOR_MCP, EntornoC

OK = FIXTURES / "mcp" / "mcp-ok"
ROTO = FIXTURES / "mcp" / "mcp-roto"
SUBS = {"@SERVIDOR@": str(SERVIDOR_MCP)}
CONF = ".claude/mecanismo.yml"


class TestVerificarStdio(EntornoC):
    def test_mcp_ok_da_exit_0_y_evidencia_ok(self):
        p = self.proyecto(OK, subs=SUBS)
        self.confiar(p)
        r = self.verificar(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ev = self.ultima_evidencia(p)
        self.comprobar_esquema(ev)
        self.assertTrue(ev["ok"])
        self.assertEqual([f["id"] for f in ev["funciones"]], ["saludar", "sumar"])
        self.assertTrue(all(f["ok"] for f in ev["funciones"]))
        self.assertEqual(ev["head"], self.git(p, "rev-parse", "HEAD").strip())
        self.assertEqual(ev["tipo"], "mcp")
        self.assertEqual(ev["funciones"][1]["comando"], "mecanismo verificar --funciones sumar")
        self.assertIn("| verificar ", self.bitacora())
        self.assertIn("ok saludar,sumar", self.bitacora())

    def test_mcp_roto_da_exit_1_y_el_diff_nombra_el_caso(self):
        p = self.proyecto(ROTO, subs=SUBS)
        self.confiar(p)
        r = self.verificar(p)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("sumar_dos_tres", r.stdout)
        ev = self.ultima_evidencia(p)
        self.comprobar_esquema(ev)
        self.assertFalse(ev["ok"])
        sumar = next(f for f in ev["funciones"] if f["id"] == "sumar")
        saludar = next(f for f in ev["funciones"] if f["id"] == "saludar")
        self.assertTrue(saludar["ok"])
        self.assertFalse(sumar["ok"])
        self.assertIn("1 de 3 casos difiere: sumar_dos_tres", sumar["resumen"])
        diff = "\n".join(sumar["diffs"])
        self.assertIn("--- golden/sumar/sumar_dos_tres.json", diff)
        self.assertIn("-content/0/text/resultado = 5", diff)
        self.assertIn("+content/0/text/resultado = 6", diff)
        self.assertNotIn("query_id", diff)       # volátil: se ignora a cualquier profundidad
        self.assertNotIn("request_id", diff)
        self.assertIn("AVISO sumar", self.bitacora())

    def test_huellas_y_seleccion_por_archivos_cambiados(self):
        p = self.proyecto(OK, subs=SUBS)
        self.confiar(p)
        self.tocar(p / "src" / "sumar.py")
        self.tocar(p / "LEEME.txt", "fuera del mapa\n")
        r = self.verificar(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ev = self.ultima_evidencia(p)
        self.assertEqual([f["id"] for f in ev["funciones"]], ["sumar"])  # solo la que cubre lo cambiado
        self.assertEqual(ev["huellas"], {"src/sumar.py": comun.sha256_archivo(p / "src" / "sumar.py")})
        # la evidencia no ensucia el árbol: no cuenta como archivo cambiado
        self.assertNotIn(".claude/evidencia", self.git(p, "status", "--porcelain"))

    def test_funciones_explicitas_y_desconocidas(self):
        p = self.proyecto(OK, subs=SUBS)
        self.confiar(p)
        r = self.verificar(p, "--funciones", "saludar")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([f["id"] for f in self.ultima_evidencia(p)["funciones"]], ["saludar"])
        r = self.verificar(p, "--funciones", "saludar,nada")
        self.assertEqual(r.returncode, 2)
        self.assertIn("nada", r.stderr)

    def test_divergencia_no_declarada_falla(self):
        p = self.proyecto(OK, subs=SUBS)
        self.confiar(p)
        casos = p / ".claude/verificacion/casos/sumar.yaml"
        casos.write_text(casos.read_text().replace(
            '"divergencias": [{"clave": "content/0/text/meta/version", "motivo": "la versión 2 del formato es intencional"}]',
            '"divergencias": []'))
        r = self.verificar(p, "--funciones", "sumar")
        self.assertEqual(r.returncode, 1, r.stdout)
        sumar = self.ultima_evidencia(p)["funciones"][0]
        self.assertIn("sumar_version_nueva", sumar["resumen"])
        self.assertIn('+content/0/text/meta/version = "2"', "\n".join(sumar["diffs"]))

    def test_falta_golden(self):
        p = self.proyecto(OK, subs=SUBS)
        self.confiar(p)
        (p / ".claude/verificacion/golden/saludar/saludar_ana.json").unlink()
        r = self.verificar(p, "--funciones", "saludar")
        self.assertEqual(r.returncode, 1)
        self.assertIn("falta golden", "\n".join(self.ultima_evidencia(p)["funciones"][0]["diffs"]))

    def test_sin_mecanismo_yml_es_uso_incorrecto(self):
        r = self.verificar(self.tmp)
        self.assertEqual(r.returncode, 2)


class TestVerificarHTTP(EntornoC):
    def _http(self, origen, modo, token=None):
        p = self.proyecto(origen, subs=SUBS)
        url = self.servidor_mcp_http(modo, token=token)
        self.editar_yml(p, CONF, comando=None, url=url, token_env="FIXTURE_TOKEN_C" if token else None)
        return p

    def test_mcp_ok_por_http_con_token(self):
        p = self._http(OK, "ok", token="secreto-c")
        env = dict(self.env, FIXTURE_TOKEN_C="secreto-c")
        r = self.verificar(p, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.ultima_evidencia(p)["ok"])

    def test_mcp_roto_por_http_con_sse(self):
        p = self._http(ROTO, "roto")
        r = self.verificar(p)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        sumar = next(f for f in self.ultima_evidencia(p)["funciones"] if f["id"] == "sumar")
        self.assertIn("sumar_dos_tres", sumar["resumen"])
        self.assertIn("+content/0/text/resultado = 6", "\n".join(sumar["diffs"]))

    def test_sin_token_da_401_y_falla(self):
        p = self._http(OK, "ok", token="secreto-c")
        r = self.verificar(p)  # sin FIXTURE_TOKEN_C en el entorno
        self.assertEqual(r.returncode, 1)
        self.assertIn("HTTP 401", self.ultima_evidencia(p)["funciones"][0]["resumen"])

    def test_arranque_levanta_y_mata_el_servidor(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
        s.close()
        p = self.proyecto(OK, subs=SUBS)
        self.editar_yml(p, CONF, comando=None, url=f"http://127.0.0.1:{puerto}/mcp")
        conf = p / CONF
        conf.write_text(conf.read_text() + f'arranque: "{sys.executable} {SERVIDOR_MCP} --http --puerto {puerto}"\n')
        self.confiar(p)  # arranque es un comando del yml
        r = self.verificar(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with self.assertRaises(OSError):  # al terminar, no queda nadie escuchando
            socket.create_connection(("127.0.0.1", puerto), timeout=1).close()


class TestComparacion(unittest.TestCase):
    def test_ignorar_a_cualquier_profundidad_y_dentro_de_text_json(self):
        v = {"a": {"query_id": 1, "b": [{"firma": "x", "c": 2}]},
             "content": [{"type": "text", "text": json.dumps({"query_id": "q", "d": {"firma": 9, "e": 1}})}]}
        n = mcp.normalizar(v, {"query_id", "firma"})
        self.assertEqual(n, {"a": {"b": [{"c": 2}]}, "content": [{"type": "text", "text": {"d": {"e": 1}}}]})

    def test_tools_list_sin_orden_pero_con_anotaciones_y_esquemas(self):
        t = [{"name": "a", "description": "x", "inputSchema": {"type": "object", "required": ["p", "q"]},
              "annotations": {"readOnlyHint": True}},
             {"name": "b", "inputSchema": {"type": "object"}}]
        g = mcp.normalizar_tools(t, set())
        otro = [dict(t[1]), dict(t[0], description="otra", inputSchema={"type": "object", "required": ["q", "p"]})]
        self.assertIsNone(mcp.comparar(g, mcp.normalizar_tools(otro, set()), None, "g", "a"))
        cambiado = [t[1], dict(t[0], annotations={"readOnlyHint": False})]
        d = mcp.comparar(g, mcp.normalizar_tools(cambiado, set()), None, "g", "a")
        self.assertIn("-a/annotations/readOnlyHint = true", d)
        falta = [t[0]]
        self.assertIn("-b/inputSchema/type", mcp.comparar(g, mcp.normalizar_tools(falta, set()), None, "g", "a"))

    def test_divergencia_por_glob_y_por_prefijo(self):
        g = {"filas": [{"v": 1, "w": 1}], "x": 1}
        a = {"filas": [{"v": 2, "w": 3}], "x": 1}
        self.assertIsNone(mcp.comparar(g, a, [{"clave": "filas/*/v"}, {"clave": "filas/0/w"}], "g", "a"))
        self.assertIsNone(mcp.comparar(g, a, [{"clave": "filas"}], "g", "a"))
        self.assertIsNotNone(mcp.comparar(g, a, [{"clave": "filas/*/v"}], "g", "a"))


if __name__ == "__main__":
    unittest.main()
