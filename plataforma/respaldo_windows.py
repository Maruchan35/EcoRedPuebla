"""Vigía Atoyac · respaldo en una PC con Windows (por si Colab se cae).

Uso:   python respaldo_windows.py          (o doble clic sobre el archivo)

Solo necesita Python 3.9 o más nuevo (python.org, con «Add python.exe to PATH»). Lo demás lo hace solo:
  1. Baja lo último de GitHub: con git si está instalado; si no, el .zip de la rama main.
  2. Crea el entorno de Python e instala las dependencias.
  3. Enciende el servidor y espera a que responda.
  4. Descarga cloudflared (versión fija, comprobando su huella SHA-256 oficial) y abre el túnel de Cloudflare;
     si Cloudflare responde 429 (demasiados túneles rápidos) reintenta solo.
  5. Muestra la dirección pública y las cuentas con su contraseña.
Después se queda vigilando: si el servidor o el túnel se caen, los vuelve a levantar. Mientras corre, la PC no
se duerme. Ctrl+C apaga todo.

Opcional (variables de entorno, antes de correrlo):
  CF_TUNNEL_TOKEN   token de un túnel con nombre de Cloudflare (dirección fija que configuras en Cloudflare)
  VA_CARPETA        dónde se instala (por defecto %USERPROFILE%\\VigiaAtoyac)
  VA_RAMA           rama de GitHub (por defecto main)
  VA_PORT           puerto local (por defecto 8000; si está ocupado, el servidor toma el siguiente)
Opciones: --sin-tunel (solo en esta PC, sin dirección pública)  --sin-git (usar siempre el .zip)

La dirección es pública: compártela solo con el jurado y el equipo.
"""
import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "https://github.com/Maruchan35/EcoRedPuebla"
RAMA = os.environ.get("VA_RAMA", "main")
CARPETA = Path(os.environ.get("VA_CARPETA") or Path.home() / "VigiaAtoyac")
CODIGO = CARPETA / "EcoRedPuebla"
PLATAFORMA = CODIGO / "plataforma"
DATOS = PLATAFORMA / "server" / "datos"
REGISTROS = CARPETA / "registros"
PUERTO = int(os.environ.get("VA_PORT", "8000"))
CF_VERSION = "2026.10.7"
CF_HUELLA = "2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343"    # cloudflared-windows-amd64.exe oficial
CF = PLATAFORMA / "herramientas" / "cloudflared.exe"                                 # la misma carpeta que usa compartir.bat
TOKEN = os.environ.get("CF_TUNNEL_TOKEN", "").strip()
SIN_TUNEL, SIN_GIT = "--sin-tunel" in sys.argv, "--sin-git" in sys.argv
PRUEBA = os.environ.get("VA_RESPALDO_PRUEBA") == "1"         # solo para probar el script: se apaga al terminar de arrancar
URL_RAPIDA = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def paso(n, texto):
    print(f"\n[{n}/5] {texto}", flush=True)


def aviso(texto):
    print(f"      {texto}", flush=True)


def ejecutar(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        raise RuntimeError(f"Falló: {' '.join(map(str, cmd))}\n{(r.stderr or r.stdout)[-1500:]}")
    return r.stdout


def bajar(url, destino):
    peticion = urllib.request.Request(url, headers={"User-Agent": "vigia-atoyac-respaldo"})
    with urllib.request.urlopen(peticion, timeout=180) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)


def huella(ruta) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def responde(url) -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(url + "/api/metricas", headers={"User-Agent": "vigia-atoyac-respaldo"}), timeout=8)
        return True
    except Exception:
        return False


def no_dormir(activar: bool):
    """Mientras el respaldo corre, Windows no suspende la PC (se restablece al apagar)."""
    try:
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if activar else 0))
    except Exception:
        pass


# ---------- 1. Código ----------
def actualizar_codigo():
    CARPETA.mkdir(parents=True, exist_ok=True)
    git = None if SIN_GIT else shutil.which("git")
    if git and (CODIGO / ".git").is_dir():
        ejecutar([git, "-C", CODIGO, "fetch", "--depth", "1", "origin", RAMA])
        ejecutar([git, "-C", CODIGO, "reset", "--hard", f"origin/{RAMA}"])          # copia de despliegue: manda GitHub
        aviso(f"Actualizado con git a lo último de {RAMA}.")
    elif git and not CODIGO.exists():
        ejecutar([git, "clone", "--depth", "1", "--branch", RAMA, REPO + ".git", CODIGO])
        aviso(f"Descargado con git ({RAMA}).")
    else:
        # Sin git: el .zip de la rama, copiado encima. Se conservan la base de datos, el entorno y cloudflared.
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "codigo.zip"
            bajar(f"{REPO}/archive/refs/heads/{RAMA}.zip", archivo)
            with zipfile.ZipFile(archivo) as z:
                z.extractall(tmp)
            raiz = next(p for p in Path(tmp).iterdir() if p.is_dir())
            shutil.copytree(raiz, CODIGO, dirs_exist_ok=True)
        aviso(f"Descargado el .zip de {RAMA} (no se usó git).")


