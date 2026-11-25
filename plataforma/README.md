# Vigía Atoyac · Plataforma web

Plataforma central de Vigía Atoyac (HackaTec 2026, reto SECIHTI Puebla): inicio de sesión por rol,
centro de monitoreo de la cuenca, reportes de la app ciudadana, casos que se asignan solos a cada dependencia,
carga por lote de los nodos (que miden sin internet), estación piloto de tratamiento junto al río, pronóstico
de la calidad por tramo y tablero de transparencia.

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
  Para entrar con una cuenta hay que darle a esa persona su correo y contraseña (las de demostración están en
  `server\datos\cuentas_demo.txt`). Compártanlas solo con quien deba entrar.
- Por el enlace también se pueden mandar reportes a `/api/reportes`. Para borrar lo que se haya juntado:
  «Reiniciar demo».
- Para cortar el acceso, cierren la ventana de `compartir.bat`.

## Demostración en Colab (sin la laptop encendida)
[![Abrir en Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Maruchan35/EcoRedPuebla/blob/main/plataforma/demo_colab.ipynb)

`demo_colab.ipynb` clona este repositorio en una máquina de Google Colab, enciende el servidor y lo publica con un
túnel de Cloudflare (descarga `cloudflared` 2026.10.7 y comprueba su huella SHA-256, igual que `compartir.bat`).
Ábranlo con el botón, usen **Entorno de ejecución → Ejecutar todo** y en unos dos minutos aparecen la dirección
`https://….trycloudflare.com` y las cuentas, cada una con su contraseña.

- La pestaña de Colab tiene que seguir abierta: en la versión gratuita la sesión se corta por inactividad o a las
  12 h. Cada ejecución en una máquina nueva cambia la dirección, las contraseñas y los datos de la demo.
- **Dirección fija:** creen un túnel con nombre en Cloudflare Zero Trust que apunte a `http://localhost:8000` y
  guarden su token en los Secretos de Colab como `CF_TUNNEL_TOKEN`; el cuaderno lo usa si existe.
- El cuaderno clona la rama `main` (variable `RAMA` de la primera celda); para probar otra rama, cámbienla ahí.
- Colab está pensado para cómputo interactivo, no para hospedar sitios, y puede cortar la sesión: úsenlo para la
  presentación y tengan la laptop con `iniciar.bat` + `compartir.bat` como plan B.

## Cuentas, inicio de sesión y permisos
Se entra siempre con **correo (o teléfono) y contraseña**, también en la computadora del servidor. Al primer
arranque se crea una cuenta de demostración por rol, **cada una con su propia contraseña** aleatoria; quedan
anotadas en `server/datos/cuentas_demo.txt` y se muestran en la ventana del servidor:

| Cuenta | Persona | Rol | Módulos que trae su rol |
|---|---|---|---|
| `admin@vigia.demo` | Mtra. Daniela Ortega Ruiz | Administración | Todo: casos de todas las dependencias, usuarios, configuración y simulaciones |
| `mariana.cuautle@vigia.demo` | Biól. Mariana Cuautle Romero | Autoridad ambiental | Casos, reportes de la app (ver y validar), nodos, predicción |
| `arturo.tepox@vigia.demo` | C. Arturo Tepox Huerta | Limpia municipal | Casos, reportes de la app (ver y validar), barreras |
| `raul.ixtlapale@vigia.demo` | Cmdte. Raúl Ixtlapale Flores | Protección Civil | Casos, validar reportes, nodos, recolección, barreras, predicción |
| `diego.tlatelpa@vigia.demo` | Ing. Diego Tlatelpa Morales | Tecnológicos | Nodos y recolección |
| `lupita.sanchez@vigia.demo` | Guadalupe Sánchez Tecuatl | Ciudadanía | Vista pública (la usa la app) |

**Cuentas nuevas:** con el servidor apagado, `python -m server.renovar_cuentas` deja solo Administración (con su
contraseña de siempre) y crea de nuevo las demás, cada una con contraseña nueva. Antes de borrar guarda una copia
de la base en `server/datos/` y al final vuelve a generar los datos de la demo a nombre de las cuentas nuevas. Una
base creada antes de este cambio conserva sus cuentas anteriores (`pc@vigia.demo`, etc.) hasta que lo corran.

Resumen, Mapa y Transparencia son públicos: se ven sin iniciar sesión.

- **Permisos por persona.** En **Usuarios**, Administración puede quitar o agregar módulos a cada cuenta
  (por ejemplo, un inspector de Autoridad ambiental que solo consulta nodos). El rol da el juego inicial;
  «Usar los del rol» lo restablece. El cambio llega al momento: el menú de esa persona se rehace solo.
  Usuarios y Configuración van únicamente con el rol Administración. Los casos que ve cada quien siguen
  siendo los de su dependencia.
- **Contraseña temporal.** Las cuentas que crea Administración (y las contraseñas que reinicia) son temporales:
  al entrar, la persona tiene que crear la suya antes de ver cualquier dato. El servidor lo exige, no solo la pantalla.
- **Bitácora de accesos.** Usuarios muestra los últimos inicios de sesión, correctos y fallidos, con la dirección
  desde donde se intentaron (se guardan seis meses).
- **Olvidé mi contraseña:** Administración asigna una temporal desde Usuarios → Contraseña.

## Guion de la demostración (4 minutos)
1. Entra como **Administración**. *Resumen* es el centro de monitoreo: índice de la cuenca y su tendencia, tramos
   en alerta, casos, reportes, agua tratada y basura retirada; abajo, mapa, perfil del río y 30 días de calidad
   por tramo. En **Simular** pulsa **Reporte desde la app**: aparece al momento en el mapa (los reportes sí tienen
   internet). Con la app real: `POST /api/reportes`.
2. Abre **Estación piloto**: lo que entra del río contra lo que sale tratado, agua tratada al día, lodos del
   sedimentador, presión de filtros, energía solar y bitácora de mantenimiento, todo calculado de la telemetría.
3. En **Simular** pulsa **Visita a N3 (trae una descarga)**. Simula que Protección Civil descargó la microSD: el
   archivo pasa por el mismo camino que uno real. El análisis encuentra el evento con su hora real, lo cruza con
   los reportes, toma el folio de la muestra y abre un caso para Autoridad ambiental. El tramo queda «por confirmar».
4. Pulsa **Visita a N2 (confirma el tramo)**: al llegar los datos del nodo de aguas arriba, el caso confirma
   que la descarga entró entre Huejotzingo y Xoxtla.
5. Abre otra ventana como **Autoridad ambiental** (o cambia de cuenta): el aviso llegó solo. Abre el caso:
   lecturas del evento, evidencia, historial, laboratorio, PDF. Atiende y cierra: quien reportó recibe el aviso.
6. **Visita a N5 (trae una crecida)** abre un caso para Protección Civil; **Barrera llena**, uno para Limpia.
7. Con hardware real: entra como **Protección Civil** → *Recolección* → sube el CSV del nodo.
8. **Reiniciar demo (90 días)** deja todo como al principio para volver a ensayar.

## Qué es real y qué es de demostración
- **Real:** sesión y permisos, base de datos, carga y validación de CSV, huella del archivo, detección de
  anomalías, localización por tramo, cruce con reportes, casos, avisos en vivo, alta de usuarios, índice
  diario de calidad, pronóstico e indicadores de la estación (se calculan de las lecturas guardadas).
- **De demostración:** las lecturas de 90 días, los reportes y los casos iniciales salen de un modelo de
  simulación (ver abajo); la estación piloto EP-1 todavía no existe y se simula completa; la «clasificación IA»
  de los reportes iniciales es fija. No hay modelo de visión conectado: un reporte nuevo queda «sin clasificar»
  salvo que la app mande su propia clasificación (el punto de conexión es `clasificar_foto` en `server/main.py`).
- **Pendiente:** notificaciones push (hoy la app las lee de `/api/notificaciones`), PDF generado en el
  servidor (hoy es la impresión del navegador), sumar al pronóstico la lluvia de Conagua.

## De los sensores a la predicción
1. **Sensores.** Cada nodo mide pH, conductividad, turbidez, color (620 nm), temperatura y nivel cada 10 min
   (cada minuto durante una anomalía) y lo guarda en la microSD con una huella encadenada. El nodo N3 registra
   además la estación piloto: caudal, calidad del agua a la salida, lodos, presión de filtros y energía solar.
2. **Carga.** En cada visita se sube el CSV en *Recolección*. El servidor lo valida, descarta lo imposible,
   detecta anomalías, abre o actualiza casos y recalcula el índice de los días que trajo el archivo.
3. **Índice diario (0–100 por tramo).** Con las medianas del día del nodo de abajo de cada tramo (al menos 4 h
   de datos), cada parámetro recibe un puntaje según los umbrales del semáforo y el índice es
   0.6 × promedio ponderado (color 30 %, conductividad 25 %, turbidez 25 %, pH 20 %) + 0.4 × el peor puntaje,
   para que un solo parámetro muy malo no se esconda en el promedio (`indice_calidad` en `server/motor.py`).
4. **Predicción.** Ajusta un Holt-Winters aditivo (tendencia amortiguada y estacionalidad semanal, porque la
   industria descarga más entre semana) a todo el historial del índice (unos 90 días; la gráfica muestra los
   últimos 30) y proyecta los próximos 7 días con una banda del 80 %. Si el nodo lleva días sin visita, lo avisa
   y proyecta desde su último dato. Es un cálculo explicable,
   no una caja negra: no hace falta IA para esto (`forecast` en `js/engine.js`).

## Datos de demostración
Las lecturas de 90 días de los seis nodos (una cada 10 min), la estación, unos 220 reportes y 40 casos salen de
`server/simulacion.py` y `server/semilla.py`. No son mediciones, pero siguen los patrones del Alto Atoyac:
lluvias que se apagan en octubre (en noviembre baja el nivel y sube la conductividad), tormentas vespertinas,
ciclo del día, industria textil de Texmelucan–Huejotzingo en días hábiles con descargas de tinte por lotes,
drenaje urbano de Puebla, sondas que se ensucian y se limpian en cada visita y huecos cuando se agota la
batería. Las visitas caen en días hábiles cada 6 a 8 días, así que cada nodo tiene su propia «última descarga».

La **estación piloto EP-1** (Xoxtla, junto a N3) se simula con captación con compuerta y rejilla, tamiz rotatorio,
sedimentador, filtros de grava, arena y carbón activado, humedal artificial de 27 m² (tule, carrizo y alcatraz) y
descarga al río. La salida responde a la entrada con retraso, los lodos se purgan cada lunes, los filtros se
retrolavan solos a 24 kPa y el carbón se cambia cada seis semanas; *Estación piloto* detecta esos eventos en los
datos, no los lee de una lista.

La simulación es determinista: la misma hora de un nodo da siempre el mismo valor, así que una visita simulada
continúa justo la serie guardada. Si se cambia `VERSION_DEMO` en `server/semilla.py`, el servidor vuelve a
generar los datos de demostración al arrancar.

## Estructura
| Archivo | Qué hace |
|---|---|
| `iniciar.bat` | Prepara el entorno e inicia el servidor en Windows |
| `compartir.bat` | Abre un enlace público temporal con Cloudflare (Quick Tunnel) |
| `demo_colab.ipynb` | Demo en Google Colab: clona el repositorio, enciende el servidor y abre el túnel de Cloudflare |
| `index.html`, `login.html` | Plataforma y pantalla de inicio de sesión |
| `css/styles.css` | Sistema de diseño (ver `docs/design-system.md`) |
| `js/config.js` | Parámetros, dependencias, roles, permisos y menú |
| `js/api.js` | Capa de datos: servidor (sesión, API, WebSocket) o demo sin servidor |
| `js/app.js` | Sesión, rutas, menú según los permisos de cada persona y avisos en vivo |
| `js/login.js` | Inicio de sesión y paso de «crea tu contraseña» para cuentas con contraseña temporal |
| `js/views.js` | Vistas: Resumen (centro de monitoreo), Mapa, Riesgo del agua, Estación piloto, Casos, Nodos, Reportes, Recolección, Predicción, Transparencia, Informes y descargas, Red de nodos, Usuarios, Configuración |
| `js/map.js` | Mapa 3D (MapLibre): relieve real, tramos, columnas 3D por nodo y barrera, satélite, calor. Respaldo 2D con Leaflet si no hay WebGL |
| `js/engine.js`, `js/charts.js`, `js/ui.js` | Semáforo y pronóstico (Holt-Winters), gráficas Chart.js y minigráficas SVG, utilidades |
| `js/cauce.js` | Cauce real del Atoyac entre nodos y posición de nodos y barreras (OpenStreetMap) |
| `js/data.js` | Datos de la demo sin servidor |
| `server/main.py` | API (FastAPI): sesión, usuarios, reportes, casos, recolección, métricas, WebSocket |
| `server/seguridad.py` | Contraseñas (PBKDF2), sesiones, roles, permisos por persona, límite de intentos |
| `server/motor.py` | Análisis por lote: anomalías (z-score robusto), huella de descarga, localización, fusión, casos, índice diario |
| `server/simulacion.py` | Modelo de simulación del río y de la estación piloto (datos de demostración, determinista) |
| `server/red.py` | Red de nodos configurable: alta, cambios y baja sobre el cauce; tramos recalculados; ajustes de la red |
| `server/riesgo.py` | Riesgo para la salud por contacto con el agua, por tramo |
| `server/informes.py` | Formatos de los informes: PDF (fpdf2), Excel (openpyxl) y CSV |
| `server/lotes.py` | Lectura y validación del CSV de la microSD, huella encadenada, generador de ejemplos |
| `server/db.py`, `server/modelos.py`, `server/semilla.py` | Esquema SQLite, formato de respuestas, datos iniciales |
| `server/prueba_rapida.py` | Prueba de punta a punta de la API (120 comprobaciones) |
| `server/renovar_cuentas.py` | Deja solo Administración y crea de nuevo una cuenta por rol, cada una con su contraseña |
| `server/prueba_motor.py` | Prueba del motor sin servidor: tiempo de tránsito del agua entre nodos (base temporal) |
| `docs/api.md`, `docs/formato-lote.md` | Referencia para la app móvil y para el firmware del nodo |
| `vendor/` | MapLibre GL 4.7.1, Leaflet, leaflet.heat, Chart.js, Lucide y fuentes (copias locales) |

## Mapa 3D
**Todo va sobre el río.** Cada nodo está sobre un puente del Atoyac (carretera a Tlaxcala en Texmelucan, puente
de Huejotzingo, Xoxtla, autopista México–Puebla, Vía Atlixcáyotl y la entrada a Valsequillo) y cada tramo sigue el
cauce real entre dos nodos (unos 65 km en total). Las barreras están sobre sus barrancas (Santuario/Xaltonac,
Alseseca y la barranca junto a la Calzada del Conde). El trazo viene de OpenStreetMap
(© colaboradores de OpenStreetMap, licencia ODbL) y vive en un solo archivo, `js/cauce.js`, que usan el
servidor y la demo sin servidor. Si se cambia, el servidor actualiza nodos y tramos al arrancar y, en modo demo,
vuelve a generar reportes y casos sobre el cauce nuevo.

El mapa usa el relieve real del terreno (los volcanes y las barrancas se ven), inclinado y mirando río abajo.
Cada nodo es una **columna 3D** del color del semáforo: entre más alta, más cerca está su última lectura del
umbral de atención. Las barreras son prismas que crecen con su llenado. Botones del mapa: **3D** (relieve y
columnas, o vista plana), **Satélite** y **Ver toda la cuenca**. Para girar o inclinar: clic derecho y arrastrar
(o Ctrl + arrastrar; en pantalla táctil, dos dedos).

Ninguna fuente necesita API key: calles de [OpenFreeMap](https://openfreemap.org), satélite de Esri, relieve de
[Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) (AWS). Necesitan internet; sin él, el río, los nodos y
las columnas se dibujan sobre un fondo liso. Si la computadora no tiene WebGL se usa el mapa plano de Leaflet.

## Pruebas
Con el servidor encendido, en otra terminal: `python -m server.prueba_rapida`. Recorre inicio de sesión,
permisos por rol y por persona, contraseña temporal, bitácora, reporte con foto, carga de CSV con descarga,
huella alterada, casos, usuarios, límite de intentos, estación piloto, series e índice diario, riesgo del agua,
informes y red de nodos (da de alta un nodo de prueba y lo elimina), y al final deja los datos de la demo en su punto de
partida (las cuentas de prueba que crea se quedan). Sirve para la sección de pruebas del documento.

Sin servidor: `python -m server.prueba_motor` revisa el tiempo de tránsito con una base temporal (la misma
descarga vista en N3 y 4 h después en N4 es un solo caso; vista en N4 a los 20 min son dos casos distintos,
porque el agua no recorre 16 km tan rápido; si el nodo de arriba la tuvo antes, el origen sube).

## Tiempo de tránsito entre nodos
Para saber si dos anomalías en nodos distintos son la misma descarga, el motor usa los km de cauce entre ellos
y la velocidad del agua: de **0.3 m/s** (estiaje) a **2 m/s** (crecida), más 30 min de margen por el muestreo.
Ejemplo: de N3 a N4 hay 16.4 km, así que el agua tarda de unas 2.3 h a 15 h; una anomalía en N4 que aparezca
en ese rango después de la de N3 se suma al mismo caso, y fuera de él se trata como otra descarga. El mapa
muestra el largo y el tiempo de cada tramo al tocarlo. Las velocidades se ajustan en **Red de nodos** (valores de
inicio en `server/motor.py`); conviene calibrarlas con aforos de Conagua o con el retraso real de una misma
descarga entre dos nodos.

## Red de nodos configurable (Administración)
Los nodos de la demo son simulados, pero la red se configura completa desde **Red de nodos**:
- **Alta:** se toca el río en el mapa y el nodo se coloca en el punto del cauce más cercano (a menos de 1.5 km del
  río y a 300 m o más de otro nodo). Toma valores normales intermedios entre sus vecinos y, en la demo, sus 90 días
  de datos simulados.
- **Cambios y baja:** renombrar, cambiar el Tecnológico que le da mantenimiento, moverlo o darlo de baja (sus
  lecturas se conservan y se puede reactivar). Un nodo dado de baja se puede eliminar para siempre.
- **Tramos:** con cada cambio los nodos se ordenan río abajo y los tramos T1…Tn se rehacen solos sobre el cauce, con
  su largo y el tiempo del agua. Los casos y el índice pasan al tramo nuevo que termina en el mismo nodo.
- **Ajustes:** radio para ligar reportes a un nodo, velocidades del agua (estiaje y crecida) y días sin visita.

Desde el primer cambio la red vive en la base de datos y el arranque ya no la toma de `js/cauce.js`, que sigue
siendo el trazo del río.

## Riesgo del agua para las personas
**Riesgo del agua** (público, y la pestaña **El río** de la app) dice por tramo qué tan peligroso es el contacto con
el agua, porque hay quien se mete a bañar al río aunque no esté permitido. Nunca dice que sea apta: los nodos no
miden bacterias, metales ni compuestos de tintes, y el río recibe drenaje sin tratar. El nivel parte de «alto» y
sube a «muy alto» o «extremo» con lecturas fuera de rango y con descargas o crecidas recientes en el tramo, con la
razón en lenguaje claro y recomendaciones (`server/riesgo.py`, `GET /api/riesgo`).

## Informes para el Ayuntamiento
**Informes y descargas** genera, para el periodo que se elija: el **informe del periodo en PDF** (índice por tramo,
casos por dependencia, reportes, agua tratada, basura y riesgo; listo para presentar en Cabildo) y, en **Excel o
CSV**, el índice diario, las lecturas de los nodos, el resumen de la estación y la basura retirada. Casos y reportes
ciudadanos solo los descarga el personal, y cada dependencia ve completos los suyos.

## Seguridad (lo que ya está y lo que falta para un despliegue real)
- Contraseñas con PBKDF2-SHA256 y sal; sesión en cookie HttpOnly + SameSite; el token solo se guarda como SHA-256.
- Cada ruta revisa en el servidor los permisos de la persona: la web solo esconde menús, no decide permisos.
- Con contraseña temporal, el servidor no entrega datos hasta que la persona crea la suya.
- Cambiar rol, contraseña o desactivar una cuenta cierra sus sesiones abiertas al momento.
- El público nunca recibe texto de reportes, fotos ni quién reportó; sí el lugar del suceso (≈1 m). La app solo envía
  un reporte con GPS de 5 m o menos de margen o con el punto marcado a mano en el mapa a nivel de calle, y el
  servidor rechaza un GPS de más de 5 m.
- Detrás del túnel de Cloudflare los límites de intentos y de reportes usan la dirección real de cada visitante
  (`CF-Connecting-IP`, que solo se acepta si la conexión viene de la misma máquina, como la de `cloudflared`).
- Cinco contraseñas fallidas bloquean un minuto; cada intento queda en la bitácora. Fotos: solo JPG/PNG/WebP de hasta 5 MB.
- **Modo demo** (`VA_DEMO=1`, por defecto): crea cuentas de prueba con contraseña conocida y activa las simulaciones.
  Para cualquier servidor público: `VA_DEMO=0`, `VA_ADMIN_CUENTA`, `VA_ADMIN_CLAVE`, HTTPS y `VA_HTTPS=1`.
- **Para que entre la app desde el celular** hay que abrir el servidor a la red: `set VA_HOST=0.0.0.0` antes de
  `iniciar.bat`, y usar la IP de la laptop. Va por HTTP sin cifrar: háganlo en su propio hotspot, no en el WiFi
  del evento.

## Variables de entorno
`VA_HOST` (127.0.0.1) · `VA_PORT` (8000) · `VA_DEMO` (1) · `VA_DEMO_CLAVE` (una misma contraseña fija para todas las cuentas demo)
· `VA_ADMIN_CUENTA`, `VA_ADMIN_CLAVE` · `VA_HTTPS` (0) · `VA_DATOS` (carpeta de la base; por defecto `server/datos`).

Si cambian el esquema de `server/db.py`, borren `server/datos/vigia.db` y vuelvan a iniciar (las columnas nuevas
de `usuarios` y `lecturas` se agregan solas a una base que ya existía).
