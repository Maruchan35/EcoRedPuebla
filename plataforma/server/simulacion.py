"""Modelo de simulación del río Atoyac y de la estación piloto (datos de demostración).

No son mediciones. Reproducen lo que guardarían los sensores, con los patrones que sí tiene el Alto Atoyac:

- Temporada de lluvias (jun–sep) que se apaga en octubre: hacia noviembre baja el nivel y la turbidez y sube
  la conductividad, porque el río se diluye menos. Las tormentas son vespertinas y el río responde horas después.
- Ciclo diario: el agua se calienta en la tarde y el pH sube un poco con la fotosíntesis.
- Industria textil de San Martín Texmelucan–Huejotzingo: color y conductividad más altos en días hábiles de
  7 a 22 h, con descargas de tinte por lotes a media tarde. Zona urbana de Puebla: drenaje en la mañana y la noche.
- Sensores reales: ruido, picos sueltos (burbujas), ensuciamiento de las sondas ópticas que se corrige al
  limpiarlas en cada visita, batería solar y huecos cuando la batería se agota.
- Estación piloto (tratamiento junto al río): la salida responde a la entrada con retraso y amortiguada,
  los lodos del sedimentador se purgan cada lunes, los filtros se retrolavan solos al tapar y el carbón
  activado se satura y se cambia cada seis semanas.

Es determinista: la misma hora del mismo nodo da siempre el mismo valor, así una visita simulada continúa
justo la serie que ya está guardada.
"""
import math

MIN = 60 * 1000
H = 60 * MIN
D = 24 * H
UTC_A_LOCAL = -6 * H                      # hora del centro, sin horario de verano

# Qué tanto pesa cada fuente de contaminación en cada nodo (0 a 1) y cuántas horas tarda en llegarle una crecida
PERFILES = {
    "N1": {"textil": 0.70, "urbano": 0.25, "retraso": 1.0},
    "N2": {"textil": 1.00, "urbano": 0.10, "retraso": 1.6},
    "N3": {"textil": 0.85, "urbano": 0.30, "retraso": 2.0},
    "N4": {"textil": 0.45, "urbano": 0.60, "retraso": 2.8},
    "N5": {"textil": 0.25, "urbano": 1.00, "retraso": 3.6},
    "N6": {"textil": 0.15, "urbano": 0.70, "retraso": 4.4},
}
GENERICO = {"textil": 0.50, "urbano": 0.30, "retraso": 2.0}

# Eventos: factores sobre el valor del momento (ph es suma) y parámetros que el análisis marca como anomalía
EVENTOS = {
    "descarga": {"ph": 1.9, "cond": 2.7, "turb": 1.6, "color": 3.2, "nivel": 0.0, "min": 12},     # textil (legado)
    "textil": {"ph": 1.9, "cond": 2.7, "turb": 1.6, "color": 3.2, "nivel": 0.0, "min": 12},
    "domestica": {"ph": -0.2, "cond": 1.3, "turb": 3.4, "color": 1.25, "nivel": 0.0, "min": 40},
    "industrial": {"ph": -1.7, "cond": 2.1, "turb": 1.5, "color": 1.2, "nivel": 0.0, "min": 20},
    "crecida": {"ph": 0.0, "cond": 0.9, "turb": 2.4, "color": 1.0, "nivel": 1.9, "min": 30},
}
CAMBIO_GRANDE = {"ph": 0.5, "cond": 0.2, "turb": 0.4, "color": 0.4}      # mismo criterio que motor.detectar

# Estación piloto
CARBON_CADA = 42 * D                       # cambio de carbón activado
CARBON_ANCLA = 1791993600000               # 14 oct 2026 10:00 (hora del centro): un cambio de carbón activado
DP_RETROLAVADO = 24.0                      # kPa: el filtro se retrolava solo al llegar aquí
LODOS_PURGA_URGENTE = 92.0                 # % del sedimentador


# ---------- Azar determinista ----------
# El hash de una tupla de enteros no cambia entre ejecuciones (la aleatorización de Python solo afecta a textos)
_BITS = (1 << 52) - 1


