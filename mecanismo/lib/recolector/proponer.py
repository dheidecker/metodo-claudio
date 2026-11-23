"""De grupos y trampas documentadas a propuestas (CONTRATO §4). Nada se activa: solo se escribe."""
from __future__ import annotations

import re
from pathlib import Path

from lib import comun
from lib.propuestas import almacen
from lib.propuestas.almacen import id_de, norm
from lib.recolector.agrupar import UMBRAL, Grupo

NOTA_DOC = "ya documentada en {}; vigilar si se repite"
SIN_VALIDAR = "sin validar: falta lib.trampas.motor"


def _probar():
    """probar_trampa(trampa) -> list[str] (vacía = ok). Lo escribe el frente A; perezoso."""
    try:
        from lib.trampas.motor import probar_trampa  # noqa: PLC0415
    except ImportError:
        return None
    return probar_trampa


def normalizar_trampa(t: dict, origen: str) -> tuple[dict | None, str]:
    """Deja la trampa con la forma de CONTRATO §3 (nivel aviso). (None, motivo) si no sirve."""
    if not isinstance(t, dict):
        return None, "no es un mapping"
    prueba = t.get("prueba") if isinstance(t.get("prueba"), dict) else {}
    out = {
        "id": almacen.slug(str(t.get("id") or ""), 48) if t.get("id") else "",
        "nivel": "aviso",
        "globs": [str(g) for g in t.get("globs") or [] if str(g).strip()],
        "patron": str(t.get("patron") or ""),
        "mensaje": comun.redactar(str(t.get("mensaje") or "").strip())[:300],
        "origen": comun.redactar(origen)[:300],
        "prueba": {"dispara": comun.redactar(str(prueba.get("dispara") or "")),
                   "no_dispara": comun.redactar(str(prueba.get("no_dispara") or ""))},
    }
    if t.get("excepto"):
        out["excepto"] = str(t["excepto"])
    faltan = [k for k in ("id", "globs", "patron", "mensaje") if not out[k]]
    if faltan or not out["prueba"]["dispara"]:
        return None, "faltan campos: " + ", ".join(faltan or ["prueba.dispara"])
    for k in ("patron", "excepto"):
        if k in out:
            try:
                re.compile(out[k])
            except re.error as e:
                return None, f"{k} no compila: {e}"
    return out, ""


def validar_trampa(trampa: dict) -> tuple[bool, str]:
    """(True, "") si su propio caso dispara y el otro no; (True, SIN_VALIDAR) si no hay motor;
    (False, errores) si hay que descartarla."""
    probar = _probar()
    if probar is None:
        return True, SIN_VALIDAR
    try:
        errores = probar(trampa)
    except Exception as e:  # noqa: BLE001 — un motor que revienta no valida nada
        return False, f"probar_trampa falló: {e}"
    return (not errores), "; ".join(map(str, errores))


def _ejemplo(texto: str) -> str:
    """Como se guarda un ejemplo: redactado ANTES de cortar, espacios colapsados, ≤160."""
    return " ".join(comun.redactar(texto).split())[:160]


def _del_proyecto(ruta_m: str | None, ruta: Path) -> bool:
    if not ruta_m:
        return False
    r = Path(ruta_m)
    return r == ruta or ruta in r.parents


def _evidencia(g: Grupo, solo: Path | None = None) -> dict:
    """`solo`: la propuesta se escribe dentro del repo de ese proyecto, que puede acabar versionado:
    los ejemplos solo pueden ser textos de ESE proyecto (o ninguno), nunca prompts de otro."""
    ejemplos, vistos = [], set()
    muestras = g.muestras if solo is None else [m for m in g.muestras if _del_proyecto(m.ruta, solo)]
    for m in sorted(muestras, key=lambda m: m.dia, reverse=True):
        t = _ejemplo(m.texto)
        if norm(t) not in vistos:
            vistos.add(norm(t))
            ejemplos.append(t)
        if len(ejemplos) == 3:
            break
    return {"ocurrencias": g.ocurrencias, "proyectos": g.proyectos, "dias": g.dias,
            "puntuacion": g.puntuacion, "ejemplos": ejemplos}


def _id_estable(g: Grupo, existentes: dict[str, dict], tomados: set[str]) -> str:
    """Ids estables (CONTRATO §11): el mismo grupo actualiza la propuesta que ya existe aunque el
    modelo lo resuma con otras palabras. Orden: (1) el `existente` que devolvió la fusión, que recibe
    los ids y resúmenes de las propuestas de estado_dir()/propuestas/; (2) mismo resumen normalizado;
    (3) comparte algún ejemplo (los prompts se repiten entre corridas: history acumula); (4) id nuevo
    de sha256(resumen). Un id existente lo toma un solo grupo por corrida."""
    libres = {pid: p for pid, p in existentes.items() if pid not in tomados and p.get("origen") == "recolector"}
    if g.existente and g.existente in libres:
        return g.existente
    n = norm(g.resumen)
    for pid, p in sorted(libres.items()):
        if norm(p.get("resumen", "")) == n:
            return pid
    mios = {norm(_ejemplo(m.texto)) for m in g.muestras}
    mejor, comun_max = "", 0
    for pid, p in sorted(libres.items()):
        suyos = {norm(e) for e in ((p.get("evidencia") or {}).get("ejemplos") or []) if isinstance(e, str)}
        k = len(mios & suyos)
        if k > comun_max:
            mejor, comun_max = pid, k
    return mejor or id_de(g.resumen)


