"""Frente B: fuentes del recolector (filtros, deduplicado, trampas en los tres formatos reales)."""
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from lib.recolector import fuentes
from tests.fixtures.recolector.armar import FX, armar

PROY = FX / "proyectos"


class TestMarkdown(unittest.TestCase):
    def test_subencabezados_10_n(self):
        items = fuentes.trampas_en_markdown(PROY / "sempat" / "SEMPAT.md")
        self.assertEqual([i["titulo"] for i in items],
                         ["Los perfiles viven en tablas separadas", "La caché local no es compartida"])
        self.assertIn("no ve", items[0]["cuerpo"])  # las viñetas bajo ### son cuerpo, no ítems

    def test_vinetas_en_negrita_bajo_trampas(self):
        items = fuentes.trampas_en_markdown(PROY / "mcp-sempat" / "CLAUDE.md")
        self.assertEqual([i["titulo"] for i in items],
                         ["Golden: empates.", "Fechas en UTC.", "Nunca `fmt.Errorf` con `%v` sobre err"])
        self.assertNotIn("CANARIO", json.dumps(items))
        self.assertIn("[REDACTADO:dsn]", items[1]["cuerpo"])

    def test_lista_numerada(self):
        items = fuentes.trampas_en_markdown(PROY / "sepa-mcp" / "docs" / "contexto" / "04-arquitectura.md")
        self.assertEqual(len(items), 4)
        self.assertTrue(items[2]["titulo"].startswith("Upsert con `SET col = EXCLUDED.col`"))
        self.assertTrue(items[3]["titulo"].startswith("Transacción abierta"))

    def test_busca_en_docs_y_raiz(self):
        nombres = {pathlib.Path(i["archivo"]).name for i in fuentes.trampas_documentadas([PROY / "sepa-mcp", PROY / "sempat"])}
        self.assertEqual(nombres, {"04-arquitectura.md", "SEMPAT.md"})


class TestFiltros(unittest.TestCase):
    def test_descartables(self):
        for t in ("/agents", "exit", "  ", "!ls", "<task-notification>x", "<agent-message>x",
                  "<system-reminder>x", "<command-name>/clear</command-name>", "<local-command-stdout>x"):
            self.assertTrue(fuentes.descartable(t), t)
        self.assertFalse(fuentes.descartable("lanza agentes en paralelo"))
        self.assertTrue(fuentes.es_acuse("Sí."))
        self.assertFalse(fuentes.es_acuse("paraleliza esto"))