def azar(*claves) -> float:
    """Número en [0, 1) que depende solo de las claves (enteros)."""
    return (hash((0x5EED,) + claves) & _BITS) / float(1 << 52)


def normal(*claves) -> float:
    """Aproximadamente normal(0, 1), determinista."""
    u1 = max(1e-12, azar(*claves, 11))
    return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * azar(*claves, 12))


def suave(semilla: int, t: int, periodo: int) -> float:
    """Ruido en [-1, 1] que cambia poco a poco (interpolación coseno entre nudos cada `periodo` ms)."""
    k, resto = divmod(t, periodo)
    a, b = azar(semilla, k) * 2 - 1, azar(semilla, k + 1) * 2 - 1
    return a + (b - a) * (1 - math.cos(math.pi * resto / periodo)) / 2


def clave(texto: str) -> int:
    return int.from_bytes(str(texto).encode("utf-8")[:8].ljust(8, b"\0"), "big")


# ---------- Calendario (hora del centro) ----------
def dia_local(t: int) -> int:
    return (t + UTC_A_LOCAL) // D


def hora_local(t: int) -> float:
    return ((t + UTC_A_LOCAL) % D) / H


def dia_semana(t: int) -> int:
    """0 = lunes ... 6 = domingo (el 1 ene 1970 fue jueves)."""
    return (dia_local(t) + 3) % 7


def dia_del_anio(t: int) -> int:
    # 2026-01-01 00:00 hora del centro = 1767247200000 ms; basta para los años de la demo
    dias = dia_local(t) - dia_local(1767247200000)
    return dias % 365 + 1


def lluvias(t: int) -> float:
    """Cuánto queda de la temporada de lluvias: 1 a fines de agosto, 0 desde mediados de noviembre."""
    doy = dia_del_anio(t)
    return min(1.0, max(0.0, (318 - doy) / 80.0)) ** 1.3


# ---------- Tormentas (comunes a toda la cuenca) ----------
_TORMENTAS = {}


def tormenta_del_dia(dia: int):
    """(inicio_ms, intensidad) o None. Vespertinas; frecuentes en septiembre, ligeras y raras en noviembre."""
    if dia in _TORMENTAS:
        return _TORMENTAS[dia]
    t_mediodia = dia * D - UTC_A_LOCAL + 12 * H
    s = lluvias(t_mediodia)
    prob = 0.07 + 0.58 * s
    res = None
    if azar(7001, dia) < prob:
        fuerte = azar(7002, dia) ** 1.6
        intensidad = (0.25 + 1.75 * fuerte) if s > 0.25 else min(0.15, 0.05 + 0.1 * fuerte)    # nov: lloviznas
        inicio = dia * D - UTC_A_LOCAL + int((14.5 + 5.5 * azar(7003, dia)) * H)
        res = (inicio, intensidad)
    _TORMENTAS[dia] = res
    return res


def _respuesta(tau: float, sube: float, baja: float) -> float:
    if tau <= 0:
        return 0.0
    pico = sube * math.log(1 + baja / sube)
    norma = (1 - math.exp(-pico / sube)) * math.exp(-pico / baja)
    return (1 - math.exp(-tau / sube)) * math.exp(-tau / baja) / norma


def efecto_lluvia(t: int, retraso_h: float):
    """(subida de nivel en m, factor de turbidez, factor de conductividad) por las tormentas recientes."""
    nivel, turb, cond = 0.0, 0.0, 0.0
    hoy = dia_local(t)
    for dia in range(hoy - 3, hoy + 1):
        st = tormenta_del_dia(dia)
        if not st:
            continue
        tau = t - st[0] - retraso_h * H
        if tau <= 0:
            continue
        i = st[1]
        nivel += 0.55 * i * _respuesta(tau, 0.8 * H, 16 * H)
        turb += 2.3 * i * _respuesta(tau, 0.6 * H, 7 * H)
        cond += 0.10 * i * _respuesta(tau, 1.0 * H, 14 * H)
    return min(nivel, 1.2), 1 + turb, 1 - min(cond, 0.15)


