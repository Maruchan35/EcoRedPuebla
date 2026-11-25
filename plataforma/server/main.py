"""Servidor de Vigía Atoyac (FastAPI + SQLite).

Arranque (desde la carpeta vigia-atoyac-web):   python -m server
Documentación interactiva de la API:            http://localhost:8000/api/docs

Variables de entorno:
  VA_DEMO=0        sin datos ni cuentas de demostración (usar con VA_ADMIN_CUENTA y VA_ADMIN_CLAVE)
  VA_HOST, VA_PORT dirección y puerto (por defecto 127.0.0.1:8000; 0.0.0.0 para que entre la app móvil)
  VA_HTTPS=1       marca la cookie de sesión como Secure (detrás de HTTPS)
"""
import json
import os
from datetime import date, datetime
import re
import secrets
import sys
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import informes, lotes, modelos, motor, red, riesgo, seguridad, semilla
from .db import FOTOS, ahora, conectar, guardar_ajuste, leer_ajuste, siguiente, transaccion

for _flujo in (sys.stdout, sys.stderr):              # consolas de Windows sin UTF-8: que un acento no detenga el arranque
    try:
        _flujo.reconfigure(errors="replace")
    except Exception:
        pass

WEB = Path(__file__).resolve().parent.parent
DEMO = os.environ.get("VA_DEMO", "1") != "0"
HTTPS = os.environ.get("VA_HTTPS", "0") == "1"
H = 3600 * 1000
D = 24 * H
DIAS_SIN_VISITA = 7                      # tras estos días el nodo se muestra en gris
AREA = (17.8, 20.9, -99.2, -96.7)        # caja del estado de Puebla y alrededores: lat mín/máx, lng mín/máx

app = FastAPI(title="Vigía Atoyac", version="0.2.0", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json",
              description="API de la plataforma central: sesión, reportes de la app, casos y carga por lote de los nodos.")
con = conectar()
catalogo_nuevo = semilla.catalogo(con)                  # True si se creó o si cambiaron posiciones de nodos y tramos
# Radio para ligar reportes, velocidades del agua y días sin visita que haya guardado Administración
DIAS_SIN_VISITA = red.aplicar_ajustes(con)["dias_sin_visita"]
# Solo quedan Administración y ciudadanía: las cuentas de los roles que se quitaron se borran al arrancar
_retiradas = semilla.quitar_roles_retirados(con, seguridad.ROLES)
if _retiradas:
    print(f"[Vigía Atoyac] Se borraron {len(_retiradas)} cuentas de roles que ya no existen: {', '.join(_retiradas)}")
if DEMO:
    semilla.cuentas_demo(con)
    # Los reportes y casos de la demo se ubican sobre el cauce: si el cauce cambió, se vuelven a generar
    if catalogo_nuevo or not semilla.demo_al_dia(con):         # también si cambió la versión de los datos de demostración
        print("[Vigía Atoyac] Generando 90 días de datos de demostración…")
        semilla.demostracion(con)
    print(f"[Vigía Atoyac] MODO DEMO: cuentas de prueba en {semilla.ARCHIVO_CUENTAS}. No usar así en un servidor público.")
    print("[Vigía Atoyac] " + semilla.resumen_cuentas_demo())
elif not semilla.admin_inicial(con):
    print("[Vigía Atoyac] No hay usuarios. Define VA_ADMIN_CUENTA y VA_ADMIN_CLAVE (8+ caracteres) y vuelve a iniciar.")

intentos = seguridad.LimiteIntentos()                                   # por dirección + cuenta
intentos_ip = seguridad.LimiteIntentos(maximo=30)                       # por dirección
cuota_registro = seguridad.Cuota(10, 3600)
cuota_reportes = seguridad.Cuota(20, 3600)


