"""Datos iniciales.

- Catálogo (siempre): nodos, tramos y barreras del piloto. Los nodos están sobre puentes del río Atoyac,
  los tramos siguen su cauce real y las barreras están sobre sus barrancas (js/cauce.js, de OpenStreetMap).
  N3 (Xoxtla) tiene además la estación piloto de tratamiento.
- Datos de demostración (solo con VA_DEMO=1): 90 días de telemetría de cada nodo y de la estación, las visitas
  de Protección Civil que la trajeron, reportes de la app, casos, vaciados de barreras, índice diario y bitácora.
  Son simulados (server/simulacion.py) con patrones reales del Alto Atoyac; no son mediciones del río.
"""
import hashlib
import json
import os
import random
import re
import secrets
import zlib
from datetime import datetime
from pathlib import Path

from . import motor
from . import simulacion as sim
from .db import DATOS, ahora, guardar_ajuste, leer_ajuste, transaccion
from .seguridad import crear_hash

H = 3600 * 1000
D = 24 * H
MIN = 60 * 1000

# Cambiarla hace que el servidor vuelva a generar los datos de demostración al arrancar (solo en modo demo)
VERSION_DEMO = "2026-11-24.6"

# Cauce real del Atoyac entre nodos y posición de nodos y barreras: un solo archivo para el servidor y
# para la demo sin servidor (el navegador lo carga como script; aquí se lee el JSON que trae).
ARCHIVO_CAUCE = Path(__file__).resolve().parent.parent / "js" / "cauce.js"


def _leer_cauce() -> dict:
    texto = ARCHIVO_CAUCE.read_text(encoding="utf-8")
    inicio = texto.index("VA.cauce = ") + len("VA.cauce = ")
    return json.loads(texto[inicio:texto.rindex(";")])


GEO = _leer_cauce()

NODOS = [
    # id, nombre, lat, lng, batería, días desde calibración, Tecnológico, valores normales, horas desde la última descarga
    ("N1", "San Martín Texmelucan · puente MEX 117", *GEO["nodos"]["N1"], 92, 6, "TecNM San Martín Texmelucan",
     {"ph": 7.4, "cond": 650, "turb": 35, "color": 1.6, "temp": 17.5, "nivel": 0.9}, 48),
    ("N2", "Huejotzingo · puente Atoyac", *GEO["nodos"]["N2"], 81, 9, "TecNM San Martín Texmelucan",
     {"ph": 7.3, "cond": 780, "turb": 42, "color": 2.0, "temp": 17.9, "nivel": 1.0}, 26),
    ("N3", "San Miguel Xoxtla · puente", *GEO["nodos"]["N3"], 74, 12, "TecNM Puebla",
     {"ph": 7.2, "cond": 980, "turb": 55, "color": 3.4, "temp": 18.4, "nivel": 1.1}, 72),
    ("N4", "Cuautlancingo · autopista México–Puebla", *GEO["nodos"]["N4"], 18, 27, "TecNM Puebla",
     {"ph": 7.1, "cond": 1100, "turb": 60, "color": 3.5, "temp": 18.8, "nivel": 1.2}, 9 * 24),
    ("N5", "Puebla capital · Vía Atlixcáyotl", *GEO["nodos"]["N5"], 88, 4, "Instituto Tecnológico de Puebla",
     {"ph": 7.2, "cond": 1150, "turb": 70, "color": 2.2, "temp": 19.1, "nivel": 1.3}, 5),
    ("N6", "Entrada a Valsequillo", *GEO["nodos"]["N6"], 95, 2, "Instituto Tecnológico de Puebla",
     {"ph": 7.5, "cond": 1200, "turb": 50, "color": 2.0, "temp": 19.6, "nivel": 1.4}, 24),
]
CAUCE = GEO["tramos"]                     # T1..T5: del nodo de arriba al de abajo, siguiendo el río
BARRERAS = [
    # id, nombre, lat, lng, llenado %, nivel, nivel máximo, días desde el último vaciado
    ("B1", "Barranca Xaltonac", *GEO["barreras"]["B1"], 46, 0.6, 2.2, 2),
    ("B2", "Río Alseseca", *GEO["barreras"]["B2"], 93, 0.9, 2.5, 9),
    ("B3", "Barranca del Conde", *GEO["barreras"]["B3"], 6, 0.5, 2.0, 1),
]
# Estación piloto de tratamiento (la estructura del render): capta agua del río junto al nodo y la devuelve tratada
ESTACIONES = {
    "N3": {"codigo": "EP-1", "nombre": "Estación piloto Xoxtla", "instalada": "26 ago 2026", "area_humedal_m2": 27,
           "etapas": ["Captación con compuerta y rejilla", "Tamiz rotatorio", "Sedimentador", "Filtros: grava, arena y carbón activado",
                      "Humedal artificial: tule, carrizo y alcatraz", "Descarga al río"]},
}


def tiene_estacion(nodo_id: str) -> bool:
    return nodo_id in ESTACIONES


def en_tramo(i: int, fraccion: float) -> list:
    """Punto sobre el cauce del tramo T(i+1) a cierta fracción de su largo (0 = nodo de arriba, 1 = nodo de abajo)."""
    pts = CAUCE[i]
    largos = [motor.km(*pts[k], *pts[k + 1]) for k in range(len(pts) - 1)]
    meta, acumulado = sum(largos) * fraccion, 0.0
    for k, l in enumerate(largos):
        if acumulado + l >= meta and l > 0:
            t = (meta - acumulado) / l
            return [round(pts[k][0] + t * (pts[k + 1][0] - pts[k][0]), 5), round(pts[k][1] + t * (pts[k + 1][1] - pts[k][1]), 5)]
        acumulado += l
    return list(pts[-1])


def _nombre_tramo(i: int) -> str:
    return NODOS[i][1].split(" · ")[0] + " → " + NODOS[i + 1][1].split(" · ")[0]


def _huella_catalogo() -> str:
    datos = [[n[:4] for n in NODOS], CAUCE, [b[:4] for b in BARRERAS]]
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# Cuentas de demostración: una por rol, cada una con su contraseña (quedan anotadas en datos/cuentas_demo.txt)
CUENTAS_DEMO = [
    ("admin@vigia.demo", "Mtra. Daniela Ortega Ruiz", "admin"),
    ("mariana.cuautle@vigia.demo", "Biól. Mariana Cuautle Romero", "ambiental"),
    ("arturo.tepox@vigia.demo", "C. Arturo Tepox Huerta", "limpia"),
    ("raul.ixtlapale@vigia.demo", "Cmdte. Raúl Ixtlapale Flores", "pc"),
    ("diego.tlatelpa@vigia.demo", "Ing. Diego Tlatelpa Morales", "tec"),
    ("lupita.sanchez@vigia.demo", "Guadalupe Sánchez Tecuatl", "ciudadano"),
]
ARCHIVO_CUENTAS = DATOS / "cuentas_demo.txt"
_TITULOS = re.compile(r"^(Mtra?\.|Ing\.|Lic\.|C\.|Dra?\.|Arq\.|Biól\.|Q\.)\s+")


def nombre_corto(nombre: str) -> str:
    """'Ing. Rafael Contreras Méndez' → 'Rafael Contreras' (para firmas de historial y lotes)."""
    partes = _TITULOS.sub("", nombre or "").split()
    return " ".join(partes[:2]) if partes else (nombre or "")