# ---------- Patrones de actividad ----------
def jornada(t: int) -> float:
    """Intensidad de la industria: días hábiles de 7 a 22 h; domingo casi nada."""
    ds, h = dia_semana(t), hora_local(t)
    if ds == 6:
        return 0.12
    sube = 1 / (1 + math.exp(-(h - 7.5) * 2.2))
    baja = 1 / (1 + math.exp((h - 22.0) * 2.2))
    return 0.08 + 0.92 * sube * baja * (0.8 if ds == 5 else 1.0)


def drenaje(t: int) -> float:
    """Aguas domésticas: picos en la mañana y en la noche."""
    h = hora_local(t)
    return math.exp(-((h - 8.0) / 1.2) ** 2 / 2) + 0.8 * math.exp(-((h - 20.5) / 1.5) ** 2 / 2)


def lote_de_tinte(semilla: int, t: int) -> float:
    """Descargas de tinte por lotes: dos al día en días hábiles, entre 10 y 18 h, de 40 a 80 min (0 a 1)."""
    if dia_semana(t) >= 6:
        return 0.0
    dia, h = dia_local(t), hora_local(t)
    v = 0.0
    for k in range(2):
        ini = 10 + 8 * azar(semilla, dia, k)
        dur = (40 + 40 * azar(semilla, dia, k, 1)) / 60
        if ini <= h <= ini + dur:
            borde = min(h - ini, ini + dur - h) / 0.15
            v = max(v, min(1.0, borde))
    return v


def sol(t: int) -> float:
    """Irradiancia relativa (0 a 1): amanece ~6:50; anochece ~19:05 en septiembre y ~17:55 en noviembre."""
    h = hora_local(t)
    s = lluvias(t)
    salida, puesta = 6.85, 17.9 + 1.1 * s
    if not salida < h < puesta:
        return 0.0
    return math.sin(math.pi * (h - salida) / (puesta - salida)) ** 1.3


# ---------- Río ----------
def _evento_en(eventos, t):
    """Evento activo en t: (tipo, intensidad 0..1 con rampas, folio, inicio)."""
    for ini, tipo, fuerza, minutos, folio in eventos:
        fin = ini + minutos * MIN
        if ini <= t < fin:
            forma = min(1.0, (t - ini) / (3 * MIN), (fin - t) / (5 * MIN))
            return tipo, fuerza * max(0.0, forma), folio, ini
    return None


