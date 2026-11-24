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
import re
import secrets
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import lotes, modelos, motor, seguridad, semilla
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
semilla.catalogo(con)
if DEMO:
    semilla.cuentas_demo(con)
    if not con.execute("SELECT 1 FROM lecturas LIMIT 1").fetchone():
        semilla.demostracion(con)
    print(f"[Vigía Atoyac] MODO DEMO: cuentas de prueba en {semilla.ARCHIVO_CUENTAS}. No usar así en un servidor público.")
elif not semilla.admin_inicial(con):
    print("[Vigía Atoyac] No hay usuarios. Define VA_ADMIN_CUENTA y VA_ADMIN_CLAVE (8+ caracteres) y vuelve a iniciar.")

intentos = seguridad.LimiteIntentos()                                   # por dirección + cuenta
intentos_ip = seguridad.LimiteIntentos(maximo=30)                       # por dirección
cuota_registro = seguridad.Cuota(10, 3600)
cuota_reportes = seguridad.Cuota(20, 3600)


# ---------- Cabeceras de seguridad y caché ----------
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://server.arcgisonline.com https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com; "
       "connect-src 'self' ws: wss:; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")


@app.middleware("http")
async def cabeceras(request: Request, call_next):
    resp = await call_next(request)
    ruta = request.url.path
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    if not ruta.startswith("/api/docs"):
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Frame-Options"] = "DENY"
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
    # Con cookie, todo lo que modifica datos exige una cabecera propia: otra página web no puede enviarla
    if fila and via == "cookie" and request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-va") != "1":
        raise HTTPException(403, "Solicitud no permitida.")
    return dict(fila) if fila else None


async def con_sesion(u: Optional[dict] = Depends(actual)) -> dict:
    if not u:
        raise HTTPException(401, "Inicia sesión para continuar.")
    return u


def con_rol(*roles):
    async def dependencia(u: dict = Depends(con_sesion)) -> dict:
        if u["rol"] not in roles:
            raise HTTPException(403, "Tu cuenta no tiene permiso para esto.")
        return u
    return dependencia


def solo_demo() -> None:
    if not DEMO:
        raise HTTPException(404, "No disponible.")


# Cabeceras que agrega cualquier intermediario (Cloudflare Tunnel, ngrok, un proxy inverso)
_CABECERAS_DE_PROXY = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded", "x-real-ip",
                       "cf-connecting-ip", "cf-ray", "cdn-loop", "via")


def es_local(request: Request) -> bool:
    """La petición viene de un navegador en la misma computadora del servidor.
    Tres candados, porque de esto depende la entrada rápida de demostración: la conexión sale de
    esta máquina, no trae cabeceras de intermediario y la dirección escrita en el navegador es
    localhost. Quien entra por un enlace público (túnel) no cumple ninguno de los dos últimos."""
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        return False
    if any(c in request.headers for c in _CABECERAS_DE_PROXY):
        return False
    try:
        anfitrion = urlsplit("//" + request.headers.get("host", "")).hostname
    except ValueError:
        return False
    return anfitrion in ("localhost", "127.0.0.1", "::1")


def ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def quien(u: dict) -> str:
    etiqueta = seguridad.ROLES[u["rol"]]["label"]
    return etiqueta if u.get("demo") else f"{etiqueta} ({u['nombre']})"


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
    canal.abiertos[ws] = fila["rol"] if fila else None
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


class CuentaDemo(BaseModel):
    cuenta: str


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
        raise HTTPException(401, "La cuenta o la contraseña no son correctas.")
    intentos.exito(llave)
    return fijar_sesion(request, response, fila, datos.origen)


@app.post("/api/auth/demo", tags=["sesión"])
async def entrar_demo(datos: CuentaDemo, request: Request, response: Response):
    """Entrada rápida con una cuenta de demostración. Solo en modo demo y solo desde la computadora del servidor."""
    solo_demo()
    if not es_local(request):
        raise HTTPException(403, "La entrada rápida solo funciona en la computadora del servidor.")
    fila = con.execute("SELECT * FROM usuarios WHERE cuenta = ? AND demo = 1 AND activo = 1", (datos.cuenta.strip().lower(),)).fetchone()
    if not fila:
        raise HTTPException(404, "Esa cuenta de demostración no existe.")
    return fijar_sesion(request, response, fila, "web")


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
    d = {"usuario": modelos.usuario_api(u) if u else None, "demo": DEMO,
         "roles": {k: v["label"] for k, v in seguridad.ROLES.items()}}
    if DEMO and es_local(request):
        d["cuentas_demo"] = [dict(f) for f in con.execute("SELECT cuenta, nombre, rol FROM usuarios WHERE demo = 1 AND activo = 1 ORDER BY id")]
    return d


