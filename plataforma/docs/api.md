# API de Vigía Atoyac (resumen)

Referencia completa e interactiva con el servidor encendido: **http://localhost:8000/api/docs**

## Sesión
| Método | Ruta | Para qué |
|---|---|---|
| POST | `/api/auth/entrar` | `{cuenta, clave, origen}`. Con `origen:"app"` devuelve `token` (30 días); la web recibe una cookie HttpOnly (12 h). |
| POST | `/api/auth/registro` | Registro de ciudadanía: `{nombre, cuenta, clave, origen}`. `cuenta` es correo o teléfono de 10 dígitos. |
| GET | `/api/auth/yo` | Quién soy: `usuario` con `rol`, `permisos` (módulos que puede usar) y `cambiar_clave`. |
| POST | `/api/auth/salir` | Cierra la sesión. |
| POST | `/api/auth/clave` | Cambiar contraseña: `{actual, nueva}`. La nueva debe ser distinta de la actual. |

**App móvil:** manda `Authorization: Bearer <token>` en cada petición.
**Web:** usa la cookie y agrega la cabecera `X-VA: 1` en todo lo que no sea GET (protección contra CSRF).

**Contraseña temporal:** si `usuario.cambiar_clave` es `true` (cuenta creada o reiniciada por Administración),
cualquier ruta distinta de `/api/auth/yo`, `/api/auth/clave` y `/api/auth/salir` responde `403` con la cabecera
`X-VA-Accion: cambiar-clave` hasta que la persona cambie su contraseña. La ciudadanía que se registra sola no pasa por esto.

## Reportes de la app
| Método | Ruta | Para qué |
|---|---|---|
| POST | `/api/reportes` | Formulario `multipart`: `cat`, `lat`, `lng`, y opcionales `texto`, `foto` (JPG/PNG/WebP ≤ 5 MB), `anonimo`, `voz`, `ia_etiqueta`, `ia_confianza`, y el origen del lugar del suceso: `ubicacion=gps` con `precision_m` (margen del GPS en metros, 5 o menos; si no, `422`) o `ubicacion=mapa` si se marcó a mano. Devuelve el folio. El público recibe la ubicación con 5 decimales (≈1 m). |
| GET | `/api/reportes?mios=true` | Mis reportes y su estado. |
| GET | `/api/reportes/{folio}` | Seguimiento por folio (también para reportes anónimos). |
| GET | `/api/notificaciones` | Avisos para mostrar como push («tu reporte avanzó»). |

Categorías válidas: Agua de color, Espuma, Basura, Descarga de tubería, Mal olor, Animal muerto.

```bash
# Entrar desde la app y mandar un reporte con foto
curl -s -X POST http://localhost:8000/api/auth/entrar -H "Content-Type: application/json" \
     -d '{"cuenta":"lupita.sanchez@vigia.demo","clave":"<la de cuentas_demo.txt>","origen":"app"}'
curl -s -X POST http://localhost:8000/api/reportes -H "Authorization: Bearer <token>" \
     -F cat="Agua de color" -F lat=19.18717 -F lng=-98.30329 -F texto="Agua azul en la orilla" -F foto=@foto.jpg
```

