"""Motor de análisis de Vigía Atoyac (versión servidor de js/engine.js).

Los nodos no tienen internet: guardan en microSD y Protección Civil descarga el archivo
en su visita. Por eso el análisis es POR LOTE: al subir un archivo se revisan todas sus
lecturas, se encuentran los eventos con su hora real y se abren los casos, aunque el
evento haya ocurrido días antes.

  detecta   -> z-score robusto (mediana y MAD) contra las últimas lecturas normales
  confirma  -> cruza con el nodo de aguas arriba y con los reportes ciudadanos cercanos. Dos anomalías en nodos
               distintos son la misma descarga solo si la diferencia de hora cabe en lo que tarda el agua en
               recorrer los km de cauce que hay entre ellos (ver ventana_transito)
  actúa     -> abre un caso con folio y lo asigna a la dependencia que corresponde
"""
import json
import math
from collections import deque
from datetime import datetime, timedelta, timezone

from .db import ahora, leer_ajuste, siguiente, transaccion

TZ = timezone(timedelta(hours=-6))            # Zona Centro (sin horario de verano desde 2022)
H = 3600 * 1000
VENTANA, MIN_BASE, Z_MIN = 36, 12, 3.5        # lecturas de referencia y umbral del z-score
MAX_RACHA = 180                               # tras tantas lecturas "anómalas" seguidas se acepta como nueva normalidad
SEPARACION_MS = 30 * 60 * 1000                # más de 30 min sin anomalía = otro evento
SUBIDA_CRECIDA_M = 0.5                        # subida de nivel que explica por sí sola un pico de turbidez
# Tiempo de tránsito: el agua tarda en ir de un nodo al siguiente según los km de cauce entre ellos.
# Velocidad del Atoyac: lenta en estiaje, rápida en crecida. Calibrar con aforos de Conagua o midiendo
# cuánto tarda una misma descarga en aparecer en dos nodos.
VEL_MIN_MS, VEL_MAX_MS = 0.3, 2.0             # metros por segundo
MARGEN_TRANSITO_MS = 30 * 60 * 1000           # tolerancia: el nodo guarda una lectura cada 10 min
MISMO_SITIO_MS = 3 * H                        # dos anomalías del mismo nodo con menos de esto = el mismo evento
RADIO_FUSION_KM, VENTANA_FUSION_MS = 2.5, 6 * H
PARAMS_ANOM = ("ph", "cond", "turb", "color")
ESTACION = ("caudal", "turb_sal", "color_sal", "cond_sal", "ph_sal", "lodos", "dp_filtro", "solar")   # columnas de la estación piloto
NOMBRE = {"ph": "pH", "cond": "conductividad", "turb": "turbidez", "color": "color a 620 nm"}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

UMBRALES_DEF = {
    "ph": {"min": 6.5, "max": 8.5, "critMin": 6.0, "critMax": 9.0},
    "cond": {"warn": 1500, "crit": 2500},
    "turb": {"warn": 100, "crit": 250},
    "color": {"warn": 3.0, "crit": 6.0},
    "temp": {"warn": 25, "crit": 30},
    "nivel": {"warn": 2.0, "crit": 2.8},
}
TIPOS_CASO = {
    "descarga": {"dep": "ambiental", "label": "Posible descarga ilegal"},
    "basura": {"dep": "limpia", "label": "Basura acumulada"},
    "inundacion": {"dep": "pc", "label": "Riesgo de inundación"},
    "recurrente": {"dep": "brigadas", "label": "Punto crítico recurrente"},
}
DEPENDENCIAS = {"ambiental": "Autoridad ambiental", "limpia": "Limpia municipal", "pc": "Protección Civil", "brigadas": "Brigadas ciudadanas"}
CATEGORIAS = ["Agua de color", "Espuma", "Basura", "Descarga de tubería", "Mal olor", "Animal muerto"]
CATS_DESCARGA = {"Agua de color", "Espuma", "Descarga de tubería", "Mal olor", "Animal muerto"}
ESTADOS_CASO = ["Nuevo", "En atención", "Inspección programada", "Cerrado"]
ESTADOS_REPORTE = ["Recibido", "Validado", "En atención", "Atendido", "Descartado"]


# ---------- Utilidades ----------
def fecha(ms: int) -> str:
    d = datetime.fromtimestamp(ms / 1000, TZ)                  # mismo formato que muestra la web (es-MX)
    return f"{d.day} {MESES[d.month - 1]}, {(d.hour % 12) or 12:02d}:{d:%M} {'a.m.' if d.hour < 12 else 'p.m.'}"


def mediana(a):
    s = sorted(a)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def mad(a):
    m = mediana(a)
    return mediana([abs(x - m) for x in a])