def catalogo(con) -> bool:
    """Crea nodos, tramos y barreras. Si ya existen y el catálogo del código cambió (por ejemplo, coordenadas
    corregidas), actualiza nombres y posiciones sin tocar lecturas ni estado. Devuelve True si cambió algo."""
    huella = _huella_catalogo()
    t = ahora()
    if con.execute("SELECT COUNT(*) AS c FROM nodos").fetchone()["c"]:
        if leer_ajuste(con, "catalogo") == huella:
            return False
        with transaccion(con):
            for i, (nid, nombre, lat, lng, *_resto) in enumerate(NODOS):
                con.execute("UPDATE nodos SET nombre = ?, lat = ?, lng = ?, orden = ? WHERE id = ?", (nombre, lat, lng, i, nid))
            for i, puntos in enumerate(CAUCE):
                con.execute("UPDATE tramos SET nombre = ?, puntos = ? WHERE id = ?", (_nombre_tramo(i), json.dumps(puntos), f"T{i + 1}"))
            for bid, nombre, lat, lng, *_resto in BARRERAS:
                con.execute("UPDATE barreras SET nombre = ?, lat = ?, lng = ? WHERE id = ?", (nombre, lat, lng, bid))
            guardar_ajuste(con, "catalogo", huella)
        return True
    with transaccion(con):
        for i, (nid, nombre, lat, lng, bat, cal, tec, base, _) in enumerate(NODOS):
            con.execute("INSERT INTO nodos (id, orden, nombre, lat, lng, bateria, calibrado, tec, base) VALUES (?,?,?,?,?,?,?,?,?)",
                        (nid, i, nombre, lat, lng, bat, t - cal * D, tec, json.dumps(base)))
        for i, puntos in enumerate(CAUCE):
            con.execute("INSERT INTO tramos (id, desde, hasta, nombre, puntos) VALUES (?,?,?,?,?)",
                        (f"T{i + 1}", NODOS[i][0], NODOS[i + 1][0], _nombre_tramo(i), json.dumps(puntos)))
        for bid, nombre, lat, lng, llenado, nivel, nivel_max, dias in BARRERAS:
            con.execute("INSERT INTO barreras (id, nombre, lat, lng, llenado, nivel, nivel_max, ultimo_vaciado, ultima_descarga) VALUES (?,?,?,?,?,?,?,?,?)",
                        (bid, nombre, lat, lng, llenado, nivel, nivel_max, t - dias * D, t - dias * D))
        guardar_ajuste(con, "catalogo", huella)
    return True


def demo_al_dia(con) -> bool:
    return leer_ajuste(con, "demo_version") == VERSION_DEMO and bool(con.execute("SELECT 1 FROM lecturas LIMIT 1").fetchone())


# =========================================================
# DATOS DE DEMOSTRACIÓN
# =========================================================
TEXTOS = {
    "Agua de color": [
        "El agua viene azul marino desde temprano, como si fuera tinta.",
        "Se ve morada cerca del puente y huele a químico.",
        "Bajó una mancha rojiza por la orilla izquierda; ayer estaba normal.",
        "Agua verde oscuro con espuma en la orilla, a la altura de la maquila.",
        "Tiene un color negro azulado, no se alcanza a ver el fondo.",
        "Desde las 6 de la mañana el río está color violeta.",
        "Franjas de colores en la corriente, como si hubieran lavado tinas de tinte.",
        "Color turquesa muy fuerte bajo el puente vehicular.",
        "El agua cambió de color en menos de una hora, ahora está azul.",
        "Se ve como café con leche y con un brillo aceitoso.",
    ],
    "Espuma": [
        "Mucha espuma blanca junto al puente, casi medio metro de alto.",
        "Se junta espuma en la curva del río y el viento la avienta a la calle.",
        "Espuma gris con olor a detergente en la orilla.",
        "Hay bolas de espuma flotando hasta donde alcanza la vista.",
        "Espuma amarillenta pegada a las piedras, no se deshace.",
        "Después de la caída de agua se forma una capa de espuma espesa.",
    ],
    "Basura": [
        "Bolsas, llantas y plástico atorados en la orilla.",
        "Tiraron cascajo y bolsas de basura junto al bordo.",
        "Hay un colchón y muebles viejos dentro del cauce.",
        "La rejilla de la barranca está tapada de PET y unicel.",
        "Basura acumulada bajo el puente, ya no pasa bien el agua.",
        "Dejaron costales de basura en la orilla durante la noche.",
        "Muchas botellas y envolturas después de la lluvia.",
        "Hay restos de poda y basura doméstica tapando el paso del agua.",
    ],
    "Descarga de tubería": [
        "Un tubo de 30 cm descarga agua gris directo al río.",
        "Sale agua caliente con vapor de un tubo de la orilla.",
        "Descarga constante de agua jabonosa desde la barda de la fábrica.",
        "Un drenaje roto tira aguas negras al cauce desde hace días.",
        "Vi una manguera que sale de un predio y descarga al río por la noche.",
        "Sale agua de color de un tubo escondido entre la hierba.",
    ],
    "Mal olor": [
        "Olor muy fuerte a drenaje desde la mañana.",
        "Huele a huevo podrido en toda la colonia.",
        "Olor a químico que pica la nariz cerca del puente.",
        "En la noche el olor es insoportable, no se puede abrir la ventana.",
        "Huele a solvente o a pintura a la altura de la secundaria.",
        "Olor a agua estancada y a basura quemada.",
    ],
    "Animal muerto": [
        "Hay peces muertos en la orilla.",
        "Un perro muerto atorado en las piedras del río.",
        "Muchos peces pequeños flotando panza arriba.",
        "Restos de un animal grande dentro de la barranca.",
        "Aves muertas cerca del agua, no sabemos por qué.",
    ],
}
LUGARES = ["bajo el puente", "frente a la cancha", "a la altura del panteón", "junto al bordo", "detrás de la secundaria",
           "cerca de la parada del camión", "a un lado de la granja", "pasando las vías", "en la curva del río", "junto a la maquila"]
TEXTO_LARGO = ("Somos vecinos de la colonia y desde hace tres semanas, casi todos los días entre las 5 y las 7 de la mañana, "
               "baja por el río una corriente de color azul oscuro con espuma que huele a químico. Se queda pegada en las "
               "piedras y en la tarde el olor llega hasta las casas. Los niños que juegan cerca dicen que les arden los ojos. "
               "Ya lo reportamos al municipio por teléfono dos veces y no hemos tenido respuesta; mandamos fotos y la ubicación "
               "exacta donde sale el tubo, a unos 200 metros río arriba del puente, detrás de la barda gris.")
# Confusiones típicas del clasificador de fotos
PARECIDOS = {"Agua de color": "Espuma", "Espuma": "Agua de color", "Basura": "Descarga de tubería", "Descarga de tubería": "Basura",
             "Mal olor": "Basura", "Animal muerto": "Basura"}

# Descargas programadas: (nodo, tipo, días atrás, hora local, minutos, fuerza). Terminan en casos con folio y muestra.
DESCARGAS = [
    ("N1", "textil", 58, 12.5, 12, 0.85),
    ("N2", "textil", 51, 2.8, 14, 1.00), ("N2", "textil", 27, 13.2, 12, 0.95), ("N2", "textil", 12, 15.3, 12, 1.05),
    ("N3", "textil", 66, 15.1, 12, 0.90), ("N3", "textil", 38, 16.7, 10, 0.85), ("N3", "textil", 19, 4.5, 16, 1.00),
    ("N3", "textil", "visita", 5.8, 14, 1.00),            # la madrugada del día de su última visita (caso abierto)
    ("N4", "industrial", 33, 23.5, 20, 1.00),
    ("N5", "domestica", 71, 20.7, 40, 0.90), ("N5", "domestica", 16, 7.8, 45, 1.00), ("N5", "industrial", 9, 22.25, 20, 1.00),
    ("N6", "domestica", 44, 6.3, 40, 0.95), ("N6", "domestica", "visita", 3.7, 45, 1.00),
]
ESTIMADO = {"textil": "Textil", "domestica": "Doméstica", "industrial": "Otra (industrial)"}
POR_QUE = {"textil": "Color y conductividad altos a la vez (tintes y sales).",
           "domestica": "Sube la turbidez sin cambio fuerte de color.",
           "industrial": "Cambio de pH o conductividad sin patrón textil ni doméstico."}
