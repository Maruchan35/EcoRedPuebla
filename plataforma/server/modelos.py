"""Convierte filas de la base al formato JSON que consumen la web y la app.

Los nombres de campo son los que ya usa la web (js/views.js), para no duplicar lógica.
`completo=False` devuelve la versión pública: sin texto libre, sin evidencia y sin datos personales.
"""
import json


def nodo_api(f) -> dict:
    return {"id": f["id"], "name": f["nombre"], "lat": f["lat"], "lng": f["lng"], "battery": f["bateria"],
            "calibrated": f["calibrado"], "tec": f["tec"], "base": json.loads(f["base"]), "lastSync": f["ultima_descarga"]}


def tramo_api(f) -> dict:
    from .motor import largo_km, tiempo_recorrido          # aquí y no arriba: motor no depende de modelos
    puntos = json.loads(f["puntos"])
    largo = largo_km(puntos)
    rapido, lento = tiempo_recorrido(largo)
    # km de cauce y cuántas horas tarda el agua en recorrerlo (en crecida, en estiaje)
    return {"id": f["id"], "from": f["desde"], "to": f["hasta"], "name": f["nombre"], "points": puntos,
            "km": round(largo, 1), "transitH": [round(rapido / 3600000, 2), round(lento / 3600000, 1)]}


def barrera_api(f) -> dict:
    return {"id": f["id"], "name": f["nombre"], "lat": f["lat"], "lng": f["lng"], "fill": f["llenado"], "nivel": f["nivel"],
            "nivelMax": f["nivel_max"], "lastEmptied": f["ultimo_vaciado"], "lastSync": f["ultima_descarga"]}


ESTACION = ("caudal", "turb_sal", "color_sal", "cond_sal", "ph_sal", "lodos", "dp_filtro", "solar")


def lectura_api(f) -> dict:
    d = {k: f[k] for k in ("t", "ph", "cond", "turb", "color", "temp", "nivel")}
    d["anom"] = json.loads(f["anom"])
    if f["muestra"]:
        d["sample"] = f["muestra"]
    if "caudal" in f.keys() and f["caudal"] is not None:           # nodo con estación de tratamiento
        d.update({k: f[k] for k in ESTACION})
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
    from .seguridad import permisos_de                 # aquí y no arriba: seguridad no depende de modelos
    d = {"id": f["id"], "cuenta": f["cuenta"], "nombre": f["nombre"], "rol": f["rol"], "permisos": sorted(permisos_de(f))}
    for k in ("activo", "creado", "ultimo_acceso", "demo", "cambiar_clave"):
        if k in f.keys():
            d[k] = bool(f[k]) if k in ("activo", "demo", "cambiar_clave") else f[k]
    if "permisos" in f.keys():
        d["permisos_propios"] = f["permisos"] is not None and f["rol"] not in ("admin", "ciudadano")
    return d


def lote_api(f) -> dict:
    return {"id": f["id"], "node": f["nodo"], "uploaded": f["subido"], "file": f["archivo"], "rows": f["filas"],
            "new": f["nuevas"], "invalid": f["invalidas"], "from": f["desde"], "to": f["hasta"],
            "integrity": f["integridad"], "events": f["eventos"], "cases": json.loads(f["casos"] or "[]"),
            "checklist": json.loads(f["checklist"] or "{}"), "by": f["quien"] if "quien" in f.keys() else None}
