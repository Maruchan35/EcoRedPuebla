# EcoRed Puebla · App Ciudadana (`app-ciudadana/`)

Módulo ciudadano PWA (Progressive Web App) construido en **HTML, CSS y JavaScript puro** sin paso de compilación y con librerías locales en `vendor/` para funcionar sin internet, integrado directamente con el servidor FastAPI de `plataforma/`.

## Qué incluye

1. **Captura inteligente en campo (`#/reportar`)**
   - Cámara trasera en vivo (`getUserMedia`), cámara nativa móvil y carga desde galería con lectura de coordenadas **GPS EXIF** antes de comprimir.
   - Análisis óptico inmediato en el navegador (`js/vision-local.js`) para detectar coloración anómala (tintes NOM-001) y espuma superficial sin requerir internet.
   - Ubicación automática GPS + mini-mapa interactivo + puntos rápidos de referencia de la cuenca del Alto Atoyac + dictado por voz (`es-MX`).
   - Cola persistente sin internet en `IndexedDB` (`js/offline-queue.js`): guarda reportes con foto cuando no hay señal y los sincroniza automáticamente al reconectar.

2. **Mapa de calor 2D (`#/mapa`)**
   - Mapa con **Leaflet + `leaflet.heat`** sobre la cuenca del Alto Atoyac (ríos, barrancas y zonas de recarga hídrica).
   - Filtros por categoría, capas conmutables (puntos calientes, marcadores de reportes, tramos/nodos/barreras) y actualización en vivo por `WS /ws/eventos`.

3. **Seguimiento de folios y avisos (`#/seguimiento`)**
   - Inicio de sesión y registro ciudadano vía `POST /api/auth/entrar` (`origen: "app"`) o reporte anónimo.
   - Consulta de folios (`R-XXXX`) con barra de avance (`Recibido → Validado → Atendido`) y avisos desde `GET /api/notificaciones`.

4. **Clasificador híbrido para el servidor (`integracion-ia/clasificador_hibrido.py`)**
   - Conectado a `clasificar_foto` en `plataforma/server/main.py`.
   - Usa Gemini Vision si se define la variable de entorno `GEMINI_API_KEY` y hay internet; si no, ejecuta clasificación óptica local sin internet ni dependencias pesadas, o deja que prevalezca la clasificación del teléfono/usuario.

## Cómo probarlo junto con `plataforma/`

1. Inicia el servidor central:
   ```bat
   plataforma\iniciar.bat
   ```
2. Abre en tu navegador o celular:
   - App ciudadana: `http://localhost:8000/app/`
   - Plataforma central: `http://localhost:8000/login.html`
3. Para probar cámara y GPS desde celulares reales en el HackaTec, ejecuta `plataforma\compartir.bat` (túnel HTTPS de Cloudflare) y comparte `<enlace-https>/app/`.
