# EcoRed Puebla · Vigía Atoyac

Proyecto del equipo para HackaTec 2026 (reto SECIHTI Puebla): vigilancia de la contaminación del Alto Atoyac
con nodos de sensores (simulados en el prototipo), reportes ciudadanos y casos asignados a cada dependencia.

| Carpeta | Qué es |
|---|---|
| `plataforma/` | Plataforma central: web con inicio de sesión y permisos por persona, mapa 3D con relieve (HTML/CSS/JS + MapLibre + Chart.js) y API (FastAPI + SQLite + WebSocket). Ver `plataforma/README.md`. |
| `app-ciudadana/` | App ciudadana PWA (HTML/CSS/JS + Leaflet + IA híbrida) para reportar con cámara, GPS, mapa de calor y seguimiento de folios. Ver `app-ciudadana/README.md`. |

**Arranque rápido (Windows):** `plataforma\iniciar.bat` → http://localhost:8000/login.html y app ciudadana en http://localhost:8000/app/
**Enlace público temporal:** `plataforma\compartir.bat` (Cloudflare Quick Tunnel).
**Demo sin laptop:** [![Abrir en Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Maruchan35/EcoRedPuebla/blob/demo-hackatec/plataforma/demo_colab.ipynb)
`plataforma/demo_colab.ipynb` enciende la plataforma en Google Colab y la publica con un túnel de Cloudflare.

Contrato para la app ciudadana y el firmware: `plataforma/docs/api.md` y `plataforma/docs/formato-lote.md`.