## Datos y casos
| Método | Ruta | Quién | Para qué |
|---|---|---|---|
| GET | `/api/estado` | todos | Todo lo que pinta la web, filtrado según el rol y los permisos. Trae también `dailyIndex` (índice 0–100 por tramo y día), `basura` (`kg30`, `kg90`, `vaciados30`) y `estaciones` (`nodo`, `codigo`, `nombre`). |
| GET | `/api/metricas` | público | Indicadores: nodos, semáforo por tramo, casos y reportes. |
| GET | `/api/nodos`, `/api/tramos`, `/api/barreras` | público | Catálogo. Cada tramo trae `points` (cauce real), `km` de cauce y `transitH` = [horas en crecida, horas en estiaje] que tarda el agua en recorrerlo. |
| GET | `/api/nodos/{id}/lecturas?limite=48` | público | Últimas lecturas. |
| GET | `/api/series?nodo=N3&dias=7&agrupar=hora` | público | Para gráficas: medianas por hora (`agrupar=hora`) o por día (`agrupar=dia`) de hasta 90 días, contados hacia atrás desde la última lectura. Devuelve `{nodo, paso, hasta, puntos}`; cada punto trae `t`, `n` (lecturas), `anom` (anómalas) y la mediana de cada parámetro, incluidas las columnas de la estación si el nodo la tiene. |
| GET | `/api/estacion?nodo=N3&dias=7` | público | Estación piloto (hasta 30 días). `kpis`: `caudal` (L/s), `m3Dia` del último día completo (`diaBase`; `null` si no hay día completo y se escala lo que haya), `remocion` y `remocionPeriodo` por parámetro (ponderadas por caudal), `solidosKgDia`, `lodos` (%), `dp` y `dpMax` (kPa), `horasRetrolavado`, `energiaWhDia`, `carbonDias`. Además `mantenimiento` (purgas, retrolavados y cambio de carbón detectados en los datos), `eficienciaColorDiaria` y `serie` por hora. `404` si el nodo no tiene estación. |
| GET | `/api/abiertos/lecturas.csv?nodo=N3&dias=7` | público | Datos abiertos en CSV (con las columnas de la estación si el nodo la tiene). |
| GET | `/api/casos`, `/api/casos/{id}` | todos | Cada dependencia ve completos los suyos; el resto, versión pública. |
| PATCH | `/api/casos/{id}` | permiso `casos` + dependencia dueña | `{accion: atender \| inspeccion \| lab \| cerrar, lab}` |
| PATCH | `/api/reportes/{folio}` | permiso `validar` | `{estado}`: Validado, Descartado… |
| PATCH | `/api/barreras/{id}` | permiso `barreras` | `{fill, nivel, vaciada}` registrado en la visita. |
| PUT | `/api/ajustes/umbrales` | permiso `config` | Umbrales del semáforo. |

## Recolección (nodos sin internet)
| Método | Ruta | Quién | Para qué |
|---|---|---|---|
| POST | `/api/sincronizacion` | permiso `recoleccion` | `multipart`: `nodo`, `archivo` (CSV) y la lista de campo `limpieza`, `calibracion`, `frascos`. Guarda, analiza y abre casos. |
| GET | `/api/sincronizacion/ejemplo?nodo=N3&evento=descarga` | los mismos | CSV de ejemplo. |
| GET | `/api/lotes` | los mismos | Archivos recibidos. |

Formato del CSV: `docs/formato-lote.md`.

## Tiempo real
`WS /ws/eventos` manda `{"tipo": "reporte" | "caso" | "lote" | "barrera" | "ajustes" | "usuarios"}` cada vez que algo cambia.
La web vuelve a pedir `/api/estado` (así también se entera si le cambiaron los permisos). El personal recibe además un `aviso` con título y texto.

## Usuarios (permiso `usuarios`, solo rol Administración)
| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/usuarios` | Cuentas, con sus `permisos` efectivos y si están ajustados (`permisos_propios`). |
| POST | `/api/usuarios` | `{nombre, cuenta, rol, clave, permisos?}`. La clave es temporal: el personal la cambia al entrar. Sin `permisos` usa los del rol. |
| PATCH | `/api/usuarios/{id}` | `{nombre?, rol?, activo?, clave?, permisos?, permisos_del_rol?}`. Cambiar de rol vuelve a los permisos del rol nuevo. |
| GET | `/api/permisos` | Catálogo: descripción de cada permiso, permisos por rol y los que son solo de Administración. |
| GET | `/api/accesos?limite=100` | Bitácora de inicios de sesión: `t`, `cuenta`, `nombre`, `ip`, `resultado` (`ok`, `clave`, `desactivada`, `bloqueo`). |

Roles: `ciudadano`, `ambiental`, `limpia`, `pc`, `tec`, `admin`.
Permisos: `casos`, `reportes`, `validar`, `nodos`, `recoleccion`, `barreras`, `prediccion`, `usuarios`, `config`
(los dos últimos solo con el rol `admin`).