class TestFuentesConEntorno(unittest.TestCase):
    VARS = ("CLAUDE_HOME", "MECANISMO_HOME", "MECANISMO_BITACORA", "MECANISMO_CLAUDE", "MECANISMO_GH", "CLAUDE_PROJECT_DIR")

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._env = {k: os.environ.get(k) for k in self.VARS}
        os.environ.update(armar(self.tmp))

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_history_filtra_y_redacta(self):
        ms = fuentes.de_history(60)
        textos = [m.texto for m in ms]
        self.assertFalse(any(t.startswith(("/", "!")) or t == "exit" for t in textos))
        self.assertFalse(any("CANARIO" in t for t in textos))
        self.assertNotIn("lanza agentes en paralelo (muy viejo)", textos)
        self.assertTrue(any("[REDACTADO:pem]" in t for t in textos))
        self.assertEqual({m.fuente for m in ms}, {"history"})

    def test_transcripts_solo_humanos(self):
        ms = fuentes.de_transcripts(60)
        self.assertEqual(sorted(m.texto for m in ms),
                         ["muestra la salida de las pruebas; el secreto es [REDACTADO:github]",
                          "responde en español por favor"])
        self.assertEqual({m.proyecto for m in ms}, {"sempat", "demo-web"})

    def test_redacta_antes_de_cortar(self):
        """Un corte en MAX_TEXTO justo antes de la `@` de una DSN o dentro de un PEM no deja ver nada."""
        dsn = "postgres://app:CANARIOclave"
        largo = "x " * 900
        largo += "y" * (fuentes.MAX_TEXTO - len(largo) - len(dsn) - 1) + " " + dsn + "@db.interno:5432/prod"
        self.assertEqual(largo.index("@"), fuentes.MAX_TEXTO)  # el corte cae justo antes de la @
        pem = "clave: -----BEGIN RSA PRIVATE KEY-----\n" + "CANARIOabc+/\n" * 300 + "-----END RSA PRIVATE KEY-----"
        h = pathlib.Path(os.environ["CLAUDE_HOME"]) / "history.jsonl"
        with open(h, "a", encoding="utf-8") as f:
            for i, t in enumerate((largo, pem)):
                f.write(json.dumps({"display": t, "timestamp": int(__import__("time").time() * 1000),
                                    "project": "/x/demo", "sessionId": f"corte-{i}"}) + "\n")
        sesion = pathlib.Path(os.environ["CLAUDE_HOME"]) / "projects" / "-x-demo"
        sesion.mkdir(parents=True)
        (sesion / "s.jsonl").write_text(json.dumps({"type": "user", "origin": {"kind": "human"}, "cwd": "/x/demo",
                                                    "message": {"role": "user", "content": largo}}) + "\n")
        textos = [m.texto for m in fuentes.de_history(60) + fuentes.de_transcripts(60)]
        self.assertFalse([t for t in textos if "CANARIO" in t])
        self.assertEqual(sum(t.startswith("x x") and t.endswith("y [REDACTADO:dsn]") for t in textos), 2)
        self.assertTrue(any(t == "clave: [REDACTADO:pem]" for t in textos))
        self.assertTrue(all(len(t) <= fuentes.MAX_TEXTO for t in textos))
        d = pathlib.Path(self.tmp / "md")
        d.mkdir()
        (d / "CLAUDE.md").write_text("## Trampas\n\n- **La base.** " + "z" * 560 + " " + dsn + "@h/db\n")
        self.assertNotIn("CANARIO", json.dumps(fuentes.trampas_en_markdown(d / "CLAUDE.md")))

    def test_sin_duplicados_entre_history_y_transcript(self):
        ms = fuentes.sin_duplicados(fuentes.de_history(60) + fuentes.de_transcripts(60))
        esp = [m for m in ms if m.texto == "responde en español por favor"]
        self.assertEqual(len(esp), 5)

    def test_bitacora(self):
        ls = fuentes.de_bitacora(60)
        self.assertEqual(len(ls), 18)
        self.assertEqual(ls[0].categoria, "AVISO")
        self.assertEqual(ls[0].detalle, ["blade-sin-escapar", "a.blade.php"])

    def test_gh_sin_binario_o_sin_remoto_se_salta(self):
        self.assertEqual(fuentes.de_gh([str(self.tmp / "proyectos" / "sempat")], 60), [])
        os.environ["MECANISMO_GH"] = "true"  # existe, pero el proyecto no tiene remoto
        self.assertEqual(fuentes.de_gh([str(self.tmp / "proyectos" / "sempat")], 60), [])

    def test_gh_lee_comentarios(self):
        os.environ["MECANISMO_GH"] = "true"
        resp = json.dumps([{"body": "usa EXCLUDED no, token ghp_CANARIO1234567890", "created_at": "2099-01-01T00:00:00Z"},
                           {"body": "viejo", "created_at": "2000-01-01T00:00:00Z"}])
        with mock.patch.object(fuentes, "repo_github", return_value="o/r"), \
                mock.patch.object(fuentes, "_ejecutar", return_value=resp):
            ms = fuentes.de_gh([str(self.tmp / "proyectos" / "sempat")], 60)
        self.assertEqual([m.texto for m in ms], ["usa EXCLUDED no, token [REDACTADO:github]"])
        self.assertEqual(ms[0].fuente, "gh")

    def test_repo_github(self):
        for url in ("git@github.com:o/r.git", "https://github.com/o/r.git", "https://github.com/o/r"):
            with mock.patch.object(fuentes, "_ejecutar", return_value=url + "\n"):
                self.assertEqual(fuentes.repo_github("/x"), "o/r")
        with mock.patch.object(fuentes, "_ejecutar", return_value="https://gitlab.com/o/r\n"):
            self.assertIsNone(fuentes.repo_github("/x"))


if __name__ == "__main__":
    unittest.main()