def de_grupo(g: Grupo, metodo_dir: Path, existentes: dict[str, dict],
             tomados: set[str] | None = None) -> tuple[dict, Path] | None:
    """Una propuesta por grupo con ≥3 ocurrencias. Devuelve (propuesta, carpeta destino).
    `existentes` son las de la carpeta global; si el grupo es una de ellas, se actualiza ahí."""
    if g.ocurrencias < UMBRAL:
        return None
    tomados = set() if tomados is None else tomados
    notas = []
    doc = g.documentada_sha or (f"«{g.documentada_en}»" if g.documentada_en else "")
    if doc:
        notas.append(NOTA_DOC.format(doc))
    nombre, ruta = g.proyecto_dominante()
    pid = _id_estable(g, existentes, tomados)
    tomados.add(pid)
    reutiliza = pid in existentes
    prop = {"id": pid, "estado": "pendiente", "origen": "recolector", "resumen": g.resumen}
    carpeta = almacen.dir_global()
    trampa = None
    if g.trampa is not None:
        trampa, motivo = normalizar_trampa(g.trampa, f"recolector: «{g.resumen}» ({g.ocurrencias} veces)")
        if trampa is not None:
            ok, motivo = validar_trampa(trampa)
            if not ok:
                trampa = None
            elif motivo:
                notas.append(motivo)
        if trampa is None:
            notas.append(f"trampa descartada: {motivo}")
    if trampa is not None:
        prop.update(tipo="subir-a-hook" if doc else "trampa-nueva", destino="trampa",
                    contenido={"trampa": trampa, "proyecto": ruta or nombre})
        if ruta and Path(ruta).is_dir() and not reutiliza:
            carpeta = almacen.dir_proyecto(ruta)
    elif g.alcance == "metodologia":
        prop.update(tipo="regla-metodologia", destino="metodologia",
                    contenido={"archivo": str(metodo_dir / "METODOLOGIA.md"), "texto": g.regla or g.resumen})
    else:
        prop.update(tipo="regla-proyecto", destino="proyecto",
                    contenido={"archivo": str(Path(ruta or nombre) / "CLAUDE.md"), "texto": g.regla or g.resumen})
    dentro_de_repo = carpeta != almacen.dir_global()
    prop["evidencia"] = _evidencia(g, Path(ruta) if dentro_de_repo else None)
    if notas:
        prop["nota"] = " · ".join(notas)
    return prop, carpeta


def ids_trampas_activas(ruta: Path) -> set[str]:
    out = set()
    for f in sorted((Path(ruta) / ".claude" / "trampas").glob("*.yml")):
        try:
            d = comun.leer_yaml(f)
        except Exception:  # noqa: BLE001
            continue
        for t in d if isinstance(d, list) else [d]:
            if isinstance(t, dict) and t.get("id"):
                out.add(t["id"])
    return out


def de_trampa_documentada(item: dict, sugerida: dict) -> tuple[dict | None, Path | None, str]:
    """trampa-nueva a partir de una trampa escrita en Markdown. (None, None, motivo) si se descarta."""
    rel = Path(item["archivo"]).name
    trampa, motivo = normalizar_trampa(sugerida, f"{rel}:{item['linea']} «{item['titulo'][:80]}»")
    if trampa is None:
        return None, None, motivo
    ruta = Path(item["ruta"])
    if trampa["id"] in ids_trampas_activas(ruta):
        return None, None, f"{trampa['id']} ya existe en {ruta.name}"
    ok, nota = validar_trampa(trampa)
    if not ok:
        return None, None, f"{trampa['id']}: {nota}"
    prop = {"id": id_de(f"{ruta}:{item['titulo']}", base=trampa["id"]), "estado": "pendiente",
            "origen": "recolector", "tipo": "trampa-nueva", "destino": "trampa",
            "resumen": trampa["mensaje"],
            "evidencia": {"ocurrencias": 1, "proyectos": [ruta.name], "dias": 1, "puntuacion": 1,
                          "ejemplos": [item["titulo"][:160]]},
            "contenido": {"trampa": trampa, "proyecto": str(ruta)}}
    if nota:
        prop["nota"] = nota
    return prop, almacen.dir_proyecto(ruta), ""
