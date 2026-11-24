"""Contraseñas, sesiones y roles.

- Las contraseñas se guardan con PBKDF2-HMAC-SHA256 y sal aleatoria (biblioteca estándar).
- La sesión es un token aleatorio; en la base solo se guarda su SHA-256.
- La web lo recibe en una cookie HttpOnly; la app móvil lo manda como `Authorization: Bearer`.
"""
import hashlib
import hmac
import re
import secrets
import time

from .db import ahora

COOKIE = "va_sesion"
ITERACIONES = 600_000
DURACION_MS = {"web": 12 * 3600 * 1000, "app": 30 * 24 * 3600 * 1000}

# Rol -> etiqueta y dependencias cuyos casos puede ver y actualizar
ROLES = {
    "ciudadano": {"label": "Ciudadanía", "deps": []},
    "ambiental": {"label": "Autoridad ambiental", "deps": ["ambiental"]},
    "limpia": {"label": "Limpia municipal", "deps": ["limpia", "brigadas"]},
    "pc": {"label": "Protección Civil", "deps": ["pc"]},
    "tec": {"label": "Tecnológicos", "deps": []},
    "admin": {"label": "Administración", "deps": ["ambiental", "limpia", "pc", "brigadas"]},
}
PERSONAL = {"ambiental", "limpia", "pc", "tec", "admin"}      # todo menos ciudadanía
RECOLECCION = {"pc", "tec", "admin"}                          # quienes visitan nodos y suben lotes

_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_TEL = re.compile(r"^\d{10}$")


def normalizar_cuenta(cuenta: str) -> str:
    """Correo en minúsculas o teléfono de 10 dígitos. Lanza ValueError si no es ninguno."""
    c = (cuenta or "").strip().lower()
    solo_digitos = re.sub(r"[\s\-()+]", "", c)
    if _RE_TEL.match(solo_digitos):
        return solo_digitos
    if _RE_CORREO.match(c) and len(c) <= 120:
        return c
    raise ValueError("Escribe un correo o un teléfono de 10 dígitos.")


def validar_clave(clave: str, cuenta: str = "") -> None:
    if len(clave) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    if len(clave) > 128:
        raise ValueError("La contraseña es demasiado larga.")
    if cuenta and clave.lower() == cuenta.lower():
        raise ValueError("La contraseña no puede ser igual a la cuenta.")


def crear_hash(clave: str) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal.hex()}${dk.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, iteraciones, sal, dk = guardado.split("$")
        calculado = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal), int(iteraciones))
        return hmac.compare_digest(calculado.hex(), dk)
    except (ValueError, TypeError):
        return False


# Se usa cuando la cuenta no existe, para que la respuesta tarde lo mismo que con una cuenta real
_HASH_SENUELO = crear_hash(secrets.token_urlsafe(16))


def gastar_tiempo(clave: str) -> None:
    verificar_clave(clave, _HASH_SENUELO)


def _huella(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def abrir_sesion(con, usuario_id: int, origen: str = "web") -> tuple:
    """Crea la sesión y devuelve (token, segundos de vida)."""
    origen = origen if origen in DURACION_MS else "web"
    token = secrets.token_urlsafe(32)
    t = ahora()
    con.execute("DELETE FROM sesiones WHERE expira < ?", (t,))
    con.execute("INSERT INTO sesiones (token_hash, usuario_id, origen, creado, expira) VALUES (?, ?, ?, ?, ?)",
                (_huella(token), usuario_id, origen, t, t + DURACION_MS[origen]))
    con.execute("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?", (t, usuario_id))
    return token, DURACION_MS[origen] // 1000


def usuario_de_token(con, token: str):
    if not token:
        return None
    return con.execute(
        """SELECT u.id, u.cuenta, u.nombre, u.rol, u.demo FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.token_hash = ? AND s.expira > ? AND u.activo = 1""", (_huella(token), ahora())).fetchone()


def cerrar_sesion(con, token: str) -> None:
    if token:
        con.execute("DELETE FROM sesiones WHERE token_hash = ?", (_huella(token),))


def cerrar_sesiones_de(con, usuario_id: int, excepto_token: str = "") -> None:
    """Al cambiar contraseña, rol o desactivar una cuenta se cierran sus sesiones abiertas."""
    con.execute("DELETE FROM sesiones WHERE usuario_id = ? AND token_hash <> ?",
                (usuario_id, _huella(excepto_token) if excepto_token else ""))


class LimiteIntentos:
    """Frena los intentos de adivinar contraseñas: 5 fallos en 10 minutos bloquean 1 minuto."""

    def __init__(self, maximo=5, ventana_s=600, bloqueo_s=60):
        self.maximo, self.ventana, self.bloqueo = maximo, ventana_s, bloqueo_s
        self.fallos = {}

    def espera(self, clave: str) -> int:
        """Segundos que faltan para poder intentar de nuevo (0 si puede)."""
        t = time.time()
        lista = [x for x in self.fallos.get(clave, []) if t - x < self.ventana]
        self.fallos[clave] = lista
        if len(lista) >= self.maximo:
            falta = self.bloqueo - (t - lista[-1])
            if falta > 0:
                return int(falta) + 1
        return 0

    def fallo(self, clave: str) -> None:
        self.fallos.setdefault(clave, []).append(time.time())
        if len(self.fallos) > 5000:                      # no crecer sin límite
            viejo = time.time() - self.ventana
            self.fallos = {k: v for k, v in self.fallos.items() if v and v[-1] > viejo}

    def exito(self, clave: str) -> None:
        self.fallos.pop(clave, None)


class Cuota:
    """Tope simple por clave (por ejemplo, reportes anónimos o registros por dirección IP)."""

    def __init__(self, maximo: int, ventana_s: int):
        self.maximo, self.ventana, self.usos = maximo, ventana_s, {}

    def permitir(self, clave: str) -> bool:
        t = time.time()
        lista = [x for x in self.usos.get(clave, []) if t - x < self.ventana]
        if len(lista) >= self.maximo:
            self.usos[clave] = lista
            return False
        lista.append(t)
        self.usos[clave] = lista
        if len(self.usos) > 5000:
            self.usos = {k: v for k, v in self.usos.items() if v and t - v[-1] < self.ventana}
        return True
