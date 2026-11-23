"""Migración de blade-trampas.sh a trampas como datos (PLAN §4, «Después de A»).

La plantilla trae las mismas trampas por dos vías: `blade-trampas.sh` (bash, ahora un shim con
fallback) y `mecanismo-trampas.sh` (que aplica .claude/trampas/blade.yml). Aquí se comprueba que,
corriendo los hooks tal como los lista el settings.json de la plantilla, cada trampa avisa
exactamente UNA vez en total, con y sin `mecanismo` en el PATH, en PostToolUse y en Stop.

Nunca toca el ~/.claude real: HOME, CLAUDE_HOME, MECANISMO_HOME y MECANISMO_BITACORA van a un tmp
en /var/tmp.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import uuid

RAIZ = pathlib.Path(__file__).resolve().parent.parent          # mecanismo/
REPO = RAIZ.parent                                              # metodo-claudio/
BIN = RAIZ / "bin" / "mecanismo"
PLANTILLA = REPO / "plantilla-proyecto"
YML_PLANTILLA = PLANTILLA / ".claude" / "trampas" / "blade.yml"
YML_FIXTURE = RAIZ / "tests" / "fixtures" / "blade" / "blade.yml"

# Un .blade.php con dos trampas (x-init con bloque, x-show con d-flex) y nada más.
BLADE = """<div x-data="panel()">
    <div x-init="localStorage.removeItem('filtros'); cargar()"></div>
    <div x-show="abierto" class="d-flex gap-2">contenido</div>
</div>
"""
# Frase del mensaje de cada trampa: igual en el texto bash y en el `mensaje` del yml.
FRASES = {
    "x-init-con-bloque": "x-init evalúa una expresión",
    "x-show-con-d-flex": "la clase !important de Bootstrap gana",
}


def _path_sin_mecanismo() -> str:
    return ":".join(d for d in os.environ.get("PATH", "").split(":")
                    if d and not os.access(os.path.join(d, "mecanismo"), os.X_OK))


class FuenteUnica(unittest.TestCase):
    def test_plantilla_y_fixture_no_divergen(self):
        """blade.yml de la plantilla es la fuente; el fixture de los tests tiene que ser idéntico."""
        self.assertTrue(YML_PLANTILLA.is_file(), YML_PLANTILLA)
        self.assertEqual(YML_PLANTILLA.read_bytes(), YML_FIXTURE.read_bytes(),
                         "plantilla-proyecto/.claude/trampas/blade.yml y tests/fixtures/blade/blade.yml divergen")


@unittest.skipUnless(shutil.which("jq"), "los hooks bash de la plantilla necesitan jq")
class NoDuplicacion(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="blade-plantilla-", dir="/var/tmp"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / "home"
        (home / ".claude").mkdir(parents=True)
        self.bitacora = home / ".claude" / "metodo-claudio.log"
        self.proy = self.tmp / "proyecto"
        shutil.copytree(PLANTILLA, self.proy)
        g = ["git", "-C", str(self.proy), "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(g + ["init", "-q"], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", "plantilla"], check=True)
        self.blade = self.proy / "resources" / "views" / "panel.blade.php"
        self.blade.parent.mkdir(parents=True)
        self.blade.write_text(BLADE)  # sin seguimiento: los dos motores miran el archivo entero
        # `mecanismo` del repo (no el instalado) en un bin propio.
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "mecanismo").symlink_to(BIN)
        self.sid = f"test-blade-{uuid.uuid4().hex}"  # sin /tmp/lint-marca-<sid>: últimos 30 min
        self.env = dict(os.environ)
        for k in ("PYTHONPATH", "CLAUDECODE"):
            self.env.pop(k, None)
        self.env.update(HOME=str(home), CLAUDE_HOME=str(home / ".claude"),
                        MECANISMO_HOME=str(self.tmp / "mecanismo"),
                        MECANISMO_BITACORA=str(self.bitacora),
                        CLAUDE_PROJECT_DIR=str(self.proy))
        self.settings = json.loads((self.proy / ".claude" / "settings.json").read_text())

    def _comandos(self, evento, herramienta=None):
        """Los comandos del settings.json de la plantilla para ese evento, en orden."""
        out = []
        for grupo in self.settings["hooks"][evento]:
            m = grupo.get("matcher")
            if herramienta and m and herramienta not in m.split("|"):
                continue
            out += [h["command"].replace("${CLAUDE_PROJECT_DIR}", str(self.proy)) for h in grupo["hooks"]]
        return out

    def _correr(self, evento, entrada, con_mecanismo):
        env = dict(self.env)
        sin = _path_sin_mecanismo()
        env["PATH"] = f"{self.bin}:{sin}" if con_mecanismo else sin
        mensajes = {}
        for cmd in self._comandos(evento, "Write" if evento == "PostToolUse" else None):
            r = subprocess.run(cmd, shell=True, cwd=self.proy, env=env, input=json.dumps(entrada),
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"{cmd}: rc={r.returncode} stderr={r.stderr}")
            msg = json.loads(r.stdout).get("systemMessage", "") if r.stdout.strip() else ""
            mensajes[pathlib.Path(cmd.split()[0]).name] = msg
        return mensajes

    def _cuentas(self, mensajes):
        return {i: sum(m.count(f) for m in mensajes.values()) for i, f in FRASES.items()}

    def _post(self, con_mecanismo):
        entrada = {"session_id": self.sid, "hook_event_name": "PostToolUse", "tool_name": "Write",
                   "cwd": str(self.proy), "tool_input": {"file_path": str(self.blade), "content": BLADE}}
        return self._correr("PostToolUse", entrada, con_mecanismo)

    def _stop(self, con_mecanismo):
        entrada = {"session_id": self.sid, "hook_event_name": "Stop", "stop_hook_active": False,
                   "cwd": str(self.proy)}
        return self._correr("Stop", entrada, con_mecanismo)

    def _verifica(self, mensajes, quien_avisa, caso):
        cuentas = self._cuentas(mensajes)
        print(f"\n  {caso}: {cuentas} (avisa {quien_avisa})", end="")
        self.assertEqual(cuentas, {i: 1 for i in FRASES}, f"{caso}: {mensajes}")
        for hook, msg in mensajes.items():
            if hook != quien_avisa:
                self.assertFalse(any(f in msg for f in FRASES.values()), f"{caso}: {hook} también avisó")

    def test_post_con_mecanismo(self):
        m = self._post(True)
        self._verifica(m, "mecanismo-trampas.sh", "PostToolUse con mecanismo")
        self.assertIn("silencio delegado-a-mecanismo", self.bitacora.read_text())

    def test_post_sin_mecanismo(self):
        self._verifica(self._post(False), "blade-trampas.sh", "PostToolUse sin mecanismo")

    def test_stop_con_mecanismo(self):
        self._verifica(self._stop(True), "mecanismo-trampas.sh", "Stop con mecanismo")

    def test_stop_sin_mecanismo(self):
        self._verifica(self._stop(False), "stop-lint.sh", "Stop sin mecanismo")

    def test_sin_blade_yml_cae_al_bash(self):
        """Proyecto que copió la plantilla antigua (sin blade.yml) en una máquina con mecanismo:
        avisa el bash y mecanismo no tiene trampas que aplicar. Una vez cada una."""
        (self.proy / ".claude" / "trampas" / "blade.yml").unlink()
        self._verifica(self._post(True), "blade-trampas.sh", "PostToolUse con mecanismo, sin blade.yml")


if __name__ == "__main__":
    unittest.main()
