"""Convierte filas de la base al formato JSON que consumen la web y la app.

Los nombres de campo son los que ya usa la web (js/views.js), para no duplicar lógica.
`completo=False` devuelve la versión pública: sin texto libre, sin evidencia y sin datos personales.
"""
import json


def nodo_api(f) -> dict:
    return {"id": f["id"], "name": f["nombre"], "lat": f["lat"], "lng": f["lng"], "battery": f["bateria"],
            "calibrated": f["calibrado"], "tec": f["tec"], "base": json.loads(f["base"]), "lastSync": f["ultima_descarga"]}


def tramo_api(f) -> dict:
    return {"id": f["id"], "from": f["desde"], "to": f["hasta"], "name": f["nombre"], "points": json.loads(f["puntos"])}


def barrera_api(f) -> dict:
    return {"id": f["id"], "name": f["nombre"], "lat": f["lat"], "lng": f["lng"], "fill": f["llenado"], "nivel": f["nivel"],
            "nivelMax": f["nivel_max"], "lastEmptied": f["ultimo_vaciado"], "lastSync": f["ultima_descarga"]}


def lectura_api(f) -> dict:
    d = {k: f[k] for k in ("t", "ph", "cond", "turb", "color", "temp", "nivel")}
    d["anom"] = json.loads(f["anom"])
    if f["muestra"]:
        d["sample"] = f["muestra"]
    return d


def reporte_api(f, completo: bool, usuario_id=None) -> dict:
    """La identidad de quien reporta nunca sale del servidor; solo `mine` para su propio dueño."""
    if not completo:
        # Público: solo el problema y su ubicación aproximada (≈100 m)
        return {"id": f["id"], "cat": f["cat"], "lat": round(f["lat"], 3), "lng": round(f["lng"], 3), "t": f["t"],
                "status": f["estado"], "text": "", "ai": None, "anonymous": False, "voice": False, "photo": False,
                "mine": usuario_id is not None and f["usuario_id"] == usuario_id}
    ia = {"label": f["ia_etiqueta"], "conf": f["ia_confianza"]} if f["ia_etiqueta"] else None
    return {"id": f["id"], "cat": f["cat"], "ai": ia, "lat": f["lat"], "lng": f["lng"], "t": f["t"], "status": f["estado"],
            "anonymous": bool(f["anonimo"]), "voice": bool(f["voz"]), "text": f["texto"] or "", "photo": bool(f["foto"]),
            "mine": usuario_id is not None and f["usuario_id"] == usuario_id}


def caso_api(f, completo: bool) -> dict:
    d = {"id": f["id"], "type": f["tipo"], "dep": f["dep"], "status": f["estado"], "priority": f["prioridad"], "t": f["t"],
         "closedAt": f["cerrado"], "tramo": f["tramo"], "node": f["nodo"], "barrier": f["barrera"],
         "lat": f["lat"], "lng": f["lng"], "reports": [], "timeline": [], "public": not completo}
    if completo:
        d.update({"estimate": f["estimado"], "confidence": f["confianza"], "sample": f["muestra"], "summary": f["resumen"],
                  "lab": f["lab"], "peak": json.loads(f["pico"]) if f["pico"] else None,
                  "reports": json.loads(f["reportes"]), "timeline": json.loads(f["historial"]),
                  "confirmedAt": json.loads(f["confirmado_en"]), "auto": bool(f["auto"]),
                  "eventT": f["evento_t"], "locPending": bool(f["loc_pendiente"])})
    return d


def usuario_api(f) -> dict:
    d = {"id": f["id"], "cuenta": f["cuenta"], "nombre": f["nombre"], "rol": f["rol"]}
    for k in ("activo", "creado", "ultimo_acceso", "demo"):
        if k in f.keys():
            d[k] = bool(f[k]) if k in ("activo", "demo") else f[k]
    return d


def lote_api(f) -> dict:
    return {"id": f["id"], "node": f["nodo"], "uploaded": f["subido"], "file": f["archivo"], "rows": f["filas"],
            "new": f["nuevas"], "invalid": f["invalidas"], "from": f["desde"], "to": f["hasta"],
            "integrity": f["integridad"], "events": f["eventos"], "cases": json.loads(f["casos"] or "[]"),
            "checklist": json.loads(f["checklist"] or "{}"), "by": f["quien"] if "quien" in f.keys() else None}
