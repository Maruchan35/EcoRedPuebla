# Vigía Atoyac · Plataforma web

Plataforma central de Vigía Atoyac (HackaTec 2026, reto SECIHTI Puebla): inicio de sesión por rol,
indicadores de la cuenca, reportes de la app ciudadana, casos que se asignan solos a cada dependencia,
carga por lote de los nodos (que miden sin internet) y tablero de transparencia.

## Cómo iniciarla

**Windows:** doble clic en `iniciar.bat`. La primera vez crea el entorno e instala las dependencias
(necesita internet y Python 3.9 o más nuevo); después abre el navegador en la pantalla de inicio de sesión (`http://localhost:8000/login.html`; si el
puerto 8000 está ocupado por otro programa, usa el siguiente libre y lo dice en la ventana).

**A mano (cualquier sistema):**
```
python -m venv .venv
.venv\Scripts\activate            (en macOS/Linux: source .venv/bin/activate)
pip install -r server/requirements.txt
python -m server
```

**Plan B sin servidor:** doble clic en `index.html`. Funciona con datos simulados en el navegador y un
selector «Ver como» en lugar de cuentas. Nada se guarda. Úsenlo si el servidor falla en la presentación.

## Compartir con un enlace público (Cloudflare)
Con el servidor encendido, doble clic en `compartir.bat`. La primera vez descarga `cloudflared` (programa oficial
de Cloudflare) a `herramientas\` y comprueba su huella SHA-256; después abre un *Quick Tunnel* y muestra una
dirección `https://….trycloudflare.com`. No necesita cuenta de Cloudflare.

- El enlace funciona mientras esa ventana y la del servidor sigan abiertas y la laptop tenga internet.
  **Cada vez que se abre `compartir.bat` la dirección cambia.**
- Cualquiera que tenga el enlace ve la vista pública (resumen, mapa, transparencia) y puede intentar iniciar sesión.
  Los botones «Entrar como…» **no** aparecen por el enlace: para entrar con un rol hay que darles la cuenta y la
  contraseña de `server\datos\cuentas_demo.txt`. Compártanla solo con quien deba entrar.
- Por el enlace también se pueden mandar reportes a `/api/reportes`. Para borrar lo que se haya juntado:
  «Reiniciar demo».
- Para cortar el acceso, cierren la ventana de `compartir.bat`.

## Cuentas
Al primer arranque se crea una cuenta de demostración por rol, con una contraseña aleatoria que queda en
`server/datos/cuentas_demo.txt`:

| Cuenta | Rol | Qué ve |
|---|---|---|
| `admin@vigia.demo` | Administración | Todo, usuarios, umbrales y simulaciones |
| `ambiental@vigia.demo` | Autoridad ambiental | Casos de descarga con evidencia, nodos, reportes |
| `limpia@vigia.demo` | Limpia municipal | Barreras llenas, basura, reportes |
| `pc@vigia.demo` | Protección Civil | Recolección de nodos, inundación, nodos |
| `tec@vigia.demo` | Tecnológicos | Estado de nodos y recolección |
| `ciudadana@vigia.demo` | Ciudadanía | Vista pública (la usa la app) |

En la computadora del servidor, la pantalla de inicio de sesión muestra botones **«Entrar como…»**; desde
otro equipo o desde la app se entra con cuenta y contraseña. Sin sesión se ve la vista pública (resumen,
mapa y transparencia). El personal nuevo se da de alta en **Usuarios**.

## Guion de la demostración (4 minutos)
1. Entra como **Administración**. En *Resumen* pulsa **Reporte desde la app**: aparece al momento en el mapa
   (los reportes sí tienen internet). Con la app real: `POST /api/reportes`.
2. Pulsa **Visita a N3 (trae una descarga)**. Simula que Protección Civil descargó la microSD: el archivo pasa
   por el mismo camino que uno real. El análisis encuentra el evento con su hora real, lo cruza con los
   reportes, toma el folio de la muestra y abre un caso para Autoridad ambiental. El tramo queda «por confirmar».
3. Pulsa **Visita a N2 (confirma el tramo)**: al llegar los datos del nodo de aguas arriba, el caso confirma
   que la descarga entró entre Huejotzingo y Xoxtla.
4. Abre otra ventana como **Autoridad ambiental** (o cambia de cuenta): el aviso llegó solo. Abre el caso:
   lecturas del evento, evidencia, historial, laboratorio, PDF. Atiende y cierra: quien reportó recibe el aviso.
5. **Visita a N5 (trae una crecida)** abre un caso para Protección Civil; **Barrera llena**, uno para Limpia.
6. Con hardware real: entra como **Protección Civil** → *Recolección* → sube el CSV del nodo.
7. **Reiniciar demo** deja todo como al principio para volver a ensayar.

