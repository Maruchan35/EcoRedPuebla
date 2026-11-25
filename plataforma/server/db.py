"""Base de datos (SQLite) de Vigía Atoyac.

Una sola conexión, usada solo desde el hilo principal: por eso todos los endpoints
y dependencias de main.py son `async def` (FastAPI ejecuta las funciones `def` en
otros hilos). Si alguien agrega una función `def` que toque la base, SQLite lo
rechaza con un error claro en vez de fallar de vez en cuando.
En la propuesta de implementación se cambia por PostgreSQL + PostGIS.
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DATOS = Path(os.environ.get("VA_DATOS") or RAIZ / "datos")
FOTOS = DATOS / "fotos"
RUTA_BD = DATOS / "vigia.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  cuenta        TEXT NOT NULL UNIQUE,          -- correo o teléfono, en minúsculas
  nombre        TEXT NOT NULL,
  rol           TEXT NOT NULL,                 -- ciudadano | ambiental | limpia | pc | tec | admin
  hash          TEXT NOT NULL,                 -- pbkdf2_sha256$iteraciones$sal$derivada
  activo        INTEGER NOT NULL DEFAULT 1,
  demo          INTEGER NOT NULL DEFAULT 0,
  creado        INTEGER NOT NULL,
  ultimo_acceso INTEGER,
  permisos      TEXT,                          -- JSON con los módulos de esta persona; NULL = los de su rol
  cambiar_clave INTEGER NOT NULL DEFAULT 0     -- 1 = entró con contraseña temporal y debe cambiarla
);
CREATE TABLE IF NOT EXISTS accesos (           -- bitácora de inicios de sesión (correctos y fallidos)
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  t          INTEGER NOT NULL,
  usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
  cuenta     TEXT NOT NULL,
  ip         TEXT,
  resultado  TEXT NOT NULL                     -- ok | clave | desactivada | bloqueo | salida
);
CREATE TABLE IF NOT EXISTS sesiones (
  token_hash TEXT PRIMARY KEY,                 -- SHA-256 del token; el token nunca se guarda
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  origen     TEXT NOT NULL,                    -- web | app
  creado     INTEGER NOT NULL,
  expira     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS nodos (
  id TEXT PRIMARY KEY, orden INTEGER NOT NULL, nombre TEXT NOT NULL,
  lat REAL NOT NULL, lng REAL NOT NULL, bateria INTEGER, calibrado INTEGER, tec TEXT,
  base TEXT NOT NULL,                          -- valores normales del sitio (JSON)
  ultima_descarga INTEGER                      -- última visita de Protección Civil
);
CREATE TABLE IF NOT EXISTS tramos (
  id TEXT PRIMARY KEY, desde TEXT NOT NULL, hasta TEXT NOT NULL, nombre TEXT NOT NULL, puntos TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS barreras (
  id TEXT PRIMARY KEY, nombre TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
  llenado REAL NOT NULL, nivel REAL NOT NULL, nivel_max REAL NOT NULL,
  ultimo_vaciado INTEGER, ultima_descarga INTEGER
);
CREATE TABLE IF NOT EXISTS lotes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, nodo TEXT NOT NULL, usuario_id INTEGER, subido INTEGER NOT NULL,
  archivo TEXT, filas INTEGER, nuevas INTEGER, invalidas INTEGER, desde INTEGER, hasta INTEGER,
  integridad TEXT, eventos INTEGER, casos TEXT, checklist TEXT
);
CREATE TABLE IF NOT EXISTS lecturas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, nodo TEXT NOT NULL, t INTEGER NOT NULL,
  ph REAL, cond REAL, turb REAL, color REAL, temp REAL, nivel REAL,
  anom TEXT NOT NULL DEFAULT '[]', muestra TEXT, lote INTEGER,
  -- Solo en nodos con estación de tratamiento (sensores de salida y del proceso); NULL en los demás
  caudal REAL, turb_sal REAL, color_sal REAL, cond_sal REAL, ph_sal REAL, lodos REAL, dp_filtro REAL, solar REAL,
  UNIQUE (nodo, t)
);
CREATE TABLE IF NOT EXISTS vaciados (          -- cada vez que la cuadrilla vacía una barrera
  id INTEGER PRIMARY KEY AUTOINCREMENT, barrera TEXT NOT NULL, t INTEGER NOT NULL, kg REAL NOT NULL, quien TEXT
);
CREATE TABLE IF NOT EXISTS reportes (
  id TEXT PRIMARY KEY, usuario_id INTEGER, cat TEXT NOT NULL,
  ia_etiqueta TEXT, ia_confianza REAL,
  lat REAL NOT NULL, lng REAL NOT NULL, t INTEGER NOT NULL, estado TEXT NOT NULL,
  anonimo INTEGER NOT NULL DEFAULT 0, voz INTEGER NOT NULL DEFAULT 0, texto TEXT, foto TEXT
);
CREATE TABLE IF NOT EXISTS casos (
  id TEXT PRIMARY KEY, tipo TEXT NOT NULL, dep TEXT NOT NULL, estado TEXT NOT NULL, prioridad TEXT NOT NULL,
  t INTEGER NOT NULL, cerrado INTEGER, tramo TEXT, nodo TEXT, barrera TEXT, lat REAL, lng REAL,
  estimado TEXT, confianza REAL, muestra TEXT, resumen TEXT, lab TEXT,
  pico TEXT, reportes TEXT NOT NULL DEFAULT '[]', historial TEXT NOT NULL DEFAULT '[]',
  confirmado_en TEXT NOT NULL DEFAULT '[]',
  auto INTEGER NOT NULL DEFAULT 0, evento_t INTEGER, evento_fin INTEGER, evento TEXT, loc_pendiente INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notificaciones (
  id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  t INTEGER NOT NULL, titulo TEXT NOT NULL, texto TEXT NOT NULL, leida INTEGER NOT NULL DEFAULT 0,
  caso TEXT, reporte TEXT
);
CREATE TABLE IF NOT EXISTS indice_diario (tramo TEXT NOT NULL, t INTEGER NOT NULL, v INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_lecturas_nodo_t ON lecturas (nodo, t);
CREATE INDEX IF NOT EXISTS ix_reportes_t ON reportes (t);
CREATE INDEX IF NOT EXISTS ix_sesiones_usuario ON sesiones (usuario_id);
CREATE INDEX IF NOT EXISTS ix_accesos_t ON accesos (t);
CREATE INDEX IF NOT EXISTS ix_vaciados_t ON vaciados (t);
CREATE INDEX IF NOT EXISTS ix_casos_t ON casos (t);
"""

