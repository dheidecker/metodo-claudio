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


def _evidencia(g: Grupo) -> dict:
    ejemplos, vistos = [], set()
    for m in sorted(g.muestras, key=lambda m: m.dia, reverse=True):
        t = " ".join(comun.redactar(m.texto).split())[:160]
        if norm(t) not in vistos:
            vistos.add(norm(t))
            ejemplos.append(t)
        if len(ejemplos) == 3:
            break
    return {"ocurrencias": g.ocurrencias, "proyectos": g.proyectos, "dias": g.dias,
            "puntuacion": g.puntuacion, "ejemplos": ejemplos}


def _id_estable(g: Grupo, existentes: dict[str, dict]) -> str:
    if g.existente and g.existente in existentes:
        return g.existente
    n = norm(g.resumen)
    for pid, p in existentes.items():
        if p.get("origen") == "recolector" and norm(p.get("resumen", "")) == n:
            return pid
    return id_de(g.resumen)


def de_grupo(g: Grupo, metodo_dir: Path, existentes: dict[str, dict]) -> tuple[dict, Path] | None:
    """Una propuesta por grupo con ≥3 ocurrencias. Devuelve (propuesta, carpeta destino)."""
    if g.ocurrencias < UMBRAL:
        return None
    notas = []
    doc = g.documentada_sha or (f"«{g.documentada_en}»" if g.documentada_en else "")
    if doc:
        notas.append(NOTA_DOC.format(doc))
    nombre, ruta = g.proyecto_dominante()
    prop = {"id": _id_estable(g, existentes), "estado": "pendiente", "origen": "recolector",
            "resumen": g.resumen, "evidencia": _evidencia(g)}
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
        if ruta and Path(ruta).is_dir():
            carpeta = almacen.dir_proyecto(ruta)
    elif g.alcance == "metodologia":
        prop.update(tipo="regla-metodologia", destino="metodologia",
                    contenido={"archivo": str(metodo_dir / "METODOLOGIA.md"), "texto": g.regla or g.resumen})
    else:
        prop.update(tipo="regla-proyecto", destino="proyecto",
                    contenido={"archivo": str(Path(ruta or nombre) / "CLAUDE.md"), "texto": g.regla or g.resumen})
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