@app.post("/api/auth/clave", tags=["sesión"])
async def cambiar_clave(datos: CambioClave, request: Request, u: dict = Depends(con_sesion)):
    fila = con.execute("SELECT hash FROM usuarios WHERE id = ?", (u["id"],)).fetchone()
    if not await run_in_threadpool(seguridad.verificar_clave, datos.actual, fila["hash"]):
        raise HTTPException(403, "La contraseña actual no es correcta.")
    try:
        seguridad.validar_clave(datos.nueva, u["cuenta"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    con.execute("UPDATE usuarios SET hash = ? WHERE id = ?", (await run_in_threadpool(seguridad.crear_hash, datos.nueva), u["id"]))
    seguridad.cerrar_sesiones_de(con, u["id"], excepto_token=request.state.token)
    return {"ok": True}


# =========================================================
# USUARIOS (Administración)
# =========================================================
class NuevoUsuario(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=80)
    cuenta: str = Field(..., max_length=120)
    rol: str
    clave: str = Field(..., max_length=128)


class EditarUsuario(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=80)
    rol: Optional[str] = None
    activo: Optional[bool] = None
    clave: Optional[str] = Field(None, max_length=128)


@app.get("/api/usuarios", tags=["usuarios"])
async def usuarios(u: dict = Depends(con_rol("admin"))):
    return [modelos.usuario_api(f) for f in con.execute("SELECT * FROM usuarios ORDER BY activo DESC, rol, nombre")]


@app.post("/api/usuarios", status_code=201, tags=["usuarios"])
async def crear_usuario(datos: NuevoUsuario, u: dict = Depends(con_rol("admin"))):
    if datos.rol not in seguridad.ROLES:
        raise HTTPException(422, "Ese rol no existe.")
    try:
        cuenta = seguridad.normalizar_cuenta(datos.cuenta)
        seguridad.validar_clave(datos.clave, cuenta)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if con.execute("SELECT 1 FROM usuarios WHERE cuenta = ?", (cuenta,)).fetchone():
        raise HTTPException(409, "Ya existe una cuenta con ese correo o teléfono.")
    hash_clave = await run_in_threadpool(seguridad.crear_hash, datos.clave)
    con.execute("INSERT INTO usuarios (cuenta, nombre, rol, hash, creado) VALUES (?, ?, ?, ?, ?)",
                (cuenta, datos.nombre.strip(), datos.rol, hash_clave, ahora()))
    return modelos.usuario_api(con.execute("SELECT * FROM usuarios WHERE cuenta = ?", (cuenta,)).fetchone())


@app.patch("/api/usuarios/{usuario_id}", tags=["usuarios"])
async def editar_usuario(usuario_id: int, datos: EditarUsuario, u: dict = Depends(con_rol("admin"))):
    fila = con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not fila:
        raise HTTPException(404, "La cuenta no existe.")
    if datos.rol is not None and datos.rol not in seguridad.ROLES:
        raise HTTPException(422, "Ese rol no existe.")
    pierde_admin = fila["rol"] == "admin" and fila["activo"] and (datos.activo is False or (datos.rol is not None and datos.rol != "admin"))
    if pierde_admin:
        if usuario_id == u["id"]:
            raise HTTPException(409, "No puedes quitarte a ti mismo el acceso de administración.")
        if con.execute("SELECT COUNT(*) AS c FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id <> ?", (usuario_id,)).fetchone()["c"] == 0:
            raise HTTPException(409, "Debe quedar al menos una cuenta de administración activa.")
    cierra = False
    if datos.nombre is not None:
        con.execute("UPDATE usuarios SET nombre = ? WHERE id = ?", (datos.nombre.strip(), usuario_id))
    if datos.rol is not None and datos.rol != fila["rol"]:
        con.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (datos.rol, usuario_id))
        cierra = True
    if datos.activo is not None and bool(fila["activo"]) != datos.activo:
        con.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (int(datos.activo), usuario_id))
        cierra = cierra or not datos.activo
    if datos.clave is not None:
        try:
            seguridad.validar_clave(datos.clave, fila["cuenta"])
        except ValueError as e:
            raise HTTPException(422, str(e))
        con.execute("UPDATE usuarios SET hash = ? WHERE id = ?", (await run_in_threadpool(seguridad.crear_hash, datos.clave), usuario_id))
        cierra = True
    if cierra and usuario_id != u["id"]:
        seguridad.cerrar_sesiones_de(con, usuario_id)                   # el cambio aplica de inmediato
    return modelos.usuario_api(con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone())