def simular(base: dict, desde_ms: int, hasta_ms: int, evento: str = "normal", bateria: int = 80, folio: str = "",
            semilla=None, *, nodo=None, estacion=False, eventos=(), bateria_inicio=None, huecos=()) -> list:
    """Lecturas como las guardaría el nodo: cada 10 min, y cada minuto mientras hay una anomalía.

    `eventos`: [(inicio_ms, tipo, fuerza, minutos, folio)]. Con `evento` = "descarga" | "crecida" (forma antigua)
    se agrega uno al final del periodo, como al simular la visita. Cada fila trae `_anom` con los parámetros que
    se salen de lo normal (lo que marcaría el análisis)."""
    perfil = PERFILES.get(nodo, GENERICO)
    sid = clave(nodo) if nodo else int((semilla or 0.5) * 1e9)
    eventos = list(eventos)
    if evento in ("descarga", "crecida"):
        ev = EVENTOS[evento]
        eventos.append((hasta_ms - 10 * MIN - ev["min"] * MIN, evento, 1.0, ev["min"], folio))
    eventos.sort()

    # Tiempos: cada 10 min alineados al reloj, cada minuto dentro de un evento
    paso = 10 * MIN
    tiempos, t = [], desde_ms - desde_ms % paso + (paso if desde_ms % paso else 0)
    marcas = set()
    for ini, tipo, _f, minutos, _fo in eventos:
        k = ini - ini % MIN
        while k < ini + minutos * MIN:
            if desde_ms <= k <= hasta_ms:
                marcas.add(k)
            k += MIN
    while t <= hasta_ms:
        marcas.add(t)
        t += paso
    tiempos = sorted(m for m in marcas if not any(a <= m < b for a, b in huecos))

    b_ini = bateria if bateria_inicio is None else bateria_inicio
    est = _Estacion(sid) if estacion else None
    filas, muestra_usada = [], set()
    for t in tiempos:
        s = lluvias(t)
        sube_nivel, f_turb_lluvia, f_cond_lluvia = efecto_lluvia(t, perfil["retraso"])
        j, dren = jornada(t), drenaje(t)
        tinte = lote_de_tinte(sid, t) * perfil["textil"]
        dias_sin_limpiar = (t - desde_ms) / D

        nivel = base["nivel"] + 0.45 * s + sube_nivel + 0.015 * suave(sid + 1, t, 3 * H) + 0.006 * normal(sid, t, 1)
        cond = (base["cond"] * (1 - 0.17 * s) * f_cond_lluvia * (1 + 0.09 * perfil["textil"] * j + 0.04 * perfil["urbano"] * dren)
                * (1 + 0.03 * suave(sid + 2, t, 5 * H)) + base["cond"] * 0.012 * normal(sid, t, 2))
        turb = (base["turb"] * (1 + 0.55 * s) * (f_turb_lluvia if perfil["urbano"] < 0.5 else 1 + (f_turb_lluvia - 1) * 1.35)
                * (1 + 0.16 * perfil["urbano"] * dren) * (1 + 0.006 * dias_sin_limpiar)
                * (1 + 0.06 * suave(sid + 3, t, 2 * H)) + base["turb"] * 0.03 * normal(sid, t, 3))
        color = (base["color"] * (1 + 0.12 * perfil["textil"] * j + 0.20 * tinte) * (1 + 0.1 * (f_turb_lluvia - 1))
                 * (1 + 0.005 * dias_sin_limpiar) * (1 + 0.04 * suave(sid + 4, t, 3 * H)) + 0.05 * normal(sid, t, 4))
        h = hora_local(t)
        temp = (base["temp"] + 2.3 * min(1.0, max(0.0, (330 - dia_del_anio(t)) / 90)) + 1.35 * math.sin(2 * math.pi * (h - 9.5) / 24)
                - 0.6 * (sube_nivel > 0.1) + 0.08 * normal(sid, t, 5))
        ph = base["ph"] + 0.11 * math.sin(2 * math.pi * (h - 10) / 24) + 0.05 * suave(sid + 5, t, 4 * H) + 0.03 * normal(sid, t, 6)
        if azar(sid, t, 99) < 0.003:
            turb *= 2.2 + azar(sid, t, 98)                           # burbuja o basura frente a la sonda: un solo dato

        anom = []
        act = _evento_en(eventos, t)
        if act:
            tipo, fuerza, fo, ini = act
            ev = EVENTOS[tipo]
            ph += ev["ph"] * fuerza
            cond *= ev["cond"] ** fuerza
            turb *= ev["turb"] ** fuerza
            color *= ev["color"] ** fuerza
            nivel += ev["nivel"] * fuerza
            for k in ("ph", "cond", "turb", "color"):
                cambio = abs(ev[k] * fuerza) if k == "ph" else abs(ev[k] ** fuerza - 1)
                if cambio >= CAMBIO_GRANDE[k]:
                    anom.append(k)

        frac = (t - desde_ms) / max(1, hasta_ms - desde_ms)
        bat = b_ini + (bateria - b_ini) * frac + 7 * math.sin(2 * math.pi * (h - 9) / 24)
        if bat < 12:
            continue                                                  # el registrador se apaga hasta que vuelve el sol
        fila = {
            "t": t,
            "ph": round(min(14, max(0, ph)), 2),
            "cond": round(max(30, cond)),
            "turb": max(1, round(turb)),
            "color": round(max(0.2, color), 2),
            "temp": round(temp, 1),
            "nivel": round(max(0.05, nivel), 2),
            "bateria": int(min(100, max(0, round(bat)))),
            "muestra": None,
            "_anom": anom,
        }
        if act and act[2] and act[3] not in muestra_usada and t >= act[3] + MIN and anom:
            fila["muestra"] = act[2]                                  # el carrusel llena un frasco al confirmar
            muestra_usada.add(act[3])
        if est:
            fila.update(est.paso(t, fila, s))
        filas.append(fila)
    return filas


