"""Red de nodos configurable desde Administración: alta, edición, baja y tramos recalculados sobre el cauce.

El cauce (la línea del río) viene de js/cauce.js (OpenStreetMap) y no cambia. Los nodos sí: Administración los
da de alta sobre el río, los renombra, los mueve o los da de baja. Cada cambio vuelve a ordenar los nodos río
abajo y rehace los tramos entre vecinos (T1…Tn): su trazo, sus km y, con eso, el tiempo que tarda el agua.
Un nodo dado de baja pasa a la tabla nodos_baja con sus lecturas intactas, así que se puede reactivar.
"""
import json

from . import motor, semilla
from .db import ahora, guardar_ajuste, leer_ajuste

DISTANCIA_MAX_M = 1500          # un nodo va sobre el cauce: un punto más lejos del río se rechaza
SEPARACION_MIN_KM = 0.3         # dos nodos a menos de esto medirían la misma agua
AJUSTES_DEF = {"radio_km": motor.RADIO_FUSION_KM, "vel_min": motor.VEL_MIN_MS, "vel_max": motor.VEL_MAX_MS, "dias_sin_visita": 7}


class ErrorRed(ValueError):
    """Un cambio que la red no admite; el mensaje se muestra tal cual a Administración."""


def ajustes(con) -> dict:
    return {**AJUSTES_DEF, **leer_ajuste(con, "red_ajustes", {})}


def aplicar_ajustes(con) -> dict:
    """Pone en el motor el radio para ligar reportes y las velocidades del agua guardados."""
    a = ajustes(con)
    motor.RADIO_FUSION_KM, motor.VEL_MIN_MS, motor.VEL_MAX_MS = a["radio_km"], a["vel_min"], a["vel_max"]
    return a


def guardar_ajustes(con, radio_km, vel_min, vel_max, dias_sin_visita) -> dict:
    if vel_min >= vel_max:
        raise ErrorRed("La velocidad mínima del agua debe ser menor que la máxima.")
    guardar_ajuste(con, "red_ajustes", {"radio_km": radio_km, "vel_min": vel_min, "vel_max": vel_max, "dias_sin_visita": dias_sin_visita})
    return aplicar_ajustes(con)


def _km(lat, lng) -> float:
    return semilla.ubicar_en_rio(lat, lng)[2]


def _validar_lugar(con, lat, lng, excepto=None):
    """Devuelve el punto del río donde queda el nodo, o explica por qué no se puede poner ahí."""
    plat, plng, km, metros = semilla.ubicar_en_rio(lat, lng)
    if metros > DISTANCIA_MAX_M:
        raise ErrorRed(f"Ese punto está a {metros / 1000:.1f} km del río. Los nodos van sobre el cauce: elige un punto más cerca de la línea del río.")
    for f in con.execute("SELECT id, nombre, lat, lng FROM nodos"):
        if f["id"] != excepto and abs(_km(f["lat"], f["lng"]) - km) < SEPARACION_MIN_KM:
            raise ErrorRed(f"Queda a menos de {SEPARACION_MIN_KM * 1000:.0f} m de {f['id']} ({f['nombre']}): mediría la misma agua. Elige otro punto.")
    return plat, plng, km


def _siguiente_id(con) -> str:
    ids = [f["id"] for f in con.execute("SELECT id FROM nodos UNION SELECT id FROM nodos_baja")]
    return f"N{max((int(i[1:]) for i in ids if i[:1] == 'N' and i[1:].isdigit()), default=0) + 1}"


def _valores_entre(con, km) -> dict:
    """Valores normales de un nodo nuevo: los de sus vecinos de arriba y de abajo, según su lugar en el río."""
    vecinos = sorted(((_km(f["lat"], f["lng"]), json.loads(f["base"])) for f in con.execute("SELECT lat, lng, base FROM nodos")),
                     key=lambda x: x[0])
    arriba = [v for v in vecinos if v[0] <= km] or vecinos[:1]
    abajo = [v for v in vecinos if v[0] >= km] or vecinos[-1:]
    (ka, va), (kb, vb) = arriba[-1], abajo[0]
    f = 0.0 if kb == ka else (km - ka) / (kb - ka)
    return {k: round(va[k] + f * (vb.get(k, va[k]) - va[k]), 2) for k in va}


