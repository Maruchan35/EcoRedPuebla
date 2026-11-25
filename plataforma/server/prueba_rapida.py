"""Prueba de punta a punta de la API contra un servidor en marcha (solo biblioteca estándar).

    1) En una terminal:   python -m server
    2) En otra terminal:  python -m server.prueba_rapida

Usa las cuentas de demostración (lee cada cuenta y su contraseña de datos/cuentas_demo.txt) y al terminar
deja los datos de demostración en su punto de partida. No correr contra un servidor con datos reales.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar
from pathlib import Path

URL = os.environ.get("VA_URL", "http://127.0.0.1:8000")
DATOS = Path(os.environ.get("VA_DATOS") or Path(__file__).resolve().parent / "datos")
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082")
ok = fallos = 0
try:
    sys.stdout.reconfigure(errors="replace")         # consolas de Windows sin UTF-8
except Exception:
    pass


class Cliente:
    """Un navegador mínimo: guarda la cookie de sesión y manda la cabecera X-VA como la web."""

    def __init__(self, cabecera=True):
        self.jar = CookieJar()
        self.abre = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.cabecera, self.token = cabecera, None

    def pedir(self, metodo, ruta, json_=None, form=None, archivos=None, crudo=False, cabeceras=None):
        cab, cuerpo = dict(cabeceras or {}), None
        if self.cabecera:
            cab["X-VA"] = "1"
        if self.token:
            cab["Authorization"] = "Bearer " + self.token
        if json_ is not None:
            cuerpo, cab["Content-Type"] = json.dumps(json_).encode(), "application/json"
        elif form is not None or archivos:
            limite = uuid.uuid4().hex
            partes = []
            for k, v in (form or {}).items():
                partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            for k, (nombre, datos, tipo) in (archivos or {}).items():
                partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"; filename="{nombre}"\r\nContent-Type: {tipo}\r\n\r\n'.encode() + datos + b"\r\n")
            cuerpo, cab["Content-Type"] = b"".join(partes) + f"--{limite}--\r\n".encode(), f"multipart/form-data; boundary={limite}"
        try:
            r = self.abre.open(urllib.request.Request(URL + ruta, data=cuerpo, headers=cab, method=metodo), timeout=30)
            codigo, datos, cabeceras = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            codigo, datos, cabeceras = e.code, e.read(), e.headers
        if crudo:
            return codigo, datos, cabeceras
        try:
            return codigo, json.loads(datos or b"null")
        except ValueError:
            return codigo, datos.decode("utf-8", "replace")

    def entrar(self, cuenta, clave):
        return self.pedir("POST", "/api/auth/entrar", {"cuenta": cuenta, "clave": clave})


def comprobar(nombre, condicion, detalle=""):
    global ok, fallos
    if condicion:
        ok += 1
        print("  ok   ", nombre)
    else:
        fallos += 1
        print("  FALLA", nombre, "->", detalle)


def leer_cuentas() -> dict:
    """{rol: (cuenta, contraseña)} de datos/cuentas_demo.txt: una línea «rol cuenta contraseña nombre» por cuenta,
    o el formato anterior con una sola contraseña para todas («Contraseña: …» y líneas «cuenta rol»)."""
    texto = (DATOS / "cuentas_demo.txt").read_text(encoding="utf-8")
    roles, comun, cuentas = ("admin", "ciudadano"), re.search(r"^Contraseña: (\S+)", texto, re.M), {}
    for p in (linea.split() for linea in texto.splitlines()):
        if len(p) >= 3 and p[0] in roles and "@" in p[1]:
            cuentas.setdefault(p[0], (p[1], p[2]))
        elif len(p) == 2 and "@" in p[0] and p[1] in roles and comun:
            cuentas.setdefault(p[1], (p[0], comun.group(1)))
    return cuentas


def main():
    cuentas = leer_cuentas()
    admin = Cliente()
    c, _ = admin.entrar(*cuentas["admin"])
    comprobar("Administración inicia sesión", c == 200, c)
    comprobar("la demo se reinicia", admin.pedir("POST", "/api/demo/reiniciar", {})[0] == 200)

    print("\nPúblico (sin sesión)")
    pub = Cliente()
    c, e = pub.pedir("GET", "/api/estado")
    comprobar("el estado público responde", c == 200 and e["usuario"] is None, c)
    comprobar("los reportes públicos no llevan texto ni clasificación", all(r["text"] == "" and r["ai"] is None for r in e["reports"]))
    comprobar("los casos públicos no llevan resumen ni evidencia", all("summary" not in k and k["timeline"] == [] for k in e["cases"]))
    comprobar("el público solo recibe la última lectura de cada nodo", all(len(v) == 1 for v in e["history"].values()))
    comprobar("la lista de usuarios pide sesión", pub.pedir("GET", "/api/usuarios")[0] == 401)
    comprobar("la carga por lote pide sesión", pub.pedir("POST", "/api/sincronizacion", form={"nodo": "N3"}, archivos={"archivo": ("a.csv", b"t,ph\n", "text/csv")})[0] == 401)
    comprobar("la base de datos no se sirve como archivo", pub.pedir("GET", "/server/datos/vigia.db", crudo=True)[0] == 404)
    comprobar("los archivos de la web sí se sirven", pub.pedir("GET", "/js/api.js", crudo=True)[0] == 200)
    c, est = pub.pedir("GET", "/api/estacion")
    comprobar("estación piloto pública: trata agua y remueve turbidez", c == 200 and est["kpis"]["m3Dia"] > 0
              and est["kpis"]["remocion"]["turb"] > 0.6 and len(est["serie"]) > 24, est.get("kpis") if c == 200 else c)
    c, se = pub.pedir("GET", "/api/series?nodo=N5&dias=30&agrupar=dia")
    comprobar("serie diaria de 30 días de un nodo", c == 200 and 25 <= len(se["puntos"]) <= 31 and "turb" in se["puntos"][-1], len(se.get("puntos", [])) if c == 200 else c)
    comprobar("el índice diario cubre casi 90 días por tramo", all(len(v) >= 75 for v in e["dailyIndex"].values()) and len(e["dailyIndex"]) == 5,
              {k: len(v) for k, v in e["dailyIndex"].items()})
    comprobar("basura retirada sale de los vaciados registrados", e["basura"]["kg90"] > e["basura"]["kg30"] > 0, e.get("basura"))
    c, tr = pub.pedir("GET", "/api/tramos")
    comprobar("cada tramo trae sus km de cauce y cuánto tarda el agua en recorrerlo",
              c == 200 and len(tr) == 5 and all(x["km"] > 0 and 0 < x["transitH"][0] < x["transitH"][1] for x in tr)
              and 60 <= sum(x["km"] for x in tr) <= 70, [(x["id"], x["km"], x["transitH"]) for x in tr] if c == 200 else c)
    c, m = pub.pedir("GET", "/api/metricas")
    comprobar("métricas públicas", c == 200 and m["nodos"]["total"] == 6 and m["reportes"]["total"] >= 36, m if c == 200 else c)
    c, portada, _ = pub.pedir("GET", "/", crudo=True)
    comprobar("la portada sin sesión lleva directo a reportar", c == 200 and b'data-view="reportar"' in portada, c)
    c, panel, _ = admin.pedir("GET", "/", crudo=True)
    comprobar("con sesión de Administración la portada es la plataforma", c == 200 and b'id="nav"' in panel, c)
    c, mapa, cab = pub.pedir("GET", "/mapa", crudo=True)
    comprobar("el mapa 3D es público y la app lo puede mostrar dentro", c == 200 and b'id="mapa3d"' in mapa
              and cab.get("X-Frame-Options") == "SAMEORIGIN" and "frame-ancestors 'self'" in cab.get("Content-Security-Policy", ""), c)
    comprobar("las demás páginas no se dejan enmarcar", pub.pedir("GET", "/login.html", crudo=True)[2].get("X-Frame-Options") == "DENY")

    print("\nInicio de sesión y roles")
    comprobar("contraseña incorrecta se rechaza", pub.entrar(cuentas["ciudadano"][0], "no-es-la-clave")[0] == 401)
    comprobar("cuenta inexistente responde igual", pub.entrar("nadie@vigia.demo", "no-es-la-clave")[0] == 401)
    web = Cliente()
    c, _, cab = web.pedir("POST", "/api/auth/entrar", {"cuenta": cuentas["admin"][0], "clave": cuentas["admin"][1]}, crudo=True)
    galleta = cab.get("Set-Cookie", "")
    comprobar("Administración inicia sesión con cookie HttpOnly y SameSite", c == 200 and "HttpOnly" in galleta and "samesite=lax" in galleta.lower(), galleta[:40])
    comprobar("la respuesta web no expone el token", b"token" not in web.pedir("POST", "/api/auth/entrar", {"cuenta": cuentas["admin"][0], "clave": cuentas["admin"][1]}, crudo=True)[1])
    c, y = web.pedir("GET", "/api/auth/yo")
    comprobar("/api/auth/yo devuelve el rol", c == 200 and y["usuario"]["rol"] == "admin", y)
    comprobar("solo hay dos roles: Administración y ciudadanía", c == 200 and sorted(y["roles"]) == ["admin", "ciudadano"], y.get("roles"))
    sin_cabecera = Cliente(cabecera=False)
    sin_cabecera.entrar(*cuentas["admin"])
    comprobar("una petición con cookie pero sin la cabecera propia se rechaza (CSRF)", sin_cabecera.pedir("POST", "/api/auth/salir", {})[0] == 403)
    c, e = admin.pedir("GET", "/api/estado")
    comprobar("Administración ve completos todos los casos", c == 200 and e["cases"] and all("summary" in k for k in e["cases"]), c)
    comprobar("Administración recibe el historial de lecturas", c == 200 and all(len(v) == 48 for v in e["history"].values()))
    ciu = Cliente()
    comprobar("la cuenta ciudadana de la demo entra", ciu.entrar(*cuentas["ciudadano"])[0] == 200)
    comprobar("la ciudadanía no administra usuarios", ciu.pedir("GET", "/api/usuarios")[0] == 403)
    c, e = ciu.pedir("GET", "/api/estado")
    comprobar("la ciudadanía recibe los casos reducidos y solo la última lectura",
              c == 200 and all("summary" not in k for k in e["cases"]) and all(len(v) == 1 for v in e["history"].values()), c)
    comprobar("no puede cambiar umbrales", ciu.pedir("PUT", "/api/ajustes/umbrales", {"params": {}})[0] == 403)
    c, portada, _ = ciu.pedir("GET", "/", crudo=True)
    comprobar("con sesión ciudadana la portada también lleva a reportar", c == 200 and b'data-view="reportar"' in portada, c)

    print("\nApp ciudadana: registro, reporte con foto y seguimiento")
    app = Cliente(cabecera=False)
    cuenta = f"prueba{int(time.time())}@correo.test"
    c, r = app.pedir("POST", "/api/auth/registro", {"nombre": "Persona de prueba", "cuenta": cuenta, "clave": "clave-de-prueba-1", "origen": "app"})
    comprobar("registro desde la app devuelve token", c == 201 and r.get("token") and r["usuario"]["rol"] == "ciudadano", r)
    app.token = r.get("token")
    comprobar("contraseña corta se rechaza", pub.pedir("POST", "/api/auth/registro", {"nombre": "X Y", "cuenta": "otra@correo.test", "clave": "corta"})[0] == 422)
    comprobar("cuenta repetida se rechaza", pub.pedir("POST", "/api/auth/registro", {"nombre": "X Y", "cuenta": cuenta, "clave": "clave-de-prueba-1"})[0] == 409)
    # En la orilla del río, sobre el tramo Huejotzingo → Xoxtla (a ~1 km del nodo N3)
    c, rep = app.pedir("POST", "/api/reportes", form={"cat": "Agua de color", "lat": 19.18717, "lng": -98.30329, "texto": "Prueba: agua azul"},
                       archivos={"foto": ("foto.png", PNG, "image/png")})
    comprobar("reporte con foto desde la app", c == 201 and rep["photo"] and rep["mine"] and rep["status"] == "Recibido", rep)
    folio = rep["id"] if c == 201 else "R-0"
    comprobar("categoría inventada se rechaza", app.pedir("POST", "/api/reportes", form={"cat": "Otra", "lat": 19.18, "lng": -98.30})[0] == 422)
    comprobar("ubicación fuera de Puebla se rechaza", app.pedir("POST", "/api/reportes", form={"cat": "Basura", "lat": 40.4, "lng": -3.7})[0] == 422)
    comprobar("un archivo que no es imagen se rechaza", app.pedir("POST", "/api/reportes", form={"cat": "Basura", "lat": 19.05, "lng": -98.2},
                                                               archivos={"foto": ("x.png", b"<script>alert(1)</script>", "image/png")})[0] == 415)
    c, mios = app.pedir("GET", "/api/reportes?mios=true")
    comprobar("la persona ve sus reportes", c == 200 and [x["id"] for x in mios] == [folio], mios)
    comprobar("la dueña puede ver su foto", app.pedir("GET", f"/api/reportes/{folio}/foto", crudo=True)[0] == 200)
    comprobar("el público no puede ver la foto", pub.pedir("GET", f"/api/reportes/{folio}/foto", crudo=True)[0] == 401)
    c, r = pub.pedir("GET", f"/api/reportes/{folio}")
    comprobar("seguimiento público por folio, sin texto", c == 200 and r["text"] == "" and r["status"] == "Recibido", r)
    c, anon = pub.pedir("POST", "/api/reportes", form={"cat": "Mal olor", "lat": 19.03, "lng": -98.23, "texto": "anónimo"})
    comprobar("reporte anónimo sin sesión", c == 201 and anon["anonymous"] and not anon["mine"], anon)
    # El reporte marca el lugar del suceso: GPS con 20 m o menos de margen, o el punto marcado a mano en el mapa
    c, r = pub.pedir("POST", "/api/reportes", form={"cat": "Basura", "lat": 19.18717, "lng": -98.30329, "ubicacion": "gps", "precision_m": "35"})
    comprobar("un GPS con más de 20 m de margen se rechaza", c == 422, r)
    c, r = pub.pedir("POST", "/api/reportes", form={"cat": "Mal olor", "lat": 19.03, "lng": -98.23, "ubicacion": "gps", "precision_m": "18"})
    comprobar("un GPS de 18 m (calle con edificios) se acepta", c == 201, r)
    c, exacto = pub.pedir("POST", "/api/reportes", form={"cat": "Basura", "lat": 19.187213, "lng": -98.303377, "ubicacion": "gps", "precision_m": "3.6"})
    comprobar("un GPS de pocos metros se acepta", c == 201, exacto)
    if c == 201:
        c, vista = pub.pedir("GET", f"/api/reportes/{exacto['id']}")
        desvio = max(abs(vista["lat"] - 19.187213) * 111320, abs(vista["lng"] + 98.303377) * 105150) if c == 200 else 99
        comprobar("el público ve el lugar del suceso a 5 m o menos", desvio <= 5, vista)
        _, est = admin.pedir("GET", "/api/estado")
        r = next((x for x in est["reports"] if x["id"] == exacto["id"]), {})
        comprobar("el personal ve de dónde salió la ubicación y su margen", r.get("loc") == "gps" and r.get("precision") == 3.6, r)
    comprobar("la ciudadanía no cambia el estado de reportes", app.pedir("PATCH", f"/api/reportes/{folio}", {"estado": "Validado"})[0] == 403)

    print("\nRecolección: archivo de la microSD con una descarga")
    c, csv_txt, _ = admin.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N3&evento=descarga&horas=8", crudo=True)
    encabezado = csv_txt.split(b"\n", 1)[0] if c == 200 else b""
    comprobar("archivo de ejemplo con huella", c == 200 and encabezado.startswith(b"t,ph,cond,turb,color,temp,nivel,bateria,muestra,")
              and encabezado.endswith(b",hash"), encabezado[:120])
    comprobar("N3 trae además las columnas de la estación piloto", b",caudal,turb_sal,color_sal,cond_sal,ph_sal,lodos,dp_filtro,solar," in encabezado, encabezado)
    comprobar("la ciudadanía no puede subir lotes", app.pedir("POST", "/api/sincronizacion", form={"nodo": "N3"}, archivos={"archivo": ("n3.csv", csv_txt, "text/csv")})[0] == 403)
    comprobar("un archivo sin columnas válidas se rechaza", admin.pedir("POST", "/api/sincronizacion", form={"nodo": "N3"}, archivos={"archivo": ("x.csv", b"hola,mundo\n1,2\n", "text/csv")})[0] == 422)
    c, lote = admin.pedir("POST", "/api/sincronizacion", form={"nodo": "N3", "limpieza": "true", "calibracion": "true"}, archivos={"archivo": ("N3.csv", csv_txt, "text/csv")})
    comprobar("el lote se guarda y detecta un evento", c == 200 and lote["eventos"] == 1 and lote["nuevas"] == lote["filas"] and len(lote["casos"]) == 1, lote)
    comprobar("la huella del archivo se verifica", c == 200 and lote["integridad"] == "verificada", lote.get("integridad") if c == 200 else c)
    caso_id = lote["casos"][0] if c == 200 and lote["casos"] else "VA-0"
    c, otra = admin.pedir("POST", "/api/sincronizacion", form={"nodo": "N3"}, archivos={"archivo": ("N3.csv", csv_txt, "text/csv")})
    comprobar("subir dos veces el mismo archivo no duplica lecturas ni casos", c == 200 and otra["nuevas"] == 0 and otra["casos"] == [], otra)
    c, n1, _ = admin.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N1&evento=normal&horas=4", crudo=True)
    lineas = n1.decode().split("\n")
    celdas = lineas[5].split(",")
    celdas[2] = str(int(celdas[2]) + 300)                    # alguien "corrige" la conductividad de la fila 5
    lineas[5] = ",".join(celdas)
    c, mal = admin.pedir("POST", "/api/sincronizacion", form={"nodo": "N1"}, archivos={"archivo": ("alterado.csv", "\n".join(lineas).encode(), "text/csv")})
    comprobar("un archivo alterado se detecta por la huella, con la fila exacta", c == 200 and mal["integridad"] == "alterada:5", mal.get("integridad") if c == 200 else mal)
    c, cruzado = admin.pedir("POST", "/api/sincronizacion", form={"nodo": "N6"}, archivos={"archivo": ("N3.csv", csv_txt, "text/csv")})
    comprobar("el archivo de un nodo subido a otro nodo se rechaza", c == 422, cruzado)
    comprobar("la ciudadanía no puede actuar sobre un caso", app.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "atender"})[0] == 403)
    # Los datos llegan por lotes con huecos: un archivo corto no debe hacer que la estación "trate" menos agua al día
    c, est2 = pub.pedir("GET", "/api/estacion")
    k2 = est2.get("kpis") or {}
    comprobar("tras un lote corto, los indicadores diarios de la estación siguen siendo de un día completo",
              c == 200 and 8 <= (k2.get("m3Dia") or 0) <= 40 and (k2.get("energiaWhDia") or 0) > 300 and (k2.get("solidosKgDia") or 0) > 0.4,
              {k: k2.get(k) for k in ("m3Dia", "energiaWhDia", "solidosKgDia", "diaBase")})

    print("\nAdministración: caso con evidencia")
    c, caso = admin.pedir("GET", f"/api/casos/{caso_id}")
    comprobar("el caso es de tipo textil, con muestra y tramo T2 por confirmar",
              c == 200 and caso.get("estimate") == "Textil" and caso.get("sample") and caso["tramo"] == "T2" and caso["locPending"], caso)
    comprobar("el caso se cruzó con reportes cercanos, incluido el de la app",
              c == 200 and folio in caso["reports"] and "R-1240" in caso["reports"] and caso["confidence"] >= 0.9, caso.get("reports"))
    comprobar("el reporte pasó a Validado y su dueña fue notificada",
              app.pedir("GET", f"/api/reportes/{folio}")[1]["status"] == "Validado" and any(n["caso"] == caso_id for n in app.pedir("GET", "/api/notificaciones")[1]))
    c, n2, _ = admin.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N2&evento=normal&horas=8", crudo=True)
    c, lote2 = admin.pedir("POST", "/api/sincronizacion", form={"nodo": "N2"}, archivos={"archivo": ("N2.csv", n2, "text/csv")})
    c, caso = admin.pedir("GET", f"/api/casos/{caso_id}")
    comprobar("al descargar el nodo de aguas arriba el tramo queda confirmado",
              lote2.get("eventos") == 0 and caso_id in lote2.get("casos_actualizados", []) and not caso["locPending"] and caso["tramo"] == "T2", (lote2, caso.get("locPending")))
    comprobar("atender", admin.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "atender"})[1].get("status") == "En atención")
    comprobar("laboratorio vacío se rechaza", admin.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "lab", "lab": "  "})[0] == 422)
    comprobar("guardar laboratorio", admin.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "lab", "lab": "DQO 380 mg/L"})[1].get("lab") == "DQO 380 mg/L")
    c, cerrado = admin.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "cerrar"})
    comprobar("cerrar el caso avisa a quien reportó con cuenta", c == 200 and cerrado["status"] == "Cerrado" and cerrado["closedAt"] and cerrado["notified"] == 1, cerrado)
    comprobar("un caso cerrado ya no se modifica", admin.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "atender"})[0] == 409)
    comprobar("el reporte ligado queda Atendido", app.pedir("GET", f"/api/reportes/{folio}")[1]["status"] == "Atendido")

    print("\nCrecida y barrera")
    c, n5, _ = admin.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N5&evento=crecida&horas=3", crudo=True)
    c, lote5 = admin.pedir("POST", "/api/sincronizacion", form={"nodo": "N5"}, archivos={"archivo": ("N5.csv", n5, "text/csv")})
    c, e = admin.pedir("GET", "/api/estado")
    inund = [k for k in e["cases"] if k["id"] in lote5.get("casos", []) and k["type"] == "inundacion"]
    comprobar("nivel crítico abre un caso de inundación para Protección Civil", len(inund) == 1 and inund[0]["dep"] == "pc" and "summary" in inund[0], lote5)
    comprobar("la turbidez de la crecida no se confunde con una descarga", lote5.get("casos") == [inund[0]["id"]] and lote5.get("eventos") == 0 and lote5.get("turbidez_por_lluvia") == 1, lote5)
    c, b = admin.pedir("PATCH", "/api/barreras/B1", {"fill": 95})
    c, e = admin.pedir("GET", "/api/estado")
    comprobar("barrera llena abre un caso para Limpia municipal", any(k["barrier"] == "B1" and k["type"] == "basura" and k["status"] == "Nuevo" for k in e["cases"]))

    print("\nAdministración de usuarios")
    comprobar("un rol que se quitó ya no se puede asignar", admin.pedir("POST", "/api/usuarios", {"nombre": "Inspectora de prueba",
              "cuenta": f"insp{int(time.time())}@gob.test", "rol": "ambiental", "clave": "clave-temporal-1"})[0] == 422)
    c, nuevo = admin.pedir("POST", "/api/usuarios", {"nombre": "Administradora de prueba", "cuenta": f"adm{int(time.time())}@gob.test", "rol": "admin", "clave": "clave-temporal-1"})
    comprobar("alta de otra cuenta de Administración con contraseña temporal", c == 201 and nuevo["rol"] == "admin" and nuevo["cambiar_clave"] is True, nuevo)
    comprobar("la cuenta nueva trae todos los módulos", c == 201 and {"casos", "nodos", "usuarios", "config"} <= set(nuevo["permisos"]), nuevo.get("permisos"))
    c, todas = admin.pedir("GET", "/api/usuarios")
    comprobar("ya no quedan cuentas de los roles que se quitaron", c == 200 and all(u["rol"] in ("admin", "ciudadano") for u in todas),
              sorted({u["rol"] for u in todas}) if c == 200 else c)
    insp = Cliente()
    c, r = insp.entrar(nuevo["cuenta"], "clave-temporal-1")
    comprobar("la cuenta nueva puede entrar y se le pide cambiar la contraseña", c == 200 and r["usuario"]["cambiar_clave"] is True, r)
    c, _, cab = insp.pedir("GET", "/api/estado", crudo=True)
    comprobar("con contraseña temporal no ve datos hasta cambiarla", c == 403 and cab.get("X-VA-Accion") == "cambiar-clave", c)
    comprobar("pero sí puede preguntar quién es", insp.pedir("GET", "/api/auth/yo")[1]["usuario"]["cambiar_clave"] is True)
    comprobar("la nueva no puede ser igual a la temporal", insp.pedir("POST", "/api/auth/clave", {"actual": "clave-temporal-1", "nueva": "clave-temporal-1"})[0] == 422)
    comprobar("cambia su contraseña", insp.pedir("POST", "/api/auth/clave", {"actual": "clave-temporal-1", "nueva": "otra-clave-larga-2"})[0] == 200)
    comprobar("después del cambio ya entra a los datos", insp.pedir("GET", "/api/estado")[0] == 200)
    comprobar("la contraseña anterior deja de servir", Cliente().entrar(nuevo["cuenta"], "clave-temporal-1")[0] == 401)

    print("\nPermisos")
    c, cat = admin.pedir("GET", "/api/permisos")
    comprobar("catálogo de permisos para Administración", c == 200 and "casos" in cat["permisos"] and sorted(cat["roles"]) == ["admin", "ciudadano"], cat)
    comprobar("el catálogo no es para la ciudadanía", ciu.pedir("GET", "/api/permisos")[0] == 403)
    comprobar("los módulos de Administración no se recortan por persona",
              admin.pedir("PATCH", f"/api/usuarios/{nuevo['id']}", {"permisos": ["nodos"]})[0] == 422)
    c, log = admin.pedir("GET", "/api/accesos")
    comprobar("la bitácora registra entradas correctas y fallidas",
              c == 200 and any(a["cuenta"] == nuevo["cuenta"] and a["resultado"] == "ok" for a in log)
              and any(a["cuenta"] == nuevo["cuenta"] and a["resultado"] == "clave" for a in log), log[:3] if c == 200 else c)
    comprobar("la bitácora es solo de Administración", ciu.pedir("GET", "/api/accesos")[0] == 403)
    comprobar("ya no existe la entrada de un clic", pub.pedir("POST", "/api/auth/demo", {"cuenta": cuentas["admin"][0]})[0] in (404, 405))
    comprobar("/api/auth/yo ya no lista cuentas de demostración", "cuentas_demo" not in pub.pedir("GET", "/api/auth/yo")[1])
    print("\nDesactivar cuentas")
    comprobar("desactivar la cuenta", admin.pedir("PATCH", f"/api/usuarios/{nuevo['id']}", {"activo": False})[1].get("activo") is False)
    comprobar("una cuenta desactivada pierde la sesión al instante", insp.pedir("GET", "/api/auth/yo")[1]["usuario"] is None)
    comprobar("y ya no puede entrar", Cliente().entrar(nuevo["cuenta"], "otra-clave-larga-2")[0] == 401)
    yo = admin.pedir("GET", "/api/auth/yo")[1]["usuario"]
    comprobar("Administración no puede quitarse su propio acceso", admin.pedir("PATCH", f"/api/usuarios/{yo['id']}", {"rol": "ciudadano"})[0] == 409)
    comprobar("rol inventado se rechaza", admin.pedir("PATCH", f"/api/usuarios/{nuevo['id']}", {"rol": "superjefe"})[0] == 422)
    c, um = admin.pedir("PUT", "/api/ajustes/umbrales", {"params": {"turb": {"warn": 300, "crit": 200}}})
    comprobar("umbrales incoherentes se rechazan", c == 422, um)

    print("\nSimulaciones de la demo y cierre de sesión")
    comprobar("la demo se reinicia", admin.pedir("POST", "/api/demo/reiniciar", {})[0] == 200)
    c, r = admin.pedir("POST", "/api/demo/reporte", {})
    c, v = admin.pedir("POST", "/api/demo/visita", {"nodo": "N3", "evento": "descarga"})
    comprobar("visita simulada a N3 con descarga crea el caso", c == 200 and v["eventos"] == 1 and len(v["casos"]) == 1 and v["integridad"] == "verificada", v)
    c, v2 = admin.pedir("POST", "/api/demo/visita", {"nodo": "N2", "evento": "normal"})
    c, e = admin.pedir("GET", "/api/estado")
    nuevo_caso = next((k for k in e["cases"] if k["id"] == (v.get("casos") or [""])[0]), {})
    comprobar("visita simulada a N2 confirma el tramo", v2.get("casos_actualizados") == v.get("casos") and nuevo_caso.get("locPending") is False and nuevo_caso.get("tramo") == "T2", (v2, nuevo_caso.get("locPending")))
    c, um = admin.pedir("PUT", "/api/ajustes/umbrales", {"params": {"turb": {"warn": 40, "crit": 250}}})
    comprobar("los umbrales nuevos llegan a todos los paneles", c == 200 and pub.pedir("GET", "/api/estado")[1]["params"]["turb"]["warn"] == 40, um)
    admin.pedir("PUT", "/api/ajustes/umbrales", {"params": {}})
    comprobar("repetir la visita enseguida avisa que no hay datos nuevos", admin.pedir("POST", "/api/demo/visita", {"nodo": "N3", "evento": "descarga"})[0] == 409)
    comprobar("las simulaciones son solo de Administración", ciu.pedir("POST", "/api/demo/reporte", {})[0] == 403)
    comprobar("cerrar sesión", ciu.pedir("POST", "/api/auth/salir", {})[0] == 200 and ciu.pedir("GET", "/api/auth/yo")[1]["usuario"] is None)

    print("\nRiesgo del agua e informes")
    c, rg = pub.pedir("GET", "/api/riesgo")
    comprobar("el riesgo del agua es público y nunca dice que sea apta para bañarse",
              c == 200 and rg["apto"] is False and rg["tramos"] and all(not t["apto"] and t["razones"] for t in rg["tramos"]), c)
    c, pdf, _ = pub.pedir("GET", "/api/informes/informe.pdf", crudo=True)
    comprobar("informe del periodo en PDF, público", c == 200 and pdf[:5] == b"%PDF-", c)
    c, xlsx, _ = pub.pedir("GET", "/api/informes/estacion.xlsx", crudo=True)
    comprobar("resumen diario de la estación en Excel", c == 200 and xlsx[:2] == b"PK", c)
    comprobar("los casos en Excel piden sesión", pub.pedir("GET", "/api/informes/casos.xlsx", crudo=True)[0] == 401)
    c, csv_casos, _ = admin.pedir("GET", "/api/informes/casos.csv", crudo=True)
    comprobar("Administración descarga los casos en CSV", c == 200 and csv_casos.decode("utf-8-sig").startswith("Folio,"), c)

    print("\nRed de nodos")
    ciu.entrar(*cuentas["ciudadano"])                     # la cuenta de la app (.test) se fue al reiniciar la demo
    comprobar("la ciudadanía no administra la red", ciu.pedir("GET", "/api/red")[0] == 403)
    c, r0 = admin.pedir("GET", "/api/red")
    comprobar("Administración ve la red y sus tramos", c == 200 and len(r0["nodos"]) >= 2 and len(r0["tramos"]) == len(r0["nodos"]) - 1, c)
    medio = r0["tramos"][len(r0["tramos"]) // 2]["points"][len(r0["tramos"][len(r0["tramos"]) // 2]["points"]) // 2] if c == 200 else [19.1, -98.3]
    c, r1 = admin.pedir("POST", "/api/red/nodos", {"nombre": "Nodo de prueba · puente", "lat": medio[0] + 0.0004, "lng": medio[1], "tec": "TecNM Puebla"})
    nuevo = r1.get("resultado") if c == 201 else None
    comprobar("alta de un nodo sobre el río: su tramo se parte en dos",
              c == 201 and len(r1["tramos"]) == len(r0["tramos"]) + 1 and any(t["to"] == nuevo for t in r1["tramos"]), r1 if c != 201 else c)
    comprobar("un punto lejos del río se rechaza",
              admin.pedir("POST", "/api/red/nodos", {"nombre": "Lejos del río", "lat": 19.40, "lng": -98.05})[0] == 422)
    if nuevo:
        _, est = admin.pedir("GET", "/api/estado")
        comprobar("el nodo nuevo ya trae datos simulados", len(est["history"].get(nuevo, [])) > 0, list(est["history"]))
        c, r2 = admin.pedir("POST", f"/api/red/nodos/{nuevo}/baja", {})
        comprobar("al darlo de baja sus dos tramos vuelven a ser uno",
                  c == 200 and len(r2["tramos"]) == len(r0["tramos"]) and any(n["id"] == nuevo for n in r2["baja"]), c)
        comprobar("un nodo dado de baja se puede eliminar", admin.pedir("DELETE", f"/api/red/nodos/{nuevo}")[0] == 200)
    c, aj = admin.pedir("PUT", "/api/red/ajustes", {"radio_km": 3.0, "vel_min": 0.25, "vel_max": 2.2, "dias_sin_visita": 8})
    comprobar("los ajustes de la red se guardan", c == 200 and aj["ajustes"]["radio_km"] == 3.0, c)
    comprobar("velocidades al revés se rechazan",
              admin.pedir("PUT", "/api/red/ajustes", {"radio_km": 2.5, "vel_min": 2.0, "vel_max": 1.0, "dias_sin_visita": 7})[0] == 422)
    admin.pedir("PUT", "/api/red/ajustes", r0["ajustes"])                    # deja los ajustes como estaban

    print("\nTúnel de Cloudflare")
    # cloudflared se conecta desde la misma máquina: la dirección real del visitante llega en CF-Connecting-IP
    Cliente().pedir("POST", "/api/auth/entrar", {"cuenta": "tunel@vigia.demo", "clave": "no-es-la-clave"}, cabeceras={"CF-Connecting-IP": "203.0.113.9"})
    _, log = admin.pedir("GET", "/api/accesos?limite=10")
    comprobar("detrás del túnel se registra la dirección real del visitante",
              any(a["cuenta"] == "tunel@vigia.demo" and a["ip"] == "203.0.113.9" for a in log), log[:2])

    print("\nLímite de intentos")
    # Cuenta nueva en cada corrida: así repetir la prueba enseguida no hereda el bloqueo de la corrida anterior
    cuenta_b = f"bloqueo{int(time.time() * 1000)}@gob.test"
    admin.pedir("POST", "/api/usuarios", {"nombre": "Prueba de bloqueo", "cuenta": cuenta_b, "rol": "ciudadano", "clave": "clave-buena-123"})
    codigos = [Cliente().entrar(cuenta_b, "mala-%d" % i)[0] for i in range(6)]
    comprobar("al quinto fallo se bloquea un minuto", codigos[:5] == [401] * 5 and codigos[5] == 429, codigos)
    comprobar("durante el bloqueo ni la contraseña correcta entra", Cliente().entrar(cuenta_b, "clave-buena-123")[0] == 429)

    comprobar("la demo se reinicia", admin.pedir("POST", "/api/demo/reiniciar", {})[0] == 200)
    print(f"\n{ok} comprobaciones correctas, {fallos} con falla.")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
