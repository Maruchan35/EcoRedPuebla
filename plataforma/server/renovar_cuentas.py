"""Deja solo las cuentas de Administración y crea de nuevo la cuenta ciudadana de demostración, con contraseña nueva.

    Con el servidor apagado:   python -m server.renovar_cuentas

Antes de borrar guarda una copia de la base en server/datos/. Las cuentas nuevas y sus contraseñas quedan en
server/datos/cuentas_demo.txt (Administración conserva la suya). Al final vuelve a generar los datos de la demo
para que reportes, casos, avisos y bitácora queden a nombre de las cuentas nuevas.
"""
import sqlite3
import time

from . import semilla
from .db import DATOS, conectar


def main() -> None:
    con = conectar()
    respaldo = DATOS / f"vigia-respaldo-{time.strftime('%Y%m%d-%H%M%S')}.db"
    copia = sqlite3.connect(respaldo)
    con.backup(copia)
    copia.close()
    print(f"Copia de la base antes de borrar: {respaldo}")
    filas = semilla.renovar_cuentas(con)
    print(f"Quedan {len(filas)} cuentas: " + ", ".join(f"{rol} ({cuenta})" for rol, cuenta, _, _ in filas))
    print(f"Las contraseñas están en {semilla.ARCHIVO_CUENTAS}")
    print("Generando de nuevo los datos de la demo a nombre de las cuentas nuevas…")
    semilla.demostracion(con)
    con.close()
    print("Listo. Ya se puede encender el servidor.")


if __name__ == "__main__":
    main()