## Qué es real y qué es de demostración
- **Real:** sesión y permisos, base de datos, carga y validación de CSV, huella del archivo, detección de
  anomalías, localización por tramo, cruce con reportes, casos, avisos en vivo, alta de usuarios.
- **De demostración:** las lecturas, reportes y casos iniciales son inventados; el índice de *Predicción* es
  una serie de ejemplo; la «clasificación IA» de los reportes iniciales es fija. No hay modelo de visión
  conectado: un reporte nuevo queda «sin clasificar» salvo que la app mande su propia clasificación
  (el punto de conexión es `clasificar_foto` en `server/main.py`).
- **Pendiente:** notificaciones push (hoy la app las lee de `/api/notificaciones`), PDF generado en el
  servidor (hoy es la impresión del navegador), modelo predictivo con datos de Conagua.

## Estructura
| Archivo | Qué hace |
|---|---|
| `iniciar.bat` | Prepara el entorno e inicia el servidor en Windows |
| `compartir.bat` | Abre un enlace público temporal con Cloudflare (Quick Tunnel) |
| `index.html`, `login.html` | Plataforma y pantalla de inicio de sesión |
| `css/styles.css` | Sistema de diseño (ver `docs/design-system.md`) |
| `js/config.js` | Parámetros, dependencias, roles y menú |
| `js/api.js` | Capa de datos: servidor (sesión, API, WebSocket) o demo sin servidor |
| `js/app.js` | Sesión, rutas, menú por rol y avisos en vivo |
| `js/views.js` | Vistas: Resumen, Mapa, Casos, Nodos, Reportes, Recolección, Predicción, Transparencia, Usuarios, Configuración |
| `js/engine.js`, `js/map.js`, `js/charts.js`, `js/ui.js` | Semáforo y pronóstico, mapa Leaflet, gráficas Chart.js, utilidades |
| `js/data.js` | Datos de la demo sin servidor |
| `server/main.py` | API (FastAPI): sesión, usuarios, reportes, casos, recolección, métricas, WebSocket |
| `server/seguridad.py` | Contraseñas (PBKDF2), sesiones, roles, límite de intentos |
| `server/motor.py` | Análisis por lote: anomalías (z-score robusto), huella de descarga, localización, fusión, casos |
| `server/lotes.py` | Lectura y validación del CSV de la microSD, huella encadenada, generador de ejemplos |
| `server/db.py`, `server/modelos.py`, `server/semilla.py` | Esquema SQLite, formato de respuestas, datos iniciales |
| `server/prueba_rapida.py` | Prueba de punta a punta de la API (73 comprobaciones) |
| `docs/api.md`, `docs/formato-lote.md` | Referencia para la app móvil y para el firmware del nodo |
| `vendor/` | Leaflet, leaflet.heat, Chart.js, Lucide y fuentes (copias locales) |

## Pruebas
Con el servidor encendido, en otra terminal: `python -m server.prueba_rapida`. Recorre inicio de sesión,
permisos por rol, reporte con foto, carga de CSV con descarga, huella alterada, casos, usuarios y límite
de intentos, y al final deja la demo en su punto de partida. Sirve para la sección de pruebas del documento.

## Seguridad (lo que ya está y lo que falta para un despliegue real)
- Contraseñas con PBKDF2-SHA256 y sal; sesión en cookie HttpOnly + SameSite; el token solo se guarda como SHA-256.
- Cada ruta revisa el rol en el servidor: la web solo esconde menús, no decide permisos.
- El público nunca recibe texto de reportes, fotos ni quién reportó; la ubicación va redondeada a ~100 m.
- Cinco contraseñas fallidas bloquean un minuto. Fotos: solo JPG/PNG/WebP de hasta 5 MB.
- **Modo demo** (`VA_DEMO=1`, por defecto): crea cuentas de prueba y permite «Entrar como…» desde la misma
  computadora. Para cualquier servidor público: `VA_DEMO=0`, `VA_ADMIN_CUENTA`, `VA_ADMIN_CLAVE`, HTTPS y `VA_HTTPS=1`.
- **Para que entre la app desde el celular** hay que abrir el servidor a la red: `set VA_HOST=0.0.0.0` antes de
  `iniciar.bat`, y usar la IP de la laptop. Va por HTTP sin cifrar: háganlo en su propio hotspot, no en el WiFi
  del evento.

## Variables de entorno
`VA_HOST` (127.0.0.1) · `VA_PORT` (8000) · `VA_DEMO` (1) · `VA_DEMO_CLAVE` (contraseña fija para las cuentas demo)
· `VA_ADMIN_CUENTA`, `VA_ADMIN_CLAVE` · `VA_HTTPS` (0) · `VA_DATOS` (carpeta de la base; por defecto `server/datos`).

Si cambian el esquema de `server/db.py`, borren `server/datos/vigia.db` y vuelvan a iniciar.