# =========================================================
# DATOS DE LA CUENCA
# =========================================================
def _deps(u) -> list:
    return seguridad.ROLES[u["rol"]]["deps"] if u else []


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
    }


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
    filas = [dict(f) for f in con.execute("SELECT t, ph, cond, turb, color, temp, nivel, anom FROM lecturas WHERE nodo = ? AND t >= ? ORDER BY t",
                                          (nodo, ahora() - max(1, min(dias, 31)) * D))]
    texto = lotes.csv_abierto(filas)
    return PlainTextResponse(texto, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="vigia_{nodo}_{dias}d.csv"'})


class EditarBarrera(BaseModel):
    fill: Optional[float] = Field(None, ge=0, le=100)
    nivel: Optional[float] = Field(None, ge=0, le=20)
    vaciada: bool = False


@app.patch("/api/barreras/{barrera_id}", tags=["datos"])
async def editar_barrera(barrera_id: str, datos: EditarBarrera, u: dict = Depends(con_rol("pc", "limpia", "admin"))):
    """Lo que se registra en la visita a una barrera: llenado, nivel del agua o que ya se vació."""
    b = con.execute("SELECT * FROM barreras WHERE id = ?", (barrera_id,)).fetchone()
    if not b:
        raise HTTPException(404, "La barrera no existe.")
    llenado = 5 if datos.vaciada else (datos.fill if datos.fill is not None else b["llenado"])
    nivel = datos.nivel if datos.nivel is not None else b["nivel"]
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
async def guardar_umbrales(datos: Umbrales, u: dict = Depends(con_rol("admin"))):
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
                        foto: Optional[UploadFile] = File(None), u: Optional[dict] = Depends(actual)):
    """Reporte ciudadano (lo envía la app). Con sesión queda ligado a la cuenta para avisarle del avance;
    sin sesión o con `anonimo=true` no se guarda quién lo envió."""
    if cat not in motor.CATEGORIAS:
        raise HTTPException(422, "Categoría no válida. Usa: " + ", ".join(motor.CATEGORIAS) + ".")
    if not (AREA[0] <= lat <= AREA[1] and AREA[2] <= lng <= AREA[3]):
        raise HTTPException(422, "La ubicación está fuera del estado de Puebla.")
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
    ia = clasificar_foto(FOTOS / nombre_foto) if nombre_foto else None
    if not ia and ia_etiqueta in motor.CATEGORIAS and ia_confianza is not None and 0 <= ia_confianza <= 1:
        ia = (ia_etiqueta, ia_confianza)                                # clasificación hecha en el teléfono
    folio = f"R-{siguiente(con, 'reporte', 1300)}"
    con.execute("""INSERT INTO reportes (id, usuario_id, cat, ia_etiqueta, ia_confianza, lat, lng, t, estado, anonimo, voz, texto, foto)
                   VALUES (?,?,?,?,?,?,?,?,'Recibido',?,?,?,?)""",
                (folio, None if anonimo or not u else u["id"], cat, ia[0] if ia else None, ia[1] if ia else None, lat, lng, ahora(),
                 int(anonimo or not u), int(voz), texto.strip()[:500], nombre_foto))
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
async def editar_reporte(folio: str, datos: EstadoReporte, u: dict = Depends(con_rol("ambiental", "limpia", "pc", "admin"))):
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
        raise HTTPException(403, f"Solo {motor.DEPENDENCIAS[d['dep']]} puede actualizar este caso.")
    if d["estado"] == "Cerrado":
        raise HTTPException(409, "El caso ya está cerrado.")
    firma = quien(u) if u["rol"] != "admin" else f"{motor.DEPENDENCIAS[d['dep']]} (vía Administración)"
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
                      u: dict = Depends(con_rol(*seguridad.RECOLECCION))):
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
async def csv_de_ejemplo(nodo: str = "N3", evento: str = "normal", horas: int = 6, u: dict = Depends(con_rol(*seguridad.RECOLECCION))):
    """Archivo de ejemplo con el formato exacto de la microSD (valores simulados). Sirve para probar la carga
    y como referencia para el firmware. `evento`: normal | descarga | crecida."""
    f = con.execute("SELECT * FROM nodos WHERE id = ?", (nodo,)).fetchone()
    if not f or evento not in ("normal", "descarga", "crecida"):
        raise HTTPException(404, "Nodo o evento no válido.")
    t = ahora()
    filas = lotes.simular(json.loads(f["base"]), t - max(1, min(horas, 168)) * H, t, evento, f["bateria"] or 80, "M-0000")
    return PlainTextResponse(lotes.a_csv(nodo, filas), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nodo}_ejemplo_{evento}.csv"'})