# ---------- 2. Entorno de Python ----------
def preparar_entorno() -> Path:
    venv = PLATAFORMA / ".venv"
    py = venv / "Scripts" / "python.exe"
    if not py.exists():
        ejecutar([sys.executable, "-m", "venv", venv])
        aviso("Entorno creado.")
    ejecutar([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", PLATAFORMA / "server" / "requirements.txt"])
    aviso("Dependencias listas.")
    return py


# ---------- 3. Servidor ----------
def encender_servidor(py: Path):
    REGISTROS.mkdir(parents=True, exist_ok=True)
    (DATOS / "puerto.txt").unlink(missing_ok=True)
    entorno = dict(os.environ, VA_HOST="127.0.0.1", VA_PORT=str(PUERTO), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    entorno.pop("VA_ABRIR", None)
    registro = open(REGISTROS / "servidor.log", "a", encoding="utf-8")
    proc = subprocess.Popen([str(py), "-m", "server"], cwd=PLATAFORMA, env=entorno, stdout=registro,
                            stderr=subprocess.STDOUT, creationflags=SIN_VENTANA)
    for _ in range(300):                                     # la primera vez genera 90 días de datos de demostración
        if proc.poll() is not None:
            raise RuntimeError(f"El servidor se detuvo al arrancar; revisa {REGISTROS / 'servidor.log'}")
        if (DATOS / "puerto.txt").exists():
            puerto = int((DATOS / "puerto.txt").read_text(encoding="ascii").strip() or PUERTO)   # toma otro si el pedido está ocupado
            if responde(f"http://127.0.0.1:{puerto}"):
                return proc, puerto
        time.sleep(1)
    proc.terminate()
    raise RuntimeError(f"El servidor no respondió en 5 minutos; revisa {REGISTROS / 'servidor.log'}")


# ---------- 4. Túnel de Cloudflare ----------
def preparar_cloudflared():
    CF.parent.mkdir(parents=True, exist_ok=True)
    if CF.exists() and huella(CF) == CF_HUELLA:
        return
    temporal = CF.with_suffix(".descarga")
    bajar(f"https://github.com/cloudflare/cloudflared/releases/download/{CF_VERSION}/cloudflared-windows-amd64.exe", temporal)
    if huella(temporal) != CF_HUELLA:
        temporal.unlink()
        raise RuntimeError("La huella de cloudflared no coincide con la oficial: no se usa ese archivo.")
    temporal.replace(CF)
    aviso(f"cloudflared {CF_VERSION} descargado y verificado.")


def abrir_tunel(puerto: int):
    """(proceso, dirección). Con CF_TUNNEL_TOKEN abre el túnel con nombre; si no, uno rápido y reintenta ante 429."""
    ruta = REGISTROS / "tunel.log"
    if TOKEN:
        proc = subprocess.Popen([str(CF), "tunnel", "--no-autoupdate", "run"], env=dict(os.environ, TUNNEL_TOKEN=TOKEN),
                                stdout=open(ruta, "w", encoding="utf-8"), stderr=subprocess.STDOUT, creationflags=SIN_VENTANA)
        time.sleep(10)
        if proc.poll() is not None:
            raise RuntimeError(f"El túnel con nombre no arrancó; revisa el token y {ruta}")
        return proc, None
    espera = 30
    while True:
        proc = subprocess.Popen([str(CF), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{puerto}"],
                                stdout=open(ruta, "w", encoding="utf-8"), stderr=subprocess.STDOUT, creationflags=SIN_VENTANA)
        texto, hallado = "", None
        for _ in range(60):
            texto = ruta.read_text(encoding="utf-8", errors="replace")
            hallado = URL_RAPIDA.search(texto)
            if hallado or proc.poll() is not None:
                break
            time.sleep(1)
        if hallado:
            url = hallado.group(0)
            for _ in range(30):                              # una dirección nueva tarda unos segundos en responder
                if responde(url):
                    break
                time.sleep(2)
            else:
                aviso("La dirección todavía no responde desde aquí; espera un minuto antes de abrirla.")
            return proc, url
        proc.terminate()
        if "429" not in texto:
            raise RuntimeError(f"cloudflared no entregó la dirección; revisa {ruta}")
        aviso(f"Cloudflare limita los túneles rápidos en este momento (429). Reintento en {espera} s…")
        time.sleep(espera)
        espera = min(espera + 30, 180)


# ---------- 5. Resumen ----------
def mostrar(url, puerto):
    print("\n" + "=" * 72)
    print(" Vigía Atoyac está en línea")
    if url:
        print(f"   Plataforma (inicio de sesión): {url}/login.html")
        print(f"   Vista pública:                 {url}/")
        print(f"   App ciudadana:                 {url}/app/")
    elif TOKEN:
        print("   En la dirección fija que configuraste en tu túnel con nombre de Cloudflare.")
        print(f"   (En Cloudflare, el túnel tiene que apuntar a http://localhost:{puerto})")
        if puerto != PUERTO:
            print(f"   [!] El puerto {PUERTO} está ocupado (¿otro servidor encendido?) y este quedó en el {puerto}:")
            print(f"       cierra lo que usa el {PUERTO} y vuelve a correr esto, o cambia el puerto del túnel en Cloudflare.")
    print(f"   En esta PC:                    http://localhost:{puerto}/login.html")
    cuentas = DATOS / "cuentas_demo.txt"
    if cuentas.exists():
        print("\n" + cuentas.read_text(encoding="utf-8").strip())
    print("\n Deja esta ventana abierta. Ctrl+C apaga el servidor y el túnel.")
    print("=" * 72, flush=True)


def apagar(*procesos):
    for p in procesos:
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
    no_dormir(False)


def principal():
    if os.name != "nt":
        sys.exit("Este respaldo es para Windows. En Linux usa el cuaderno de Colab o iniciar el servidor con python -m server.")
    if sys.version_info < (3, 9):
        sys.exit("Necesitas Python 3.9 o más nuevo (python.org).")
    print(f"Vigía Atoyac · respaldo en Windows\n  Carpeta: {CARPETA}\n  Rama:    {RAMA}")
    servidor = tunel = None
    try:
        paso(1, "Código desde GitHub")
        actualizar_codigo()
        paso(2, "Entorno de Python y dependencias (la primera vez tarda un par de minutos)")
        py = preparar_entorno()
        paso(3, "Servidor (la primera vez genera 90 días de datos de demostración)")
        servidor, puerto = encender_servidor(py)
        aviso(f"Servidor listo en http://localhost:{puerto}")
        url = None
        if SIN_TUNEL:
            paso(4, "Túnel de Cloudflare: omitido (--sin-tunel)")
        else:
            paso(4, "Túnel de Cloudflare")
            preparar_cloudflared()
            tunel, url = abrir_tunel(puerto)
        paso(5, "Listo")
        no_dormir(True)
        mostrar(url, puerto)
        if PRUEBA:
            apagar(tunel, servidor)
            return
        # Vigilancia: si algo se cae, se vuelve a levantar
        fallos = 0
        while True:
            time.sleep(10)
            caido = servidor.poll() is not None                 # el proceso terminó: se reinicia de inmediato
            fallos = 0 if not caido and responde(f"http://127.0.0.1:{puerto}") else fallos + 1
            if caido or fallos >= 3:                             # vivo pero sin responder 30 s: también
                print("\n[!] El servidor dejó de responder: lo vuelvo a encender…", flush=True)
                apagar(servidor)
                no_dormir(True)
                servidor, nuevo = encender_servidor(py)
                fallos = 0
                if tunel and nuevo != puerto:                   # quedó en otro puerto: el túnel tiene que apuntar ahí
                    apagar(tunel)
                    no_dormir(True)
                    tunel, url = abrir_tunel(nuevo)
                    mostrar(url, nuevo)
                puerto = nuevo
            if tunel and tunel.poll() is not None:
                print("\n[!] El túnel se cayó: lo vuelvo a abrir (la dirección rápida cambia)…", flush=True)
                tunel, url = abrir_tunel(puerto)
                mostrar(url, puerto)
    except KeyboardInterrupt:
        print("\nApagando…", flush=True)
        apagar(tunel, servidor)
        print("Listo: servidor y túnel apagados.")
    except Exception as e:
        apagar(tunel, servidor)
        print(f"\n[x] {e}", flush=True)
        if sys.stdin and sys.stdin.isatty():
            input("\nPresiona Enter para cerrar…")
        sys.exit(1)


if __name__ == "__main__":
    principal()
