"""Archivo de la microSD: lectura, validación, huella encadenada y generador de ejemplos.

Formato del CSV (lo escribe el firmware del nodo; ver docs/formato-lote.md):

    t,ph,cond,turb,color,temp,nivel,bateria,muestra,hash
    2026-11-23T21:40:00-06:00,7.21,985,56,3.41,18.4,1.10,74,,9f2c...

Huella encadenada (opcional): hash_i = SHA-256( hash_{i-1} + "|" + "t,ph,cond,turb,color,temp,nivel" )
con el texto tal cual está en el archivo y hash_0 = id del nodo. Si alguien cambia una fila,
todas las huellas siguientes dejan de coincidir.

Los nodos con estación de tratamiento agregan columnas opcionales del proceso (ver ESTACION); no entran en
la huella, así un archivo de un nodo sin estación y uno con estación se validan igual.
"""
import csv
import hashlib
import io
import json
from datetime import datetime

from .motor import TZ
from .simulacion import EVENTOS, simular  # noqa: F401  (el generador vive en simulacion.py)

MAX_BYTES = 5 * 1024 * 1024
MAX_FILAS = 60000
MEDIDAS = ("ph", "cond", "turb", "color", "temp", "nivel")
# Estación piloto: caudal (L/s), salida tratada, lodos del sedimentador (%), presión de filtros (kPa), panel solar (W)
ESTACION = ("caudal", "turb_sal", "color_sal", "cond_sal", "ph_sal", "lodos", "dp_filtro", "solar")
# Fuera de estos rangos físicos el valor se descarta (sonda desconectada o dañada)
RANGOS = {"ph": (0, 14), "cond": (0, 100000), "turb": (0, 10000), "color": (0, 1000), "temp": (-5, 60), "nivel": (0, 20),
          "caudal": (0, 50), "turb_sal": (0, 10000), "color_sal": (0, 1000), "cond_sal": (0, 100000), "ph_sal": (0, 14),
          "lodos": (0, 100), "dp_filtro": (0, 500), "solar": (0, 2000)}
ALIAS = {"fecha_hora": "t", "fecha": "t", "timestamp": "t", "hora": "t", "conductividad": "cond", "tds": "cond",
         "turbidez": "turb", "color620": "color", "temperatura": "temp", "bat": "bateria", "batería": "bateria",
         "folio": "muestra", "huella": "hash"}


def _tiempo(txt: str):
    txt = txt.strip()
    if not txt:
        return None
    try:
        n = float(txt)
        return int(n * 1000) if n < 1e11 else int(n)          # segundos o milisegundos
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(txt.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)                               # el reloj del nodo va en hora del centro
    return int(d.timestamp() * 1000)


def _numero(txt, punto_y_coma: bool):
    txt = (txt or "").strip()
    if not txt:
        return None
    if punto_y_coma:
        txt = txt.replace(",", ".")                            # Excel en español: 7,21
    try:
        v = float(txt)
    except ValueError:
        return None
    return v if v == v and abs(v) != float("inf") else None


def huella(previa: str, crudo: dict) -> str:
    linea = ",".join((crudo.get(k) or "").strip() for k in ("t",) + MEDIDAS)
    return hashlib.sha256(f"{previa}|{linea}".encode("utf-8")).hexdigest()


