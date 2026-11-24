"""Datos iniciales.

- Catálogo (siempre): nodos, tramos y barreras del piloto. Coordenadas aproximadas.
- Datos de demostración (solo con VA_DEMO=1): lecturas, reportes, casos y cuentas de prueba.
  Son inventados para ensayar la presentación; no son mediciones reales del río.
"""
import json
import os
import random
import secrets

from . import lotes, motor
from .db import DATOS, ahora, guardar_ajuste, transaccion
from .seguridad import crear_hash

H = 3600 * 1000
D = 24 * H

NODOS = [
    # id, nombre, lat, lng, batería, días desde calibración, Tecnológico, valores normales, horas desde la última descarga
    ("N1", "San Martín Texmelucan", 19.2785, -98.4290, 92, 6, "TecNM San Martín Texmelucan",
     {"ph": 7.4, "cond": 650, "turb": 35, "color": 1.6, "temp": 17.5, "nivel": 0.9}, 48),
    ("N2", "Huejotzingo · puente Atoyac", 19.1985, -98.3620, 81, 9, "TecNM San Martín Texmelucan",
     {"ph": 7.3, "cond": 780, "turb": 42, "color": 2.0, "temp": 17.9, "nivel": 1.0}, 26),
    ("N3", "San Miguel Xoxtla", 19.1790, -98.2990, 74, 12, "TecNM Puebla",
     {"ph": 7.2, "cond": 980, "turb": 55, "color": 3.4, "temp": 18.4, "nivel": 1.1}, 72),
    ("N4", "Cuautlancingo · Periférico", 19.0960, -98.2600, 18, 27, "TecNM Puebla",
     {"ph": 7.1, "cond": 1100, "turb": 60, "color": 3.5, "temp": 18.8, "nivel": 1.2}, 9 * 24),
    ("N5", "Puebla capital · Atoyac sur", 19.0280, -98.2330, 88, 4, "Instituto Tecnológico de Puebla",
     {"ph": 7.2, "cond": 1150, "turb": 70, "color": 2.2, "temp": 19.1, "nivel": 1.3}, 5),
    ("N6", "Entrada a Valsequillo", 18.9660, -98.1680, 95, 2, "Instituto Tecnológico de Puebla",
     {"ph": 7.5, "cond": 1200, "turb": 50, "color": 2.0, "temp": 19.6, "nivel": 1.4}, 24),
]
CAUCE = [
    [[19.2785, -98.4290], [19.2450, -98.4050], [19.1985, -98.3620]],
    [[19.1985, -98.3620], [19.1900, -98.3300], [19.1790, -98.2990]],
    [[19.1790, -98.2990], [19.1400, -98.2850], [19.0960, -98.2600]],
    [[19.0960, -98.2600], [19.0600, -98.2500], [19.0280, -98.2330]],
    [[19.0280, -98.2330], [18.9950, -98.2050], [18.9660, -98.1680]],
]
BARRERAS = [
    # id, nombre, lat, lng, llenado %, nivel, nivel máximo, días desde el último vaciado
    ("B1", "Barranca Xaltonac", 19.0420, -98.1950, 46, 0.6, 2.2, 2),
    ("B2", "Río Alseseca", 19.0560, -98.1650, 81, 0.9, 2.5, 5),
    ("B3", "Barranca del Conde", 19.0730, -98.2030, 28, 0.5, 2.0, 1),
]
TEXTOS = {
    "Agua de color": "El agua bajó azul oscuro y con olor a químico.",
    "Espuma": "Mucha espuma blanca junto al puente.",
    "Basura": "Bolsas, llantas y plástico atorados en la orilla.",
    "Descarga de tubería": "Un tubo descarga agua gris directo al río.",
    "Mal olor": "Olor muy fuerte desde la mañana.",
    "Animal muerto": "Hay peces muertos en la orilla.",
}
CUENTAS_DEMO = [
    ("admin@vigia.demo", "Administración (demo)", "admin"),
    ("ambiental@vigia.demo", "Autoridad ambiental (demo)", "ambiental"),
    ("limpia@vigia.demo", "Limpia municipal (demo)", "limpia"),
    ("pc@vigia.demo", "Protección Civil (demo)", "pc"),
    ("tec@vigia.demo", "Tecnológico (demo)", "tec"),
    ("ciudadana@vigia.demo", "Ciudadana (demo)", "ciudadano"),
]
ARCHIVO_CUENTAS = DATOS / "cuentas_demo.txt"


