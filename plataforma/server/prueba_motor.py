"""Prueba del motor de análisis sin servidor: tiempo de tránsito del agua entre nodos.

    python -m server.prueba_motor

Usa una base de datos temporal (nunca la real). Simula los archivos de la microSD de dos nodos con una
descarga a distintas horas y revisa que el motor los junte en un solo caso solo cuando al agua le da
tiempo de recorrer los km de cauce entre ellos.
"""
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="va_prueba_motor_")
os.environ["VA_DATOS"] = _TMP                         # antes de importar db: así nunca toca la base real

from . import db, lotes, motor, semilla  # noqa: E402

H = 3600 * 1000
ok = fallos = 0
try:
    sys.stdout.reconfigure(errors="replace")         # consolas de Windows sin UTF-8
except Exception:
    pass


def comprobar(nombre, condicion, detalle=""):
    global ok, fallos
    if condicion:
        ok += 1
        print("  ok   ", nombre)
    else:
        fallos += 1
        print("  FALLA", nombre, "->", detalle)


def subir(con, nodo, fin, evento="normal"):
    """Archivo de 8 h del nodo que termina en `fin`; si trae descarga, el evento queda 22 a 10 min antes del final."""
    base = next(n[7] for n in semilla.NODOS if n[0] == nodo)
    filas = lotes.simular(base, fin - 8 * H, fin, evento, 80, "", semilla=0.42)
    leido = lotes.leer_csv(lotes.a_csv(nodo, filas).encode("utf-8"), nodo, db.ahora())
    return motor.ingerir(con, nodo, leido["filas"], "Prueba", archivo=f"{nodo}.csv", integridad=leido["integridad"])


def limpiar(con):
    for tabla in ("lecturas", "lotes", "casos", "notificaciones", "reportes"):
        con.execute(f"DELETE FROM {tabla}")


def descargas(con):
    ids = [f["id"] for f in con.execute("SELECT id FROM casos WHERE tipo = 'descarga' ORDER BY t")]
    return [motor.leer_caso(con, i) for i in ids]


def main():
    con = db.conectar()
    semilla.catalogo(con)
    t = db.ahora() - 6 * H                            # todo en el pasado: el lector rechaza horas futuras

    print("Distancias por el cauce")
    dist = motor.km_por_rio(con)
    comprobar("del primer al último nodo hay entre 60 y 70 km de río", 60 <= dist["N6"] <= 70, round(dist["N6"], 1))
    n3_n4 = dist["N4"] - dist["N3"]
    rapido, lento = motor.ventana_transito(n3_n4)
    comprobar(f"N3 → N4 son {n3_n4:.1f} km: el agua tarda de ~2 h (crecida) a ~15 h (estiaje)",
              1.5 * H < rapido < 2.2 * H and 14 * H < lento < 16.5 * H, (rapido / H, lento / H))

    print("\nLa misma descarga baja de N3 a N4 cuatro horas después")
    limpiar(con)
    subir(con, "N3", t, "descarga")
    r4 = subir(con, "N4", t + 4 * H, "descarga")
    cs = descargas(con)
    comprobar("queda un solo caso", len(cs) == 1, [c["id"] for c in cs])
    comprobar("el caso sigue en N3 y marca que la anomalía llegó a N4",
              bool(cs) and cs[0]["nodo"] == "N3" and "N4" in cs[0]["confirmado_en"], cs and (cs[0]["nodo"], cs[0]["confirmado_en"]))
    comprobar("el lote de N4 actualiza ese caso en vez de abrir otro", not r4["creados"] and len(r4["actualizados"]) >= 1, r4["eventos"])

    print("\nAnomalía en N4 apenas 20 min después que en N3: no puede ser la misma agua (16 km)")
    limpiar(con)
    subir(con, "N3", t, "descarga")
    subir(con, "N4", t + 20 * 60 * 1000, "descarga")
    cs = descargas(con)
    comprobar("se abren dos casos", len(cs) == 2, [(c["id"], c["nodo"]) for c in cs])
    otro = next((c for c in cs if c["nodo"] == "N4"), None)
    comprobar("el de N4 se ubica entre N3 y N4 (T3), ya confirmado", bool(otro) and otro["tramo"] == "T3" and not otro["loc_pendiente"],
              otro and (otro["tramo"], otro["loc_pendiente"]))

    print("\nSe ve primero en N3 y después se descarga N2, que la tuvo una hora antes")
    limpiar(con)
    subir(con, "N3", t + 1 * H, "descarga")
    subir(con, "N2", t, "descarga")
    cs = descargas(con)
    comprobar("sigue siendo un solo caso", len(cs) == 1, [c["id"] for c in cs])
    comprobar("el origen sube a N2 (tramo T1, por confirmar hasta descargar N1)",
              bool(cs) and cs[0]["nodo"] == "N2" and cs[0]["tramo"] == "T1" and cs[0]["loc_pendiente"],
              cs and (cs[0]["nodo"], cs[0]["tramo"], cs[0]["loc_pendiente"]))

    con.close()
    print(f"\n{ok} comprobaciones correctas, {fallos} con falla.")
    return 1 if fallos else 0


if __name__ == "__main__":
    try:
        codigo = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(codigo)