def recalcular(con) -> list:
    """Ordena río abajo los nodos activos y rehace los tramos T1…Tn sobre el cauce. Los casos y el índice de un
    tramo pasan al tramo nuevo que termina en el mismo nodo (el que da su semáforo). Si ese nodo salió de la red,
    su índice se borra (era de ese nodo) y sus casos pasan al tramo que ahora cubre su lugar.
    Corre dentro de la transacción de quien llama."""
    nodos = [dict(f) for f in con.execute("SELECT id, nombre, lat, lng FROM nodos")]
    for n in nodos:
        n["km"] = _km(n["lat"], n["lng"])
    nodos.sort(key=lambda n: n["km"])
    nuevos = [{"id": f"T{i + 1}", "desde": a["id"], "hasta": b["id"], "km0": a["km"], "km1": b["km"],
               "nombre": a["nombre"].split(" · ")[0] + " → " + b["nombre"].split(" · ")[0],
               "puntos": semilla.trazo_entre(a["km"], b["km"])} for i, (a, b) in enumerate(zip(nodos, nodos[1:]))]
    por_hasta = {t["hasta"]: t["id"] for t in nuevos}
    for i, n in enumerate(nodos):
        con.execute("UPDATE nodos SET orden = ? WHERE id = ?", (i, n["id"]))
    for viejo in con.execute("SELECT id, hasta FROM tramos").fetchall():
        nuevo = por_hasta.get(viejo["hasta"])
        if nuevo is None:
            con.execute("DELETE FROM indice_diario WHERE tramo = ?", (viejo["id"],))
            baja = con.execute("SELECT lat, lng FROM nodos_baja WHERE id = ?", (viejo["hasta"],)).fetchone()
            pos = _km(baja["lat"], baja["lng"]) if baja else None
            nuevo = next((t["id"] for t in nuevos if pos is not None and t["km0"] <= pos <= t["km1"]), None)
        # En dos pasos (con ~) para que un tramo renombrado no choque con otro que todavía no se mueve
        con.execute("UPDATE casos SET tramo = ? WHERE tramo = ?", ("~" + nuevo if nuevo else None, viejo["id"]))
        con.execute("UPDATE indice_diario SET tramo = ? WHERE tramo = ?", ("~" + nuevo if nuevo else "~", viejo["id"]))
    con.execute("UPDATE casos SET tramo = substr(tramo, 2) WHERE tramo LIKE '~%'")
    con.execute("DELETE FROM indice_diario WHERE tramo = '~'")
    con.execute("UPDATE indice_diario SET tramo = substr(tramo, 2) WHERE tramo LIKE '~%'")
    con.execute("DELETE FROM tramos")
    con.executemany("INSERT INTO tramos (id, desde, hasta, nombre, puntos) VALUES (?,?,?,?,?)",
                    [(t["id"], t["desde"], t["hasta"], t["nombre"], json.dumps(t["puntos"])) for t in nuevos])
    guardar_ajuste(con, "red_editada", True)                       # el arranque ya no la vuelve a tomar del archivo
    return [n["id"] for n in nodos]


def alta(con, nombre: str, lat: float, lng: float, tec: str) -> str:
    plat, plng, km = _validar_lugar(con, lat, lng)
    nid = _siguiente_id(con)
    con.execute("INSERT INTO nodos (id, orden, nombre, lat, lng, bateria, calibrado, tec, base) VALUES (?,?,?,?,?,?,?,?,?)",
                (nid, 999, nombre.strip(), plat, plng, 90, ahora(), tec.strip() or None, json.dumps(_valores_entre(con, km))))
    recalcular(con)
    return nid


def editar(con, nid: str, nombre=None, tec=None, lat=None, lng=None) -> None:
    if not con.execute("SELECT 1 FROM nodos WHERE id = ?", (nid,)).fetchone():
        raise LookupError(nid)
    if nombre:
        con.execute("UPDATE nodos SET nombre = ? WHERE id = ?", (nombre.strip(), nid))
    if tec is not None:
        con.execute("UPDATE nodos SET tec = ? WHERE id = ?", (tec.strip() or None, nid))
    if lat is not None and lng is not None:
        plat, plng, _ = _validar_lugar(con, lat, lng, excepto=nid)
        con.execute("UPDATE nodos SET lat = ?, lng = ? WHERE id = ?", (plat, plng, nid))
    recalcular(con)


def baja(con, nid: str) -> None:
    if not con.execute("SELECT 1 FROM nodos WHERE id = ?", (nid,)).fetchone():
        raise LookupError(nid)
    if con.execute("SELECT COUNT(*) AS c FROM nodos").fetchone()["c"] <= 2:
        raise ErrorRed("La red necesita al menos dos nodos activos para formar un tramo.")
    con.execute("DELETE FROM nodos_baja WHERE id = ?", (nid,))
    con.execute("INSERT INTO nodos_baja SELECT * FROM nodos WHERE id = ?", (nid,))
    con.execute("DELETE FROM nodos WHERE id = ?", (nid,))
    recalcular(con)


def reactivar(con, nid: str) -> None:
    f = con.execute("SELECT lat, lng FROM nodos_baja WHERE id = ?", (nid,)).fetchone()
    if not f:
        raise LookupError(nid)
    _validar_lugar(con, f["lat"], f["lng"])
    con.execute("INSERT INTO nodos SELECT * FROM nodos_baja WHERE id = ?", (nid,))
    con.execute("DELETE FROM nodos_baja WHERE id = ?", (nid,))
    recalcular(con)


def eliminar(con, nid: str) -> None:
    """Borra para siempre un nodo que ya estaba dado de baja, con sus lecturas y lotes (por ejemplo, uno de prueba)."""
    if not con.execute("SELECT 1 FROM nodos_baja WHERE id = ?", (nid,)).fetchone():
        raise LookupError(nid)
    for tabla in ("lecturas", "lotes"):
        con.execute(f"DELETE FROM {tabla} WHERE nodo = ?", (nid,))
    con.execute("DELETE FROM nodos_baja WHERE id = ?", (nid,))


def estado(con) -> dict:
    """Lo que muestra la pantalla Red de nodos: nodos con su km sobre el río, los dados de baja, el cauce y los ajustes."""
    pts, km = semilla.curso_rio()
    paso = max(1, len(pts) // 600)                                # la línea del río, aligerada para el mapa
    activos = []
    for f in con.execute("SELECT id, nombre, lat, lng, tec, orden, ultima_descarga FROM nodos ORDER BY orden"):
        activos.append({**dict(f), "km": round(_km(f["lat"], f["lng"]), 2)})
    baja = [{**dict(f), "km": round(_km(f["lat"], f["lng"]), 2)} for f in con.execute("SELECT id, nombre, lat, lng, tec FROM nodos_baja ORDER BY id")]
    return {"nodos": activos, "baja": baja, "curso": pts[::paso] + ([pts[-1]] if (len(pts) - 1) % paso else []),
            "largoRioKm": round(km[-1], 1), "ajustes": ajustes(con),
            "limites": {"distanciaMaxM": DISTANCIA_MAX_M, "separacionMinKm": SEPARACION_MIN_KM}}
