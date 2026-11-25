"""Riesgo para la salud por contacto con el agua del río, por tramo (para la ciudadanía).

Los nodos miden pH, conductividad, turbidez, color, temperatura y nivel. NO miden bacterias del drenaje
(E. coli, coliformes), metales pesados ni compuestos de tintes y solventes, que son justo lo que enferma.
Por eso el riesgo nunca baja de «alto»: el Alto Atoyac recibe aguas residuales municipales e industriales
sin tratar y bañarse en él no es seguro en ningún tramo, aunque el semáforo marque «bien». Las lecturas
fuera de rango y los casos recientes del tramo (descargas, crecidas) solo suben el nivel y explican por qué.
"""
from . import motor

H = 3600 * 1000
D = 24 * H

NIVELES = {
    "alto": {"orden": 1, "etiqueta": "Riesgo alto",
             "resumen": "No te metas al agua: trae drenaje y químicos aunque los sensores marquen normal."},
    "muy_alto": {"orden": 2, "etiqueta": "Riesgo muy alto",
                 "resumen": "Evita cualquier contacto con el agua: hay valores fuera de lo normal."},
    "extremo": {"orden": 3, "etiqueta": "Riesgo extremo",
                "resumen": "Peligro: aléjate de la orilla y no dejes que niños ni animales toquen el agua."},
}
NO_MIDE = [
    "Bacterias del drenaje (E. coli y coliformes), que causan diarrea, vómito e infecciones de piel y oídos.",
    "Metales pesados como cromo y plomo, y compuestos de tintes y solventes de la industria textil.",
]
RECOMENDACIONES = [
    "No te bañes, no nades ni juegues en el río ni en las barrancas, aunque el agua se vea limpia.",
    "No bebas el agua ni la uses para cocinar, lavar trastes, dar de beber a animales o regar hortalizas.",
    "Si tuviste contacto, lávate cuanto antes con agua limpia y jabón, y no te frotes los ojos.",
    "Acude a tu centro de salud si en los días siguientes tienes ronchas, ardor en ojos o piel, diarrea, vómito o fiebre.",
    "Después de una lluvia fuerte aléjate de la orilla: la corriente crece rápido y el drenaje se desborda.",
]


def _razon(k, v, estado, u):
    """Frase para la ciudadanía sobre un parámetro fuera de lo normal."""
    if k == "ph":
        tipo = "ácida" if v < (u["ph"]["min"] + u["ph"]["max"]) / 2 else "alcalina"
        return f"pH {v:.1f}: agua {tipo}; irrita la piel y los ojos."
    if k == "cond":
        return f"Conductividad de {v:,.0f} µS/cm: muchas sales y químicos disueltos, típico de descargas industriales."
    if k == "turb":
        return f"Turbidez de {v:,.0f} NTU: lodo y drenaje arrastrados; con ellos viajan más bacterias."
    if k == "color":
        return f"Color de {v:.1f} m⁻¹ a 620 nm: tintes textiles en el agua; algunos irritan la piel."
    if k == "nivel":
        return f"Nivel de {v:.2f} m: crecida; la corriente es peligrosa y el drenaje se desborda."
    return None


def _hace(ms):
    horas = max(1, round(ms / H))
    return f"hace {horas} h" if horas < 48 else f"hace {round(horas / 24)} días"


def calcular(con, ahora_ms, dias_sin_visita=7):
    u = motor.umbrales(con)
    tramos = con.execute("""SELECT t.id, t.nombre, t.desde, t.hasta FROM tramos t JOIN nodos n ON n.id = t.desde
                            ORDER BY n.orden""").fetchall()
    casos = con.execute("""SELECT tipo, tramo, nodo, COALESCE(evento_t, t) AS t FROM casos
                           WHERE tipo IN ('descarga', 'inundacion') AND COALESCE(evento_t, t) >= ?""",
                        (ahora_ms - 3 * D,)).fetchall()
    salida = []
    for tr in tramos:
        lectura = con.execute("SELECT t, ph, cond, turb, color, temp, nivel FROM lecturas WHERE nodo = ? ORDER BY t DESC LIMIT 1",
                              (tr["hasta"],)).fetchone()
        nivel, razones = "alto", []
        vieja = False
        if lectura:
            vieja = ahora_ms - lectura["t"] > dias_sin_visita * D
            for k in ("ph", "cond", "turb", "color", "nivel"):
                v = lectura[k]
                estado = motor.estado_param(k, v, u) if v is not None else "ok"
                if estado == "ok":
                    continue
                razon = _razon(k, v, estado, u)
                if razon:
                    razones.append(razon)
                nivel = "extremo" if estado == "crit" else max(nivel, "muy_alto", key=lambda x: NIVELES[x]["orden"])
        for c in casos:
            if c["tramo"] != tr["id"] and c["nodo"] not in (tr["desde"], tr["hasta"]):
                continue
            edad = ahora_ms - c["t"]
            que = "Descarga detectada" if c["tipo"] == "descarga" else "Crecida registrada"
            razones.append(f"{que} {_hace(edad)} en este tramo.")
            nivel = "extremo" if edad <= D else max(nivel, "muy_alto", key=lambda x: NIVELES[x]["orden"])
        if vieja:
            razones.append(f"El nodo no se ha visitado desde hace {round((ahora_ms - lectura['t']) / D)} días: "
                           "no se puede descartar un riesgo mayor.")
        elif not lectura:
            razones.append("Este tramo todavía no tiene lecturas.")
        if not razones:
            razones.append("Los sensores marcan valores normales, pero no miden bacterias ni metales: el agua sigue sin ser apta.")
        salida.append({
            "tramo": tr["id"], "nombre": tr["nombre"], "nodo": tr["hasta"], "nivel": nivel, **NIVELES[nivel],
            "apto": False, "razones": razones, "vieja": vieja,
            "lectura": dict(lectura) if lectura else None,
        })
    peor = max((s["nivel"] for s in salida), key=lambda x: NIVELES[x]["orden"], default="alto")
    return {
        "t": ahora_ms, "apto": False, "peor": peor,
        "mensaje": "No es seguro bañarse en ningún tramo del Alto Atoyac.",
        "noMide": NO_MIDE, "recomendaciones": RECOMENDACIONES,
        "niveles": {k: {"etiqueta": v["etiqueta"], "resumen": v["resumen"], "orden": v["orden"]} for k, v in NIVELES.items()},
        "tramos": salida,
    }