def catalogo(con) -> None:
    if con.execute("SELECT COUNT(*) AS c FROM nodos").fetchone()["c"]:
        return
    t = ahora()
    with transaccion(con):
        for i, (nid, nombre, lat, lng, bat, cal, tec, base, _) in enumerate(NODOS):
            con.execute("INSERT INTO nodos (id, orden, nombre, lat, lng, bateria, calibrado, tec, base) VALUES (?,?,?,?,?,?,?,?,?)",
                        (nid, i, nombre, lat, lng, bat, t - cal * D, tec, json.dumps(base)))
        for i, puntos in enumerate(CAUCE):
            a, b = NODOS[i], NODOS[i + 1]
            con.execute("INSERT INTO tramos (id, desde, hasta, nombre, puntos) VALUES (?,?,?,?,?)",
                        (f"T{i + 1}", a[0], b[0], a[1].split(" · ")[0] + " → " + b[1].split(" · ")[0], json.dumps(puntos)))
        for bid, nombre, lat, lng, llenado, nivel, nivel_max, dias in BARRERAS:
            con.execute("INSERT INTO barreras (id, nombre, lat, lng, llenado, nivel, nivel_max, ultimo_vaciado, ultima_descarga) VALUES (?,?,?,?,?,?,?,?,?)",
                        (bid, nombre, lat, lng, llenado, nivel, nivel_max, t - dias * D, t - dias * D))