# Columnas agregadas después de la primera versión: las bases que ya existían las reciben al arrancar
_COLUMNAS_NUEVAS = {
    "usuarios": {"permisos": "TEXT", "cambiar_clave": "INTEGER NOT NULL DEFAULT 0"},
    "lecturas": {c: "REAL" for c in ("caudal", "turb_sal", "color_sal", "cond_sal", "ph_sal", "lodos", "dp_filtro", "solar")},
}


def ahora() -> int:
    """Milisegundos desde 1970 (el mismo formato que usa la web)."""
    return int(time.time() * 1000)


def conectar() -> sqlite3.Connection:
    DATOS.mkdir(parents=True, exist_ok=True)
    FOTOS.mkdir(exist_ok=True)
    con = sqlite3.connect(RUTA_BD, isolation_level=None)       # check_same_thread=True: candado contra usos desde otro hilo
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    for tabla, columnas in _COLUMNAS_NUEVAS.items():           # antes del esquema: sus índices pueden usarlas
        existentes = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
        for nombre, tipo in columnas.items():
            if existentes and nombre not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
    con.executescript(ESQUEMA)
    return con


@contextmanager
def transaccion(con: sqlite3.Connection):
    """Todo o nada: si algo falla a la mitad, no queda un lote a medias."""
    con.execute("BEGIN")
    try:
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def leer_ajuste(con, clave, defecto=None):
    f = con.execute("SELECT valor FROM ajustes WHERE clave = ?", (clave,)).fetchone()
    return json.loads(f["valor"]) if f else defecto


def guardar_ajuste(con, clave, valor):
    con.execute("INSERT INTO ajustes (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, json.dumps(valor)))


def siguiente(con, clave, inicio) -> int:
    """Contador persistente para folios (casos, reportes, muestras)."""
    n = leer_ajuste(con, "seq_" + clave, inicio) + 1
    guardar_ajuste(con, "seq_" + clave, n)
    return n