CATS_EVENTO = {"textil": ["Agua de color", "Agua de color", "Espuma", "Mal olor"], "domestica": ["Mal olor", "Descarga de tubería"],
               "industrial": ["Mal olor", "Agua de color"]}
LAB = {
    "textil": "DQO {dqo} mg/L · SST {sst} mg/L · color verdadero {pt} U Pt-Co · pH {ph}. Rebasa los límites de descarga; se notificó a la empresa responsable.",
    "domestica": "Coliformes fecales {cf}×10⁶ NMP/100 mL · DBO₅ {dbo} mg/L · SST {sst} mg/L. Colector dañado; el organismo operador lo reparó.",
    "industrial": "pH {ph} · conductividad {cond} µS/cm · DQO {dqo} mg/L. Se ordenó la clausura temporal de la descarga.",
}


def _hace(t: int, dias: int, hora: float) -> int:
    """Hora local `hora` del día de hace `dias` días."""
    return (sim.dia_local(t) - dias) * D - sim.UTC_A_LOCAL + int(hora * H)


def _ultima_visita(t: int, nid: str) -> int:
    """Última visita de Protección Civil a cada nodo: en día hábil, por la mañana."""
    horas = next(n[8] for n in NODOS if n[0] == nid)
    dias = round(horas / 24)
    while sim.dia_semana(_hace(t, dias, 12)) >= 5:                    # sábado o domingo: fue el viernes
        dias += 1
    v = _hace(t, dias, 10.0 + (sim.clave(nid) % 7) * 0.45)
    return min(v, t - 3 * H) if dias == 0 else v


def _visitas(t: int, nid: str, rng) -> list:
    """Visitas de recolección hacia atrás desde la última: cada 6 a 8 días, en día hábil y de mañana."""
    v = [_ultima_visita(t, nid)]
    inicio = t - 90 * D
    while True:
        prev = v[-1] - rng.choice((6, 7, 7, 8)) * D
        while sim.dia_semana(prev) >= 5:                       # sábado o domingo: la visita fue el viernes
            prev -= D
        prev = (sim.dia_local(prev)) * D - sim.UTC_A_LOCAL + int((9.4 + 4 * rng.random()) * H)
        if prev <= inicio + 2 * D:
            break
        v.append(prev)
    return sorted(v)


def _bateria(nid: str, t: int, t_fin: int) -> float:
    """Nivel medio de la batería: estable, salvo N4, cuyo panel se ensucia y va perdiendo carga."""
    nivel = next(n[4] for n in NODOS if n[0] == nid)
    if nid == "N4":
        return nivel + 46 * min(1.0, max(0.0, (t_fin - t) / (25 * D)))
    return nivel


def _punto_cerca(rng, p, metros=60):
    g = metros / 111320
    return round(p[0] + (rng.random() - 0.5) * 2 * g, 5), round(p[1] + (rng.random() - 0.5) * 2 * g, 5)


def _tramo_de(nid: str):
    i = next(k for k, n in enumerate(NODOS) if n[0] == nid)
    return i - 1 if i > 0 else None                             # índice del tramo que termina en el nodo


def demostracion(con) -> None:
    """90 días simulados de telemetría, visitas, reportes, casos y vaciados. Se repite con «Reiniciar demo»."""
    rng = random.Random(20261124)
    t = ahora()
    with transaccion(con):
        for tabla in ("lecturas", "lotes", "reportes", "casos", "notificaciones", "indice_diario", "vaciados", "accesos"):
            con.execute(f"DELETE FROM {tabla}")
        # Cuentas que dejan las pruebas automáticas (dominio .test, reservado para pruebas): no son de nadie
        con.execute("DELETE FROM usuarios WHERE cuenta LIKE '%.test'")
        for cuenta, nombre, _rol in CUENTAS_DEMO:
            con.execute("UPDATE usuarios SET nombre = ? WHERE cuenta = ? AND demo = 1", (nombre, cuenta))
        ids = {f["rol"]: (f["id"], f["nombre"]) for f in con.execute("SELECT id, rol, nombre FROM usuarios WHERE demo = 1")}

        eventos = _programar_descargas(t)
        visitas = _telemetria(con, rng, t, eventos, ids)
        crecidas = _crecidas(con)
        llenadas = _barreras(con, rng, t)
        reportes = _reportes(con, rng, t, eventos, ids)
        n_casos, n_muestras = _casos(con, rng, t, eventos, crecidas, llenadas, reportes, visitas, ids)
        for nid, *_ in NODOS:
            motor.recalcular_indice(con, nid)
        _accesos(con, rng, t, ids)
        _notificaciones(con, t, ids, reportes)
        guardar_ajuste(con, "seq_caso", n_casos)
        guardar_ajuste(con, "seq_reporte", 1300)
        guardar_ajuste(con, "seq_muestra", n_muestras)
        guardar_ajuste(con, "demo_version", VERSION_DEMO)


def _programar_descargas(t: int) -> list:
    """Descargas con su hora; las marcadas "visita" ocurren la madrugada del día de la última visita al nodo."""
    horarios = []
    for nid, tipo, dias, hora, minutos, fuerza in DESCARGAS:
        if dias == "visita":
            v = _ultima_visita(t, nid)
            ini = sim.dia_local(v) * D - sim.UTC_A_LOCAL + int(hora * H)
        else:
            ini = _hace(t, dias, hora)
        horarios.append((ini, nid, tipo, minutos, fuerza))
    eventos = []
    for k, (ini, nid, tipo, minutos, fuerza) in enumerate(sorted(horarios)):
        eventos.append({"n": k, "nodo": nid, "tipo": tipo, "ini": ini, "min": minutos, "fuerza": fuerza,
                        "folio": f"M-{k + 1:04d}", "filas": [], "eco": None, "reportes": []})
    return eventos