def demostracion(con) -> None:
    """Lecturas, reportes y casos inventados para ensayar. Se puede repetir con el botón «Reiniciar demo»."""
    rng = random.Random(20261123)
    t = ahora()
    with transaccion(con):
        for tabla in ("lecturas", "lotes", "reportes", "casos", "notificaciones", "indice_diario"):
            con.execute(f"DELETE FROM {tabla}")
        # Estado inicial de nodos y barreras
        for nid, _, _, _, bat, cal, _, base, horas in NODOS:
            visita = t - horas * H
            con.execute("UPDATE nodos SET bateria = ?, calibrado = ?, ultima_descarga = ? WHERE id = ?", (bat, t - cal * D, visita, nid))
            filas = lotes.simular(base, visita - 4 * D, visita, bateria=bat, semilla=rng.random())
            lote = con.execute("INSERT INTO lotes (nodo, subido, archivo, filas, nuevas, invalidas, desde, hasta, integridad, eventos, casos, checklist) "
                               "VALUES (?,?,?,?,?,0,?,?,'verificada',0,'[]','{}')",
                               (nid, visita, f"{nid}_demo.csv", len(filas), len(filas), filas[0]["t"], filas[-1]["t"])).lastrowid
            con.executemany("INSERT INTO lecturas (nodo, t, ph, cond, turb, color, temp, nivel, lote) VALUES (?,?,?,?,?,?,?,?,?)",
                            [(nid, f["t"], f["ph"], f["cond"], f["turb"], f["color"], f["temp"], f["nivel"], lote) for f in filas])
        for bid, _, _, _, llenado, nivel, _, dias in BARRERAS:
            con.execute("UPDATE barreras SET llenado = ?, nivel = ?, ultimo_vaciado = ?, ultima_descarga = ? WHERE id = ?",
                        (llenado, nivel, t - dias * D, t - 12 * H, bid))

        # Reportes de la app
        anclas = [p for tramo in CAUCE for p in tramo] + [[b[2], b[3]] for b in BARRERAS] * 2
        barreras = {(b[2], b[3]) for b in BARRERAS}
        reportes = []
        for i in range(34):
            a = rng.choice(anclas)
            cat = rng.choice(motor.CATEGORIAS)
            if tuple(a) in barreras and rng.random() < 0.7:
                cat = "Basura"
            reportes.append((f"R-{1201 + i}", cat, cat, round(0.72 + rng.random() * 0.26, 2), a[0] + (rng.random() - 0.5) * 0.02,
                             a[1] + (rng.random() - 0.5) * 0.02, t - int(rng.random() * 7 * D), rng.choice(motor.ESTADOS_REPORTE[:4]),
                             int(rng.random() < 0.35), int(rng.random() < 0.2), TEXTOS[cat]))
        # Dos reportes recientes cerca de Xoxtla: sirven para mostrar el cruce con los sensores
        reportes.append(("R-1240", "Agua de color", "Agua de color", 0.94, 19.1852, -98.3090, t - 40 * 60 * 1000, "Recibido", 0, 1,
                         "Nota de voz: «el río viene azul, como tinta, desde hace rato»."))
        reportes.append(("R-1241", "Espuma", "Espuma", 0.88, 19.1760, -98.2920, t - 25 * 60 * 1000, "Recibido", 1, 0,
                         "Espuma y agua oscura bajo el puente."))
        con.executemany("INSERT INTO reportes (id, cat, ia_etiqueta, ia_confianza, lat, lng, t, estado, anonimo, voz, texto) VALUES (?,?,?,?,?,?,?,?,?,?,?)", reportes)

        # Casos de ejemplo en distintos estados
        def ev(dt, quien, que):
            return {"t": t - int(dt), "who": quien, "what": que}

        casos = [
            dict(id="VA-2026-0007", tipo="descarga", estado="En atención", prioridad="Alta", t=t - 20 * H, tramo="T5", nodo="N6",
                 lat=18.99, lng=-98.20, estimado="Doméstica", confianza=0.78, muestra="M-0019",
                 resumen="Turbidez 3.4 veces arriba de lo normal en el nodo de Valsequillo; el nodo de Puebla sur sin cambios.",
                 reportes=["R-1203", "R-1219"], pico={"turb": 238, "cond": 1420, "color": 2.4, "ph": 7.0},
                 historial=[ev(20 * H, "Sistema", "Anomalía detectada en N6; muestra M-0019 tomada"), ev(19 * H, "Sistema", "Caso asignado a Autoridad ambiental"),
                            ev(6 * H, "Autoridad ambiental", "En atención: se solicita inspección del colector")]),
            dict(id="VA-2026-0006", tipo="basura", estado="Nuevo", prioridad="Media", t=t - 9 * H, lat=19.094, lng=-98.262,
                 estimado="Residuo sólido", confianza=0.86, resumen="Reportes con foto de basura acumulada en la orilla, cerca del Periférico.",
                 reportes=["R-1207", "R-1212", "R-1222"], historial=[ev(9 * H, "Sistema", "Agrupamiento de reportes; caso asignado a Limpia municipal")]),
            dict(id="VA-2026-0005", tipo="recurrente", estado="Nuevo", prioridad="Media", t=t - 30 * H, lat=19.181, lng=-98.305,
                 estimado="Basura y espuma recurrentes", confianza=0.8,
                 resumen="Zona con reportes repetidos en las últimas tres semanas. Se propone jornada de limpieza.",
                 reportes=["R-1205"], historial=[ev(30 * H, "Sistema", "Punto crítico recurrente detectado; propuesta de jornada ciudadana")]),
            dict(id="VA-2026-0002", tipo="basura", estado="En atención", prioridad="Alta", t=t - 2 * D, barrera="B2", lat=19.0560, lng=-98.1650,
                 estimado="Barrera llena", confianza=0.97, resumen="La barrera del río Alseseca llegó a 92% de llenado.",
                 historial=[ev(2 * D, "Barrera B2", "Llenado 92%"), ev(2 * D - 2 * H, "Limpia municipal", "Cuadrilla asignada, ruta enviada")]),
            dict(id="VA-2026-0001", tipo="descarga", estado="Inspección programada", prioridad="Alta", t=t - 3 * D, tramo="T2", nodo="N3",
                 lat=19.19, lng=-98.33, estimado="Textil", confianza=0.91, muestra="M-0011",
                 resumen="Color a 620 nm 3 veces arriba de lo normal y conductividad de 2,650 µS/cm en Xoxtla; el nodo de Huejotzingo sin cambios. "
                         "Coincide con 3 reportes de agua azul.",
                 reportes=["R-1201", "R-1214", "R-1226"], pico={"color": 7.8, "cond": 2650, "ph": 9.3, "turb": 88},
                 historial=[ev(3 * D, "Sistema", "Anomalía detectada en N3; muestra M-0011 tomada"),
                            ev(3 * D - 10 * 60 * 1000, "Sistema", "Confianza alta por 3 reportes cercanos; caso asignado"),
                            ev(2 * D, "Autoridad ambiental", "Inspección programada al tramo Huejotzingo → Xoxtla")]),
            dict(id="VA-2026-0004", tipo="descarga", estado="Cerrado", prioridad="Alta", t=t - 9 * D, cerrado=t - int(6.5 * D), tramo="T4", nodo="N5",
                 lat=19.06, lng=-98.25, estimado="Otra (industrial)", confianza=0.74, muestra="M-0007",
                 lab="DQO 410 mg/L; fuera de norma. Se clausuró la descarga.", resumen="pH 5.6 y conductividad alta en Puebla sur.",
                 pico={"ph": 5.6, "cond": 2310, "color": 2.1, "turb": 95},
                 historial=[ev(9 * D, "Sistema", "Anomalía detectada en N5"), ev(8 * D, "Autoridad ambiental", "Inspección realizada"),
                            ev(6.5 * D, "Autoridad ambiental", "Laboratorio confirma; caso cerrado")]),
            dict(id="VA-2026-0003", tipo="inundacion", estado="Cerrado", prioridad="Alta", t=t - 12 * D, cerrado=t - int(11.8 * D), barrera="B3",
                 lat=19.0730, lng=-98.2030, estimado="Nivel alto", confianza=0.95,
                 resumen="El nivel en la barranca del Conde llegó a 1.9 m con lluvia fuerte.",
                 historial=[ev(12 * D, "Barrera B3", "Nivel 1.9 m"), ev(12 * D - 5 * 60 * 1000, "Protección Civil", "Alerta enviada a vecinos suscritos"),
                            ev(11.8 * D, "Protección Civil", "Nivel normalizado; caso cerrado")]),
            dict(id="VA-2026-0008", tipo="basura", estado="Cerrado", prioridad="Media", t=t - 6 * D, cerrado=t - int(5.6 * D), barrera="B1",
                 lat=19.0420, lng=-98.1950, estimado="Barrera llena", confianza=0.96, resumen="Barrera de Xaltonac al 88%. Se retiraron 140 kg.",
                 historial=[ev(6 * D, "Barrera B1", "Llenado 88%"), ev(5.6 * D, "Limpia municipal", "Recolección: 140 kg; caso cerrado")]),
        ]
        for c in casos:
            d = {"dep": motor.TIPOS_CASO[c["tipo"]]["dep"], "reportes": [], "confirmado_en": [], "auto": 0, "loc_pendiente": 0}
            d.update(c)
            motor.guardar_caso(con, d)

        # Índice diario de calidad por tramo (0 = muy mala, 100 = buena); T3 empeora en los últimos días
        forma = {"T1": (80, 79, 78), "T2": (66, 63, 60), "T3": (58, 54, 44), "T4": (71, 70, 69), "T5": (73, 72, 71)}
        for tramo, (a, b, c) in forma.items():
            for i in range(20):
                v = a + (b - a) * i / 9 if i < 10 else b + (c - b) * (i - 10) / 9
                con.execute("INSERT INTO indice_diario (tramo, t, v) VALUES (?,?,?)", (tramo, t - (20 - i) * D, round(v + rng.gauss(0, 1.2))))

        guardar_ajuste(con, "seq_caso", 20)
        guardar_ajuste(con, "seq_reporte", 1300)
        guardar_ajuste(con, "seq_muestra", 20)