def leer_csv(contenido: bytes, nodo_id: str, ahora_ms: int) -> dict:
    """Devuelve {filas, invalidas, integridad}. Lanza ValueError si el archivo no se puede usar."""
    if len(contenido) > MAX_BYTES:
        raise ValueError("El archivo pesa más de 5 MB.")
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")
    primera = texto.split("\n", 1)[0]
    punto_y_coma = primera.count(";") > primera.count(",")
    lector = csv.reader(io.StringIO(texto), delimiter=";" if punto_y_coma else ",")
    try:
        encabezado = [ALIAS.get(c.strip().lower(), c.strip().lower()) for c in next(lector)]
    except StopIteration:
        raise ValueError("El archivo está vacío.")
    if "t" not in encabezado or not any(m in encabezado for m in MEDIDAS):
        raise ValueError("Falta la columna de fecha y hora (t) o las columnas de medición. Revisa el formato del archivo.")

    filas, invalidas, vistos = [], 0, set()
    previa, con_huella, alterada = nodo_id, False, None
    for n, celdas in enumerate(lector, start=1):
        if not any(c.strip() for c in celdas):
            continue
        if n > MAX_FILAS:
            raise ValueError(f"El archivo tiene más de {MAX_FILAS:,} filas; súbelo en partes.")
        crudo = dict(zip(encabezado, celdas))
        if (crudo.get("hash") or "").strip():
            con_huella = True
            esperada = huella(previa, crudo)
            if alterada is None and esperada != crudo["hash"].strip().lower():
                alterada = n
            previa = crudo["hash"].strip().lower()
        t = _tiempo(crudo.get("t", ""))
        fila = {"t": t}
        for m in MEDIDAS:
            v = _numero(crudo.get(m), punto_y_coma)
            fila[m] = v if v is not None and RANGOS[m][0] <= v <= RANGOS[m][1] else None
        # Hora imposible (reloj sin pila), fila sin mediciones o repetida: no se guarda
        if t is None or t > ahora_ms + 10 * 60 * 1000 or t < 1577836800000 or t in vistos or all(fila[m] is None for m in MEDIDAS):
            invalidas += 1
            continue
        vistos.add(t)
        bat = _numero(crudo.get("bateria"), punto_y_coma)
        fila["bateria"] = bat if bat is not None and 0 <= bat <= 100 else None
        fila["muestra"] = (crudo.get("muestra") or "").strip()[:20] or None
        for m in ESTACION:
            if m in crudo:
                v = _numero(crudo.get(m), punto_y_coma)
                fila[m] = v if v is not None and RANGOS[m][0] <= v <= RANGOS[m][1] else None
        filas.append(fila)
    if not filas:
        raise ValueError("Ninguna fila del archivo tiene fecha y mediciones válidas.")
    filas.sort(key=lambda f: f["t"])
    integridad = "sin_huella" if not con_huella else ("alterada:%d" % alterada if alterada else "verificada")
    return {"filas": filas, "invalidas": invalidas, "integridad": integridad}


# ---------- Archivo como lo escribe el nodo (también para la demo y el archivo de ejemplo) ----------
def a_csv(nodo_id: str, filas: list) -> str:
    """Escribe el archivo como lo haría el nodo, con la huella encadenada. Si las filas traen datos de la
    estación de tratamiento, agrega sus columnas antes de la huella."""
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\n")
    con_estacion = any(f.get("caudal") is not None for f in filas)
    extra = ESTACION if con_estacion else ()
    w.writerow(("t",) + MEDIDAS + ("bateria", "muestra") + extra + ("hash",))
    previa = nodo_id
    for f in filas:
        crudo = {"t": datetime.fromtimestamp(f["t"] / 1000, TZ).isoformat(timespec="seconds")}
        crudo.update({m: "" if f[m] is None else str(f[m]) for m in MEDIDAS})
        previa = huella(previa, crudo)
        w.writerow([crudo["t"]] + [crudo[m] for m in MEDIDAS] + [f.get("bateria") if f.get("bateria") is not None else "", f.get("muestra") or ""]
                   + ["" if f.get(m) is None else f[m] for m in extra] + [previa])
    return salida.getvalue()


def csv_abierto(filas: list) -> str:
    """Datos abiertos: las lecturas ya guardadas, con la marca de anomalía del análisis. Sin huella:
    la huella original solo vale para el archivo de la microSD."""
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\n")
    extra = ESTACION if any(f["caudal"] is not None for f in filas if "caudal" in f.keys()) else ()
    w.writerow(("t",) + MEDIDAS + extra + ("anomalia",))
    for f in filas:
        w.writerow([datetime.fromtimestamp(f["t"] / 1000, TZ).isoformat(timespec="seconds")]
                   + ["" if f[m] is None else f[m] for m in MEDIDAS + extra] + [" ".join(json.loads(f["anom"] or "[]"))])
    return salida.getvalue()