def km(a_lat, a_lng, b_lat, b_lng) -> float:
    r = 6371.0
    d_lat, d_lng = math.radians(b_lat - a_lat), math.radians(b_lng - a_lng)
    h = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(d_lng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def largo_km(puntos) -> float:
    """Largo de una polilínea [[lat, lng], ...] en km (el cauce de un tramo)."""
    return sum(km(*puntos[i], *puntos[i + 1]) for i in range(len(puntos) - 1))


def tiempo_recorrido(km_rio: float) -> tuple:
    """(más rápido, más lento) en ms que tarda el agua en recorrer km_rio kilómetros de cauce."""
    metros = km_rio * 1000
    return metros / VEL_MAX_MS * 1000, metros / VEL_MIN_MS * 1000


def ventana_transito(km_rio: float) -> tuple:
    """Retraso aceptable (mínimo, máximo) en ms entre que una descarga pasa por un nodo y llega a otro
    km_rio kilómetros río abajo. Incluye un margen por la resolución del muestreo."""
    rapido, lento = tiempo_recorrido(km_rio)
    return max(0, rapido - MARGEN_TRANSITO_MS), lento + MARGEN_TRANSITO_MS


def km_por_rio(con) -> dict:
    """Kilómetros de cauce desde el primer nodo hasta cada nodo, siguiendo los tramos (línea recta si falta uno)."""
    nodos = con.execute("SELECT id, lat, lng FROM nodos ORDER BY orden").fetchall()
    tramos = {(f["desde"], f["hasta"]): json.loads(f["puntos"]) for f in con.execute("SELECT desde, hasta, puntos FROM tramos")}
    acumulado, total = {}, 0.0
    for i, n in enumerate(nodos):
        if i:
            anterior = nodos[i - 1]
            puntos = tramos.get((anterior["id"], n["id"]))
            total += largo_km(puntos) if puntos else km(anterior["lat"], anterior["lng"], n["lat"], n["lng"])
        acumulado[n["id"]] = total
    return acumulado


def umbrales(con) -> dict:
    guardados = leer_ajuste(con, "umbrales", {})
    return {k: {**v, **guardados.get(k, {})} for k, v in UMBRALES_DEF.items()}


# ---------- Semáforo ----------
def estado_param(k, v, u) -> str:
    p = u.get(k)
    if v is None or not p:
        return "ok"
    if k == "ph":
        if v < p["critMin"] or v > p["critMax"]:
            return "crit"
        return "warn" if v < p["min"] or v > p["max"] else "ok"
    return "crit" if v >= p["crit"] else "warn" if v >= p["warn"] else "ok"


def estado_lectura(r, u) -> str:
    orden = {"ok": 0, "warn": 1, "crit": 2}
    return max((estado_param(k, r.get(k), u) for k in u), key=orden.get)


# ---------- Índice de calidad del agua (0 = muy mala, 100 = buena) ----------
# Cada parámetro da un puntaje: 100 en agua limpia, 50 justo en su umbral de atención y 0 un poco arriba del
# crítico. El índice mezcla el promedio ponderado con el peor parámetro: un solo valor malo no se esconde.
PESOS_INDICE = {"cond": 0.25, "turb": 0.25, "color": 0.30, "ph": 0.20}


def _interpola(v, puntos):
    """Línea quebrada [(x, y), ...] con x creciente."""
    if v <= puntos[0][0]:
        return puntos[0][1]
    for (x0, y0), (x1, y1) in zip(puntos, puntos[1:]):
        if v <= x1:
            return y0 + (y1 - y0) * (v - x0) / (x1 - x0)
    return puntos[-1][1]


def puntaje(k, v, u) -> float:
    p = u[k]
    if k == "ph":
        medio, mitad = (p["min"] + p["max"]) / 2, (p["max"] - p["min"]) / 2
        lejos = max(p["critMax"] - medio, medio - p["critMin"])
        return _interpola(abs(v - medio), [(0.3 * mitad, 100), (mitad, 60), (lejos, 20), (lejos + 0.5, 0)])
    return _interpola(v, [(p["warn"] / (4 if k == "turb" else 3), 100), (p["warn"], 50), (p["crit"] * 1.2, 0)])


def indice_calidad(r, u):
    """Índice 0–100 de una lectura (o de las medianas de un día). None si faltan datos."""
    q = {k: puntaje(k, r[k], u) for k in PESOS_INDICE if r.get(k) is not None}
    if len(q) < 3:
        return None
    ponderado = sum(PESOS_INDICE[k] * v for k, v in q.items()) / sum(PESOS_INDICE[k] for k in q)
    return round(0.6 * ponderado + 0.4 * min(q.values()))


def dia_local(t: int) -> int:
    return (t - 6 * H) // (24 * H)


def recalcular_indice(con, nodo_id, desde=None, hasta=None) -> int:
    """Índice diario de los tramos que terminan en `nodo_id` (el semáforo del tramo es el nodo de abajo),
    con la mediana de las lecturas de cada día. Devuelve cuántos días se guardaron."""
    tramos = [f["id"] for f in con.execute("SELECT id FROM tramos WHERE hasta = ?", (nodo_id,))]
    if not tramos:
        return 0
    u = umbrales(con)
    filtro, args = "", [nodo_id]
    if desde is not None:
        inicio = dia_local(desde) * 24 * H + 6 * H                          # medianoche (hora del centro) del primer día
        fin = (dia_local(hasta if hasta is not None else ahora()) + 1) * 24 * H + 6 * H
        filtro, args = " AND t >= ? AND t < ?", [nodo_id, inicio, fin]
    filas = con.execute(f"SELECT t, ph, cond, turb, color FROM lecturas WHERE nodo = ?{filtro} ORDER BY t", args).fetchall()
    por_dia = {}
    for f in filas:
        por_dia.setdefault(dia_local(f["t"]), []).append(f)
    guardados = 0
    for dia, lista in por_dia.items():
        if len(lista) < 24:                                    # menos de 4 horas de datos: no alcanza para el día
            continue
        medianas = {k: mediana([x[k] for x in lista if x[k] is not None]) for k in PESOS_INDICE if any(x[k] is not None for x in lista)}
        v = indice_calidad(medianas, u)
        if v is None:
            continue
        t_dia = dia * 24 * H + 6 * H
        for tr in tramos:
            con.execute("DELETE FROM indice_diario WHERE tramo = ? AND t = ?", (tr, t_dia))
            con.execute("INSERT INTO indice_diario (tramo, t, v) VALUES (?, ?, ?)", (tr, t_dia, v))
        guardados += 1
    return guardados


# ---------- Anomalías ----------
def detectar(base, r) -> list:
    """Parámetros de la lectura `r` que se salen de lo normal del sitio.
    Además del z-score se pide un cambio real, para no alarmar por ruido del sensor."""
    fuera = []
    for k in PARAMS_ANOM:
        v = r.get(k)
        serie = [x[k] for x in base if x.get(k) is not None]
        if v is None or len(serie) < MIN_BASE:
            continue
        m = mediana(serie)
        z = 0.6745 * (v - m) / (mad(serie) or 1e-6)
        dif = abs(v - m)
        grande = dif >= 0.5 if k == "ph" else dif >= abs(m) * (0.2 if k == "cond" else 0.4)
        if abs(z) >= Z_MIN and grande:
            fuera.append(k)
    return fuera


def _referencia(base) -> dict:
    """Valor normal de cada parámetro justo antes del evento (mediana de la ventana)."""
    ref = {}
    for k in PARAMS_ANOM:
        serie = [x[k] for x in base if x.get(k) is not None]
        ref[k] = round(mediana(serie), 2) if serie else None
    return ref


def clasificar(pico, base) -> tuple:
    """Huella: tipo probable de descarga según cómo cambian juntos color, conductividad y turbidez."""
    def veces(k):
        return (pico.get(k) or 0) / base[k] if base.get(k) else 1
    if veces("color") >= 2 and (veces("cond") >= 1.5 or (pico.get("ph") or 7) > 8.8):
        return "Textil", "Color y conductividad altos a la vez (tintes y sales)."
    if veces("turb") >= 2 and veces("color") < 1.6:
        return "Doméstica", "Sube la turbidez sin cambio fuerte de color."
    return "Otra (industrial)", "Cambio de pH o conductividad sin patrón textil ni doméstico."


def confianza(n_params, n_reportes) -> float:
    return min(0.97, round(0.5 + 0.1 * min(n_params, 3) + 0.1 * min(n_reportes, 3), 2))


# ---------- Casos ----------
_COLS = ("id", "tipo", "dep", "estado", "prioridad", "t", "cerrado", "tramo", "nodo", "barrera", "lat", "lng", "estimado",
         "confianza", "muestra", "resumen", "lab", "pico", "reportes", "historial", "confirmado_en", "auto",
         "evento_t", "evento_fin", "evento", "loc_pendiente")
_JSON = {"pico": None, "reportes": [], "historial": [], "confirmado_en": [], "evento": None}


def leer_caso(con, caso_id):
    f = con.execute("SELECT * FROM casos WHERE id = ?", (caso_id,)).fetchone()
    if not f:
        return None
    d = dict(f)
    for k, vacio in _JSON.items():
        d[k] = json.loads(d[k]) if d[k] else (list(vacio) if isinstance(vacio, list) else vacio)
    return d


def guardar_caso(con, d) -> None:
    vals = [json.dumps(d.get(k), ensure_ascii=False) if k in _JSON and d.get(k) is not None else d.get(k) for k in _COLS]
    for i, k in enumerate(_COLS):                       # columnas JSON de lista nunca quedan en NULL
        if k in _JSON and vals[i] is None and isinstance(_JSON[k], list):
            vals[i] = "[]"
    con.execute(f"INSERT OR REPLACE INTO casos ({', '.join(_COLS)}) VALUES ({', '.join('?' * len(_COLS))})", vals)


def paso(quien, que, t=None) -> dict:
    return {"t": t or ahora(), "who": quien, "what": que}


def nuevo_caso(con, tipo, **campos) -> dict:
    folio = f"VA-{datetime.now(TZ).year}-{siguiente(con, 'caso', 20):04d}"
    d = {k: None for k in _COLS}
    d.update({"id": folio, "tipo": tipo, "dep": TIPOS_CASO[tipo]["dep"], "estado": "Nuevo", "prioridad": "Media", "t": ahora(),
              "reportes": [], "historial": [], "confirmado_en": [], "auto": 1, "loc_pendiente": 0})
    d.update(campos)
    guardar_caso(con, d)
    return d


def notificar(con, usuario_id, titulo, texto, caso=None, reporte=None) -> None:
    """Aviso para la app de quien reportó (la app lo muestra como notificación push)."""
    if usuario_id:
        con.execute("INSERT INTO notificaciones (usuario_id, t, titulo, texto, caso, reporte) VALUES (?, ?, ?, ?, ?, ?)",
                    (usuario_id, ahora(), titulo, texto, caso, reporte))


# ---------- Localización: ¿en qué tramo entró la descarga? ----------
def localizar(con, nodo_id, t0, t1) -> dict:
    """Sube de nodo en nodo mientras el de aguas arriba haya tenido la anomalía ANTES, con el adelanto que
    corresponde a los km de cauce entre ambos (el agua no llega al instante ni tarda un día).
    Si el de arriba aún no se ha descargado hasta esa hora, el tramo queda "por confirmar"."""
    nodos = [dict(f) for f in con.execute("SELECT id, nombre, lat, lng FROM nodos ORDER BY orden")]
    i = next(k for k, n in enumerate(nodos) if n["id"] == nodo_id)
    dist = km_por_rio(con)
    pendiente = False
    while i > 0:
        arriba = nodos[i - 1]["id"]
        # Si la descarga entró más arriba, pasó por este nodo entre `lento` y `rapido` antes de llegar a nodo_id
        rapido, lento = ventana_transito(dist[nodo_id] - dist[arriba])
        paso_antes = con.execute("SELECT 1 FROM lecturas WHERE nodo = ? AND t BETWEEN ? AND ? AND anom <> '[]' LIMIT 1",
                                 (arriba, t0 - lento, t0 - rapido)).fetchone()
        if paso_antes:
            i -= 1
            continue
        hasta = con.execute("SELECT MAX(t) AS m FROM lecturas WHERE nodo = ?", (arriba,)).fetchone()["m"]
        if hasta is None or hasta < t0 - rapido:
            pendiente = True                                      # aún no hay datos de ese nodo para esa hora
        break
    origen = nodos[i]
    if i == 0:
        return {"origen": origen["id"], "tramo": None, "pendiente": False, "lat": origen["lat"], "lng": origen["lng"],
                "texto": f"Aguas arriba de {origen['nombre']}, antes del primer nodo de la red"}
    tr = con.execute("SELECT id, puntos FROM tramos WHERE desde = ? AND hasta = ?", (nodos[i - 1]["id"], origen["id"])).fetchone()
    puntos = json.loads(tr["puntos"])
    medio = puntos[len(puntos) // 2]
    texto = f"Entre {nodos[i - 1]['nombre']} y {origen['nombre']} ({largo_km(puntos):.1f} km de cauce)"
    if pendiente:
        texto += f" (por confirmar al descargar {nodos[i - 1]['id']})"
    return {"origen": origen["id"], "tramo": tr["id"], "pendiente": pendiente, "lat": medio[0], "lng": medio[1], "texto": texto}


def _reportes_cercanos(con, puntos, t_evento) -> list:
    filas = con.execute("SELECT * FROM reportes WHERE estado <> 'Descartado' AND t BETWEEN ? AND ?",
                        (t_evento - VENTANA_FUSION_MS, t_evento + VENTANA_FUSION_MS)).fetchall()
    return [f for f in filas if f["cat"] in CATS_DESCARGA
            and any(km(p[0], p[1], f["lat"], f["lng"]) <= RADIO_FUSION_KM for p in puntos)]


def resolver_descarga(con, d) -> dict:
    """Recalcula, con lo que hoy hay en la base, tramo, reportes vinculados, confianza, tipo y resumen.
    Se llama al crear el caso y cada vez que llega información nueva (otro nodo, otro reporte)."""
    loc = localizar(con, d["nodo"], d["evento_t"], d["evento_fin"])
    if loc["origen"] != d["nodo"]:
        d["confirmado_en"] = sorted(set(d["confirmado_en"]) | {d["nodo"]})
        d["nodo"] = loc["origen"]
    nodo = con.execute("SELECT nombre, lat, lng FROM nodos WHERE id = ?", (d["nodo"],)).fetchone()
    d.update(tramo=loc["tramo"], lat=loc["lat"], lng=loc["lng"], loc_pendiente=int(loc["pendiente"]))

    nuevos = [r for r in _reportes_cercanos(con, [(loc["lat"], loc["lng"]), (nodo["lat"], nodo["lng"])], d["evento_t"])
              if r["id"] not in d["reportes"]]
    for r in nuevos:
        if r["estado"] == "Recibido":
            con.execute("UPDATE reportes SET estado = 'Validado' WHERE id = ?", (r["id"],))
        notificar(con, r["usuario_id"], "Tu reporte coincide con los sensores",
                  f"Lo que reportaste ({r['cat'].lower()}) coincide con una medición del río. Se abrió el caso {d['id']}.",
                  caso=d["id"], reporte=r["id"])
    d["reportes"] = d["reportes"] + [r["id"] for r in nuevos]

    ev = d["evento"]
    d["confianza"] = confianza(len(ev["params"]), len(d["reportes"]))
    d["estimado"], porque = clasificar(d["pico"], ev["base"])
    d["prioridad"] = "Alta" if d["confianza"] >= 0.75 or ev.get("critico") else "Media"
    params = ", ".join(NOMBRE[k] for k in PARAMS_ANOM if k in ev["params"])
    n = len(d["reportes"])
    d["resumen"] = (f"Cambio brusco de {params} en {nodo['nombre']} ({fecha(d['evento_t'])}). {loc['texto']}. {porque}"
                    + (f" Coincide con {n} reporte{'s' if n != 1 else ''} de la app cerca del tramo." if n else ""))
    return {"loc": loc, "nuevos": nuevos}


def _descarga_relacionada(con, nodo_id, t0):
    """Caso abierto que sea la misma descarga: en el mismo nodo, a menos de MISMO_SITIO_MS; en otro nodo, solo si
    el retraso entre las dos anomalías cabe en lo que tarda el agua en recorrer el cauce entre ellos (y el nodo
    de abajo la ve después). Si hay varios, el que mejor encaja con el tiempo de recorrido esperado."""
    dist = km_por_rio(con)
    mejor, desvio_min = None, None
    for f in con.execute("SELECT id, nodo, evento_t FROM casos WHERE tipo = 'descarga' AND auto = 1 AND estado <> 'Cerrado'").fetchall():
        if f["evento_t"] is None:
            continue
        if f["nodo"] == nodo_id:
            desvio = abs(t0 - f["evento_t"])
            if desvio > MISMO_SITIO_MS:
                continue
        else:
            if f["nodo"] not in dist or nodo_id not in dist:
                continue
            km_entre = dist[nodo_id] - dist[f["nodo"]]                # > 0: el nodo nuevo está río abajo del caso
            retraso = t0 - f["evento_t"] if km_entre > 0 else f["evento_t"] - t0
            rapido, lento = ventana_transito(abs(km_entre))
            if not rapido <= retraso <= lento:
                continue
            desvio = abs(retraso - (rapido + lento) / 2)
        if desvio_min is None or desvio < desvio_min:
            mejor, desvio_min = f["id"], desvio
    return leer_caso(con, mejor) if mejor else None


def procesar_evento(con, nodo, ev, quien) -> tuple:
    """Convierte un evento anómalo en caso. Devuelve (caso, es_nuevo)."""
    params = ", ".join(NOMBRE[k] for k in PARAMS_ANOM if k in ev["params"])
    datos_evento = {"params": sorted(ev["params"]), "base": ev["base"], "critico": ev["critico"], "lecturas": ev["n"]}
    d = _descarga_relacionada(con, nodo["id"], ev["t0"])
    if d:
        # La misma descarga vista en otro nodo (o de nuevo en el mismo): se une al caso que ya existe
        orden = {f["id"]: f["orden"] for f in con.execute("SELECT id, orden FROM nodos")}
        d["evento"]["params"] = sorted(set(d["evento"]["params"]) | ev["params"])
        d["evento"]["critico"] = d["evento"].get("critico") or ev["critico"]
        if nodo["id"] == d["nodo"]:
            d["evento_t"], d["evento_fin"] = min(d["evento_t"], ev["t0"]), max(d["evento_fin"], ev["t1"])
            for k, v in ev["pico"].items():
                a = d["pico"].get(k)
                d["pico"][k] = v if a is None or (abs(v - 7) > abs(a - 7) if k == "ph" else v > a) else a
            d["historial"].append(paso("Nodo " + nodo["id"], f"Otra anomalía del mismo evento ({params})", ev["t0"]))
        elif orden[nodo["id"]] < orden[d["nodo"]]:
            d["confirmado_en"] = sorted(set(d["confirmado_en"]) | {d["nodo"]})
            d.update(nodo=nodo["id"], evento_t=ev["t0"], evento_fin=ev["t1"], pico=ev["pico"])
            d["evento"]["base"] = ev["base"]
            d["historial"].append(paso("Sistema", f"Al descargar {nodo['id']} · {nodo['nombre']} apareció la misma anomalía antes "
                                                  f"({fecha(ev['t0'])}): el origen está más arriba"))
        else:
            d["confirmado_en"] = sorted(set(d["confirmado_en"]) | {nodo["id"]})
            d["historial"].append(paso("Nodo " + nodo["id"], f"La anomalía llegó aguas abajo a {nodo['nombre']}", ev["t0"]))
        if ev["muestra"] and not d["muestra"]:
            d["muestra"] = ev["muestra"]
            d["historial"].append(paso("Nodo " + nodo["id"], f"El carrusel tomó la muestra {ev['muestra']}", ev["t0"]))
        res = resolver_descarga(con, d)
        d["historial"].append(paso("Sistema", f"Tramo probable: {res['loc']['texto']}"))
        guardar_caso(con, d)
        return d, False

    d = nuevo_caso(con, "descarga", nodo=nodo["id"], evento_t=ev["t0"], evento_fin=ev["t1"], pico=ev["pico"],
                   muestra=ev["muestra"], evento=datos_evento)
    d["historial"].append(paso("Nodo " + nodo["id"], f"Anomalía registrada sin internet ({params})", ev["t0"]))
    if ev["muestra"]:
        d["historial"].append(paso("Nodo " + nodo["id"], f"El carrusel tomó la muestra {ev['muestra']}", ev["t0"]))
    d["historial"].append(paso(quien, f"Datos de {nodo['id']} descargados en la visita y subidos a la plataforma"))
    res = resolver_descarga(con, d)
    if d["reportes"]:
        d["historial"].append(paso("Sistema", f"Cruce con {len(d['reportes'])} reporte(s) de la app: confianza {round(d['confianza'] * 100)}%"))
    d["historial"].append(paso("Sistema", f"Tramo probable: {res['loc']['texto']}. Caso asignado a Autoridad ambiental"))
    guardar_caso(con, d)
    return d, True


def revisar_descargas_abiertas(con, solo_pendientes=True) -> list:
    """Tras un lote o un reporte nuevo: ¿cambia el tramo o la evidencia de algún caso abierto?"""
    cambiados = []
    filtro = "AND loc_pendiente = 1" if solo_pendientes else ""
    for f in con.execute(f"SELECT id FROM casos WHERE tipo = 'descarga' AND auto = 1 AND estado <> 'Cerrado' {filtro}").fetchall():
        d = leer_caso(con, f["id"])
        antes = (d["tramo"], d["loc_pendiente"], d["nodo"])
        res = resolver_descarga(con, d)
        cambio_loc = antes != (d["tramo"], d["loc_pendiente"], d["nodo"])
        if not cambio_loc and not res["nuevos"]:
            continue
        if cambio_loc:
            verbo = "Tramo confirmado" if not d["loc_pendiente"] else "Tramo actualizado"
            d["historial"].append(paso("Sistema", f"{verbo} con los datos del nodo vecino: {res['loc']['texto']}"))
        if res["nuevos"]:
            n = len(res["nuevos"])
            d["historial"].append(paso("Sistema", f"{n} reporte{'s' if n != 1 else ''} de la app coincide{'n' if n != 1 else ''} "
                                                  f"con el evento: confianza {round(d['confianza'] * 100)}%"))
        guardar_caso(con, d)
        cambiados.append(d)
    return cambiados


def caso_inundacion(con, lugar_id, nombre, lat, lng, nivel, t_evento, es_barrera=False):
    campo = "barrera" if es_barrera else "nodo"
    ya = con.execute(f"""SELECT 1 FROM casos WHERE tipo = 'inundacion' AND estado <> 'Cerrado' AND {campo} = ?
                         AND ABS(COALESCE(evento_t, t) - ?) <= ?""", (lugar_id, t_evento, 6 * H)).fetchone()
    if ya:
        return None
    origen = ("Barrera " if es_barrera else "Nodo ") + lugar_id
    return nuevo_caso(
        con, "inundacion", prioridad="Alta", lat=lat, lng=lng, estimado="Nivel alto", confianza=0.95, evento_t=t_evento,
        **{campo: lugar_id},
        resumen=f"El nivel del agua llegó a {nivel:.2f} m en {nombre} ({fecha(t_evento)}). "
                "La alarma local (luz y sirena) avisó en el momento a quienes viven cerca.",
        historial=[paso(origen, f"Nivel {nivel:.2f} m: alarma local activada", t_evento),
                   paso("Sistema", "Caso asignado a Protección Civil; aviso a vecinos suscritos en la app")])


def caso_barrera_llena(con, barrera):
    """Barrera al 90% o más y sin caso abierto: avisa a Limpia municipal."""
    if barrera["llenado"] < 90 or con.execute(
            "SELECT 1 FROM casos WHERE tipo = 'basura' AND barrera = ? AND estado <> 'Cerrado'", (barrera["id"],)).fetchone():
        return None
    return nuevo_caso(
        con, "basura", prioridad="Alta", barrera=barrera["id"], lat=barrera["lat"], lng=barrera["lng"],
        estimado="Barrera llena", confianza=0.97,
        resumen=f"La barrera de {barrera['nombre']} llegó a {barrera['llenado']:.0f}% de llenado. Se envió la ubicación a la cuadrilla.",
        historial=[paso("Barrera " + barrera["id"], f"Llenado {barrera['llenado']:.0f}%"),
                   paso("Sistema", "Caso asignado a Limpia municipal con ruta de recolección")])


def agrupar_basura(con, reporte):
    """Tres o más reportes de basura a menos de 500 m en 7 días abren un caso para Limpia municipal."""
    if reporte["cat"] != "Basura":
        return None
    desde = reporte["t"] - 7 * 24 * H
    cerca = [f for f in con.execute("SELECT id, lat, lng FROM reportes WHERE cat = 'Basura' AND estado <> 'Descartado' AND t >= ?", (desde,))
             if km(reporte["lat"], reporte["lng"], f["lat"], f["lng"]) <= 0.5]
    if len(cerca) < 3:
        return None
    for f in con.execute("SELECT lat, lng FROM casos WHERE tipo = 'basura' AND estado <> 'Cerrado' AND lat IS NOT NULL"):
        if km(reporte["lat"], reporte["lng"], f["lat"], f["lng"]) <= 0.5:
            return None
    return nuevo_caso(
        con, "basura", lat=reporte["lat"], lng=reporte["lng"], estimado="Residuo sólido",
        confianza=min(0.95, 0.75 + 0.04 * len(cerca)), reportes=[f["id"] for f in cerca],
        resumen=f"{len(cerca)} reportes con basura acumulada a menos de 500 m entre sí en los últimos 7 días.",
        historial=[paso("Sistema", f"Agrupamiento de {len(cerca)} reportes de la app; caso asignado a Limpia municipal")])


# ---------- Ingesta de un lote ----------
def ingerir(con, nodo_id, filas, quien, usuario_id=None, archivo="", integridad="sin_huella", invalidas=0, checklist=None) -> dict:
    """Guarda las lecturas nuevas de un nodo, detecta eventos y abre o actualiza casos.
    `filas`: lista de dict {t, ph, cond, turb, color, temp, nivel, bateria?, muestra?} ordenada por t."""
    nodo = con.execute("SELECT * FROM nodos WHERE id = ?", (nodo_id,)).fetchone()
    if not nodo:
        raise ValueError("El nodo no existe.")
    checklist = checklist or {}
    u = umbrales(con)
    t_subida = ahora()
    creados, actualizados, eventos, nuevas = [], [], [], 0
    crecida = None

    with transaccion(con):
        lote = con.execute("INSERT INTO lotes (nodo, usuario_id, subido, archivo, filas, invalidas, integridad, checklist) VALUES (?,?,?,?,?,?,?,?)",
                           (nodo_id, usuario_id, t_subida, archivo, len(filas), invalidas, integridad, json.dumps(checklist))).lastrowid
        if filas:
            t_min, t_max = filas[0]["t"], filas[-1]["t"]
            ya = {f["t"] for f in con.execute("SELECT t FROM lecturas WHERE nodo = ? AND t BETWEEN ? AND ?", (nodo_id, t_min, t_max))}
            previas = con.execute("""SELECT ph, cond, turb, color, nivel FROM lecturas WHERE nodo = ? AND t < ? AND anom = '[]'
                                     ORDER BY t DESC LIMIT ?""", (nodo_id, t_min, VENTANA)).fetchall()
            base = deque((dict(f) for f in reversed(previas)), maxlen=VENTANA)
            actual, racha = None, 0
            for r in filas:
                if r["t"] in ya:
                    continue
                fuera = detectar(base, r)
                if not fuera:
                    racha = 0
                elif racha >= MAX_RACHA:
                    fuera = []                              # cambio permanente: pasa a ser la referencia
                if fuera:
                    racha += 1
                    if not actual or r["t"] - actual["t1"] > SEPARACION_MS:
                        niveles = [x["nivel"] for x in base if x.get("nivel") is not None]
                        actual = {"t0": r["t"], "t1": r["t"], "params": set(), "pico": {}, "muestra": None, "critico": False, "n": 0,
                                  "base": _referencia(base), "nivel_base": mediana(niveles) if niveles else None, "nivel_pico": None}
                        eventos.append(actual)
                    actual["t1"] = r["t"]
                    actual["n"] += 1
                    actual["params"] |= set(fuera)
                    actual["critico"] = actual["critico"] or estado_lectura(r, u) == "crit"
                    actual["muestra"] = actual["muestra"] or r.get("muestra") or None
                    if r.get("nivel") is not None:
                        actual["nivel_pico"] = max(actual["nivel_pico"] or 0, r["nivel"])
                    for k in PARAMS_ANOM:
                        v, a = r.get(k), actual["pico"].get(k)
                        if v is not None and (a is None or (abs(v - 7) > abs(a - 7) if k == "ph" else v > a)):
                            actual["pico"][k] = v
                else:
                    base.append(r)
                if crecida is None and estado_param("nivel", r.get("nivel"), u) == "crit":
                    crecida = r
                con.execute("""INSERT OR IGNORE INTO lecturas (nodo, t, ph, cond, turb, color, temp, nivel, anom, muestra, lote,
                                   caudal, turb_sal, color_sal, cond_sal, ph_sal, lodos, dp_filtro, solar)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (nodo_id, r["t"], r.get("ph"), r.get("cond"), r.get("turb"), r.get("color"), r.get("temp"), r.get("nivel"),
                             json.dumps(fuera), r.get("muestra") or None, lote) + tuple(r.get(k) for k in ESTACION))
                nuevas += 1

            bateria = next((r["bateria"] for r in reversed(filas) if r.get("bateria") is not None), None)
            if bateria is not None:
                con.execute("UPDATE nodos SET bateria = ? WHERE id = ?", (int(bateria), nodo_id))
        con.execute("UPDATE nodos SET ultima_descarga = ? WHERE id = ?", (t_subida, nodo_id))
        if checklist.get("calibracion"):
            con.execute("UPDATE nodos SET calibrado = ? WHERE id = ?", (t_subida, nodo_id))

        # Un evento cuenta si duró al menos dos lecturas o si el propio nodo tomó muestra
        firmes = [e for e in eventos if e["n"] >= 2 or e["muestra"]]
        # Si solo subió la turbidez y al mismo tiempo subió el nivel, es lodo arrastrado por la lluvia, no una descarga
        por_lluvia = [e for e in firmes if e["params"] <= {"turb"} and e["nivel_base"] is not None and e["nivel_pico"] is not None
                      and e["nivel_pico"] - e["nivel_base"] >= SUBIDA_CRECIDA_M]
        firmes = [e for e in firmes if e not in por_lluvia]
        for e in firmes:
            caso, es_nuevo = procesar_evento(con, nodo, e, quien)
            (creados if es_nuevo else actualizados).append(caso)
        if crecida:
            c = caso_inundacion(con, nodo_id, nodo["nombre"], nodo["lat"], nodo["lng"], crecida["nivel"], crecida["t"])
            if c:
                creados.append(c)
        if integridad.startswith("alterada"):
            # El archivo se guarda, pero los casos que salgan de él quedan marcados para revisión
            for c in creados:
                c["historial"].append(paso("Sistema", f"Advertencia: la huella digital del archivo no coincide desde la fila {integridad.split(':')[1]}. "
                                                      "Confirmar con la microSD original antes de usarlo como evidencia"))
                guardar_caso(con, c)
        ids = {c["id"] for c in creados + actualizados}
        actualizados += [c for c in revisar_descargas_abiertas(con) if c["id"] not in ids]

        if filas:
            recalcular_indice(con, nodo_id, filas[0]["t"], filas[-1]["t"])      # el índice diario del tramo se actualiza solo
        con.execute("UPDATE lotes SET nuevas = ?, desde = ?, hasta = ?, eventos = ?, casos = ? WHERE id = ?",
                    (nuevas, filas[0]["t"] if filas else None, filas[-1]["t"] if filas else None, len(firmes),
                     json.dumps([c["id"] for c in creados + actualizados]), lote))

    return {"lote": lote, "nodo": nodo_id, "filas": len(filas), "nuevas": nuevas, "duplicadas": len(filas) - nuevas,
            "invalidas": invalidas, "desde": filas[0]["t"] if filas else None, "hasta": filas[-1]["t"] if filas else None,
            "integridad": integridad, "eventos": len(firmes), "turbidez_por_lluvia": len(por_lluvia),
            "eventos_detalle": [{"t0": e["t0"], "t1": e["t1"], "params": sorted(e["params"]), "muestra": e["muestra"]} for e in firmes],
            "creados": creados, "actualizados": actualizados}