# ---------- Estación piloto: captación → tamiz → sedimentador → filtros → humedal → río ----------
class _Estacion:
    def __init__(self, sid):
        self.sid = sid
        self.t = None
        self.ema = {}
        self.lodos = 34.0
        self.dp = 11.0
        self.parada_hasta = 0

    def _suaviza(self, k, v, t, tau):
        if k not in self.ema or self.t is None:
            self.ema[k] = v
        else:
            a = 1 - math.exp(-(t - self.t) / tau)
            self.ema[k] += a * (v - self.ema[k])
        return self.ema[k]

    def paso(self, t, r, s):
        h, dsem = hora_local(t), dia_semana(t)
        dt_pasos = 1.0 if self.t is None else min(6.0, (t - self.t) / (10 * MIN))
        # Purga de lodos los lunes 10:00–10:40, o antes si el sedimentador se llena; retrolavado al tapar el filtro
        if (dsem == 0 and 10.0 <= h < 10.67) or self.lodos >= LODOS_PURGA_URGENTE:
            if self.lodos > 15:
                self.parada_hasta = t + 40 * MIN
            self.lodos = 6 + 3 * azar(self.sid, dia_local(t), 31)
        if self.dp >= DP_RETROLAVADO:
            self.dp = 6.2 + 0.8 * azar(self.sid, t, 32)
            self.parada_hasta = max(self.parada_hasta, t + 20 * MIN)
        parada = t < self.parada_hasta

        caudal = 0.0 if parada else max(0.12, min(0.34, 0.17 + 0.16 * (r["nivel"] - 0.9) + 0.012 * normal(self.sid, t, 33)))
        turb_in, color_in = r["turb"], r["color"]
        # Carga al sedimentador y a los filtros (crecen con la turbidez y el caudal)
        carga = (turb_in / 60) * (caudal / 0.25) * dt_pasos
        self.lodos = min(100.0, self.lodos + 0.0625 * carga)
        self.dp = self.dp + 0.07 * (turb_in * 0.45 / 27) * (caudal / 0.25) * dt_pasos

        edad_carbon = (t - CARBON_ANCLA) % CARBON_CADA
        efic_color = 0.74 - 0.30 * (edad_carbon / CARBON_CADA) ** 1.2
        lodos_alto = max(0.0, (self.lodos - 75) / 25)
        f_turb = 0.45 * (1 + 0.35 * lodos_alto) * 0.38 * (0.55 + 0.01 * max(0.0, 17 - r["temp"]))
        turb_sal = self._suaviza("turb", turb_in, t, 9 * H) * f_turb + 0.25 * normal(self.sid, t, 34)
        color_sal = self._suaviza("color", color_in, t, 11 * H) * (1 - efic_color) * 0.85 + 0.03 * normal(self.sid, t, 35)
        cond_sal = self._suaviza("cond", r["cond"], t, 14 * H) * (0.975 + 0.008 * math.sin(2 * math.pi * (h - 14) / 24))
        ph_sal = (7.35 + 0.35 * (self._suaviza("ph", r["ph"], t, 14 * H) - 7.25) + 0.12 * math.sin(2 * math.pi * (h - 11) / 24)
                  + 0.025 * normal(self.sid, t, 36))
        nubes = 1 - 0.45 * max(0.0, suave(self.sid + 40, t, 2 * H)) - 0.35 * s * (azar(7001, dia_local(t)) < 0.07 + 0.58 * s)
        solar = 128 * sol(t) * max(0.15, nubes) + (1.5 * normal(self.sid, t, 37) if sol(t) > 0 else 0)
        self.t = t
        return {"caudal": round(caudal, 3), "turb_sal": round(max(1.2, turb_sal), 1), "color_sal": round(max(0.15, color_sal), 2),
                "cond_sal": round(cond_sal), "ph_sal": round(ph_sal, 2), "lodos": round(self.lodos, 1),
                "dp_filtro": round(self.dp, 1), "solar": round(max(0.0, solar), 1)}
