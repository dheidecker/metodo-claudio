"""Hook PermissionRequest: el juez de permisos (CONTRATO §12).

Intercepta el diálogo de permiso de los comandos Bash de ciertas familias (deploy de Cloud Run,
`gcloud builds submit`, `rm -rf`, `gcloud run jobs execute`, `docker push`, `git push`) y decide en
lugar de la persona: reglas deterministas para `rm -rf` y `git push` y, si no bastan, un juez modelo.
Ante cualquier fallo, exit 0 sin salida: vuelve el diálogo humano.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from lib import comun
from lib.juez import auditoria, contexto, llamada, reglas
from lib.juez.llamada import ErrorJuez
from lib.permisos import familias as F

HOOK = "juez-permisos"
EVENTO = "PermissionRequest"


def familias_configuradas() -> tuple[str, ...]:
    """`familias:` de estado_dir()/juez.yml, o las de por defecto. PyYAML solo si el archivo existe."""
    p = comun.estado_dir() / "juez.yml"
    if not p.exists():
        return reglas.FAMILIAS_POR_DEFECTO
    conf = comun.leer_yaml(p)
    fams = conf.get("familias") if isinstance(conf, dict) else None
    if not isinstance(fams, list) or not all(isinstance(x, str) for x in fams):
        raise ErrorJuez("config-invalida", str(p))
    return tuple(fams)


def salida(decision: str, motivo: str) -> dict:
    motivo = motivo.rstrip(". ")
    if decision == reglas.PERMITE:
        return {"hookSpecificOutput": {"hookEventName": EVENTO, "decision": {"behavior": "allow"}},
                "systemMessage": f"juez: permitido — {motivo}"}
    return {"hookSpecificOutput": {"hookEventName": EVENTO, "decision": {
                "behavior": "deny", "interrupt": False,
                "message": f"Juez de permisos: {motivo}. Si es correcto, explica por qué o pídeselo a la persona."}},
            "systemMessage": f"juez: negado — {motivo}"}


class _Caso:
    def __init__(self, d: dict, cmd: str, cwd: str, t0: float):
        self.d, self.cmd, self.cwd, self.t0 = d, cmd, cwd, t0
        self.raiz = str(comun.raiz_proyecto(cwd))
        self.proyecto = Path(self.raiz).name or "/"

    def decidir(self, decision: str, via: str, motivo: str, familia: str, riesgo: str, extra=None) -> int:
        motivo = contexto.redactar(motivo)
        ms = int((time.monotonic() - self.t0) * 1000)
        try:
            auditoria.anotar({"proyecto": self.raiz, "cwd": self.cwd, "comando": contexto.cortar(self.cmd, 4000),
                              "familia": familia, "via": via, "decision": decision, "motivo": motivo,
                              "riesgo": riesgo, "duracion_ms": ms, **(extra or {})})
        except OSError as e:
            comun.bitacora(HOOK, f"error auditoria {type(e).__name__}", proyecto=self.proyecto)
        if decision == reglas.PERMITE:
            comun.bitacora(HOOK, f"PERMITE {familia} {via}", proyecto=self.proyecto)
        else:
            comun.bitacora(HOOK, f"NIEGA {familia} {motivo[:80]}", proyecto=self.proyecto)
        print(json.dumps(salida(decision, motivo), ensure_ascii=False))
        return 0


def juzgar(d: dict, t0: float) -> int:
    cmd = (d.get("tool_input") or {}).get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return 0
    conf = familias_configuradas()
    ps = reglas.piezas(cmd)
    presentes = reglas.familias_presentes(cmd, ps)
    juzgadas = [f for f in presentes if f in conf]
    if not juzgadas:
        return 0
    cwd = d.get("cwd") or os.getcwd()
    caso = _Caso(d, cmd, cwd, t0)
    familia = "+".join(juzgadas)

    # Reglas deterministas (rm -rf, git push): un NIEGA de cualquiera manda, esté o no configurada.
    vs: dict[str, reglas.Veredicto] = {}
    if "rm -rf" in presentes:
        vs["rm -rf"] = reglas.reglas_rm(ps, cwd, caso.raiz)
    if "git push" in presentes:
        vs["git push"] = reglas.reglas_push(ps, cwd)
    for v in vs.values():
        if v.decision == reglas.NIEGA:
            return caso.decidir(reglas.NIEGA, "regla", v.motivo, familia, "alto")
    # Otra irreversible que no le toca al juez (p. ej. `kubectl apply` encadenado): un allow aprobaría
    # el comando entero, así que decide la persona.
    otras = [f for f in presentes if f not in conf and (f in F.FAMILIAS_IRREVERSIBLES or f in F.FAMILIAS_SENSIBLES)]
    if otras:
        comun.bitacora(HOOK, f"silencio fuera-de-juez {'+'.join(otras)}", proyecto=caso.proyecto)
        return 0
    if all(f in vs and vs[f].decision == reglas.PERMITE for f in juzgadas):
        return caso.decidir(reglas.PERMITE, "regla", "; ".join(vs[f].motivo for f in juzgadas), familia, "bajo")

    nota = "; ".join(v.motivo for v in vs.values() if v.motivo)
    destinos = vs["git push"].destinos if "git push" in vs else []
    datos = contexto.armar(cmd, cwd, juzgadas, nota, d.get("transcript_path"), destinos)
    try:
        r = llamada.juzgar(datos)
    except ErrorJuez as e:
        # Un fallo suelto del modelo no debe devolverle el diálogo a Derek: un reintento si queda tiempo
        # (el hook tiene 90 s; cada llamada, 45 como mucho).
        if e.tipo in ("timeout", "sin-claude") or time.monotonic() - t0 > 40:
            raise
        comun.bitacora(HOOK, f"reintento {e}"[:120], proyecto=caso.proyecto)
        r = llamada.juzgar(datos)
    return caso.decidir(r["decision"], "modelo", r["motivo"], familia, r["riesgo"],
                        {"costo_usd": r["costo_usd"]})


def main(t0: float | None = None) -> int:
    """t0: cuándo arrancó el proceso del hook (para que duracion_ms incluya las importaciones)."""
    t0 = time.monotonic() if t0 is None else t0
    if os.environ.get("MECANISMO_JUEZ_ANIDADO") == "1":
        return 0
    d = comun.leer_stdin_json()
    if d.get("tool_name") != "Bash":
        return 0
    proyecto = Path(d["cwd"]).name if isinstance(d.get("cwd"), str) and d["cwd"] else None
    try:
        return juzgar(d, t0)
    except ErrorJuez as e:
        comun.bitacora(HOOK, f"error {e}"[:120], proyecto=proyecto)
    except comun.SinPyYAML:
        comun.bitacora(HOOK, "error sin-pyyaml", proyecto=proyecto)
    except Exception as e:  # noqa: BLE001 — un fallo del juez nunca rompe la sesión: vuelve el diálogo
        comun.bitacora(HOOK, f"error excepcion {type(e).__name__}", proyecto=proyecto)
    sys.stdout.flush()
    return 0