def cuentas_demo(con) -> None:
    """Crea una cuenta por rol con una contraseña aleatoria y la deja anotada en datos/cuentas_demo.txt."""
    if con.execute("SELECT COUNT(*) AS c FROM usuarios").fetchone()["c"]:
        return
    clave = os.environ.get("VA_DEMO_CLAVE") or secrets.token_urlsafe(9)
    t, hash_clave = ahora(), crear_hash(clave)                 # misma contraseña para todas: se calcula una vez
    with transaccion(con):
        for cuenta, nombre, rol in CUENTAS_DEMO:
            con.execute("INSERT INTO usuarios (cuenta, nombre, rol, hash, demo, creado) VALUES (?,?,?,?,1,?)",
                        (cuenta, nombre, rol, hash_clave, t))
    ARCHIVO_CUENTAS.write_text(
        "Cuentas de demostración de Vigía Atoyac (todas usan la misma contraseña)\n"
        f"Contraseña: {clave}\n\n" + "\n".join(f"{c:24} {r}" for c, _, r in CUENTAS_DEMO) + "\n\n"
        "En la computadora del servidor no hace falta escribirla: la pantalla de inicio de sesión\n"
        "tiene botones «Entrar como…». Desde otro equipo o desde la app, usa cuenta y contraseña.\n",
        encoding="utf-8")


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
