"""Prueba de punta a punta de la API contra un servidor en marcha (solo biblioteca estándar).

    1) En una terminal:   python -m server
    2) En otra terminal:  python -m server.prueba_rapida

Usa las cuentas de demostración (lee la contraseña de datos/cuentas_demo.txt) y al terminar
deja los datos de demostración en su punto de partida. No correr contra un servidor con datos reales.
"""
import json
import os
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

    def pedir(self, metodo, ruta, json_=None, form=None, archivos=None, crudo=False):
        cab, cuerpo = {}, None
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


def main():
    clave = (DATOS / "cuentas_demo.txt").read_text(encoding="utf-8").split("Contraseña: ")[1].split()[0]
    admin = Cliente()
    c, _ = admin.entrar("admin@vigia.demo", clave)
    comprobar("Administración inicia sesión", c == 200, c)
    admin.pedir("POST", "/api/demo/reiniciar", {})

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
    c, m = pub.pedir("GET", "/api/metricas")
    comprobar("métricas públicas", c == 200 and m["nodos"]["total"] == 6 and m["reportes"]["total"] >= 36, m if c == 200 else c)

    print("\nInicio de sesión y permisos")
    comprobar("contraseña incorrecta se rechaza", pub.entrar("pc@vigia.demo", "no-es-la-clave")[0] == 401)
    comprobar("cuenta inexistente responde igual", pub.entrar("nadie@vigia.demo", "no-es-la-clave")[0] == 401)
    pc = Cliente()
    c, _, cab = pc.pedir("POST", "/api/auth/entrar", {"cuenta": "pc@vigia.demo", "clave": clave}, crudo=True)
    galleta = cab.get("Set-Cookie", "")
    comprobar("Protección Civil inicia sesión con cookie HttpOnly y SameSite", c == 200 and "HttpOnly" in galleta and "samesite=lax" in galleta.lower(), galleta[:40])
    comprobar("la respuesta web no expone el token", b"token" not in pc.pedir("POST", "/api/auth/entrar", {"cuenta": "pc@vigia.demo", "clave": clave}, crudo=True)[1])
    c, y = pc.pedir("GET", "/api/auth/yo")
    comprobar("/api/auth/yo devuelve el rol", c == 200 and y["usuario"]["rol"] == "pc", y)
    sin_cabecera = Cliente(cabecera=False)
    sin_cabecera.entrar("pc@vigia.demo", clave)
    comprobar("una petición con cookie pero sin la cabecera propia se rechaza (CSRF)", sin_cabecera.pedir("POST", "/api/auth/salir", {})[0] == 403)
    comprobar("Protección Civil no administra usuarios", pc.pedir("GET", "/api/usuarios")[0] == 403)
    c, e = pc.pedir("GET", "/api/estado")
    comprobar("ve completos sus casos y reducidos los de otra dependencia",
              all(("summary" in k) == (k["dep"] == "pc") for k in e["cases"]), [(k["id"], k["dep"], "summary" in k) for k in e["cases"]])
    comprobar("el personal recibe el historial de lecturas", all(len(v) == 48 for v in e["history"].values()))
    comprobar("no puede cambiar umbrales", pc.pedir("PUT", "/api/ajustes/umbrales", {"params": {}})[0] == 403)

    print("\nApp ciudadana: registro, reporte con foto y seguimiento")
    app = Cliente(cabecera=False)
    cuenta = f"prueba{int(time.time())}@correo.test"
    c, r = app.pedir("POST", "/api/auth/registro", {"nombre": "Persona de prueba", "cuenta": cuenta, "clave": "clave-de-prueba-1", "origen": "app"})
    comprobar("registro desde la app devuelve token", c == 201 and r.get("token") and r["usuario"]["rol"] == "ciudadano", r)
    app.token = r.get("token")
    comprobar("contraseña corta se rechaza", pub.pedir("POST", "/api/auth/registro", {"nombre": "X Y", "cuenta": "otra@correo.test", "clave": "corta"})[0] == 422)
    comprobar("cuenta repetida se rechaza", pub.pedir("POST", "/api/auth/registro", {"nombre": "X Y", "cuenta": cuenta, "clave": "clave-de-prueba-1"})[0] == 409)
    c, rep = app.pedir("POST", "/api/reportes", form={"cat": "Agua de color", "lat": 19.1840, "lng": -98.3060, "texto": "Prueba: agua azul"},
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
    comprobar("la ciudadanía no cambia el estado de reportes", app.pedir("PATCH", f"/api/reportes/{folio}", {"estado": "Validado"})[0] == 403)

    print("\nRecolección: archivo de la microSD con una descarga")
    c, csv_txt, _ = pc.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N3&evento=descarga&horas=8", crudo=True)
    comprobar("archivo de ejemplo con huella", c == 200 and csv_txt.startswith(b"t,ph,cond,turb,color,temp,nivel,bateria,muestra,hash"), c)
    comprobar("la ciudadanía no puede subir lotes", app.pedir("POST", "/api/sincronizacion", form={"nodo": "N3"}, archivos={"archivo": ("n3.csv", csv_txt, "text/csv")})[0] == 403)
    comprobar("un archivo sin columnas válidas se rechaza", pc.pedir("POST", "/api/sincronizacion", form={"nodo": "N3"}, archivos={"archivo": ("x.csv", b"hola,mundo\n1,2\n", "text/csv")})[0] == 422)
    c, lote = pc.pedir("POST", "/api/sincronizacion", form={"nodo": "N3", "limpieza": "true", "calibracion": "true"}, archivos={"archivo": ("N3.csv", csv_txt, "text/csv")})
    comprobar("el lote se guarda y detecta un evento", c == 200 and lote["eventos"] == 1 and lote["nuevas"] == lote["filas"] and len(lote["casos"]) == 1, lote)
    comprobar("la huella del archivo se verifica", c == 200 and lote["integridad"] == "verificada", lote.get("integridad") if c == 200 else c)
    caso_id = lote["casos"][0] if c == 200 and lote["casos"] else "VA-0"
    c, otra = pc.pedir("POST", "/api/sincronizacion", form={"nodo": "N3"}, archivos={"archivo": ("N3.csv", csv_txt, "text/csv")})
    comprobar("subir dos veces el mismo archivo no duplica lecturas ni casos", c == 200 and otra["nuevas"] == 0 and otra["casos"] == [], otra)
    c, n1, _ = pc.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N1&evento=normal&horas=4", crudo=True)
    lineas = n1.decode().split("\n")
    celdas = lineas[5].split(",")
    celdas[2] = str(int(celdas[2]) + 300)                    # alguien "corrige" la conductividad de la fila 5
    lineas[5] = ",".join(celdas)
    c, mal = pc.pedir("POST", "/api/sincronizacion", form={"nodo": "N1"}, archivos={"archivo": ("alterado.csv", "\n".join(lineas).encode(), "text/csv")})
    comprobar("un archivo alterado se detecta por la huella, con la fila exacta", c == 200 and mal["integridad"] == "alterada:5", mal.get("integridad") if c == 200 else mal)
    c, cruzado = pc.pedir("POST", "/api/sincronizacion", form={"nodo": "N6"}, archivos={"archivo": ("N3.csv", csv_txt, "text/csv")})
    comprobar("el archivo de un nodo subido a otro nodo se rechaza", c == 422, cruzado)
    comprobar("Protección Civil no puede actuar sobre un caso de Autoridad ambiental", pc.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "atender"})[0] == 403)

    print("\nAutoridad ambiental: caso con evidencia")
    amb = Cliente()
    amb.entrar("ambiental@vigia.demo", clave)
    c, caso = amb.pedir("GET", f"/api/casos/{caso_id}")
    comprobar("el caso es de tipo textil, con muestra y tramo T2 por confirmar",
              c == 200 and caso.get("estimate") == "Textil" and caso.get("sample") and caso["tramo"] == "T2" and caso["locPending"], caso)
    comprobar("el caso se cruzó con reportes cercanos, incluido el de la app",
              c == 200 and folio in caso["reports"] and "R-1240" in caso["reports"] and caso["confidence"] >= 0.9, caso.get("reports"))
    comprobar("el reporte pasó a Validado y su dueña fue notificada",
              app.pedir("GET", f"/api/reportes/{folio}")[1]["status"] == "Validado" and any(n["caso"] == caso_id for n in app.pedir("GET", "/api/notificaciones")[1]))
    c, n2, _ = pc.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N2&evento=normal&horas=8", crudo=True)
    c, lote2 = pc.pedir("POST", "/api/sincronizacion", form={"nodo": "N2"}, archivos={"archivo": ("N2.csv", n2, "text/csv")})
    c, caso = amb.pedir("GET", f"/api/casos/{caso_id}")
    comprobar("al descargar el nodo de aguas arriba el tramo queda confirmado",
              lote2.get("eventos") == 0 and caso_id in lote2.get("casos_actualizados", []) and not caso["locPending"] and caso["tramo"] == "T2", (lote2, caso.get("locPending")))
    comprobar("atender", amb.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "atender"})[1].get("status") == "En atención")
    comprobar("laboratorio vacío se rechaza", amb.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "lab", "lab": "  "})[0] == 422)
    comprobar("guardar laboratorio", amb.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "lab", "lab": "DQO 380 mg/L"})[1].get("lab") == "DQO 380 mg/L")
    c, cerrado = amb.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "cerrar"})
    comprobar("cerrar el caso avisa a quien reportó con cuenta", c == 200 and cerrado["status"] == "Cerrado" and cerrado["closedAt"] and cerrado["notified"] == 1, cerrado)
    comprobar("un caso cerrado ya no se modifica", amb.pedir("PATCH", f"/api/casos/{caso_id}", {"accion": "atender"})[0] == 409)
    comprobar("el reporte ligado queda Atendido", app.pedir("GET", f"/api/reportes/{folio}")[1]["status"] == "Atendido")

    print("\nCrecida y barrera")
    c, n5, _ = pc.pedir("GET", "/api/sincronizacion/ejemplo?nodo=N5&evento=crecida&horas=3", crudo=True)
    c, lote5 = pc.pedir("POST", "/api/sincronizacion", form={"nodo": "N5"}, archivos={"archivo": ("N5.csv", n5, "text/csv")})
    c, e = pc.pedir("GET", "/api/estado")
    inund = [k for k in e["cases"] if k["id"] in lote5.get("casos", []) and k["type"] == "inundacion"]
    comprobar("nivel crítico abre un caso de inundación para Protección Civil", len(inund) == 1 and inund[0]["dep"] == "pc" and "summary" in inund[0], lote5)
    comprobar("la turbidez de la crecida no se confunde con una descarga", lote5.get("casos") == [inund[0]["id"]] and lote5.get("eventos") == 0 and lote5.get("turbidez_por_lluvia") == 1, lote5)
    c, b = pc.pedir("PATCH", "/api/barreras/B1", {"fill": 95})
    c, e = admin.pedir("GET", "/api/estado")
    comprobar("barrera llena abre un caso para Limpia municipal", any(k["barrier"] == "B1" and k["type"] == "basura" and k["status"] == "Nuevo" for k in e["cases"]))

    print("\nAdministración de usuarios")
    c, nuevo = admin.pedir("POST", "/api/usuarios", {"nombre": "Inspectora de prueba", "cuenta": f"insp{int(time.time())}@gob.test", "rol": "ambiental", "clave": "clave-temporal-1"})
    comprobar("alta de personal", c == 201 and nuevo["rol"] == "ambiental", nuevo)
    insp = Cliente()
    comprobar("la cuenta nueva puede entrar", insp.entrar(nuevo["cuenta"], "clave-temporal-1")[0] == 200)
    comprobar("cambia su contraseña", insp.pedir("POST", "/api/auth/clave", {"actual": "clave-temporal-1", "nueva": "otra-clave-larga-2"})[0] == 200)
    comprobar("la contraseña anterior deja de servir", Cliente().entrar(nuevo["cuenta"], "clave-temporal-1")[0] == 401)
    comprobar("desactivar la cuenta", admin.pedir("PATCH", f"/api/usuarios/{nuevo['id']}", {"activo": False})[1].get("activo") is False)
    comprobar("una cuenta desactivada pierde la sesión al instante", insp.pedir("GET", "/api/auth/yo")[1]["usuario"] is None)
    comprobar("y ya no puede entrar", Cliente().entrar(nuevo["cuenta"], "otra-clave-larga-2")[0] == 401)
    yo = admin.pedir("GET", "/api/auth/yo")[1]["usuario"]
    comprobar("Administración no puede quitarse su propio acceso", admin.pedir("PATCH", f"/api/usuarios/{yo['id']}", {"rol": "pc"})[0] == 409)
    comprobar("rol inventado se rechaza", admin.pedir("PATCH", f"/api/usuarios/{nuevo['id']}", {"rol": "superjefe"})[0] == 422)
    c, um = admin.pedir("PUT", "/api/ajustes/umbrales", {"params": {"turb": {"warn": 300, "crit": 200}}})
    comprobar("umbrales incoherentes se rechazan", c == 422, um)

    print("\nSimulaciones de la demo y cierre de sesión")
    admin.pedir("POST", "/api/demo/reiniciar", {})
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
    comprobar("las simulaciones son solo de Administración", pc.pedir("POST", "/api/demo/reporte", {})[0] == 403)
    comprobar("cerrar sesión", pc.pedir("POST", "/api/auth/salir", {})[0] == 200 and pc.pedir("GET", "/api/auth/yo")[1]["usuario"] is None)

    print("\nLímite de intentos")
    codigos = [Cliente().entrar("limpia@vigia.demo", "mala-%d" % i)[0] for i in range(6)]
    comprobar("al quinto fallo se bloquea un minuto", codigos[:5] == [401] * 5 and codigos[5] == 429, codigos)
    comprobar("durante el bloqueo ni la contraseña correcta entra", Cliente().entrar("limpia@vigia.demo", clave)[0] == 429)

    admin.pedir("POST", "/api/demo/reiniciar", {})
    print(f"\n{ok} comprobaciones correctas, {fallos} con falla.")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
