# EcoRed Puebla · Vigía Atoyac

Proyecto del equipo para HackaTec 2026 (reto SECIHTI Puebla): vigilancia de la contaminación del Alto Atoyac
con nodos de sensores (simulados en el prototipo), reportes ciudadanos y casos asignados a cada dependencia.

| Carpeta | Qué es |
|---|---|
| `plataforma/` | Plataforma central: web con inicio de sesión por rol (HTML/CSS/JS + Leaflet + Chart.js) y API (FastAPI + SQLite + WebSocket). Ver `plataforma/README.md`. |

**Arranque rápido (Windows):** `plataforma\iniciar.bat` → http://localhost:8000/login.html
**Enlace público temporal:** `plataforma\compartir.bat` (Cloudflare Quick Tunnel).

Contrato para la app ciudadana y el firmware: `plataforma/docs/api.md` y `plataforma/docs/formato-lote.md`.