def _telemetria(con, rng, t, eventos, ids) -> dict:
    """Inserta las lecturas visita por visita (como si cada archivo se hubiera subido) y deja el estado de cada nodo."""
    pc_id, pc_nombre = ids.get("pc", (None, "Protección Civil"))
    tec_id, _ = ids.get("tec", (None, ""))
    dist = motor.km_por_rio(con)
    orden = [n[0] for n in NODOS]
    # El agua de cada descarga llega más débil al nodo de abajo (si para entonces ese nodo tiene datos)
    ecos = []
    for e in eventos:
        i = orden.index(e["nodo"])
        if i + 1 < len(orden):
            abajo = orden[i + 1]
            km = dist[abajo] - dist[e["nodo"]]
            ecos.append({"nodo": abajo, "tipo": e["tipo"], "ini": e["ini"] + int(km * 1000 / 0.8 * 1000), "min": int(e["min"] * 1.8),
                         "fuerza": e["fuerza"] * 0.5, "folio": "", "de": e})
    resultado = {}
    for nid, nombre, _la, _lo, bat, cal_dias, _tec, base, _h in NODOS:
        vs = _visitas(t, nid, rng)
        inicio = t - 90 * D
        huecos = [(_hace(t, 20, 8.2), _hace(t, 20, 16.8))] if nid == "N2" else []       # sonda en mantenimiento
        lotes, ultima_cal, ultimo_bat = [], None, bat
        for k, visita in enumerate(vs):
            desde = inicio if k == 0 else vs[k - 1] + 10 * MIN
            propios = [e for e in eventos if e["nodo"] == nid and desde <= e["ini"] < visita]
            de_arriba = [x for x in ecos if x["nodo"] == nid and desde <= x["ini"] < visita]
            lista = [(e["ini"], e["tipo"], e["fuerza"], e["min"], e["folio"]) for e in propios] + \
                    [(x["ini"], x["tipo"], x["fuerza"], x["min"], "") for x in de_arriba]
            filas = sim.simular(base, desde, visita, nodo=nid, estacion=tiene_estacion(nid), eventos=lista,
                                bateria=_bateria(nid, visita, vs[-1]), bateria_inicio=_bateria(nid, desde, vs[-1]), huecos=huecos)
            calibra = (len(vs) - 1 - k) % 4 == 0 and k > 0
            quien_id = tec_id if calibra and tec_id else pc_id
            invalidas = 0 if rng.random() < 0.85 else rng.randint(1, 3)
            nombre_archivo = f"{nid}_{datetime.fromtimestamp(visita / 1000, motor.TZ):%Y-%m-%d}.csv"
            con_anom = sorted({e["n"] for e in propios})
            lote = con.execute("""INSERT INTO lotes (nodo, usuario_id, subido, archivo, filas, nuevas, invalidas, desde, hasta,
                                  integridad, eventos, casos, checklist) VALUES (?,?,?,?,?,?,?,?,?, 'verificada', ?, '[]', ?)""",
                               (nid, quien_id, visita, nombre_archivo, len(filas) + invalidas, len(filas), invalidas,
                                filas[0]["t"] if filas else desde, filas[-1]["t"] if filas else visita, len(con_anom),
                                json.dumps({"limpieza": True, "calibracion": calibra, "frascos": bool(propios)}))).lastrowid
            con.executemany("""INSERT INTO lecturas (nodo, t, ph, cond, turb, color, temp, nivel, anom, muestra, lote,
                               caudal, turb_sal, color_sal, cond_sal, ph_sal, lodos, dp_filtro, solar) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            [(nid, f["t"], f["ph"], f["cond"], f["turb"], f["color"], f["temp"], f["nivel"], json.dumps(f["_anom"]),
                              f["muestra"], lote, f.get("caudal"), f.get("turb_sal"), f.get("color_sal"), f.get("cond_sal"),
                              f.get("ph_sal"), f.get("lodos"), f.get("dp_filtro"), f.get("solar")) for f in filas])
            for e in propios:
                e["filas"] = [f for f in filas if e["ini"] <= f["t"] < e["ini"] + e["min"] * MIN]
                e["base"] = [f for f in filas if e["ini"] - 6 * H <= f["t"] < e["ini"]]
                e["visita"], e["lote"], e["quien"] = visita, lote, pc_nombre
            for x in de_arriba:
                if any(f["_anom"] for f in filas if x["ini"] <= f["t"] < x["ini"] + x["min"] * MIN):
                    x["de"]["eco"] = nid
            if calibra:
                ultima_cal = visita
            if filas:
                ultimo_bat = filas[-1]["bateria"]
            lotes.append({"id": lote, "visita": visita, "desde": desde})
        con.execute("UPDATE nodos SET bateria = ?, calibrado = ?, ultima_descarga = ? WHERE id = ?",
                    (ultimo_bat, ultima_cal or (vs[-1] - cal_dias * D), vs[-1], nid))
        resultado[nid] = lotes
    return resultado


def _crecidas(con) -> list:
    """Episodios en los que el nivel pasó del crítico en N5 y N6 (salen de la telemetría simulada)."""
    critico = motor.umbrales(con)["nivel"]["crit"]
    episodios = []
    for nid in ("N5", "N6"):
        actual = None
        for f in con.execute("SELECT t, nivel FROM lecturas WHERE nodo = ? AND nivel >= ? ORDER BY t", (nid, critico)):
            if actual and f["t"] - actual["fin"] <= 3 * H:
                actual["fin"] = f["t"]
                if f["nivel"] > actual["pico"]:
                    actual["pico"], actual["t"] = f["nivel"], f["t"]
            else:
                actual = {"nodo": nid, "inicio": f["t"], "fin": f["t"], "t": f["t"], "pico": f["nivel"]}
                episodios.append(actual)
    episodios.sort(key=lambda e: -e["pico"])
    return sorted(episodios[:4], key=lambda e: e["t"])


def _barreras(con, rng, t) -> list:
    """Llenado diario de cada barrera (más basura después de cada tormenta) y vaciados de la cuadrilla.
    Devuelve las veces que llegó al 90% (cada una abre un caso para Limpia municipal)."""
    capacidad = {"B1": 260, "B2": 340, "B3": 210}
    ritmo = {"B1": 5.5, "B2": 11.0, "B3": 4.0}                   # % por día en secas (el Alseseca arrastra más)
    sin_vaciar = {"B2": 9 * D}                                    # B2 lleva días sin vaciarse: hoy está llena
    llenadas = []
    for bid, nombre, lat, lng, final, nivel, nivel_max, _dias in BARRERAS:
        llenado = 12.0
        dia0 = sim.dia_local(t) - 90
        pendiente = None                                       # vaciado programado tras llegar al 90%
        ultimo_vaciado = t - 90 * D
        for dia in range(dia0, sim.dia_local(t) + 1):
            t_dia = dia * D - sim.UTC_A_LOCAL
            tormenta = sim.tormenta_del_dia(dia)
            llenado += ritmo[bid] * (0.7 + 0.6 * rng.random()) + (7 + 12 * tormenta[1] if tormenta else 0)
            limite = t - sin_vaciar.get(bid, 3 * D)
            if llenado >= 90 and pendiente is None and t_dia < limite:
                aviso = t_dia + int((11 + 6 * rng.random()) * H)
                pendiente = (aviso, aviso + int((20 + 30 * rng.random()) * H))
                llenadas.append({"barrera": bid, "nombre": nombre, "lat": lat, "lng": lng, "t": aviso, "llenado": min(99, round(llenado)),
                                 "vaciado": pendiente[1], "kg": None})
            # Ruta preventiva de los martes: si ya va a más de un tercio y lleva casi una semana, se vacía sin esperar al aviso
            rutina = sim.dia_semana(t_dia) == 1 and llenado > 35 and t_dia - ultimo_vaciado > 6 * D and t_dia < limite
            if (pendiente and t_dia + D > pendiente[1]) or rutina:
                cuando = pendiente[1] if pendiente else t_dia + int((9 + 3 * rng.random()) * H)
                kg = round(capacidad[bid] * min(llenado, 100) / 100 * (0.85 + 0.25 * rng.random()))
                con.execute("INSERT INTO vaciados (barrera, t, kg, quien) VALUES (?, ?, ?, ?)",
                            (bid, cuando, kg, f"Limpia municipal · cuadrilla {1 + sim.clave(bid) % 4}"))
                if pendiente:
                    llenadas[-1]["kg"] = kg
                llenado, pendiente, ultimo_vaciado = 4 + 4 * rng.random(), None, cuando
            llenado = min(llenado, 100)
        # Estado de hoy: B2 llena y con caso abierto; B3 recién vaciada; B1 a media capacidad
        if bid == "B3":
            con.execute("INSERT INTO vaciados (barrera, t, kg, quien) VALUES (?, ?, ?, ?)",
                        (bid, t - 26 * H, 168, "Limpia municipal · cuadrilla 2"))
            ultimo_vaciado = t - 26 * H
        con.execute("UPDATE barreras SET llenado = ?, nivel = ?, ultimo_vaciado = ?, ultima_descarga = ? WHERE id = ?",
                    (final, nivel, ultimo_vaciado, t - int((10 + 4 * rng.random()) * H), bid))
    return llenadas


def _fraccion(*claves) -> float:
    """Número fijo entre 0 y 1 para unas claves, sin tocar el generador de la demo (no mueve los demás datos)."""
    return zlib.crc32("|".join(map(str, claves)).encode("utf-8")) / 0xFFFFFFFF


def _reporte(rid, cat, p, t_rep, estado, rng, usuario=None, texto=None, ia=True, anonimo=None, voz=None):
    if ia and rng.random() < 0.95:
        acierta = rng.random() < 0.86
        etiqueta = cat if acierta else PARECIDOS[cat]
        conf = round(0.74 + 0.23 * rng.random(), 2) if acierta else round(0.46 + 0.22 * rng.random(), 2)
    else:
        etiqueta, conf = None, None
    if texto is None:
        texto = rng.choice(TEXTOS[cat])
        if rng.random() < 0.35:
            texto = texto.rstrip(".") + ", " + rng.choice(LUGARES) + "."
    anon = (rng.random() < 0.3) if anonimo is None else anonimo
    # Lugar del suceso: casi siempre con el GPS del teléfono (margen de 2.2 a 5 m); a veces marcado a mano.
    # Se calcula con el punto y la hora (el folio se asigna después) y sin tocar el generador de la demo
    clave = (round(p[0], 6), round(p[1], 6), t_rep)
    con_gps = _fraccion("ubicacion", *clave) < 0.82
    return {"id": rid, "usuario_id": None if anon else usuario, "cat": cat, "ia_etiqueta": etiqueta, "ia_confianza": conf,
            "lat": p[0], "lng": p[1], "t": t_rep, "estado": estado, "anonimo": int(anon),
            "voz": int(rng.random() < 0.12) if voz is None else int(voz), "texto": texto,
            "ubicacion": "gps" if con_gps else "mapa",
            "precision_m": round(2.2 + 2.8 * _fraccion("precision", *clave), 1) if con_gps else None}


def _reportes(con, rng, t, eventos, ids) -> dict:
    """Reportes de la app: de fondo (más en fin de semana y en lluvias) y los que acompañan cada descarga."""
    ciudadana = ids.get("ciudadano", (None, ""))[0]
    lista = []
    # Zonas: tramos textiles (T1, T2), mixto (T3), urbanos (T4, T5) y barrancas con barrera
    zonas = [("T1", 1.0), ("T2", 1.3), ("T3", 1.0), ("T4", 1.5), ("T5", 1.2), ("B", 1.6)]
    cats_zona = {
        "textil": [("Agua de color", 30), ("Espuma", 18), ("Mal olor", 14), ("Basura", 18), ("Descarga de tubería", 14), ("Animal muerto", 6)],
        "urbano": [("Basura", 34), ("Mal olor", 22), ("Descarga de tubería", 18), ("Agua de color", 8), ("Espuma", 8), ("Animal muerto", 10)],
        "barranca": [("Basura", 70), ("Mal olor", 20), ("Animal muerto", 10)],
    }

    def elige(pares):
        x, acum = rng.random() * sum(p for _, p in pares), 0
        for v, p in pares:
            acum += p
            if x <= acum:
                return v
        return pares[-1][0]

    for dia in range(sim.dia_local(t) - 89, sim.dia_local(t) + 1):
        t_dia = dia * D - sim.UTC_A_LOCAL
        s = sim.lluvias(t_dia + 12 * H)
        lam = 1.5 * (1 + 0.5 * s) * (1.45 if sim.dia_semana(t_dia) >= 5 else 1.0)
        n = sum(1 for _ in range(8) if rng.random() < lam / 8)
        for _ in range(n):
            hora = rng.choice((8, 9, 10, 11, 13, 14, 17, 18, 19, 20)) + rng.random()
            t_rep = t_dia + int(hora * H)
            if t_rep > t - 30 * MIN:
                continue
            zona = elige(zonas)
            if zona == "B":
                b = rng.choice(BARRERAS)
                p, cat = _punto_cerca(rng, (b[2], b[3]), 80), elige(cats_zona["barranca"])
            else:
                i = int(zona[1]) - 1
                p = _punto_cerca(rng, en_tramo(i, rng.random()))
                cat = elige(cats_zona["textil" if i < 2 else "urbano" if i > 2 else rng.choice(("textil", "urbano"))])
            lista.append(_reporte(None, cat, p, t_rep, None, rng, usuario=ciudadana if rng.random() < 0.06 else None))

    # Reportes que acompañan cada descarga: la gente ve el agua rara poco después
    for e in eventos:
        i = _tramo_de(e["nodo"])
        n = {"textil": rng.randint(2, 4), "domestica": rng.randint(1, 2), "industrial": rng.randint(1, 2)}[e["tipo"]]
        for k in range(n):
            t_rep = e["ini"] + int((0.4 + 3.5 * rng.random()) * H)
            if t_rep > t - 30 * MIN:
                t_rep = e["ini"] + int(0.5 * H)
            p = _punto_cerca(rng, en_tramo(i, 0.55 + 0.4 * rng.random()) if i is not None else (NODOS[0][2], NODOS[0][3]), 90)
            r = _reporte(None, CATS_EVENTO[e["tipo"]][k % len(CATS_EVENTO[e["tipo"]])], p, t_rep, None, rng,
                         usuario=ciudadana if k == 0 and e["n"] % 3 == 0 else None)
            r["_evento"] = e["n"]
            lista.append(r)

    # Basura junto a la autopista (caso de hoy para Limpia) y casos límite
    for k in range(3):
        lista.append(_reporte(None, "Basura", _punto_cerca(rng, en_tramo(3, 0.05 + 0.02 * k), 70), t - int((9.5 + 2.2 * k) * H), None, rng)
                     | {"_grupo": "N4"})
    lista.append(_reporte(None, "Agua de color", _punto_cerca(rng, en_tramo(1, 0.7)), t - int(30 * H), None, rng, texto=TEXTO_LARGO, anonimo=False))
    lista.append(_reporte(None, "Mal olor", _punto_cerca(rng, en_tramo(4, 0.3)), t - int(52 * H), None, rng, texto="", anonimo=True, voz=False))

    lista.sort(key=lambda r: r["t"])
    for k, r in enumerate(lista):
        r["id"] = f"R-{1240 - len(lista) + k}"
    # Los dos más recientes: agua azul en el tramo que llega a Xoxtla (sirven para mostrar el cruce con los sensores)
    lista.append(_reporte("R-1240", "Agua de color", en_tramo(1, 0.75), t - 40 * MIN, "Recibido", rng,
                          texto="Nota de voz: «el río viene azul, como tinta, desde hace rato».", anonimo=False, voz=True)
                 | {"ia_etiqueta": "Agua de color", "ia_confianza": 0.94})
    lista.append(_reporte("R-1241", "Espuma", en_tramo(1, 0.97), t - 25 * MIN, "Recibido", rng,
                          texto="Espuma y agua oscura bajo el puente.", anonimo=True, voz=False) | {"ia_etiqueta": "Espuma", "ia_confianza": 0.88})
    return {"lista": lista}


def _estado_reporte(rng, edad_dias, caso_estado=None):
    if caso_estado == "Cerrado":
        return "Atendido"
    if caso_estado:
        return "Validado" if caso_estado == "Nuevo" else "En atención"
    if edad_dias < 1:
        return rng.choice(("Recibido", "Recibido", "Validado"))
    if edad_dias < 7:
        return rng.choice(("Validado", "En atención", "Atendido", "Recibido"))
    return rng.choice(("Atendido",) * 7 + ("Validado",) * 2 + ("Descartado",))


def _casos(con, rng, t, eventos, crecidas, llenadas, reportes, visitas, ids) -> tuple:
    """Casos de 90 días alineados con la telemetría (descargas y crecidas), las barreras y los reportes."""
    amb = nombre_corto(ids.get("ambiental", (None, "Autoridad ambiental"))[1])
    pcn = nombre_corto(ids.get("pc", (None, "Protección Civil"))[1])
    lim = nombre_corto(ids.get("limpia", (None, "Limpia municipal"))[1])
    u = motor.umbrales(con)
    nodos = {n[0]: n for n in NODOS}
    por_evento = {}
    for r in reportes["lista"]:
        if "_evento" in r:
            por_evento.setdefault(r["_evento"], []).append(r)
    casos = []

    def ev(tt, quien, que):
        return {"t": int(tt), "who": quien, "what": que}

    # --- Descargas: una por evento programado, con lo que midió el nodo ---
    abiertos = {"N3": "Inspección programada", "N6": "En atención"}
    for e in eventos:
        if not e["filas"]:
            continue
        nid, n = e["nodo"], nodos[e["nodo"]]
        i = _tramo_de(nid)
        anom = sorted({k for f in e["filas"] for k in f["_anom"]})
        if not anom:
            continue
        pico = {}
        for k in ("color", "cond", "ph", "turb"):
            vals = [f[k] for f in e["filas"]]
            pico[k] = max(vals, key=lambda v: abs(v - 7)) if k == "ph" else max(vals)
        ref = {k: round(motor.mediana([f[k] for f in e["base"]]), 2) if e["base"] else n[7][k] for k in ("ph", "cond", "turb", "color")}
        rep = por_evento.get(e["n"], [])
        confianza = motor.confianza(len(anom), len(rep))
        reciente = t - e["ini"] < 6 * D
        estado = abiertos.get(nid, "Cerrado") if reciente else "Cerrado"
        creado = e["visita"] + int((4 + 20 * rng.random()) * MIN)
        cierre = None if estado != "Cerrado" else creado + int(rng.choice((3.5, 5, 6, 7.5, 9, 11, 14)) * D)
        if cierre and cierre > t - 2 * H:
            cierre, estado = None, "En atención"
        if i is not None:
            pts = CAUCE[i]
            lat, lng = pts[len(pts) // 2]
            lugar = f"Entre {NODOS[i][1]} y {n[1]} ({motor.largo_km(pts):.1f} km de cauce)"
        else:
            lat, lng = n[2], n[3]
            lugar = f"Aguas arriba de {n[1]}, antes del primer nodo de la red"
        params = ", ".join(motor.NOMBRE[k] for k in motor.PARAMS_ANOM if k in anom)
        veces = {k: pico[k] / ref[k] for k in ("color", "cond", "turb") if ref.get(k)}
        resumen = (f"Cambio brusco de {params} en {n[1]} ({motor.fecha(e['ini'])}). {lugar}. {POR_QUE[e['tipo']]}"
                   + (f" Coincide con {len(rep)} reporte{'s' if len(rep) != 1 else ''} de la app cerca del tramo." if rep else ""))
        hist = [ev(e["ini"], "Nodo " + nid, f"Anomalía registrada sin internet ({params})"),
                ev(e["ini"] + 2 * MIN, "Nodo " + nid, f"El carrusel tomó la muestra {e['folio']}"),
                ev(e["visita"], f"Protección Civil · {pcn}", f"Datos de {nid} descargados en la visita y subidos a la plataforma"),
                ev(creado, "Sistema", f"Tramo probable: {lugar}. Caso asignado a Autoridad ambiental")]
        if rep:
            hist.insert(3, ev(creado - MIN, "Sistema", f"Cruce con {len(rep)} reporte(s) de la app: confianza {round(confianza * 100)}%"))
        if e["eco"]:
            hist.append(ev(creado + 5 * MIN, "Sistema", f"La anomalía también llegó aguas abajo a {nodos[e['eco']][1]}, más diluida"))
        lab = None
        if estado in ("En atención", "Inspección programada", "Cerrado"):
            hist.append(ev(creado + int((3 + 20 * rng.random()) * H), f"Autoridad ambiental · {amb}", "Caso en atención"))
        if estado == "Inspección programada":
            hist.append(ev(creado + int(30 * H), f"Autoridad ambiental · {amb}", "Inspección programada al tramo con personal de vigilancia"))
        if estado == "Cerrado":
            sin_evidencia = e["n"] == 5
            lab = ("Muestra dentro de los valores habituales del tramo; no se identificó responsable. Se mantiene la vigilancia."
                   if sin_evidencia else LAB[e["tipo"]].format(
                       dqo=rng.randint(320, 690), sst=rng.randint(95, 240), pt=rng.randint(420, 980), ph=round(pico["ph"], 1),
                       cf=round(1.2 + 2.6 * rng.random(), 1), dbo=rng.randint(140, 290), cond=int(pico["cond"])))
            hist.append(ev(creado + int(2 * D), f"Autoridad ambiental · {amb}", "Inspección realizada en el tramo"))
            hist.append(ev(cierre - int(6 * H), f"Autoridad ambiental · {amb}", f"Resultado de laboratorio capturado (muestra {e['folio']})"))
            hist.append(ev(cierre, f"Autoridad ambiental · {amb}", "Caso cerrado; se avisó a quienes reportaron"))
        casos.append({
            "tipo": "descarga", "estado": estado, "prioridad": "Alta" if confianza >= 0.75 or any(motor.estado_lectura(f, u) == "crit" for f in e["filas"]) else "Media",
            "t": creado, "cerrado": cierre, "tramo": f"T{i + 1}" if i is not None else None, "nodo": nid, "lat": lat, "lng": lng,
            "estimado": ESTIMADO[e["tipo"]], "confianza": confianza, "muestra": e["folio"], "resumen": resumen, "lab": lab,
            "pico": {k: round(v, 2) for k, v in pico.items()}, "reportes": [r["id"] for r in rep], "historial": hist,
            "confirmado_en": [e["eco"]] if e["eco"] else [], "evento_t": e["ini"], "evento_fin": e["ini"] + e["min"] * MIN,
            "evento": {"params": anom, "base": ref, "critico": True, "lecturas": len(e["filas"])}, "_reportes": rep,
            "_veces": veces})

    # --- Crecidas: el nivel pasó del crítico (sale de la simulación) ---
    for k, c in enumerate(crecidas):
        n = nodos[c["nodo"]]
        creado = c["t"] + int(4 * MIN)
        cierre = c["fin"] + int((5 + 8 * rng.random()) * H)
        casos.append({"tipo": "inundacion", "estado": "Cerrado", "prioridad": "Alta", "t": creado, "cerrado": cierre, "nodo": c["nodo"],
                      "lat": n[2], "lng": n[3], "estimado": "Nivel alto", "confianza": 0.95, "evento_t": c["t"],
                      "resumen": f"El nivel del agua llegó a {c['pico']:.2f} m en {n[1]} ({motor.fecha(c['t'])}) con la tormenta de la tarde. "
                                 "La alarma local (luz y sirena) avisó en el momento a quienes viven cerca.",
                      "historial": [ev(c["inicio"], "Nodo " + c["nodo"], f"Nivel {c['pico']:.2f} m: alarma local activada"),
                                    ev(creado, "Sistema", "Caso asignado a Protección Civil; aviso a vecinos suscritos en la app"),
                                    ev(creado + int(35 * MIN), f"Protección Civil · {pcn}", "Brigada en sitio; se cerró el paso del vado"),
                                    ev(cierre, f"Protección Civil · {pcn}", "Nivel normalizado; caso cerrado")]})
    if crecidas:
        c = max(crecidas, key=lambda x: x["pico"])
        b = next(x for x in BARRERAS if x[0] == "B3")
        creado = c["t"] - int(50 * MIN)
        casos.append({"tipo": "inundacion", "estado": "Cerrado", "prioridad": "Alta", "t": creado, "cerrado": creado + int(9 * H), "barrera": "B3",
                      "lat": b[2], "lng": b[3], "estimado": "Nivel alto", "confianza": 0.95, "evento_t": creado - int(4 * MIN),
                      "resumen": f"El nivel en la barranca del Conde llegó a 1.86 m con la tormenta ({motor.fecha(creado)}).",
                      "historial": [ev(creado - int(4 * MIN), "Barrera B3", "Nivel 1.86 m"),
                                    ev(creado, f"Protección Civil · {pcn}", "Alerta enviada a vecinos suscritos"),
                                    ev(creado + int(9 * H), f"Protección Civil · {pcn}", "Nivel normalizado; caso cerrado")]})

    # --- Barreras llenas: Limpia municipal las vacía ---
    for ll in llenadas:
        kg = ll["kg"] or 150
        casos.append({"tipo": "basura", "estado": "Cerrado", "prioridad": "Alta", "t": ll["t"], "cerrado": ll["vaciado"], "barrera": ll["barrera"],
                      "lat": ll["lat"], "lng": ll["lng"], "estimado": "Barrera llena", "confianza": 0.97,
                      "resumen": f"La barrera de {ll['nombre']} llegó a {ll['llenado']}% de llenado. Se retiraron {kg} kg.",
                      "historial": [ev(ll["t"] - MIN, "Barrera " + ll["barrera"], f"Llenado {ll['llenado']}%"),
                                    ev(ll["t"], "Sistema", "Caso asignado a Limpia municipal con ruta de recolección"),
                                    ev(ll["t"] + int(2 * H), f"Limpia municipal · {lim}", "Cuadrilla asignada"),
                                    ev(ll["vaciado"], f"Limpia municipal · {lim}", f"Recolección: {kg} kg; caso cerrado")]})
    b2 = next(x for x in BARRERAS if x[0] == "B2")
    t_b2 = t - int(47 * H)
    casos.append({"tipo": "basura", "estado": "En atención", "prioridad": "Alta", "t": t_b2, "barrera": "B2", "lat": b2[2], "lng": b2[3],
                  "estimado": "Barrera llena", "confianza": 0.97, "resumen": "La barrera del río Alseseca llegó a 92% de llenado.",
                  "historial": [ev(t_b2 - MIN, "Barrera B2", "Llenado 92%"), ev(t_b2, "Sistema", "Caso asignado a Limpia municipal con ruta de recolección"),
                                ev(t_b2 + int(3 * H), f"Limpia municipal · {lim}", "Cuadrilla asignada; el camión llega mañana por la mañana")]})

    # --- Basura por reportes agrupados (hoy, bajo el puente de la autopista) y punto crítico recurrente ---
    grupo = [r for r in reportes["lista"] if r.get("_grupo") == "N4"]
    if grupo:
        p = en_tramo(3, 0.06)
        casos.append({"tipo": "basura", "estado": "Nuevo", "prioridad": "Media", "t": max(r["t"] for r in grupo) + 3 * MIN, "lat": p[0], "lng": p[1],
                      "estimado": "Residuo sólido", "confianza": 0.87, "reportes": [r["id"] for r in grupo], "_reportes": grupo,
                      "resumen": f"{len(grupo)} reportes con foto de basura acumulada en la orilla, bajo el puente de la autopista México–Puebla.",
                      "historial": [ev(max(r["t"] for r in grupo) + 3 * MIN, "Sistema", "Agrupamiento de reportes; caso asignado a Limpia municipal")]})
    p = en_tramo(1, 0.85)
    t_rec = t - int(30 * H)
    casos.append({"tipo": "recurrente", "estado": "Nuevo", "prioridad": "Media", "t": t_rec, "lat": p[0], "lng": p[1],
                  "estimado": "Basura y espuma recurrentes", "confianza": 0.8,
                  "resumen": "Zona con 11 reportes en las últimas tres semanas a menos de 500 m. Se propone una jornada de limpieza con vecinos.",
                  "historial": [ev(t_rec, "Sistema", "Punto crítico recurrente detectado; propuesta de jornada ciudadana")]})
    p = en_tramo(4, 0.35)
    t_rec2 = t - int(41 * D)
    casos.append({"tipo": "recurrente", "estado": "Cerrado", "prioridad": "Media", "t": t_rec2, "cerrado": t_rec2 + 9 * D, "lat": p[0], "lng": p[1],
                  "estimado": "Basura recurrente", "confianza": 0.82,
                  "resumen": "Tiradero recurrente en la orilla. Jornada de limpieza con 46 voluntarios: 1.2 toneladas retiradas.",
                  "historial": [ev(t_rec2, "Sistema", "Punto crítico recurrente detectado; propuesta de jornada ciudadana"),
                                ev(t_rec2 + 2 * D, "Brigadas ciudadanas", "Jornada convocada para el sábado"),
                                ev(t_rec2 + 9 * D, "Brigadas ciudadanas", "Jornada realizada con 46 voluntarios; 1.2 t retiradas")]})

    # --- Folios en orden de creación y estado de los reportes ligados ---
    casos.sort(key=lambda c: c["t"])
    anio = datetime.now(motor.TZ).year
    por_reporte = {}
    for k, c in enumerate(casos):
        c["id"] = f"VA-{anio}-{k + 1:04d}"
        c["dep"] = motor.TIPOS_CASO[c["tipo"]]["dep"]
        for r in c.pop("_reportes", []):
            por_reporte[r["id"]] = c
        c.pop("_veces", None)
        d = {k2: None for k2 in motor._COLS}
        d.update({"reportes": [], "historial": [], "confirmado_en": [], "auto": 0, "loc_pendiente": 0})
        d.update(c)
        motor.guardar_caso(con, d)
    for nid, lotes in visitas.items():
        for lote in lotes:
            folios = [c["id"] for c in casos if c["tipo"] == "descarga" and c.get("nodo") == nid and c.get("evento_t")
                      and lote["desde"] <= c["evento_t"] < lote["visita"]]
            if folios:
                con.execute("UPDATE lotes SET casos = ? WHERE id = ?", (json.dumps(folios), lote["id"]))

    filas = []
    for r in reportes["lista"]:
        caso = por_reporte.get(r["id"])
        if r["estado"] is None:
            r["estado"] = _estado_reporte(rng, (t - r["t"]) / D, caso["estado"] if caso else None)
        filas.append((r["id"], r["usuario_id"], r["cat"], r["ia_etiqueta"], r["ia_confianza"], r["lat"], r["lng"], r["t"], r["estado"],
                      r["anonimo"], r["voz"], r["texto"], r.get("ubicacion"), r.get("precision_m")))
    con.executemany("""INSERT INTO reportes (id, usuario_id, cat, ia_etiqueta, ia_confianza, lat, lng, t, estado, anonimo, voz, texto,
                                             ubicacion, precision_m)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", filas)
    return len(casos), len(eventos) + 1


def _accesos(con, rng, t, ids) -> None:
    """Bitácora de las últimas dos semanas: el personal entra en días hábiles; algún error de contraseña;
    un intento de fuerza bruta desde fuera que terminó bloqueado."""
    cuentas = {f["rol"]: f for f in con.execute("SELECT id, cuenta, rol FROM usuarios WHERE demo = 1")}
    ips = {"admin": "10.20.4.31", "ambiental": "10.20.7.112", "limpia": "10.32.1.58", "pc": "189.203.44.17", "tec": "148.208.90.23"}
    filas = []
    for dias in range(14, -1, -1):
        t_dia = (sim.dia_local(t) - dias) * D - sim.UTC_A_LOCAL
        if sim.dia_semana(t_dia) >= 5:
            continue
        for rol, ip in ips.items():
            f = cuentas.get(rol)
            if not f or rng.random() < 0.15:
                continue
            for hora in ([8.2 + 1.6 * rng.random()] + ([15 + 2.5 * rng.random()] if rng.random() < 0.35 else [])):
                tt = t_dia + int(hora * H)
                if tt > t - 5 * MIN:
                    continue
                if rng.random() < 0.06:
                    filas.append((tt - 40 * 1000, f["id"], f["cuenta"], ip, "clave"))
                filas.append((tt, f["id"], f["cuenta"], ip, "ok"))
    ataque = (sim.dia_local(t) - 4) * D - sim.UTC_A_LOCAL + int(3.4 * H)
    for k in range(6):
        filas.append((ataque + k * 9000, None, "admin@puebla.gob.mx", "45.155.205.86", "clave" if k < 5 else "bloqueo"))
    con.executemany("INSERT INTO accesos (t, usuario_id, cuenta, ip, resultado) VALUES (?,?,?,?,?)", filas)


def _notificaciones(con, t, ids, reportes) -> None:
    ciudadana = ids.get("ciudadano", (None, ""))[0]
    if not ciudadana:
        return
    suyos = [r for r in reportes["lista"] if r["usuario_id"] == ciudadana][-5:]
    for r in suyos:
        if r["estado"] in ("Validado", "En atención", "Atendido"):
            con.execute("INSERT INTO notificaciones (usuario_id, t, titulo, texto, leida, reporte) VALUES (?,?,?,?,?,?)",
                        (ciudadana, min(t, r["t"] + 5 * H), "Tu reporte avanzó",
                         f"El reporte {r['id']} ({r['cat'].lower()}) ahora está: {r['estado']}.", int(t - r["t"] > 2 * D), r["id"]))


NOTA_ACCESO = ("Se entra igual que con una cuenta real: correo y contraseña en la pantalla de inicio de sesión.\n"
               "Cada cuenta ve solo los módulos de su rol. Administración puede crear cuentas nuevas y ajustar\n"
               "los permisos de cada persona en Usuarios.\n")
_NOTA_VIEJA = "En la computadora del servidor no hace falta escribirla"        # de cuando había entrada de un clic


def _texto_cuentas(filas) -> str:
    """filas: (rol, cuenta, contraseña, nombre). Una línea por cuenta, columnas separadas por espacios."""
    ancho = max(len(c) for _, c, _, _ in filas)
    tabla = [f"{'Rol':10} {'Cuenta':{ancho}} {'Contraseña':14} Nombre"] + [f"{r:10} {c:{ancho}} {k:14} {n}" for r, c, k, n in filas]
    return ("Cuentas de demostración de Vigía Atoyac: una por rol, cada una con su contraseña\n\n" + "\n".join(tabla)
            + "\n\n" + NOTA_ACCESO + "Para dejar solo Administración y crear cuentas nuevas, con el servidor apagado:\n"
            "python -m server.renovar_cuentas\n")


def leer_cuentas_demo() -> dict:
    """{cuenta: (rol, contraseña)} anotadas en datos/cuentas_demo.txt. Lee también el formato anterior, con una
    sola contraseña para todas («Contraseña: …» y una línea «cuenta rol» por cuenta)."""
    try:
        texto = ARCHIVO_CUENTAS.read_text(encoding="utf-8")
    except OSError:
        return {}
    roles, comun, cuentas = {r for _, _, r in CUENTAS_DEMO}, re.search(r"^Contraseña: (\S+)", texto, re.M), {}
    for p in (linea.split() for linea in texto.splitlines()):
        if len(p) >= 3 and p[0] in roles and "@" in p[1]:
            cuentas[p[1]] = (p[0], p[2])
        elif len(p) == 2 and "@" in p[0] and p[1] in roles and comun:
            cuentas[p[0]] = (p[1], comun.group(1))
    return cuentas


def _crear_cuentas(con, cuentas) -> list:
    """Da de alta cuentas de demostración, cada una con su contraseña aleatoria (todas con VA_DEMO_CLAVE si está
    definida). Devuelve (rol, cuenta, contraseña, nombre) para anotarlas."""
    fija, t, filas = os.environ.get("VA_DEMO_CLAVE"), ahora(), []
    with transaccion(con):
        for cuenta, nombre, rol in cuentas:
            clave = fija or secrets.token_urlsafe(9)
            con.execute("INSERT INTO usuarios (cuenta, nombre, rol, hash, demo, creado) VALUES (?,?,?,?,1,?)",
                        (cuenta, nombre, rol, crear_hash(clave), t))
            filas.append((rol, cuenta, clave, nombre))
    return filas


def cuentas_demo(con) -> None:
    """Primer arranque en modo demo: una cuenta por rol, cada una con su contraseña, anotadas en datos/cuentas_demo.txt."""
    if con.execute("SELECT COUNT(*) AS c FROM usuarios").fetchone()["c"]:
        # Ya hay cuentas. Si el archivo es de una versión que tenía botones «Entrar como…», se corrige solo esa
        # explicación: las contraseñas no se pueden recuperar del hash y se dejan como están
        try:
            texto = ARCHIVO_CUENTAS.read_text(encoding="utf-8")
        except OSError:
            return
        if _NOTA_VIEJA in texto:
            ARCHIVO_CUENTAS.write_text(texto[:texto.index(_NOTA_VIEJA)] + NOTA_ACCESO, encoding="utf-8")
        return
    ARCHIVO_CUENTAS.write_text(_texto_cuentas(_crear_cuentas(con, CUENTAS_DEMO)), encoding="utf-8")


def renovar_cuentas(con) -> list:
    """Deja solo las cuentas de Administración (con su contraseña de siempre) y crea de nuevo una cuenta de
    demostración por cada otro rol, cada una con su contraseña. Devuelve lo que queda anotado en el archivo."""
    anotadas = leer_cuentas_demo()
    with transaccion(con):
        con.execute("DELETE FROM usuarios WHERE rol <> 'admin'")       # sus sesiones y avisos se van en cascada
    nuevas = _crear_cuentas(con, [c for c in CUENTAS_DEMO if c[2] != "admin"])
    admins = [("admin", f["cuenta"], anotadas.get(f["cuenta"], ("admin", "-"))[1], f["nombre"])
              for f in con.execute("SELECT cuenta, nombre FROM usuarios WHERE rol = 'admin' ORDER BY id")]
    ARCHIVO_CUENTAS.write_text(_texto_cuentas(admins + nuevas), encoding="utf-8")
    return admins + nuevas


def resumen_cuentas_demo() -> str:
    """Para la consola del servidor: cada cuenta de prueba con su contraseña."""
    cuentas = leer_cuentas_demo()
    if not cuentas:
        return f"Las cuentas de prueba están en {ARCHIVO_CUENTAS}."
    return "Cuentas de prueba:\n" + "\n".join(f"    {rol:10} {cuenta:28} {clave}" for cuenta, (rol, clave) in cuentas.items())


def admin_inicial(con) -> bool:
    """Sin modo demo: crea la primera cuenta de administración a partir de variables de entorno."""
    if con.execute("SELECT COUNT(*) AS c FROM usuarios").fetchone()["c"]:
        return True
    cuenta, clave = os.environ.get("VA_ADMIN_CUENTA", "").strip().lower(), os.environ.get("VA_ADMIN_CLAVE", "")
    if not cuenta or len(clave) < 8:
        return False
    con.execute("INSERT INTO usuarios (cuenta, nombre, rol, hash, creado) VALUES (?,?,?,?,?)",
                (cuenta, "Administración", "admin", crear_hash(clave), ahora()))
    return True