@app.get("/api/lotes", tags=["recolección"])
async def listar_lotes(u: dict = Depends(con_rol(*seguridad.PERSONAL))):
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
async def demo_reporte(u: dict = Depends(con_rol("admin"))):
    """Simula un reporte de «agua de color» enviado desde la app cerca de Xoxtla."""
    solo_demo()
    ciudadana = con.execute("SELECT id FROM usuarios WHERE rol = 'ciudadano' AND demo = 1 LIMIT 1").fetchone()
    folio = f"R-{siguiente(con, 'reporte', 1300)}"
    con.execute("""INSERT INTO reportes (id, usuario_id, cat, ia_etiqueta, ia_confianza, lat, lng, t, estado, anonimo, voz, texto)
                   VALUES (?, ?, 'Agua de color', 'Agua de color', 0.93, 19.1835, -98.3050, ?, 'Recibido', 0, 0, ?)""",
                (folio, ciudadana["id"] if ciudadana else None, ahora(), "Reporte simulado: agua azul bajo el puente."))
    await despues_de_reporte(con.execute("SELECT * FROM reportes WHERE id = ?", (folio,)).fetchone())
    return {"reporte": folio}


@app.post("/api/demo/visita", tags=["demo"])
async def demo_visita(datos: DemoVisita, u: dict = Depends(con_rol("admin"))):
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
    filas = lotes.simular(json.loads(f["base"]), max(ultima + 10 * 60 * 1000, t - 5 * D), t, datos.evento, f["bateria"] or 80, folio)
    leido = lotes.leer_csv(lotes.a_csv(datos.nodo, filas).encode("utf-8"), datos.nodo, t)
    res = motor.ingerir(con, datos.nodo, leido["filas"], "Protección Civil", usuario_id=u["id"], archivo=f"{datos.nodo}_visita_simulada.csv",
                        integridad=leido["integridad"], invalidas=leido["invalidas"], checklist={"limpieza": True, "calibracion": False, "frascos": bool(folio)})
    await canal.emitir("lote")
    await avisar_casos(res["creados"], res["actualizados"])
    return _resumen_lote(res)


@app.post("/api/demo/barrera", tags=["demo"])
async def demo_barrera(datos: DemoBarrera, u: dict = Depends(con_rol("admin"))):
    solo_demo()
    if not con.execute("SELECT 1 FROM barreras WHERE id = ?", (datos.barrera,)).fetchone():
        raise HTTPException(404, "La barrera no existe.")
    con.execute("UPDATE barreras SET llenado = 94, ultima_descarga = ? WHERE id = ?", (ahora(), datos.barrera))
    caso = motor.caso_barrera_llena(con, con.execute("SELECT * FROM barreras WHERE id = ?", (datos.barrera,)).fetchone())
    await canal.emitir("barrera")
    await avisar_casos([caso] if caso else [])
    return {"caso": caso["id"] if caso else None}


@app.post("/api/demo/reiniciar", tags=["demo"])
async def demo_reiniciar(u: dict = Depends(con_rol("admin"))):
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
async def pagina_principal():
    return FileResponse(WEB / "index.html")


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