# ---------- Cabeceras de seguridad y caché ----------
# Mapas sin API key: OpenFreeMap (calles, letras e íconos), Esri (satélite), Terrain Tiles de AWS (relieve 3D) y OpenStreetMap
_MAPAS = "https://tiles.openfreemap.org https://server.arcgisonline.com https://s3.amazonaws.com https://tile.openstreetmap.org https://*.tile.openstreetmap.org"
CSP = (f"default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: {_MAPAS}; "
       f"connect-src 'self' ws: wss: {_MAPAS}; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
CSP_ENMARCABLE = CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")    # /mapa va dentro de la App Ciudadana


@app.middleware("http")
async def cabeceras(request: Request, call_next):
    resp = await call_next(request)
    ruta = request.url.path
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    if not ruta.startswith("/api/docs"):
        enmarcable = ruta == "/mapa"                                    # solo el mapa 3D, y solo dentro de este mismo sitio
        resp.headers["Content-Security-Policy"] = CSP_ENMARCABLE if enmarcable else CSP
        resp.headers["X-Frame-Options"] = "SAMEORIGIN" if enmarcable else "DENY"
    if ruta.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    elif not ruta.startswith("/vendor/"):
        resp.headers["Cache-Control"] = "no-cache"                      # siempre revalida HTML, JS y CSS
    return resp


@app.exception_handler(RequestValidationError)
async def datos_invalidos(request: Request, exc: RequestValidationError):
    campos = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
    return JSONResponse({"detail": "Revisa los datos enviados" + (": " + ", ".join(campos) if campos else "") + ".", "campos": campos}, status_code=422)


# ---------- Sesión y permisos ----------
# Las dependencias son `async def` a propósito: FastAPI manda las funciones `def` a otro hilo,
# y la conexión de SQLite solo se usa desde el hilo principal (ver db.py).
async def actual(request: Request) -> Optional[dict]:
    """Usuario de la sesión (cookie de la web o token Bearer de la app), o None."""
    token, via = "", ""
    autorizacion = request.headers.get("authorization", "")
    if autorizacion[:7].lower() == "bearer ":
        token, via = autorizacion[7:].strip(), "bearer"
    elif request.cookies.get(seguridad.COOKIE):
        token, via = request.cookies[seguridad.COOKIE], "cookie"
    request.state.token = token
    fila = seguridad.usuario_de_token(con, token) if token else None
    if not fila:
        return None
    # Con cookie, todo lo que modifica datos exige una cabecera propia: otra página web no puede enviarla
    if via == "cookie" and request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-va") != "1":
        raise HTTPException(403, "Solicitud no permitida.")
    # Contraseña temporal (la dio Administración): hasta cambiarla solo puede ver quién es, cambiarla o salir
    if fila["cambiar_clave"] and request.url.path not in _LIBRE_CON_CLAVE_TEMPORAL:
        raise HTTPException(403, "Antes de continuar cambia la contraseña temporal que te dio Administración.",
                            headers={"X-VA-Accion": "cambiar-clave"})
    u = dict(fila)
    u["perm"] = seguridad.permisos_de(fila)
    return u


_LIBRE_CON_CLAVE_TEMPORAL = {"/api/auth/yo", "/api/auth/clave", "/api/auth/salir"}


async def con_sesion(u: Optional[dict] = Depends(actual)) -> dict:
    if not u:
        raise HTTPException(401, "Inicia sesión para continuar.")
    return u


def con_permiso(permiso: str):
    """El servidor es quien decide: aunque alguien arme la petición a mano, sin el permiso no pasa."""
    async def dependencia(u: dict = Depends(con_sesion)) -> dict:
        if permiso not in u["perm"]:
            raise HTTPException(403, "Tu cuenta no tiene permiso para esto.")
        return u
    return dependencia


def solo_demo() -> None:
    if not DEMO:
        raise HTTPException(404, "No disponible.")


def ip(request: Request) -> str:
    """Dirección de quien pide. Detrás del túnel de Cloudflare (cloudflared en esta misma máquina) todo llega
    desde 127.0.0.1; la dirección real la pone Cloudflare en CF-Connecting-IP y quien visita no puede cambiarla
    a través del túnel. Por eso esa cabecera solo se acepta cuando la conexión es local."""
    directa = request.client.host if request.client else "?"
    real = request.headers.get("cf-connecting-ip", "").strip()
    return real[:45] if real and directa in ("127.0.0.1", "::1") else directa


def quien(u: dict) -> str:
    etiqueta = seguridad.ROLES[u["rol"]]["label"]
    return f"{etiqueta} · {semilla.nombre_corto(u['nombre'])}"


def fijar_sesion(request: Request, response: Response, fila, origen: str) -> dict:
    origen = "app" if origen == "app" else "web"
    por_https = HTTPS or request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    token, vida = seguridad.abrir_sesion(con, fila["id"], origen)
    cuerpo = {"usuario": modelos.usuario_api(fila)}
    if origen == "app":
        cuerpo.update(token=token, expira_en=vida)                      # la app lo guarda y lo manda como Bearer
    else:
        response.set_cookie(seguridad.COOKIE, token, max_age=vida, httponly=True, samesite="lax", secure=por_https, path="/")
    return cuerpo


# ---------- Avisos en tiempo real (WebSocket) ----------
class Canal:
    def __init__(self):
        self.abiertos = {}                                              # websocket -> rol (None = público)

    async def emitir(self, tipo: str, aviso: Optional[dict] = None, roles=None) -> None:
        """Todos reciben el `tipo` (para volver a pedir datos); el texto del aviso solo los roles indicados."""
        for ws, rol in list(self.abiertos.items()):
            msg = {"tipo": tipo}
            if aviso and rol and (roles is None or rol in roles):
                msg["aviso"] = aviso
            try:
                await ws.send_json(msg)
            except Exception:
                self.abiertos.pop(ws, None)


canal = Canal()


def roles_de(dep: str) -> set:
    return {r for r, v in seguridad.ROLES.items() if dep in v["deps"]}


@app.websocket("/ws/eventos")
async def ws_eventos(ws: WebSocket):
    origen = ws.headers.get("origin")
    if origen and urlsplit(origen).netloc != ws.headers.get("host"):
        await ws.close(code=1008)                                       # solo páginas servidas por este servidor
        return
    autorizacion = ws.headers.get("authorization", "")
    token = autorizacion[7:].strip() if autorizacion[:7].lower() == "bearer " else ws.cookies.get(seguridad.COOKIE, "")
    fila = seguridad.usuario_de_token(con, token) if token else None
    await ws.accept()
    canal.abiertos[ws] = fila["rol"] if fila and not fila["cambiar_clave"] else None
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        canal.abiertos.pop(ws, None)


async def avisar_casos(creados, actualizados=()) -> None:
    for c in creados:
        titulo = motor.TIPOS_CASO[c["tipo"]]["label"]
        if c["tipo"] == "descarga" and c.get("estimado"):
            titulo = "Posible descarga " + c["estimado"].lower()
        texto = f"{c['resumen']} Caso {c['id']}."
        if c["tipo"] == "descarga":                                     # el resumen completo se lee en el caso
            lugar = con.execute("SELECT nombre FROM nodos WHERE id = ?", (c["nodo"],)).fetchone()
            n = len(c["reportes"])
            texto = (f"{lugar['nombre'] if lugar else c['nodo']} ({motor.fecha(c['evento_t'])}). Confianza {round(c['confianza'] * 100)}%"
                     + (f" con {n} reporte{'s' if n != 1 else ''} de la app" if n else "") + f". Caso {c['id']}.")
        await canal.emitir("caso", {"kind": "crit" if c["prioridad"] == "Alta" else "warn", "title": titulo, "msg": texto, "caso": c["id"]},
                           roles_de(c["dep"]))
    for c in actualizados:
        await canal.emitir("caso", {"kind": "info", "title": "Caso actualizado", "msg": f"{c['id']}: {c['historial'][-1]['what']}", "caso": c["id"]},
                           roles_de(c["dep"]))


# =========================================================
# SESIÓN
# =========================================================
class Entrar(BaseModel):
    cuenta: str = Field(..., max_length=120)
    clave: str = Field(..., max_length=128)
    origen: str = "web"


class Registro(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=80)
    cuenta: str = Field(..., max_length=120)
    clave: str = Field(..., max_length=128)
    origen: str = "web"


class CambioClave(BaseModel):
    actual: str = Field(..., max_length=128)
    nueva: str = Field(..., max_length=128)


def anotar_acceso(cuenta: str, resultado: str, request: Request, usuario_id: Optional[int] = None) -> None:
    """Bitácora para Administración. Guarda la cuenta tal como se escribió (recortada) aunque no exista."""
    con.execute("INSERT INTO accesos (t, usuario_id, cuenta, ip, resultado) VALUES (?, ?, ?, ?, ?)",
                (ahora(), usuario_id, (cuenta or "")[:120], ip(request), resultado))
    con.execute("DELETE FROM accesos WHERE t < ?", (ahora() - 180 * D,))       # se conservan seis meses


@app.post("/api/auth/entrar", tags=["sesión"])
async def entrar(datos: Entrar, request: Request, response: Response):
    cuenta = datos.cuenta.strip().lower()
    try:
        cuenta = seguridad.normalizar_cuenta(cuenta)
    except ValueError:
        pass                                                            # se responde igual que una contraseña incorrecta
    llave = f"{ip(request)}|{cuenta}"
    espera = max(intentos.espera(llave), intentos_ip.espera(ip(request)))
    if espera:
        anotar_acceso(cuenta, "bloqueo", request)
        raise HTTPException(429, f"Demasiados intentos. Espera {espera} segundos e inténtalo de nuevo.", headers={"Retry-After": str(espera)})
    fila = con.execute("SELECT * FROM usuarios WHERE cuenta = ?", (cuenta,)).fetchone()
    if fila:
        correcta = await run_in_threadpool(seguridad.verificar_clave, datos.clave, fila["hash"])
    else:
        await run_in_threadpool(seguridad.gastar_tiempo, datos.clave)
        correcta = False
    if not fila or not correcta or not fila["activo"]:
        intentos.fallo(llave)
        intentos_ip.fallo(ip(request))
        anotar_acceso(cuenta, "desactivada" if fila and correcta else "clave", request, fila["id"] if fila else None)
        raise HTTPException(401, "La cuenta o la contraseña no son correctas.")
    intentos.exito(llave)
    anotar_acceso(cuenta, "ok", request, fila["id"])
    return fijar_sesion(request, response, fila, datos.origen)


@app.post("/api/auth/registro", status_code=201, tags=["sesión"])
async def registro(datos: Registro, request: Request, response: Response):
    """Registro rápido de ciudadanía (lo usa la app móvil). El personal de gobierno lo da de alta Administración."""
    try:
        cuenta = seguridad.normalizar_cuenta(datos.cuenta)
        seguridad.validar_clave(datos.clave, cuenta)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not cuota_registro.permitir(ip(request)):
        raise HTTPException(429, "Demasiados registros desde esta conexión. Inténtalo más tarde.")
    if con.execute("SELECT 1 FROM usuarios WHERE cuenta = ?", (cuenta,)).fetchone():
        raise HTTPException(409, "Ya existe una cuenta con ese correo o teléfono.")
    hash_clave = await run_in_threadpool(seguridad.crear_hash, datos.clave)
    con.execute("INSERT INTO usuarios (cuenta, nombre, rol, hash, creado) VALUES (?, ?, 'ciudadano', ?, ?)",
                (cuenta, datos.nombre.strip(), hash_clave, ahora()))
    fila = con.execute("SELECT * FROM usuarios WHERE cuenta = ?", (cuenta,)).fetchone()
    return fijar_sesion(request, response, fila, datos.origen)


@app.post("/api/auth/salir", tags=["sesión"])
async def salir(request: Request, response: Response, u: Optional[dict] = Depends(actual)):
    seguridad.cerrar_sesion(con, request.state.token)
    response.delete_cookie(seguridad.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/yo", tags=["sesión"])
async def yo(request: Request, u: Optional[dict] = Depends(actual)):
    return {"usuario": modelos.usuario_api(u) if u else None, "demo": DEMO,
            "roles": {k: v["label"] for k, v in seguridad.ROLES.items()}}


@app.post("/api/auth/clave", tags=["sesión"])
async def cambiar_clave(datos: CambioClave, request: Request, u: dict = Depends(con_sesion)):
    fila = con.execute("SELECT hash FROM usuarios WHERE id = ?", (u["id"],)).fetchone()
    if not await run_in_threadpool(seguridad.verificar_clave, datos.actual, fila["hash"]):
        raise HTTPException(403, "La contraseña actual no es correcta.")
    if datos.nueva == datos.actual:
        raise HTTPException(422, "La contraseña nueva debe ser distinta de la actual.")
    try:
        seguridad.validar_clave(datos.nueva, u["cuenta"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    con.execute("UPDATE usuarios SET hash = ?, cambiar_clave = 0 WHERE id = ?",
                (await run_in_threadpool(seguridad.crear_hash, datos.nueva), u["id"]))
    seguridad.cerrar_sesiones_de(con, u["id"], excepto_token=request.state.token)
    return {"ok": True, "usuario": modelos.usuario_api(con.execute("SELECT * FROM usuarios WHERE id = ?", (u["id"],)).fetchone())}


# =========================================================
# USUARIOS (Administración)
# =========================================================
class NuevoUsuario(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=80)
    cuenta: str = Field(..., max_length=120)
    rol: str
    clave: str = Field(..., max_length=128)
    permisos: Optional[List[str]] = None          # None = los del rol


class EditarUsuario(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=80)
    rol: Optional[str] = None
    activo: Optional[bool] = None
    clave: Optional[str] = Field(None, max_length=128)
    permisos: Optional[List[str]] = None          # lista propia de módulos
    permisos_del_rol: bool = False                # true = volver a los del rol


def _permisos_propios(rol: str, lista) -> Optional[str]:
    """JSON para la columna `permisos`, o None si coincide con los del rol (así sigue al rol si este cambia)."""
    if lista is None or rol in ("admin", "ciudadano"):
        return None
    try:
        limpia = seguridad.limpiar_permisos(lista)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return None if set(limpia) == seguridad.PERMISOS_ROL.get(rol, set()) else json.dumps(limpia)


@app.get("/api/usuarios", tags=["usuarios"])
async def usuarios(u: dict = Depends(con_permiso("usuarios"))):
    return [modelos.usuario_api(f) for f in con.execute("SELECT * FROM usuarios ORDER BY activo DESC, rol, nombre")]


@app.get("/api/permisos", tags=["usuarios"])
async def catalogo_permisos(u: dict = Depends(con_permiso("usuarios"))):
    """Lo que la pantalla de Usuarios necesita para armar las casillas de permisos."""
    return {"permisos": seguridad.PERMISOS, "por_rol": {k: sorted(v) for k, v in seguridad.PERMISOS_ROL.items()},
            "solo_admin": sorted(seguridad.SOLO_ADMIN), "roles": {k: v["label"] for k, v in seguridad.ROLES.items()}}


@app.get("/api/accesos", tags=["usuarios"])
async def bitacora_accesos(limite: int = 100, u: dict = Depends(con_permiso("usuarios"))):
    """Últimos inicios de sesión, correctos y fallidos, con la dirección desde donde se intentaron."""
    filas = con.execute("""SELECT a.t, a.cuenta, a.ip, a.resultado, us.nombre FROM accesos a LEFT JOIN usuarios us ON us.id = a.usuario_id
                           ORDER BY a.t DESC, a.id DESC LIMIT ?""", (max(1, min(limite, 500)),)).fetchall()
    return [dict(f) for f in filas]


@app.post("/api/usuarios", status_code=201, tags=["usuarios"])
async def crear_usuario(datos: NuevoUsuario, u: dict = Depends(con_permiso("usuarios"))):
    if datos.rol not in seguridad.ROLES:
        raise HTTPException(422, "Ese rol no existe.")
    try:
        cuenta = seguridad.normalizar_cuenta(datos.cuenta)
        seguridad.validar_clave(datos.clave, cuenta)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if con.execute("SELECT 1 FROM usuarios WHERE cuenta = ?", (cuenta,)).fetchone():
        raise HTTPException(409, "Ya existe una cuenta con ese correo o teléfono.")
    permisos = _permisos_propios(datos.rol, datos.permisos)
    hash_clave = await run_in_threadpool(seguridad.crear_hash, datos.clave)
    # El personal entra la primera vez con una contraseña temporal y el sistema le pide cambiarla
    con.execute("INSERT INTO usuarios (cuenta, nombre, rol, hash, creado, permisos, cambiar_clave) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cuenta, datos.nombre.strip(), datos.rol, hash_clave, ahora(), permisos, int(datos.rol != "ciudadano")))
    return modelos.usuario_api(con.execute("SELECT * FROM usuarios WHERE cuenta = ?", (cuenta,)).fetchone())


@app.patch("/api/usuarios/{usuario_id}", tags=["usuarios"])
async def editar_usuario(usuario_id: int, datos: EditarUsuario, u: dict = Depends(con_permiso("usuarios"))):
    fila = con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not fila:
        raise HTTPException(404, "La cuenta no existe.")
    if datos.rol is not None and datos.rol not in seguridad.ROLES:
        raise HTTPException(422, "Ese rol no existe.")
    rol_final = datos.rol if datos.rol is not None else fila["rol"]
    if (datos.permisos is not None or datos.permisos_del_rol) and rol_final in ("admin", "ciudadano"):
        raise HTTPException(422, "Administración tiene todos los permisos y la ciudadanía ninguno: no se ajustan por persona.")
    pierde_admin = fila["rol"] == "admin" and fila["activo"] and (datos.activo is False or (datos.rol is not None and datos.rol != "admin"))
    if pierde_admin:
        if usuario_id == u["id"]:
            raise HTTPException(409, "No puedes quitarte a ti mismo el acceso de administración.")
        if con.execute("SELECT COUNT(*) AS c FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id <> ?", (usuario_id,)).fetchone()["c"] == 0:
            raise HTTPException(409, "Debe quedar al menos una cuenta de administración activa.")
    if datos.clave is not None:
        try:
            seguridad.validar_clave(datos.clave, fila["cuenta"])
        except ValueError as e:
            raise HTTPException(422, str(e))
    permisos_nuevos = _permisos_propios(rol_final, datos.permisos) if datos.permisos is not None else None
    # El hash se calcula antes de abrir la transacción: mientras se espera, otras peticiones usan la misma conexión
    hash_nuevo = await run_in_threadpool(seguridad.crear_hash, datos.clave) if datos.clave is not None else None
    cierra = False
    with transaccion(con):                                              # todo o nada
        if datos.nombre is not None:
            con.execute("UPDATE usuarios SET nombre = ? WHERE id = ?", (datos.nombre.strip(), usuario_id))
        if datos.rol is not None and datos.rol != fila["rol"]:
            # Al cambiar de rol se vuelve a los permisos del rol nuevo
            con.execute("UPDATE usuarios SET rol = ?, permisos = NULL WHERE id = ?", (datos.rol, usuario_id))
            cierra = True
        if datos.permisos is not None:
            con.execute("UPDATE usuarios SET permisos = ? WHERE id = ?", (permisos_nuevos, usuario_id))
        elif datos.permisos_del_rol:
            con.execute("UPDATE usuarios SET permisos = NULL WHERE id = ?", (usuario_id,))
        if datos.activo is not None and bool(fila["activo"]) != datos.activo:
            con.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (int(datos.activo), usuario_id))
            cierra = cierra or not datos.activo
        if datos.clave is not None:
            # Contraseña temporal: la persona tendrá que cambiarla al entrar (salvo que sea quien la escribe)
            con.execute("UPDATE usuarios SET hash = ?, cambiar_clave = ? WHERE id = ?",
                        (hash_nuevo, int(usuario_id != u["id"] and rol_final != "ciudadano"), usuario_id))
            cierra = True
    if cierra and usuario_id != u["id"]:
        seguridad.cerrar_sesiones_de(con, usuario_id)                   # el cambio aplica de inmediato
    await canal.emitir("usuarios")                                      # los paneles abiertos rehacen su menú
    return modelos.usuario_api(con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone())


# =========================================================
# DATOS DE LA CUENCA
# =========================================================
def _deps(u) -> list:
    """Dependencias cuyos casos ve completos y puede atender: las de su rol, si tiene el permiso de casos."""
    return seguridad.ROLES[u["rol"]]["deps"] if u and "casos" in u["perm"] else []


def _es_personal(u) -> bool:
    return bool(u) and u["rol"] in seguridad.PERSONAL


def _lecturas(nodo_id: str, limite: int) -> list:
    filas = con.execute("SELECT * FROM lecturas WHERE nodo = ? ORDER BY t DESC LIMIT ?", (nodo_id, limite)).fetchall()
    return [modelos.lectura_api(f) for f in reversed(filas)]


def _reportes(u, desde: int = 0) -> list:
    personal, uid = _es_personal(u), (u["id"] if u else None)
    return [modelos.reporte_api(f, personal or (uid is not None and f["usuario_id"] == uid), uid)
            for f in con.execute("SELECT * FROM reportes WHERE t >= ? ORDER BY t DESC LIMIT 500", (desde,))]


def _casos(u) -> list:
    deps = _deps(u)
    return [modelos.caso_api(f, f["dep"] in deps) for f in con.execute("SELECT * FROM casos ORDER BY t DESC LIMIT 500")]


@app.get("/api/estado", tags=["datos"])
async def estado(u: Optional[dict] = Depends(actual)):
    """Todo lo que la web necesita en una sola respuesta, ya filtrado según quién pregunta."""
    nodos = [modelos.nodo_api(f) for f in con.execute("SELECT * FROM nodos ORDER BY orden")]
    indice = {}
    for f in con.execute("SELECT tramo, t, v FROM indice_diario ORDER BY t"):
        indice.setdefault(f["tramo"], []).append({"t": f["t"], "v": f["v"]})
    return {
        "usuario": modelos.usuario_api(u) if u else None, "demo": DEMO, "ahora": ahora(),
        "nodes": nodos,
        "tramos": [modelos.tramo_api(f) for f in con.execute("SELECT * FROM tramos ORDER BY id")],
        "barriers": [modelos.barrera_api(f) for f in con.execute("SELECT * FROM barreras ORDER BY id")],
        "history": {n["id"]: _lecturas(n["id"], 48 if _es_personal(u) else 1) for n in nodos},
        "reports": _reportes(u, ahora() - 30 * D),
        "cases": _casos(u),
        "dailyIndex": indice, "categorias": motor.CATEGORIAS, "params": motor.umbrales(con), "staleDays": DIAS_SIN_VISITA,
        # Basura retirada de las barreras (de los vaciados registrados) y estaciones de tratamiento
        "basura": {"kg30": _kg_desde(ahora() - 30 * D), "kg90": _kg_desde(ahora() - 90 * D),
                   "vaciados30": con.execute("SELECT COUNT(*) AS c FROM vaciados WHERE t >= ?", (ahora() - 30 * D,)).fetchone()["c"]},
        "estaciones": [{"nodo": k, "codigo": v["codigo"], "nombre": v["nombre"]} for k, v in semilla.ESTACIONES.items()
                       if any(n["id"] == k for n in nodos)],
        # Ajustes de la red que también usa la web (tiempo del agua en el mapa y reportes cercanos a cada nodo)
        "red": {"velMin": motor.VEL_MIN_MS, "velMax": motor.VEL_MAX_MS, "radioKm": motor.RADIO_FUSION_KM},
    }


def _kg_desde(t0: int) -> int:
    return int(con.execute("SELECT COALESCE(SUM(kg), 0) AS s FROM vaciados WHERE t >= ?", (t0,)).fetchone()["s"])


@app.get("/api/nodos", tags=["datos"])
async def nodos():
    return [modelos.nodo_api(f) for f in con.execute("SELECT * FROM nodos ORDER BY orden")]


@app.get("/api/tramos", tags=["datos"])
async def tramos():
    return [modelos.tramo_api(f) for f in con.execute("SELECT * FROM tramos ORDER BY id")]


@app.get("/api/barreras", tags=["datos"])
async def barreras():
    return [modelos.barrera_api(f) for f in con.execute("SELECT * FROM barreras ORDER BY id")]


@app.get("/api/nodos/{nodo_id}/lecturas", tags=["datos"])
async def lecturas(nodo_id: str, limite: int = 48):
    if not con.execute("SELECT 1 FROM nodos WHERE id = ?", (nodo_id,)).fetchone():
        raise HTTPException(404, "El nodo no existe.")
    return _lecturas(nodo_id, max(1, min(limite, 2000)))


@app.get("/api/abiertos/lecturas.csv", tags=["datos"], response_class=PlainTextResponse)
async def datos_abiertos(nodo: str, dias: int = 7):
    """Datos abiertos para universidades: lecturas de un nodo en CSV."""
    if not con.execute("SELECT 1 FROM nodos WHERE id = ?", (nodo,)).fetchone():
        raise HTTPException(404, "El nodo no existe.")
    filas = [dict(f) for f in con.execute(f"SELECT t, ph, cond, turb, color, temp, nivel, anom, {', '.join(motor.ESTACION)} FROM lecturas "
                                          "WHERE nodo = ? AND t >= ? ORDER BY t", (nodo, ahora() - max(1, min(dias, 31)) * D))]
    texto = lotes.csv_abierto(filas)
    return PlainTextResponse(texto, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="vigia_{nodo}_{dias}d.csv"'})


# ---------- Series para gráficas y estación piloto ----------
SERIE_PARAMS = ("ph", "cond", "turb", "color", "temp", "nivel") + motor.ESTACION


def _agrupar(filas, paso: int, campos) -> list:
    """Mediana de cada campo por hora o por día (hora del centro) y cuántas lecturas anómalas hubo."""
    cubetas = {}
    for f in filas:
        cubetas.setdefault((f["t"] - 6 * H) // paso, []).append(f)
    salida = []
    for k in sorted(cubetas):
        grupo = cubetas[k]
        p = {"t": k * paso + 6 * H, "n": len(grupo), "anom": sum(1 for f in grupo if f["anom"] and f["anom"] != "[]")}
        for c in campos:
            vals = [f[c] for f in grupo if f[c] is not None]
            if vals:
                p[c] = round(motor.mediana(vals), 3)
        salida.append(p)
    return salida


@app.get("/api/series", tags=["datos"])
async def series(nodo: str, dias: int = 7, agrupar: str = "hora"):
    """Medianas por hora (`agrupar=hora`) o por día (`agrupar=dia`) de un nodo, para las gráficas. Pública."""
    if not con.execute("SELECT 1 FROM nodos WHERE id = ?", (nodo,)).fetchone():
        raise HTTPException(404, "El nodo no existe.")
    dias = max(1, min(dias, 90))
    ultima = con.execute("SELECT MAX(t) AS m FROM lecturas WHERE nodo = ?", (nodo,)).fetchone()["m"]
    if not ultima:
        return {"nodo": nodo, "puntos": [], "hasta": None}
    filas = con.execute(f"SELECT t, anom, {', '.join(SERIE_PARAMS)} FROM lecturas WHERE nodo = ? AND t > ? ORDER BY t",
                        (nodo, ultima - dias * D)).fetchall()
    return {"nodo": nodo, "paso": H if agrupar != "dia" else D, "hasta": ultima,
            "puntos": _agrupar(filas, H if agrupar != "dia" else D, SERIE_PARAMS)}


def _integra(filas, campo, factor=1.0) -> float:
    """Suma de campo × tiempo entre lecturas (caudal en L/s → litros; potencia en W → W·s)."""
    total = 0.0
    for a, b in zip(filas, filas[1:]):
        if a[campo] is not None:
            total += a[campo] * min(b["t"] - a["t"], 20 * 60 * 1000) / 1000 * factor
    return total


def _cubierto(filas) -> int:
    """Tiempo (ms) que cubren unas lecturas: huecos de más de 20 min no cuentan."""
    return sum(min(b["t"] - a["t"], 20 * 60 * 1000) for a, b in zip(filas, filas[1:]))


def _remocion(filas, entra, sale):
    """Fracción removida ponderada por caudal: 1 − (Σ salida·Q) / (Σ entrada·Q)."""
    num = sum(f[sale] * (f["caudal"] or 0) for f in filas if f[sale] is not None and f[entra] is not None)
    den = sum(f[entra] * (f["caudal"] or 0) for f in filas if f[sale] is not None and f[entra] is not None)
    return round(1 - num / den, 3) if den else None


@app.get("/api/estacion", tags=["estación"])
async def estacion(nodo: str = "N3", dias: int = 7):
    """Estación piloto de tratamiento: qué entra, qué sale, cuánto trata y cómo va su mantenimiento. Pública."""
    meta = semilla.ESTACIONES.get(nodo)
    if not meta:
        raise HTTPException(404, "Ese nodo no tiene estación de tratamiento.")
    dias = max(1, min(dias, 30))
    cols = "t, anom, ph, cond, turb, color, temp, nivel, " + ", ".join(motor.ESTACION)
    ultima = con.execute("SELECT MAX(t) AS m FROM lecturas WHERE nodo = ? AND caudal IS NOT NULL", (nodo,)).fetchone()["m"]
    n = con.execute("SELECT nombre, lat, lng, ultima_descarga, bateria FROM nodos WHERE id = ?", (nodo,)).fetchone()
    if not n:
        raise HTTPException(404, "El nodo de esa estación está dado de baja.")
    base = {"nodo": nodo, **meta, "nombreNodo": n["nombre"], "lat": n["lat"], "lng": n["lng"], "ultimaVisita": n["ultima_descarga"]}
    if not ultima:
        return {**base, "hasta": None, "kpis": None, "serie": [], "mantenimiento": []}
    filas = con.execute(f"SELECT {cols} FROM lecturas WHERE nodo = ? AND t > ? AND caudal IS NOT NULL ORDER BY t",
                        (nodo, ultima - dias * D)).fetchall()
    # Indicadores "por día": del día completo más reciente (20 h o más de datos). Los datos llegan por lotes con
    # huecos, así que las últimas 24 h de reloj pueden traer solo unas horas; sin día completo se escala lo que haya.
    por_dia = {}
    for f in filas:
        por_dia.setdefault((f["t"] - 6 * H) // D, []).append(f)
    completos = [k for k, v in por_dia.items() if _cubierto(v) >= 20 * H]
    if completos:
        dia, dia_base, escala = por_dia[max(completos)], max(completos) * D + 6 * H, 1.0
    else:
        dia = [f for f in filas if f["t"] > ultima - D]
        dia_base, escala = None, D / max(_cubierto(dia), H)
    ult = filas[-1]
    # Presión de filtros: a este ritmo, ¿cuándo toca retrolavado?
    rec = [f for f in filas if f["t"] > ultima - 6 * H and f["dp_filtro"] is not None]
    ritmo = (rec[-1]["dp_filtro"] - rec[0]["dp_filtro"]) / max(1, (rec[-1]["t"] - rec[0]["t"]) / H) if len(rec) > 2 else 0
    # Mantenimiento detectado en los datos: purgas (cae el lodo), retrolavados (cae la presión) y paros (caudal 0)
    eventos = []
    for a, b in zip(filas, filas[1:]):
        if a["lodos"] is not None and b["lodos"] is not None and a["lodos"] - b["lodos"] > 15:
            eventos.append({"t": b["t"], "tipo": "purga", "texto": f"Purga de lodos del sedimentador ({a['lodos']:.0f}% → {b['lodos']:.0f}%)"})
        if a["dp_filtro"] is not None and b["dp_filtro"] is not None and a["dp_filtro"] - b["dp_filtro"] > 8:
            eventos.append({"t": b["t"], "tipo": "retrolavado", "texto": f"Retrolavado automático de filtros ({a['dp_filtro']:.0f} → {b['dp_filtro']:.0f} kPa)"})
    # Carbón activado: el cambio se nota como un salto en la remoción de color (se busca en 60 días)
    largo = con.execute("SELECT t, color, color_sal, caudal FROM lecturas WHERE nodo = ? AND t > ? AND caudal IS NOT NULL ORDER BY t",
                        (nodo, ultima - 60 * D)).fetchall()
    por_dia = {}
    for f in largo:
        por_dia.setdefault((f["t"] - 6 * H) // D, []).append(f)
    efic_dia = [(k * D + 6 * H, _remocion(v, "color", "color_sal")) for k, v in sorted(por_dia.items()) if len(v) > 50]
    cambio = None
    for (t0, e0), (t1, e1) in zip(efic_dia, efic_dia[1:]):
        if e0 is not None and e1 is not None and e1 - e0 > 0.12:
            cambio = t1
    if cambio:
        eventos.append({"t": cambio, "tipo": "carbon", "texto": "Cambio de carbón activado (la remoción de color subió de golpe)"})
    eventos.sort(key=lambda e: e["t"], reverse=True)
    kpis = {
        "caudal": ult["caudal"], "nivelRio": ult["nivel"],
        "diaBase": dia_base,
        "m3Dia": round(_integra(dia, "caudal") / 1000 * escala, 1), "m3Periodo": round(_integra(filas, "caudal") / 1000, 1),
        "remocion": {k: _remocion(dia, k, k + "_sal") for k in ("turb", "color", "cond")},
        "remocionPeriodo": {k: _remocion(filas, k, k + "_sal") for k in ("turb", "color", "cond")},
        # Sólidos suspendidos ≈ 1.3 mg/L por NTU en este río; retenidos = (entrada − salida) × volumen tratado
        "solidosKgDia": round(sum(1.3 * max(0.0, (a["turb"] or 0) - (a["turb_sal"] or 0)) * (a["caudal"] or 0)
                                  * min(b["t"] - a["t"], 20 * 60 * 1000) / 1000 for a, b in zip(dia, dia[1:])) / 1e6 * escala, 2),
        "lodos": ult["lodos"], "dp": ult["dp_filtro"], "dpMax": 24.0,
        "horasRetrolavado": round((24.0 - ult["dp_filtro"]) / ritmo, 1) if ritmo > 0.05 and ult["dp_filtro"] is not None else None,
        "energiaWhDia": round(_integra(dia, "solar") / 3600 * escala), "bateria": n["bateria"],
        "carbonDias": round((ultima - cambio) / D, 1) if cambio else None, "carbonCada": 42,
        "ph": {"entra": ult["ph"], "sale": ult["ph_sal"]},
    }
    return {**base, "hasta": ultima, "kpis": kpis, "mantenimiento": eventos[:12], "eficienciaColorDiaria": efic_dia,
            "serie": _agrupar(filas, H, ("turb", "turb_sal", "color", "color_sal", "cond", "cond_sal", "ph", "ph_sal",
                                          "caudal", "lodos", "dp_filtro", "solar", "nivel"))}


@app.get("/api/riesgo", tags=["datos"])
async def riesgo_agua():
    """Riesgo para la salud por contacto con el agua, por tramo. Público: es para quien se acerca al río.
    Nunca dice que sea apto para bañarse, porque los sensores no miden bacterias ni metales."""
    return riesgo.calcular(con, ahora(), DIAS_SIN_VISITA)


# ---------- Informes descargables para el Ayuntamiento (PDF, Excel y CSV) ----------
TIPOS_CASO = {"descarga": "Descarga", "inundacion": "Crecida o inundación", "basura": "Basura acumulada",
              "recurrente": "Punto crítico recurrente"}
INFORMES = {                                                     # nombre: (título, solo para el personal)
    "informe": ("Informe del periodo", False),
    "indice": ("Índice diario por tramo", False),
    "lecturas": ("Lecturas de los nodos", False),
    "estacion": ("Estación piloto: resumen diario", False),
    "basura": ("Basura retirada de las barreras", False),
    "casos": ("Casos", True),
    "reportes": ("Reportes ciudadanos", True),
}
MEDIOS = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}


def _dia(texto: str) -> int:
    try:
        return (datetime.strptime(texto, "%Y-%m-%d").date() - date(1970, 1, 1)).days
    except ValueError:
        raise HTTPException(422, "Usa fechas con el formato AAAA-MM-DD.")


def _periodo(desde, hasta, dias=30):
    """Días completos en hora del centro → (inicio_ms, fin_ms, etiqueta legible, rango para el nombre del archivo)."""
    fin = _dia(hasta) if hasta else motor.dia_local(ahora())
    ini = _dia(desde) if desde else fin - dias + 1
    ini, fin = min(ini, fin), max(ini, fin)
    if fin - ini > 366:
        raise HTTPException(422, "El periodo máximo es de un año.")
    t0, t1 = ini * D + 6 * H, (fin + 1) * D + 6 * H - 1
    f0, f1 = informes.fecha(t0), informes.fecha(t1)
    etiqueta = f"{f0.day} {motor.MESES[f0.month - 1]} {f0.year} al {f1.day} {motor.MESES[f1.month - 1]} {f1.year}"
    return t0, t1, etiqueta, f"{f0:%Y-%m-%d}_{f1:%Y-%m-%d}"


def _estado_indice(v):
    return "Bien" if v >= 70 else "Atención" if v >= 40 else "Crítico"


def _tabla_indice(t0, t1):
    nombres = {f["id"]: f["nombre"] for f in con.execute("SELECT id, nombre FROM tramos")}
    filas = [{"tramo": f["tramo"], "nombre": nombres.get(f["tramo"], ""), "dia": informes.fecha(f["t"]), "v": f["v"],
              "estado": _estado_indice(f["v"])}
             for f in con.execute("SELECT tramo, t, v FROM indice_diario WHERE t BETWEEN ? AND ? ORDER BY tramo, t", (t0, t1))]
    return [("tramo", "Tramo", 8, None), ("nombre", "Recorrido", 40, None), ("dia", "Día", 12, "fecha"),
            ("v", "Índice (0 a 100)", 15, "0"), ("estado", "Estado", 12, None)], filas


def _tabla_lecturas(t0, t1, nodo):
    if t1 - t0 > 92 * D:
        raise HTTPException(422, "Para las lecturas el periodo máximo es de 92 días.")
    campos = ("ph", "cond", "turb", "color", "temp", "nivel") + motor.ESTACION
    filtro, args = (" AND nodo = ?", (t0, t1, nodo)) if nodo else ("", (t0, t1))
    filas = []
    for f in con.execute(f"SELECT nodo, t, anom, {', '.join(campos)} FROM lecturas WHERE t BETWEEN ? AND ?{filtro} ORDER BY nodo, t", args):
        anom = json.loads(f["anom"]) if f["anom"] and f["anom"] != "[]" else []
        filas.append({"nodo": f["nodo"], "t": informes.fecha(f["t"]), "anom": ", ".join(motor.NOMBRE.get(k, k) for k in anom),
                      **{k: f[k] for k in campos}})
    cols = [("nodo", "Nodo", 7, None), ("t", "Fecha y hora", 17, "fechahora"), ("ph", "pH", 7, "0.00"),
            ("cond", "Conductividad (µS/cm)", 14, "0"), ("turb", "Turbidez (NTU)", 11, "0.0"), ("color", "Color 620 nm (m⁻¹)", 13, "0.00"),
            ("temp", "Temperatura (°C)", 12, "0.0"), ("nivel", "Nivel (m)", 9, "0.00"), ("anom", "Anomalía", 18, None)]
    if any(r["caudal"] is not None for r in filas):            # nodo con estación piloto
        cols += [("caudal", "Caudal EP-1 (L/s)", 12, "0.0"), ("turb_sal", "Turbidez salida (NTU)", 13, "0.0"),
                 ("color_sal", "Color salida (m⁻¹)", 12, "0.00"), ("cond_sal", "Conductividad salida", 13, "0"),
                 ("ph_sal", "pH salida", 9, "0.00"), ("lodos", "Lodos (%)", 9, "0"), ("dp_filtro", "Presión filtros (kPa)", 13, "0.0"),
                 ("solar", "Solar (W)", 9, "0")]
    return cols, filas


def _tabla_estacion(t0, t1):
    filas = []
    for nodo, meta in semilla.ESTACIONES.items():
        lect = con.execute("""SELECT t, caudal, turb, turb_sal, color, color_sal, cond, cond_sal, lodos, dp_filtro, solar FROM lecturas
                              WHERE nodo = ? AND caudal IS NOT NULL AND t BETWEEN ? AND ? ORDER BY t""", (nodo, t0, t1)).fetchall()
        por_dia = {}
        for f in lect:
            por_dia.setdefault(motor.dia_local(f["t"]), []).append(f)
        for k in sorted(por_dia):
            v = por_dia[k]
            solidos = sum(1.3 * max(0.0, (a["turb"] or 0) - (a["turb_sal"] or 0)) * (a["caudal"] or 0) * min(b["t"] - a["t"], 20 * 60 * 1000) / 1000
                          for a, b in zip(v, v[1:])) / 1e6
            filas.append({"estacion": meta["codigo"], "dia": informes.fecha(k * D + 6 * H), "horas": round(_cubierto(v) / H, 1),
                          "m3": round(_integra(v, "caudal") / 1000, 1), "solidos": round(solidos, 2), "energia": round(_integra(v, "solar") / 3600),
                          **{"rem_" + p: _remocion(v, p, p + "_sal") for p in ("turb", "color", "cond")},
                          "lodos": max((f["lodos"] for f in v if f["lodos"] is not None), default=None),
                          "dp": max((f["dp_filtro"] for f in v if f["dp_filtro"] is not None), default=None)})
    return [("estacion", "Estación", 9, None), ("dia", "Día", 12, "fecha"), ("horas", "Horas con datos", 11, "0.0"),
            ("m3", "Agua tratada (m³)", 13, "0.0"), ("rem_turb", "Remoción de turbidez", 13, "%"), ("rem_color", "Remoción de color", 13, "%"),
            ("rem_cond", "Remoción de conductividad", 15, "%"), ("solidos", "Sólidos retenidos (kg)", 14, "0.00"),
            ("energia", "Energía solar (Wh)", 13, "0"), ("lodos", "Lodos máximo (%)", 11, "0"), ("dp", "Presión de filtros máxima (kPa)", 15, "0.0")], filas


def _tabla_basura(t0, t1, personal):
    nombres = {f["id"]: f["nombre"] for f in con.execute("SELECT id, nombre FROM barreras")}
    filas = [{"barrera": f["barrera"], "nombre": nombres.get(f["barrera"], ""), "t": informes.fecha(f["t"]), "kg": f["kg"], "quien": f["quien"]}
             for f in con.execute("SELECT barrera, t, kg, quien FROM vaciados WHERE t BETWEEN ? AND ? ORDER BY t", (t0, t1))]
    cols = [("barrera", "Barrera", 8, None), ("nombre", "Ubicación", 36, None), ("t", "Vaciado", 17, "fechahora"), ("kg", "Basura (kg)", 11, "0")]
    return (cols + [("quien", "Registró", 32, None)] if personal else cols), filas


def _tabla_casos(u, t0, t1):
    deps, filas = _deps(u), []
    for f in con.execute("SELECT * FROM casos WHERE t BETWEEN ? AND ? ORDER BY t", (t0, t1)):
        c = modelos.caso_api(f, f["dep"] in deps)                # los de otra dependencia, en versión pública
        filas.append({"id": c["id"], "tipo": TIPOS_CASO.get(c["type"], c["type"]), "dep": motor.DEPENDENCIAS.get(c["dep"], c["dep"]),
                      "estado": c["status"], "prioridad": c["priority"], "creado": informes.fecha(c["t"]),
                      "cerrado": informes.fecha(c["closedAt"]), "dias": round((c["closedAt"] - c["t"]) / D, 1) if c["closedAt"] else None,
                      "tramo": c["tramo"], "nodo": c["node"], "barrera": c["barrier"],
                      "resumen": c.get("summary") or ("El detalle lo ve la dependencia responsable" if c["public"] else "")})
    return [("id", "Folio", 15, None), ("tipo", "Tipo", 22, None), ("dep", "Dependencia", 20, None), ("estado", "Estado", 12, None),
            ("prioridad", "Prioridad", 10, None), ("creado", "Abierto", 17, "fechahora"), ("cerrado", "Cerrado", 17, "fechahora"),
            ("dias", "Días de atención", 11, "0.0"), ("tramo", "Tramo", 8, None), ("nodo", "Nodo", 7, None), ("barrera", "Barrera", 8, None),
            ("resumen", "Resumen", 60, None)], filas


def _tabla_reportes(u, t0, t1):
    filas = []
    for f in con.execute("SELECT * FROM reportes WHERE t BETWEEN ? AND ? ORDER BY t", (t0, t1)):
        r = modelos.reporte_api(f, True, u["id"])
        filas.append({"id": r["id"], "cat": r["cat"], "estado": r["status"], "t": informes.fecha(r["t"]), "lat": r["lat"], "lng": r["lng"],
                      "loc": {"gps": "GPS", "mapa": "Marcado en el mapa"}.get(r.get("loc"), "Sin dato"), "precision": r.get("precision"),
                      "ia": r["ai"]["label"] if r["ai"] else None, "conf": r["ai"]["conf"] if r["ai"] else None,
                      "anonimo": "Sí" if r["anonymous"] else "No", "foto": "Sí" if r["photo"] else "No", "texto": r["text"]})
    return [("id", "Folio", 9, None), ("cat", "Categoría", 18, None), ("estado", "Estado", 11, None), ("t", "Recibido", 17, "fechahora"),
            ("lat", "Latitud", 11, None), ("lng", "Longitud", 11, None), ("loc", "Ubicación", 17, None), ("precision", "Margen GPS (m)", 11, "0.0"),
            ("ia", "Clasificación IA", 18, None), ("conf", "Confianza IA", 11, "%"), ("anonimo", "Anónimo", 9, None), ("foto", "Foto", 7, None),
            ("texto", "Texto", 60, None)], filas


def _bloques_informe(t0, t1):
    """Contenido del informe del periodo en PDF: solo datos agregados, sin datos personales (es público)."""
    tramos = con.execute("SELECT t.id, t.nombre FROM tramos t JOIN nodos n ON n.id = t.desde ORDER BY n.orden").fetchall()
    filas_tr, todos = [], []
    for tr in tramos:
        vals = [f["v"] for f in con.execute("SELECT v FROM indice_diario WHERE tramo = ? AND t BETWEEN ? AND ?", (tr["id"], t0, t1))]
        todos += vals
        filas_tr.append([tr["id"], tr["nombre"], f"{sum(vals) / len(vals):.0f}" if vals else "-", f"{min(vals):.0f}" if vals else "-",
                         str(sum(1 for v in vals if v < 40)), str(sum(1 for v in vals if 40 <= v < 70)), str(len(vals))])
    casos = con.execute("SELECT dep, t, cerrado FROM casos WHERE t BETWEEN ? AND ?", (t0, t1)).fetchall()
    por_dep = {}
    for c in casos:
        por_dep.setdefault(c["dep"], []).append(c)
    filas_dep = []
    for dep, lista in sorted(por_dep.items()):
        cerrados = [c for c in lista if c["cerrado"]]
        prom = sum((c["cerrado"] - c["t"]) / D for c in cerrados) / len(cerrados) if cerrados else None
        filas_dep.append([motor.DEPENDENCIAS.get(dep, dep), str(len(lista)), str(len(cerrados)), str(len(lista) - len(cerrados)),
                          f"{prom:.1f}" if prom is not None else "-"])
    reps = con.execute("SELECT cat, estado FROM reportes WHERE t BETWEEN ? AND ?", (t0, t1)).fetchall()
    por_cat = {}
    for r in reps:
        por_cat.setdefault(r["cat"], []).append(r["estado"])
    filas_cat = [[cat, str(len(e)), str(sum(1 for x in e if x in ("Validado", "Atendido"))), str(sum(1 for x in e if x == "Descartado"))]
                 for cat, e in sorted(por_cat.items(), key=lambda x: -len(x[1]))]
    _, est = _tabla_estacion(t0, t1)
    kg = int(con.execute("SELECT COALESCE(SUM(kg), 0) AS s FROM vaciados WHERE t BETWEEN ? AND ?", (t0, t1)).fetchone()["s"])
    cerr = [c for c in casos if c["cerrado"]]
    prom_total = sum((c["cerrado"] - c["t"]) / D for c in cerr) / len(cerr) if cerr else None
    dias_crit = len({f["t"] for f in con.execute("SELECT t FROM indice_diario WHERE v < 40 AND t BETWEEN ? AND ?", (t0, t1))})
    rg = riesgo.calcular(con, ahora(), DIAS_SIN_VISITA)
    bloques = [
        ("kpis", [("Índice promedio de la cuenca", f"{sum(todos) / len(todos):.0f} / 100" if todos else "Sin datos"),
                  ("Días con algún tramo crítico", str(dias_crit)), ("Casos nuevos en el periodo", str(len(casos))),
                  ("Casos cerrados", str(len(cerr))), ("Atención promedio", f"{prom_total:.1f} días" if prom_total is not None else "-"),
                  ("Reportes ciudadanos", str(len(reps))), ("Agua tratada en EP-1", f"{sum(f['m3'] for f in est):,.0f} m³"),
                  ("Basura retirada", f"{kg:,} kg"), ("Apto para bañarse", "Ningún tramo")]),
        ("h", "Calidad del agua por tramo"),
        ("p", "Índice diario de 0 a 100 con la mediana del día del nodo de abajo de cada tramo: 70 o más es «Bien», "
              "de 40 a 69 «Atención» y menos de 40 «Crítico»."),
        ("tabla", ["Tramo", "Recorrido", "Promedio", "Mínimo", "Días críticos", "Días en atención", "Días con datos"], filas_tr,
         (8, 36, 10, 10, 11, 12, 11)),
        ("h", "Atención de casos por dependencia"),
        ("tabla", ["Dependencia", "Casos", "Cerrados", "Abiertos", "Días promedio"], filas_dep or [["Sin casos en el periodo", "", "", "", ""]],
         (40, 14, 14, 14, 16)),
        ("h", "Reportes de la ciudadanía"),
        ("tabla", ["Categoría", "Recibidos", "Validados o atendidos", "Descartados"],
         filas_cat or [["Sin reportes en el periodo", "", "", ""]], (40, 16, 22, 16)),
        ("h", "Riesgo para la salud por contacto con el agua (al día de hoy)"),
        ("tabla", ["Tramo", "Nivel", "Motivo principal"], [[t["tramo"], t["etiqueta"], t["razones"][0]] for t in rg["tramos"]], (10, 18, 72)),
        ("lista", rg["recomendaciones"][:3]),
        ("h", "Notas"),
        ("p", "Fuente: plataforma Vigía Atoyac (nodos de monitoreo del Alto Atoyac, App Ciudadana y estación piloto EP-1). "
              "Los sensores no miden bacterias ni metales pesados; para eso se requieren análisis de laboratorio."),
    ]
    if DEMO:
        bloques.append(("p", "Prototipo de HackaTec 2026: las lecturas, reportes y casos de este informe son datos de demostración simulados."))
    return bloques


@app.get("/api/informes/{nombre}.{formato}", tags=["informes"])
async def descargar_informe(nombre: str, formato: str, desde: Optional[str] = None, hasta: Optional[str] = None,
                            nodo: Optional[str] = None, u: Optional[dict] = Depends(actual)):
    """Informes para el Ayuntamiento, por periodo (`desde`/`hasta` en AAAA-MM-DD; 30 días si no se indica).
    Públicos: informe (PDF), indice, lecturas, estacion y basura. Casos y reportes: solo el personal, y cada
    dependencia ve completos los suyos."""
    if nombre not in INFORMES or formato not in MEDIOS or (formato == "pdf") != (nombre == "informe"):
        raise HTTPException(404, "Ese informe no existe.")
    titulo, solo_personal = INFORMES[nombre]
    if solo_personal and not _es_personal(u):
        raise HTTPException(403 if u else 401, "Este informe es solo para el personal de las dependencias.")
    if nodo and not con.execute("SELECT 1 FROM nodos WHERE id = ?", (nodo,)).fetchone():
        raise HTTPException(404, "El nodo no existe.")
    t0, t1, etiqueta, rango = _periodo(desde, hasta)
    generado = f"{informes.fecha(ahora()):%d/%m/%Y %H:%M} (hora del centro)"
    if nombre == "informe":
        contenido = await run_in_threadpool(informes.pdf, "Informe de calidad del agua del Alto Atoyac",
                                            f"Periodo: {etiqueta} · Generado el {generado}", _bloques_informe(t0, t1),
                                            "Vigía Atoyac · Informe del periodo")
    else:
        cols, filas = {"indice": lambda: _tabla_indice(t0, t1), "lecturas": lambda: _tabla_lecturas(t0, t1, nodo),
                       "estacion": lambda: _tabla_estacion(t0, t1), "basura": lambda: _tabla_basura(t0, t1, _es_personal(u)),
                       "casos": lambda: _tabla_casos(u, t0, t1), "reportes": lambda: _tabla_reportes(u, t0, t1)}[nombre]()
        if formato == "csv":
            contenido = informes.csv_bytes(cols, filas)
        else:
            portada = [(f"Vigía Atoyac · {titulo}", ""), ("Periodo", etiqueta), ("Registros", len(filas)), ("Generado", generado),
                       ("Fuente", "Plataforma Vigía Atoyac" + (" · datos de demostración simulados" if DEMO else ""))]
            contenido = await run_in_threadpool(informes.xlsx, [(titulo, cols, filas)], portada)
    archivo = f"vigia_{nombre}{'_' + nodo if nodo else ''}_{rango}.{formato}"
    return Response(content=contenido, media_type=MEDIOS[formato], headers={"Content-Disposition": f'attachment; filename="{archivo}"'})


# ---------- Red de nodos (Administración): alta, cambios, baja y ajustes ----------
class NodoNuevo(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=80)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    tec: str = Field("", max_length=80)


class NodoCambios(BaseModel):
    nombre: Optional[str] = Field(None, min_length=3, max_length=80)
    tec: Optional[str] = Field(None, max_length=80)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)


class AjustesRed(BaseModel):
    radio_km: float = Field(..., ge=0.2, le=20)
    vel_min: float = Field(..., ge=0.05, le=5)
    vel_max: float = Field(..., ge=0.1, le=10)
    dias_sin_visita: int = Field(..., ge=1, le=60)


def _red_respuesta() -> dict:
    return {**red.estado(con), "tramos": [modelos.tramo_api(f) for f in con.execute("SELECT * FROM tramos ORDER BY id")]}


async def _red_cambio(cambio, texto: str) -> dict:
    """Aplica un cambio a la red en una transacción. En la demo vuelve a generar los 90 días simulados (así un nodo
    nuevo trae datos); con datos reales recalcula el índice. Las pantallas abiertas se actualizan solas."""
    try:
        with transaccion(con):
            resultado = cambio()
    except red.ErrorRed as e:
        raise HTTPException(422, str(e))
    except LookupError:
        raise HTTPException(404, "Ese nodo no existe.")
    if DEMO:
        semilla.demostracion(con)
    else:
        with transaccion(con):
            for f in con.execute("SELECT id FROM nodos").fetchall():
                motor.recalcular_indice(con, f["id"])
    await canal.emitir("ajustes", {"kind": "info", "title": "Red de nodos actualizada", "msg": texto})
    return {"resultado": resultado, **_red_respuesta()}


@app.get("/api/red", tags=["red"])
async def red_ver(u: dict = Depends(con_permiso("config"))):
    return _red_respuesta()


@app.post("/api/red/nodos", tags=["red"], status_code=201)
async def red_alta(datos: NodoNuevo, u: dict = Depends(con_permiso("config"))):
    """Da de alta un nodo en el punto del río más cercano a (lat, lng); los tramos se recalculan solos."""
    return await _red_cambio(lambda: red.alta(con, datos.nombre, datos.lat, datos.lng, datos.tec),
                             f"Nodo nuevo: {datos.nombre.strip()}. Los tramos se recalcularon.")


@app.patch("/api/red/nodos/{nodo_id}", tags=["red"])
async def red_editar(nodo_id: str, datos: NodoCambios, u: dict = Depends(con_permiso("config"))):
    if (datos.lat is None) != (datos.lng is None):
        raise HTTPException(422, "Para mover un nodo manda latitud y longitud.")
    return await _red_cambio(lambda: red.editar(con, nodo_id, datos.nombre, datos.tec, datos.lat, datos.lng),
                             f"Se actualizó el nodo {nodo_id}.")


@app.post("/api/red/nodos/{nodo_id}/baja", tags=["red"])
async def red_baja(nodo_id: str, u: dict = Depends(con_permiso("config"))):
    """Saca el nodo de la red sin borrar sus lecturas; los tramos vecinos se unen."""
    return await _red_cambio(lambda: red.baja(con, nodo_id), f"El nodo {nodo_id} se dio de baja; sus lecturas se conservan.")


@app.post("/api/red/nodos/{nodo_id}/alta", tags=["red"])
async def red_reactivar(nodo_id: str, u: dict = Depends(con_permiso("config"))):
    return await _red_cambio(lambda: red.reactivar(con, nodo_id), f"El nodo {nodo_id} volvió a la red.")


@app.delete("/api/red/nodos/{nodo_id}", tags=["red"])
async def red_eliminar(nodo_id: str, u: dict = Depends(con_permiso("config"))):
    """Borra para siempre un nodo que ya estaba dado de baja, con sus lecturas. La red activa no cambia."""
    try:
        with transaccion(con):
            red.eliminar(con, nodo_id)
    except LookupError:
        raise HTTPException(404, "Solo se pueden eliminar nodos que ya estén dados de baja.")
    await canal.emitir("ajustes", {"kind": "info", "title": "Nodo eliminado", "msg": f"Se borró {nodo_id} con sus lecturas."})
    return _red_respuesta()


@app.put("/api/red/ajustes", tags=["red"])
async def red_ajustes(datos: AjustesRed, u: dict = Depends(con_permiso("config"))):
    """Radio para ligar reportes a un nodo, velocidades del agua (tiempo entre nodos) y días para marcar un nodo sin visita."""
    global DIAS_SIN_VISITA
    try:
        a = red.guardar_ajustes(con, datos.radio_km, datos.vel_min, datos.vel_max, datos.dias_sin_visita)
    except red.ErrorRed as e:
        raise HTTPException(422, str(e))
    DIAS_SIN_VISITA = a["dias_sin_visita"]
    await canal.emitir("ajustes", {"kind": "info", "title": "Ajustes de la red guardados",
                                   "msg": f"Radio de reportes {a['radio_km']} km · agua de {a['vel_min']} a {a['vel_max']} m/s."})
    return _red_respuesta()


CAPACIDAD_KG = {"B1": 260, "B2": 340, "B3": 210}         # basura que cabe en cada barrera llena


def registrar_vaciado(barrera_id: str, llenado: float, por: str) -> None:
    """Kilos estimados por el llenado al momento de vaciar (la báscula del camión puede corregirlos después)."""
    kg = round(CAPACIDAD_KG.get(barrera_id, 250) * max(0.0, min(100.0, llenado or 0)) / 100)
    con.execute("INSERT INTO vaciados (barrera, t, kg, quien) VALUES (?, ?, ?, ?)", (barrera_id, ahora(), kg, por))


class EditarBarrera(BaseModel):
    fill: Optional[float] = Field(None, ge=0, le=100)
    nivel: Optional[float] = Field(None, ge=0, le=20)
    vaciada: bool = False


@app.patch("/api/barreras/{barrera_id}", tags=["datos"])
async def editar_barrera(barrera_id: str, datos: EditarBarrera, u: dict = Depends(con_permiso("barreras"))):
    """Lo que se registra en la visita a una barrera: llenado, nivel del agua o que ya se vació."""
    b = con.execute("SELECT * FROM barreras WHERE id = ?", (barrera_id,)).fetchone()
    if not b:
        raise HTTPException(404, "La barrera no existe.")
    llenado = 5 if datos.vaciada else (datos.fill if datos.fill is not None else b["llenado"])
    nivel = datos.nivel if datos.nivel is not None else b["nivel"]
    if datos.vaciada:
        registrar_vaciado(barrera_id, b["llenado"], quien(u))
    con.execute("UPDATE barreras SET llenado = ?, nivel = ?, ultima_descarga = ?, ultimo_vaciado = ? WHERE id = ?",
                (llenado, nivel, ahora(), ahora() if datos.vaciada else b["ultimo_vaciado"], barrera_id))
    b = con.execute("SELECT * FROM barreras WHERE id = ?", (barrera_id,)).fetchone()
    creados = [c for c in (motor.caso_barrera_llena(con, b),
                           motor.caso_inundacion(con, b["id"], b["nombre"], b["lat"], b["lng"], nivel, ahora(), es_barrera=True)
                           if nivel >= b["nivel_max"] * 0.85 else None) if c]
    await avisar_casos(creados)
    await canal.emitir("barrera")
    return modelos.barrera_api(b)


# ---------- Umbrales del semáforo ----------
class Umbrales(BaseModel):
    params: dict


@app.put("/api/ajustes/umbrales", tags=["datos"])
async def guardar_umbrales(datos: Umbrales, u: dict = Depends(con_permiso("config"))):
    limpio = {}
    for k, defecto in motor.UMBRALES_DEF.items():
        nuevo = {}
        for campo in defecto:
            v = (datos.params.get(k) or {}).get(campo, defecto[campo])
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) > 1e6:
                raise HTTPException(422, f"El valor de {k} no es un número válido.")
            nuevo[campo] = v
        if k == "ph":
            if not (nuevo["critMin"] <= nuevo["min"] < nuevo["max"] <= nuevo["critMax"]):
                raise HTTPException(422, "En pH, el rango normal debe quedar dentro del rango crítico.")
        elif not nuevo["crit"] > nuevo["warn"]:
            raise HTTPException(422, "El umbral crítico debe ser mayor que el de atención.")
        limpio[k] = nuevo
    guardar_ajuste(con, "umbrales", limpio)
    await canal.emitir("ajustes")
    return motor.umbrales(con)


# =========================================================
# REPORTES DE LA APP
# =========================================================
FIRMAS = {b"\xff\xd8\xff": ".jpg", b"\x89PNG\r\n\x1a\n": ".png"}
MAX_FOTO = 5 * 1024 * 1024
PRECISION_MAX_M = 20.0                   # el reporte marca el lugar del suceso: margen del GPS de 20 m o menos


_CLASIFICADOR_FN = None
_CLASIFICADOR_CARGADO = False


def clasificar_foto(ruta) -> Optional[tuple]:
    """Punto de conexión del modelo de visión híbrido (app-ciudadana/integracion-ia/clasificador_hibrido.py).
    Devuelve (categoría, confianza) o None si no hay modelo/confianza suficiente."""
    global _CLASIFICADOR_FN, _CLASIFICADOR_CARGADO
    if not _CLASIFICADOR_CARGADO:
        _CLASIFICADOR_CARGADO = True
        try:
            import importlib.util
            mod_path = WEB.parent / "app-ciudadana" / "integracion-ia" / "clasificador_hibrido.py"
            if mod_path.is_file():
                spec = importlib.util.spec_from_file_location("ecored_clasificador_hibrido", mod_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    _CLASIFICADOR_FN = getattr(mod, "clasificar_foto", None)
        except Exception:
            _CLASIFICADOR_FN = None
    if _CLASIFICADOR_FN is None:
        return None
    try:
        return _CLASIFICADOR_FN(ruta)
    except Exception:
        return None


def _extension_foto(datos: bytes) -> Optional[str]:
    for firma, ext in FIRMAS.items():
        if datos.startswith(firma):
            return ext
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return ".webp"
    return None


async def despues_de_reporte(fila) -> None:
    """Un reporte nuevo puede respaldar una descarga abierta o completar un grupo de basura."""
    with transaccion(con):
        cambiados = motor.revisar_descargas_abiertas(con, solo_pendientes=False)
        caso = motor.agrupar_basura(con, fila)
    lugar = con.execute("SELECT nombre, lat, lng FROM nodos").fetchall() + con.execute("SELECT nombre, lat, lng FROM barreras").fetchall()
    cerca = min(lugar, key=lambda p: motor.km(fila["lat"], fila["lng"], p["lat"], p["lng"]))["nombre"]
    await canal.emitir("reporte", {"kind": "info", "title": "Nuevo reporte desde la app", "msg": f"{fila['cat']} cerca de {cerca}. Folio {fila['id']}."},
                       seguridad.PERSONAL)
    await avisar_casos([caso] if caso else [], cambiados)


@app.post("/api/reportes", status_code=201, tags=["reportes"])
async def crear_reporte(request: Request, cat: str = Form(...), lat: float = Form(...), lng: float = Form(...),
                        texto: str = Form(""), anonimo: bool = Form(False), voz: bool = Form(False),
                        ia_etiqueta: str = Form(""), ia_confianza: Optional[float] = Form(None),
                        ubicacion: str = Form(""), precision_m: Optional[float] = Form(None),
                        foto: Optional[UploadFile] = File(None), u: Optional[dict] = Depends(actual)):
    """Reporte ciudadano (lo envía la app). Con sesión queda ligado a la cuenta para avisarle del avance;
    sin sesión o con `anonimo=true` no se guarda quién lo envió. La ubicación es el lugar del suceso:
    `ubicacion=gps` con `precision_m` de 20 m o menos, o `ubicacion=mapa` si la persona marcó el punto a mano."""
    if cat not in motor.CATEGORIAS:
        raise HTTPException(422, "Categoría no válida. Usa: " + ", ".join(motor.CATEGORIAS) + ".")
    if not (AREA[0] <= lat <= AREA[1] and AREA[2] <= lng <= AREA[3]):
        raise HTTPException(422, "La ubicación está fuera del estado de Puebla.")
    if ubicacion == "gps" or precision_m is not None:
        if precision_m is None or not 0 <= precision_m <= PRECISION_MAX_M:
            margen = f"±{precision_m:.0f} m" if precision_m is not None else "una ubicación sin margen"
            raise HTTPException(422, f"El GPS marca {margen} y el lugar del suceso necesita {PRECISION_MAX_M:.0f} m o menos. "
                                     "Vuelve a tomar el GPS a cielo abierto o marca el punto exacto en el mapa.")
        ubicacion = "gps"
    elif ubicacion != "mapa":
        ubicacion = None                                         # versiones anteriores de la app: sin dato
    if not cuota_reportes.permitir(f"u{u['id']}" if u else ip(request)):
        raise HTTPException(429, "Llegaron muchos reportes desde aquí en poco tiempo. Inténtalo más tarde.")
    nombre_foto = None
    if foto is not None and foto.filename:
        datos = await foto.read(MAX_FOTO + 1)
        if len(datos) > MAX_FOTO:
            raise HTTPException(413, "La foto pesa más de 5 MB.")
        ext = _extension_foto(datos)
        if not ext:
            raise HTTPException(415, "La foto debe ser JPG, PNG o WebP.")
        nombre_foto = secrets.token_hex(16) + ext
        (FOTOS / nombre_foto).write_bytes(datos)
    # Fuera del hilo principal: la consulta a Gemini puede tardar segundos y no debe congelar el servidor
    # (el clasificador no toca la base de datos, así que puede correr en otro hilo)
    ia = await run_in_threadpool(clasificar_foto, FOTOS / nombre_foto) if nombre_foto else None
    if not ia and ia_etiqueta in motor.CATEGORIAS and ia_confianza is not None and 0 <= ia_confianza <= 1:
        ia = (ia_etiqueta, ia_confianza)                                # clasificación hecha en el teléfono
    folio = f"R-{siguiente(con, 'reporte', 1300)}"
    con.execute("""INSERT INTO reportes (id, usuario_id, cat, ia_etiqueta, ia_confianza, lat, lng, t, estado, anonimo, voz, texto, foto,
                                         ubicacion, precision_m)
                   VALUES (?,?,?,?,?,?,?,?,'Recibido',?,?,?,?,?,?)""",
                (folio, None if anonimo or not u else u["id"], cat, ia[0] if ia else None, ia[1] if ia else None, lat, lng, ahora(),
                 int(anonimo or not u), int(voz), texto.strip()[:500], nombre_foto,
                 ubicacion, round(precision_m, 1) if precision_m is not None else None))
    fila = con.execute("SELECT * FROM reportes WHERE id = ?", (folio,)).fetchone()
    await despues_de_reporte(fila)
    return modelos.reporte_api(con.execute("SELECT * FROM reportes WHERE id = ?", (folio,)).fetchone(), True, u["id"] if u else None)


@app.get("/api/reportes", tags=["reportes"])
async def listar_reportes(mios: bool = False, dias: int = 30, u: Optional[dict] = Depends(actual)):
    """Personal de gobierno: reportes completos. Público: solo categoría, zona aproximada y estado. `mios=true`: los de mi cuenta."""
    if mios:
        if not u:
            raise HTTPException(401, "Inicia sesión para ver tus reportes.")
        return [modelos.reporte_api(f, True, u["id"]) for f in con.execute("SELECT * FROM reportes WHERE usuario_id = ? ORDER BY t DESC", (u["id"],))]
    return _reportes(u, ahora() - max(1, min(dias, 365)) * D)


@app.get("/api/reportes/{folio}", tags=["reportes"])
async def ver_reporte(folio: str, u: Optional[dict] = Depends(actual)):
    """Seguimiento por folio (también sirve para reportes anónimos)."""
    f = con.execute("SELECT * FROM reportes WHERE id = ?", (folio,)).fetchone()
    if not f:
        raise HTTPException(404, "No hay un reporte con ese folio.")
    uid = u["id"] if u else None
    return modelos.reporte_api(f, _es_personal(u) or (uid is not None and f["usuario_id"] == uid), uid)


@app.get("/api/reportes/{folio}/foto", tags=["reportes"])
async def foto_reporte(folio: str, u: dict = Depends(con_sesion)):
    f = con.execute("SELECT usuario_id, foto FROM reportes WHERE id = ?", (folio,)).fetchone()
    if not f or not f["foto"] or not (FOTOS / f["foto"]).is_file():
        raise HTTPException(404, "Este reporte no tiene foto.")
    if not (_es_personal(u) or f["usuario_id"] == u["id"]):
        raise HTTPException(403, "Tu cuenta no tiene permiso para esto.")
    return FileResponse(FOTOS / f["foto"], headers={"Cache-Control": "private, max-age=3600"})


class EstadoReporte(BaseModel):
    estado: str


@app.patch("/api/reportes/{folio}", tags=["reportes"])
async def editar_reporte(folio: str, datos: EstadoReporte, u: dict = Depends(con_permiso("validar"))):
    if datos.estado not in motor.ESTADOS_REPORTE:
        raise HTTPException(422, "Estado no válido.")
    f = con.execute("SELECT * FROM reportes WHERE id = ?", (folio,)).fetchone()
    if not f:
        raise HTTPException(404, "No hay un reporte con ese folio.")
    if f["estado"] != datos.estado:
        con.execute("UPDATE reportes SET estado = ? WHERE id = ?", (datos.estado, folio))
        motor.notificar(con, f["usuario_id"], "Tu reporte avanzó", f"El reporte {folio} ({f['cat'].lower()}) ahora está: {datos.estado}.", reporte=folio)
        await canal.emitir("reporte")
    cuerpo = modelos.reporte_api(con.execute("SELECT * FROM reportes WHERE id = ?", (folio,)).fetchone(), True, u["id"])
    cuerpo["notified"] = bool(f["usuario_id"]) and f["estado"] != datos.estado
    return cuerpo


# =========================================================
# CASOS
# =========================================================
class AccionCaso(BaseModel):
    accion: str                                   # atender | inspeccion | lab | cerrar
    lab: Optional[str] = Field(None, max_length=2000)


@app.get("/api/casos", tags=["casos"])
async def listar_casos(u: Optional[dict] = Depends(actual)):
    """Cada dependencia ve completos sus casos; el resto se devuelve en versión pública (folio, tipo, lugar y estado)."""
    return _casos(u)


@app.get("/api/casos/{caso_id}", tags=["casos"])
async def ver_caso(caso_id: str, u: Optional[dict] = Depends(actual)):
    f = con.execute("SELECT * FROM casos WHERE id = ?", (caso_id,)).fetchone()
    if not f:
        raise HTTPException(404, "El caso no existe.")
    return modelos.caso_api(f, f["dep"] in _deps(u))


@app.patch("/api/casos/{caso_id}", tags=["casos"])
async def actuar_caso(caso_id: str, datos: AccionCaso, u: dict = Depends(con_sesion)):
    d = motor.leer_caso(con, caso_id)
    if not d:
        raise HTTPException(404, "El caso no existe.")
    if d["dep"] not in _deps(u):
        raise HTTPException(403, "Solo Administración puede actualizar los casos.")
    if d["estado"] == "Cerrado":
        raise HTTPException(409, "El caso ya está cerrado.")
    firma = f"{motor.DEPENDENCIAS[d['dep']]} (vía Administración)"
    aviso = None
    if datos.accion == "atender":
        if d["estado"] != "Nuevo":
            raise HTTPException(409, "El caso ya está en atención.")
        d["estado"] = "En atención"
        d["historial"].append(motor.paso(firma, "Caso en atención"))
        aviso = "ya está en atención"
    elif datos.accion == "inspeccion":
        if d["tipo"] != "descarga":
            raise HTTPException(422, "Solo los casos de descarga llevan inspección.")
        d["estado"] = "Inspección programada"
        d["historial"].append(motor.paso(firma, "Inspección programada"))
        aviso = "tiene una inspección programada"
    elif datos.accion == "lab":
        if d["tipo"] != "descarga":
            raise HTTPException(422, "Solo los casos de descarga llevan resultado de laboratorio.")
        if not (datos.lab or "").strip():
            raise HTTPException(422, "Escribe el resultado de laboratorio.")
        d["lab"] = datos.lab.strip()
        d["historial"].append(motor.paso(firma, "Resultado de laboratorio capturado" + (f" (muestra {d['muestra']})" if d["muestra"] else "")))
    elif datos.accion == "cerrar":
        d["estado"], d["cerrado"] = "Cerrado", ahora()
        d["historial"].append(motor.paso(firma, "Caso cerrado; se avisó a quienes reportaron"))
        aviso = "se atendió y quedó cerrado"
    else:
        raise HTTPException(422, "Acción no válida.")
    avisados = 0
    with transaccion(con):
        motor.guardar_caso(con, d)
        if datos.accion == "cerrar":
            if d["barrera"] and d["tipo"] == "basura":
                b = con.execute("SELECT llenado FROM barreras WHERE id = ?", (d["barrera"],)).fetchone()
                registrar_vaciado(d["barrera"], b["llenado"] if b else 0, firma)
                con.execute("UPDATE barreras SET llenado = 5, ultimo_vaciado = ? WHERE id = ?", (ahora(), d["barrera"]))
            for rid in d["reportes"]:
                con.execute("UPDATE reportes SET estado = 'Atendido' WHERE id = ? AND estado <> 'Descartado'", (rid,))
        if aviso:
            for rid in d["reportes"]:
                r = con.execute("SELECT usuario_id FROM reportes WHERE id = ?", (rid,)).fetchone()
                if r and r["usuario_id"]:
                    motor.notificar(con, r["usuario_id"], "Tu reporte avanzó", f"El caso {d['id']} ligado a tu reporte {rid} {aviso}.", caso=d["id"], reporte=rid)
                    avisados += 1
    await canal.emitir("caso")
    cuerpo = modelos.caso_api(con.execute("SELECT * FROM casos WHERE id = ?", (caso_id,)).fetchone(), True)
    cuerpo["notified"] = avisados                                      # personas que reciben el aviso en la app
    return cuerpo


# =========================================================
# RECOLECCIÓN: carga por lote del archivo de la microSD
# =========================================================
def _resumen_lote(res: dict) -> dict:
    limpio = {k: v for k, v in res.items() if k not in ("creados", "actualizados")}
    limpio["casos"] = [c["id"] for c in res["creados"]]
    limpio["casos_actualizados"] = [c["id"] for c in res["actualizados"]]
    return limpio


@app.post("/api/sincronizacion", tags=["recolección"])
async def sincronizar(nodo: str = Form(...), archivo: UploadFile = File(...), limpieza: bool = Form(False),
                      calibracion: bool = Form(False), frascos: bool = Form(False),
                      u: dict = Depends(con_permiso("recoleccion"))):
    """Sube el CSV que se descargó del nodo en la visita. El servidor guarda las lecturas nuevas,
    busca eventos con su hora real, los cruza con los reportes y abre o actualiza los casos."""
    if not con.execute("SELECT 1 FROM nodos WHERE id = ?", (nodo,)).fetchone():
        raise HTTPException(404, "El nodo no existe.")
    contenido = await archivo.read(lotes.MAX_BYTES + 1)
    try:
        leido = lotes.leer_csv(contenido, nodo, ahora())
    except ValueError as e:
        raise HTTPException(422, str(e))
    nombre = re.sub(r"[^\w.\- ]", "_", os.path.basename(archivo.filename or "lote.csv"))[:80]
    # Es fácil confundir archivos al visitar varios nodos el mismo día: dos candados antes de guardar
    otro = re.match(r"(N\d+)", nombre.upper())
    if otro and otro.group(1) != nodo and con.execute("SELECT 1 FROM nodos WHERE id = ?", (otro.group(1),)).fetchone():
        raise HTTPException(422, f"El nombre del archivo indica {otro.group(1)}, pero elegiste {nodo}. Revisa que sea el archivo correcto.")
    if leido["integridad"] == "alterada:1":
        raise HTTPException(422, f"La huella del archivo no corresponde a {nodo} desde la primera fila. Revisa que el archivo sea de este nodo.")
    res = motor.ingerir(con, nodo, leido["filas"], quien(u), usuario_id=u["id"], archivo=nombre, integridad=leido["integridad"],
                        invalidas=leido["invalidas"], checklist={"limpieza": limpieza, "calibracion": calibracion, "frascos": frascos})
    await canal.emitir("lote")
    await avisar_casos(res["creados"], res["actualizados"])
    return _resumen_lote(res)


@app.get("/api/sincronizacion/ejemplo", tags=["recolección"], response_class=PlainTextResponse)
async def csv_de_ejemplo(nodo: str = "N3", evento: str = "normal", horas: int = 6, u: dict = Depends(con_permiso("recoleccion"))):
    """Archivo de ejemplo con el formato exacto de la microSD (valores simulados). Sirve para probar la carga
    y como referencia para el firmware. `evento`: normal | descarga | crecida."""
    f = con.execute("SELECT * FROM nodos WHERE id = ?", (nodo,)).fetchone()
    if not f or evento not in ("normal", "descarga", "crecida"):
        raise HTTPException(404, "Nodo o evento no válido.")
    t = ahora()
    filas = lotes.simular(json.loads(f["base"]), t - max(1, min(horas, 168)) * H, t, evento, f["bateria"] or 80, "M-0000",
                          nodo=nodo, estacion=semilla.tiene_estacion(nodo))
    return PlainTextResponse(lotes.a_csv(nodo, filas), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nodo}_ejemplo_{evento}.csv"'})


@app.get("/api/lotes", tags=["recolección"])
async def listar_lotes(u: dict = Depends(con_permiso("recoleccion"))):
    filas = con.execute("""SELECT l.*, COALESCE(us.nombre, 'Carga inicial') AS quien FROM lotes l LEFT JOIN usuarios us ON us.id = l.usuario_id
                           ORDER BY l.subido DESC LIMIT 50""").fetchall()
    return [modelos.lote_api(f) for f in filas]


# =========================================================
# MÉTRICAS Y NOTIFICACIONES
# =========================================================
@app.get("/api/metricas", tags=["datos"])
async def metricas():
    """Indicadores públicos del tablero: nodos, semáforo por tramo, casos y reportes."""
    t, u = ahora(), motor.umbrales(con)
    estados = {}
    nodos_info = {"total": 0, "al_dia": 0, "sin_visita": 0, "bateria_baja": 0}
    for n in con.execute("SELECT id, bateria, ultima_descarga FROM nodos"):
        nodos_info["total"] += 1
        viejo = not n["ultima_descarga"] or t - n["ultima_descarga"] > DIAS_SIN_VISITA * D
        nodos_info["sin_visita" if viejo else "al_dia"] += 1
        nodos_info["bateria_baja"] += int((n["bateria"] or 100) < 25)
        ult = con.execute("SELECT * FROM lecturas WHERE nodo = ? ORDER BY t DESC LIMIT 1", (n["id"],)).fetchone()
        estados[n["id"]] = "off" if viejo or not ult else motor.estado_lectura(dict(ult), u)
    semaforo = {"ok": 0, "warn": 0, "crit": 0, "off": 0}
    por_tramo = {}
    for tr in con.execute("SELECT id, hasta FROM tramos"):
        por_tramo[tr["id"]] = estados.get(tr["hasta"], "off")
        semaforo[por_tramo[tr["id"]]] += 1
    cerrados = con.execute("SELECT t, cerrado, dep FROM casos WHERE cerrado IS NOT NULL").fetchall()
    dias = [(c["cerrado"] - c["t"]) / D for c in cerrados]
    return {
        "ahora": t, "nodos": nodos_info, "tramos": semaforo, "tramos_detalle": por_tramo,
        "casos": {
            "abiertos": con.execute("SELECT COUNT(*) AS c FROM casos WHERE estado <> 'Cerrado'").fetchone()["c"],
            "cerrados": len(cerrados),
            "dias_promedio_atencion": round(sum(dias) / len(dias), 1) if dias else None,
            "por_tipo": {f["tipo"]: f["c"] for f in con.execute("SELECT tipo, COUNT(*) AS c FROM casos GROUP BY tipo")},
            "por_dependencia": {f["dep"]: f["c"] for f in con.execute("SELECT dep, COUNT(*) AS c FROM casos GROUP BY dep")},
        },
        "reportes": {
            "total": con.execute("SELECT COUNT(*) AS c FROM reportes").fetchone()["c"],
            "ultimos_7_dias": con.execute("SELECT COUNT(*) AS c FROM reportes WHERE t >= ?", (t - 7 * D,)).fetchone()["c"],
            "por_categoria": {f["cat"]: f["c"] for f in con.execute("SELECT cat, COUNT(*) AS c FROM reportes GROUP BY cat")},
            "por_estado": {f["estado"]: f["c"] for f in con.execute("SELECT estado, COUNT(*) AS c FROM reportes GROUP BY estado")},
        },
    }


@app.get("/api/notificaciones", tags=["sesión"])
async def notificaciones(u: dict = Depends(con_sesion)):
    """Avisos para la persona que inició sesión (la app los muestra como notificaciones push)."""
    return [dict(f) for f in con.execute("SELECT id, t, titulo, texto, leida, caso, reporte FROM notificaciones WHERE usuario_id = ? ORDER BY t DESC LIMIT 50", (u["id"],))]


@app.post("/api/notificaciones/leidas", tags=["sesión"])
async def marcar_leidas(u: dict = Depends(con_sesion)):
    con.execute("UPDATE notificaciones SET leida = 1 WHERE usuario_id = ?", (u["id"],))
    return {"ok": True}


# =========================================================
# DEMOSTRACIÓN (solo Administración y solo con VA_DEMO=1)
# =========================================================
class DemoVisita(BaseModel):
    nodo: str = "N3"
    evento: str = "normal"                        # normal | descarga | crecida


class DemoBarrera(BaseModel):
    barrera: str = "B1"


@app.post("/api/demo/reporte", tags=["demo"])
async def demo_reporte(u: dict = Depends(con_permiso("config"))):
    """Simula un reporte de «agua de color» enviado desde la app en la orilla del río, antes de Xoxtla."""
    solo_demo()
    ciudadana = con.execute("SELECT id FROM usuarios WHERE rol = 'ciudadano' AND demo = 1 LIMIT 1").fetchone()
    folio = f"R-{siguiente(con, 'reporte', 1300)}"
    lat, lng = semilla.en_tramo(1, 0.8)                                 # sobre el tramo Huejotzingo → Xoxtla
    con.execute("""INSERT INTO reportes (id, usuario_id, cat, ia_etiqueta, ia_confianza, lat, lng, t, estado, anonimo, voz, texto)
                   VALUES (?, ?, 'Agua de color', 'Agua de color', 0.93, ?, ?, ?, 'Recibido', 0, 0, ?)""",
                (folio, ciudadana["id"] if ciudadana else None, lat, lng, ahora(), "Reporte simulado: agua azul en la orilla del río."))
    await despues_de_reporte(con.execute("SELECT * FROM reportes WHERE id = ?", (folio,)).fetchone())
    return {"reporte": folio}


@app.post("/api/demo/visita", tags=["demo"])
async def demo_visita(datos: DemoVisita, u: dict = Depends(con_permiso("config"))):
    """Simula la visita de Protección Civil: genera el archivo que habría guardado el nodo desde su última
    descarga (con o sin evento) y lo pasa por el mismo camino que un archivo real."""
    solo_demo()
    f = con.execute("SELECT * FROM nodos WHERE id = ?", (datos.nodo,)).fetchone()
    if not f or datos.evento not in ("normal", "descarga", "crecida"):
        raise HTTPException(404, "Nodo o evento no válido.")
    t = ahora()
    ultima = con.execute("SELECT MAX(t) AS m FROM lecturas WHERE nodo = ?", (datos.nodo,)).fetchone()["m"] or 0
    if ultima > t - 45 * 60 * 1000:
        raise HTTPException(409, f"{datos.nodo} se acaba de descargar y no tiene datos nuevos. Usa «Reiniciar demo» para repetir la simulación.")
    folio = f"M-{siguiente(con, 'muestra', 20):04d}" if datos.evento == "descarga" else ""
    filas = lotes.simular(json.loads(f["base"]), max(ultima + 10 * 60 * 1000, t - 5 * D), t, datos.evento, f["bateria"] or 80, folio,
                          nodo=datos.nodo, estacion=semilla.tiene_estacion(datos.nodo))
    leido = lotes.leer_csv(lotes.a_csv(datos.nodo, filas).encode("utf-8"), datos.nodo, t)
    res = motor.ingerir(con, datos.nodo, leido["filas"], "Protección Civil", usuario_id=u["id"], archivo=f"{datos.nodo}_visita_simulada.csv",
                        integridad=leido["integridad"], invalidas=leido["invalidas"], checklist={"limpieza": True, "calibracion": False, "frascos": bool(folio)})
    await canal.emitir("lote")
    await avisar_casos(res["creados"], res["actualizados"])
    return _resumen_lote(res)


@app.post("/api/demo/barrera", tags=["demo"])
async def demo_barrera(datos: DemoBarrera, u: dict = Depends(con_permiso("config"))):
    solo_demo()
    if not con.execute("SELECT 1 FROM barreras WHERE id = ?", (datos.barrera,)).fetchone():
        raise HTTPException(404, "La barrera no existe.")
    con.execute("UPDATE barreras SET llenado = 94, ultima_descarga = ? WHERE id = ?", (ahora(), datos.barrera))
    caso = motor.caso_barrera_llena(con, con.execute("SELECT * FROM barreras WHERE id = ?", (datos.barrera,)).fetchone())
    await canal.emitir("barrera")
    await avisar_casos([caso] if caso else [])
    return {"caso": caso["id"] if caso else None}


@app.post("/api/demo/reiniciar", tags=["demo"])
async def demo_reiniciar(u: dict = Depends(con_permiso("config"))):
    """Regresa los datos de demostración al punto de partida (no toca las cuentas)."""
    solo_demo()
    semilla.demostracion(con)
    await canal.emitir("reinicio", {"kind": "info", "title": "Demo reiniciada", "msg": "Los datos de demostración volvieron al punto de partida."})
    return {"ok": True}


# =========================================================
# PÁGINAS Y ARCHIVOS DE LA WEB
# =========================================================
@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def pagina_principal(request: Request):
    """La plataforma (sensores, casos, reportes, configuración) es de Administración. Quien llega sin esa sesión
    va directo a reportar en la app ciudadana; Administración entra por /login.html."""
    fila = seguridad.usuario_de_token(con, request.cookies.get(seguridad.COOKIE, ""))
    if not fila or fila["rol"] not in seguridad.PERSONAL:
        return RedirectResponse(url="/app/", status_code=302)
    return FileResponse(WEB / "index.html")


@app.get("/mapa", include_in_schema=False)
async def pagina_mapa():
    """Mapa 3D público: el mismo de la plataforma, sin el panel de datos. La App Ciudadana lo muestra en «Mapa»."""
    return FileResponse(WEB / "mapa.html")


@app.get("/login.html", include_in_schema=False)
async def pagina_login():
    return FileResponse(WEB / "login.html")


# Solo se publican estas carpetas: nunca server/ ni la base de datos
for carpeta in ("css", "js", "vendor"):
    app.mount("/" + carpeta, StaticFiles(directory=WEB / carpeta), name=carpeta)

APP_CIUDADANA = WEB.parent / "app-ciudadana"
if APP_CIUDADANA.is_dir():
    @app.get("/app", include_in_schema=False)
    async def app_ciudadana_redir():
        return RedirectResponse(url="/app/", status_code=307)

    @app.get("/app/", include_in_schema=False)
    @app.get("/app/index.html", include_in_schema=False)
    async def app_ciudadana_inicio():
        return FileResponse(APP_CIUDADANA / "index.html")

    @app.get("/app/manifest.json", include_in_schema=False)
    async def app_ciudadana_manifest():
        return FileResponse(APP_CIUDADANA / "manifest.json", media_type="application/manifest+json")

    @app.get("/app/sw.js", include_in_schema=False)
    async def app_ciudadana_sw():
        return FileResponse(APP_CIUDADANA / "sw.js", media_type="application/javascript")

    for carpeta in ("css", "js", "vendor", "icons"):
        ruta_carpeta = APP_CIUDADANA / carpeta
        if ruta_carpeta.is_dir():
            app.mount("/app/" + carpeta, StaticFiles(directory=ruta_carpeta), name="app_" + carpeta)
