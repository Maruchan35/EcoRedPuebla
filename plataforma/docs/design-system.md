# Sistema de diseño · Vigía Atoyac

Definido con los datos de la skill **ui-ux-pro-max** (tablas `products.csv`, `colors.csv`,
`ui-reasoning.csv`, `typography.csv`, `styles.csv`, `charts.csv` y `quick-reference.md`).

## Tipo de producto
- **Government/Public Service** + **Real-Time Monitoring** (panel denso de monitoreo).
- Estilo: *Accessible & Ethical* + *Minimalism & Swiss Style*. Vista general tipo *Executive Dashboard*
  (4–6 KPIs, semáforo, tendencias) y vistas de operación tipo *Real-Time Monitoring*
  (indicador en vivo, estado de conexión, alertas prominentes).
- Patrón: *Minimal & Direct*. Lenguaje claro, sin adornos.

## Anti-patrones (no usar)
Diseño ornamentado, bajo contraste, efectos de movimiento llamativos, degradados morado/rosa "de IA",
emojis como íconos, información transmitida solo con color.

## Color (tokens en `css/styles.css`)
| Token | Valor | Uso |
|---|---|---|
| `--color-primary` | `#0F172A` | Barra lateral, títulos |
| `--color-secondary` | `#334155` | Texto secundario fuerte |
| `--color-accent` | `#0369A1` | Acciones, enlaces, foco |
| `--color-water` | `#0E7490` | Río, telemetría |
| `--color-bg` | `#F8FAFC` | Fondo |
| `--color-card` | `#FFFFFF` | Tarjetas |
| `--color-muted` / `--color-muted-fg` | `#E8ECF1` / `#475569` | Fondos y texto tenue |
| `--color-border` | `#E2E8F0` | Bordes |
| `--color-destructive` | `#DC2626` | Acciones peligrosas |

Semáforo (siempre con **ícono + texto**, nunca solo color):
- Bien: texto `#15803D` sobre `#DCFCE7`, punto `#22C55E`
- Atención: texto `#B45309` sobre `#FEF3C7`, punto `#F59E0B`
- Crítico: texto `#B91C1C` sobre `#FEE2E2`, punto `#EF4444`

## Tipografía
Pareja *Corporate Trust*: **Lexend** (títulos) + **Source Sans 3** (cuerpo). Recomendada para gobierno
y accesibilidad. Cuerpo 16 px, interlineado 1.5; números con `tabular-nums`. Fuentes incluidas en
`vendor/fonts` para funcionar sin internet.

## Espaciado
Densidad de panel (8–32 px): 4, 8, 12, 16, 24, 32. Radios 8 px (controles) y 12 px (tarjetas).

## Accesibilidad (obligatorio)
- Contraste ≥ 4.5:1 en texto; anillo de foco visible de 3 px.
- Enlace "Saltar al contenido", navegación completa con teclado, orden de tabulación lógico.
- Botones de solo ícono con `aria-label`; íconos decorativos con `aria-hidden`.
- Alertas en región `aria-live` sin mover el foco.
- `prefers-reduced-motion`: se desactiva el pulso del indicador en vivo y las animaciones.
- Áreas de clic ≥ 44 px en controles principales.

## Gráficas
- Telemetría: línea con **marcadores de anomalía** (forma distinta + etiqueta), con botón Pausar/Reanudar
  y el valor actual en texto.
- Predicción: real en línea sólida, pronóstico punteado y banda de confianza.
- Mapa: Leaflet con mapa de calor y leyenda numérica; tramos con etiqueta de texto además del color.
- Toda gráfica tiene un resumen en texto o una tabla alternativa.

## Navegación
Barra lateral en pantallas ≥ 1024 px; menú desplegable en pantallas pequeñas. Cada vista tiene URL
propia (`#/mapa`, `#/casos/VA-2026-0007`) para compartir y para abrir desde notificaciones.
