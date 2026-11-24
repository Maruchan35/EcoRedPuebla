# API de Vigía Atoyac (resumen)

Referencia completa e interactiva con el servidor encendido: **http://localhost:8000/api/docs**

## Sesión
| Método | Ruta | Para qué |
|---|---|---|
| POST | `/api/auth/entrar` | `{cuenta, clave, origen}`. Con `origen:"app"` devuelve `token` (30 días); la web recibe una cookie HttpOnly (12 h). |
| POST | `/api/auth/registro` | Registro de ciudadanía: `{nombre, cuenta, clave, origen}`. `cuenta` es correo o teléfono de 10 dígitos. |
| GET | `/api/auth/yo` | Quién soy. |
| POST | `/api/auth/salir` | Cierra la sesión. |
| POST | `/api/auth/clave` | Cambiar contraseña: `{actual, nueva}`. |

**App móvil:** manda `Authorization: Bearer <token>` en cada petición.
**Web:** usa la cookie y agrega la cabecera `X-VA: 1` en todo lo que no sea GET (protección contra CSRF).

## Reportes de la app
| Método | Ruta | Para qué |
|---|---|---|
| POST | `/api/reportes` | Formulario `multipart`: `cat`, `lat`, `lng`, y opcionales `texto`, `foto` (JPG/PNG/WebP ≤ 5 MB), `anonimo`, `voz`, `ia_etiqueta`, `ia_confianza`. Devuelve el folio. |
| GET | `/api/reportes?mios=true` | Mis reportes y su estado. |
| GET | `/api/reportes/{folio}` | Seguimiento por folio (también para reportes anónimos). |
| GET | `/api/notificaciones` | Avisos para mostrar como push («tu reporte avanzó»). |

Categorías válidas: Agua de color, Espuma, Basura, Descarga de tubería, Mal olor, Animal muerto.

```bash
# Entrar desde la app y mandar un reporte con foto
curl -s -X POST http://localhost:8000/api/auth/entrar -H "Content-Type: application/json" \
     -d '{"cuenta":"ciudadana@vigia.demo","clave":"<la de cuentas_demo.txt>","origen":"app"}'
curl -s -X POST http://localhost:8000/api/reportes -H "Authorization: Bearer <token>" \
     -F cat="Agua de color" -F lat=19.1835 -F lng=-98.3050 -F texto="Agua azul bajo el puente" -F foto=@foto.jpg
```

## Datos y casos
| Método | Ruta | Quién | Para qué |
|---|---|---|---|
| GET | `/api/estado` | todos | Todo lo que pinta la web, filtrado según el rol. |
| GET | `/api/metricas` | público | Indicadores: nodos, semáforo por tramo, casos y reportes. |
| GET | `/api/nodos`, `/api/tramos`, `/api/barreras` | público | Catálogo. |
| GET | `/api/nodos/{id}/lecturas?limite=48` | público | Últimas lecturas. |
| GET | `/api/abiertos/lecturas.csv?nodo=N3&dias=7` | público | Datos abiertos en CSV. |
| GET | `/api/casos`, `/api/casos/{id}` | todos | Cada dependencia ve completos los suyos; el resto, versión pública. |
| PATCH | `/api/casos/{id}` | dependencia dueña | `{accion: atender \| inspeccion \| lab \| cerrar, lab}` |
| PATCH | `/api/reportes/{folio}` | gobierno | `{estado}`: Validado, Descartado… |
| PATCH | `/api/barreras/{id}` | PC, Limpia | `{fill, nivel, vaciada}` registrado en la visita. |
| PUT | `/api/ajustes/umbrales` | Administración | Umbrales del semáforo. |

## Recolección (nodos sin internet)
| Método | Ruta | Quién | Para qué |
|---|---|---|---|
| POST | `/api/sincronizacion` | PC, Tecnológicos, Administración | `multipart`: `nodo`, `archivo` (CSV) y la lista de campo `limpieza`, `calibracion`, `frascos`. Guarda, analiza y abre casos. |
| GET | `/api/sincronizacion/ejemplo?nodo=N3&evento=descarga` | los mismos | CSV de ejemplo. |
| GET | `/api/lotes` | gobierno | Archivos recibidos. |

Formato del CSV: `docs/formato-lote.md`.

## Tiempo real
`WS /ws/eventos` manda `{"tipo": "reporte" | "caso" | "lote" | "barrera" | "ajustes"}` cada vez que algo cambia.
La web vuelve a pedir `/api/estado`. El personal recibe además un `aviso` con título y texto.

## Usuarios (Administración)
`GET /api/usuarios` · `POST /api/usuarios` `{nombre, cuenta, rol, clave}` · `PATCH /api/usuarios/{id}` `{nombre, rol, activo, clave}`

Roles: `ciudadano`, `ambiental`, `limpia`, `pc`, `tec`, `admin`.
