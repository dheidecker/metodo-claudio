"""Propuestas de permisos (CONTRATO §4, origen: permisos, destino: permisos).

Tres tipos:
  permiso-allow       familia con N aprobaciones simples y 0 rechazos -> agregar a allow
  permiso-quitar-ask  regla ask con 0 diálogos en el período         -> quitarla de ask
  envolver-script     lo que no debe ir a allow pelado pero se repite -> script o hook guardián + su allow

Nunca se escribe settings.json: cada propuesta lleva `comando_jq`, que se imprime y aplica una persona
tras `mecanismo aprobar ID`. Nunca sale `permiso-allow` para la lista fija de familias.IRREVERSIBLES,
para las SENSIBLES (van envueltas) ni para intérpretes y shells remotos (NUNCA_ALLOW). Y ninguna regla
`permiso-allow` casa con un comando del corpus familias.CORPUS: si `Bash(<familia> *)` casaría, se
estrecha al comando exacto más aprobado, y si ni así es segura, no se propone.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re
from pathlib import Path

from lib import comun
from lib.permisos import familias, reglas as mreglas
from lib.permisos.analisis import Analisis, Grupo

MINIMO = 3   # aprobaciones (o repeticiones de un compuesto) para proponer


def _slug(texto: str, largo: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return (s[:largo].rstrip("-")) or "x"


def _id(tipo: str, nombre: str, canon: str) -> str:
    """slug + 8 hex de sha256(texto canónico): estable entre corridas mientras no cambie la regla."""
    return f"{_slug(tipo + '-' + nombre)}-{hashlib.sha256(canon.encode()).hexdigest()[:8]}"


def _base(tipo: str, nombre: str, canon: str, resumen: str, evidencia: dict, contenido: dict, nota: str | None) -> dict:
    p = {
        "id": _id(tipo, nombre, canon),
        "estado": "pendiente",
        "creada": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "origen": "permisos",
        "tipo": tipo,
        "destino": "permisos",
        "resumen": comun.redactar(resumen),
        "evidencia": evidencia,
        "contenido": contenido,
    }
    if nota:
        p["nota"] = comun.redactar(nota)
    return p


def _evidencia_vacia() -> dict:
    return {"ocurrencias": 0, "proyectos": [], "dias": 0, "puntuacion": 0, "ejemplos": []}


def puede_allow(g: Grupo) -> bool:
    """La barrera dura: ¿esta familia podría ir a allow pelado alguna vez?"""
    if g.herramienta != "Bash":
        return True
    if g.irreversible or g.nombre in familias.FAMILIAS_IRREVERSIBLES:
        return False
    if (g.nombre in familias.FAMILIAS_SENSIBLES or g.nombre in familias.NUNCA_ALLOW
            or g.nombre.split()[0] in familias.NUNCA_ALLOW):
        return False
    if g.nombre.startswith("(") or familias.clasificar(g.nombre).irreversible:
        return False
    return True


def regla_segura(regla: str) -> bool:
    """Una regla allow es segura si no deja pasar NINGÚN comando del corpus de irreversibles
    (familias.CORPUS), simulando el casado de Claude Code. Se comprueba la regla, no su prefijo:
    `Bash(npm run *)` tiene un prefijo inocente y casa con `npm run deploy`. Además, `rm` nunca
    lleva comodín."""
    tool, pat = mreglas.partes(regla)
    if tool != "Bash":
        return True
    if pat is None or not pat.strip():
        return False                      # `Bash` a secas casa con todo
    if "*" in pat:
        cabeza = familias.normalizar(mreglas.prefijo(regla)).split()
        if not cabeza or familias._palabra_comando(cabeza[0]) in familias.SIN_COMODIN:
            return False
    return mreglas.casa_corpus(regla) is None


def _exacta(g: Grupo) -> tuple[str | None, str]:
    """La regla sin comodín para el comando aprobado más frecuente del grupo, o None si ni así es segura."""
    if not g.comandos:
        return None, "sin comandos aprobados"
    cmd, n = g.comandos.most_common(1)[0]
    if not cmd or "\n" in cmd or any(c in cmd for c in "*()"):
        return None, f"el comando más aprobado ({n}×) no cabe en una regla exacta"
    if comun.redactar(cmd) != cmd:
        return None, "el comando más aprobado lleva un secreto"
    if familias.es_irreversible(cmd) or familias.clasificar(cmd).compuesto:
        return None, "el comando más aprobado es irreversible o compuesto"
    regla = f"Bash({cmd})"
    if not regla_segura(regla):
        return None, f"{regla} casa con un irreversible"
    return regla, f"{n} de {g.simples_aprobados} aprobaciones son exactamente ese comando"


def _permiso_allow(a: Analisis, cfg: dict, minimo: int) -> list[dict]:
    out = []
    for g in sorted(a.familias.values(), key=lambda g: -g.dialogos):
        if g.rechazados or g.simples_aprobados < minimo or not puede_allow(g):
            continue
        nota, cubre = None, g.nombre
        if g.herramienta != "Bash":
            regla = g.herramienta
        else:
            regla = f"Bash({g.nombre} *)"
            choca = None if regla_segura(regla) else (mreglas.casa_corpus(regla) or "rm con comodín")
            top = g.comandos.most_common(1)[0][0] if g.comandos else None
            no_cubre = top is not None and not mreglas.casa_claude(regla, top)
            if choca or no_cubre:
                exacta, porque = _exacta(g)
                if not exacta:
                    continue
                motivo = (f"{regla} dejaría pasar `{choca}`" if choca
                          else f"{regla} no cubre el comando más aprobado")
                nota = f"Estrechada: {motivo}. Se propone solo el comando exacto ({porque})."
                regla, cubre = exacta, mreglas.partes(exacta)[1]
        if regla in cfg.get("allow", []):
            continue
        # Si una regla ask la cubre, un allow no quita el diálogo (ask gana): no se propone.
        if any(mreglas.casa(r, g.herramienta, cubre) for r in cfg.get("ask", [])):
            continue
        out.append(_base(
            "permiso-allow", g.nombre, f"permiso-allow|{regla}",
            f"Permitir {regla}: {g.simples_aprobados} aprobaciones y 0 rechazos en {a.dias or 'todos los'} días",
            g.evidencia(),
            {"lista": "allow", "accion": "agregar", "regla": regla,
             "comando_jq": mreglas.comando_jq(agregar={"allow": [regla]})},
            nota))
    return out


def _quitar_ask(a: Analisis, cfg: dict) -> list[dict]:
    out = []
    for regla, n in a.reglas.get("ask", {}).items():
        if n or mreglas.es_protegida(regla):
            continue
        out.append(_base(
            "permiso-quitar-ask", mreglas.prefijo(regla) or regla, f"permiso-quitar-ask|{regla}",
            f"Quitar {regla} de ask: 0 diálogos en {a.dias or 'todos los'} días",
            _evidencia_vacia(),
            {"lista": "ask", "accion": "quitar", "regla": regla,
             "comando_jq": mreglas.comando_jq(quitar={"ask": [regla]})},
            "Sin diálogos no hay fricción que quitar; sin la regla, el comando pasa al modo por defecto."))
    return out


def _git_push(a: Analisis, minimo: int) -> list[dict]:
    """Decisión de Derek (PLAN §7.3): push a ramas que no son main -> script guardián + su allow.
    Push a main/master y --force/-f/--force-with-lease siguen en ask (y en deny el force)."""
    g = a.familias.get("git push")
    if not g or g.aprobados < minimo:
        return []
    regla = "Bash(git-push-rama *)"
    v = g.variantes
    return [_base(
        "envolver-script", "git-push-rama", "envolver-script|git push|git-push-rama",
        f"git push a ramas que no son main vía script guardián git-push-rama (+ allow); "
        f"{g.dialogos} diálogos: rama {v.get('rama', 0)}, sin destino {v.get('sin-destino', 0)}, "
        f"main {v.get('main', 0)}, force {v.get('force', 0)}",
        g.evidencia(),
        {"lista": "allow", "accion": "agregar", "regla": regla,
         "comando_jq": mreglas.comando_jq(agregar={"allow": [regla]}),
         "script": {
             "nombre": "git-push-rama",
             "hace": "git push [remoto] <rama> pasando los argumentos tal cual",
             "rechaza": ["destino main o master (explícito, o la rama actual si no se da destino)",
                         "--force, -f, --force-with-lease y refspecs con +",
                         "--mirror, --all, --delete y :rama"],
             "sale": "exit 1 con el motivo; el push a main sigue por `git push` y su regla ask"},
         "mantener": {"ask": ["Bash(git push*)"], "deny": ["Bash(git push --force*)", "Bash(git push -f*)"]},
         "variantes": dict(v)},
        "Aprobada por Derek (PLAN §7.3). El script guardián no existe todavía: aplicar comando_jq solo "
        "después de instalarlo.")]


def _bq_query(a: Analisis, cfg: dict) -> list[dict]:
    """Decisión de Derek (PLAN §7.3): bq query a allow solo con un hook que obligue --maximum_bytes_billed."""
    g = a.familias.get("bq query")
    en_ask = [r for r in cfg.get("ask", []) if familias.clasificar(mreglas.prefijo(r)).familia == "bq query"]
    if not g and not en_ask:
        return []
    regla = "Bash(bq query*)"
    return [_base(
        "envolver-script", "bq-query-con-tope", "envolver-script|bq query|hook-maximum-bytes-billed",
        f"bq query a allow con un hook PreToolUse que exija --maximum_bytes_billed "
        f"({g.dialogos if g else 0} diálogos en {a.dias or 'todos los'} días)",
        g.evidencia() if g else _evidencia_vacia(),
        {"lista": "allow", "accion": "agregar", "regla": regla,
         "comando_jq": mreglas.comando_jq(agregar={"allow": [regla]}, quitar={"ask": en_ask} if en_ask else None),
         "script": {
             "nombre": "bq-con-tope",
             "tipo": "hook PreToolUse (matcher Bash)",
             "hace": "si el comando contiene `bq query` sin --maximum_bytes_billed=<n>, exit 2 con el motivo",
             "rechaza": ["bq query sin --maximum_bytes_billed", "--maximum_bytes_billed por encima del tope acordado"]},
         "quitar_de_ask": en_ask},
        "Aprobada por Derek (PLAN §7.3). El hook no existe todavía: aplicar comando_jq solo después de engancharlo.")]


def _compuestos(a: Analisis, minimo: int) -> list[dict]:
    out = []
    for f, g in sorted(a.complejos.items(), key=lambda x: -x[1].dialogos):
        if g.dialogos < minimo or g.rechazados or g.irreversible or f.startswith("("):
            continue
        nombre = _slug(f.replace(" + ", "-"), 40)
        regla = f"Bash({nombre} *)"
        out.append(_base(
            "envolver-script", nombre, f"envolver-script|{f}",
            f"Compuesto recurrente ({g.dialogos}× too-complex): {f} -> script {nombre} + allow",
            g.evidencia(),
            {"lista": "allow", "accion": "agregar", "regla": regla,
             "comando_jq": mreglas.comando_jq(agregar={"allow": [regla]}),
             "script": {"nombre": nombre, "forma": f,
                        "hace": "la secuencia de la forma, con lo variable como argumentos (ver ejemplos)"}},
            "Bash no puede evaluar un compuesto contra reglas (bashMiss:too-complex): un script con "
            "nombre propio sí se puede permitir. Escribir el script antes de aplicar comando_jq."))
    return out


def generar(a: Analisis, cfg: dict | None = None, minimo: int = MINIMO) -> list[dict]:
    cfg = cfg if cfg is not None else mreglas.leer_reglas()
    props = (_permiso_allow(a, cfg, minimo) + _quitar_ask(a, cfg) + _git_push(a, minimo)
             + _bq_query(a, cfg) + _compuestos(a, minimo))
    # Defensa en profundidad: ninguna permiso-allow que deje pasar un irreversible conocido, pase lo
    # que pase arriba. Se comprueba la REGLA contra el corpus, no solo su prefijo.
    return [p for p in props if not (p["tipo"] == "permiso-allow" and (
        not regla_segura(p["contenido"]["regla"])
        or familias.clasificar(mreglas.prefijo(p["contenido"]["regla"])).irreversible))]


def escribir(props: list[dict], destino: Path | None = None) -> list[tuple[str, str]]:
    """Escribe en comun.estado_dir()/propuestas. Una ya aprobada o rechazada no se toca; una
    pendiente se actualiza conservando `creada`. Devuelve [(id, nueva|actualizada|decidida)]."""
    import yaml  # noqa: PLC0415  (la CLI ya comprobó que está)
    d = destino or comun.estado_dir() / "propuestas"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for p in props:
        f = d / f"{p['id']}.yml"
        que = "nueva"
        if f.exists():
            try:
                viejo = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                viejo = {}
            if viejo.get("estado") in ("aprobada", "rechazada"):
                out.append((p["id"], "decidida"))
                continue
            if viejo.get("creada"):
                c = viejo["creada"]
                p = {**p, "creada": c if isinstance(c, str) else c.isoformat()}
            que = "actualizada"
        f.write_text(yaml.safe_dump(p, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        out.append((p["id"], que))
    return out
