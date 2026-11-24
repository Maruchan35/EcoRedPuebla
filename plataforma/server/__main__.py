"""Arranque: `python -m server` desde la carpeta vigia-atoyac-web.

Si el puerto pedido (VA_PORT, 8000 por defecto) ya lo usa otro programa, toma el siguiente libre
y lo avisa. Con VA_ABRIR=1 abre el navegador en la pantalla de inicio de sesión.
"""
import os
import socket
import sys
import threading
import webbrowser

import uvicorn


def puerto_libre(host: str, inicio: int, intentos: int = 20) -> int:
    for puerto in range(inicio, inicio + intentos):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prueba:
            prueba.settimeout(0.3)
            if prueba.connect_ex(("127.0.0.1", puerto)) == 0:      # alguien ya responde ahí
                continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prueba:
            try:
                prueba.bind((host, puerto))
                return puerto
            except OSError:
                continue
    return inicio


if __name__ == "__main__":
    for flujo in (sys.stdout, sys.stderr):                       # consolas de Windows sin UTF-8
        try:
            flujo.reconfigure(errors="replace")
        except Exception:
            pass
    host, pedido = os.environ.get("VA_HOST", "127.0.0.1"), int(os.environ.get("VA_PORT", "8000"))
    puerto = puerto_libre(host, pedido)
    url = f"http://localhost:{puerto}/login.html"
    if puerto != pedido:
        print(f"[Vigía Atoyac] El puerto {pedido} ya lo usa otro programa: se usará el {puerto}.")
    print(f"[Vigía Atoyac] Plataforma en {url}   (Ctrl+C para detener)")
    try:                                                         # compartir.bat lee de aquí en qué puerto quedó el servidor
        from .db import DATOS
        DATOS.mkdir(parents=True, exist_ok=True)
        (DATOS / "puerto.txt").write_text(str(puerto), encoding="ascii")
    except OSError:
        pass
    if os.environ.get("VA_ABRIR") == "1":
        threading.Timer(2.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("server.main:app", host=host, port=puerto, log_level="info")
