/* =========================================================
   Configuración general: parámetros, umbrales, roles y menú.
   Todo lo "ajustable" vive aquí para no tocar la lógica.
   ========================================================= */
window.VA = window.VA || {};

VA.config = {
  // Cada cuánto llega una lectura en la demo sin servidor (ms). El nodo real guarda una cada 10 min
  // y una por minuto mientras detecta una anomalía; sus datos llegan con la visita de Protección Civil.
  telemetryIntervalMs: 3000,
  // Ventana de lecturas para el z-score robusto
  anomalyWindow: 36,
  anomalyZ: 3.5,
  // Radio (km) y ventana (h) para cruzar un evento de sensor con reportes ciudadanos
  fusionRadiusKm: 2.5,
  fusionWindowH: 6,

  // ---------- Parámetros que mide el nodo ----------
  // warn/crit: umbrales del semáforo. Ajustables desde Configuración.
  params: {
    ph:    { label: "pH",            unit: "",        dec: 2, min: 6.5, max: 8.5, critMin: 6.0, critMax: 9.0, anomaly: true },
    cond:  { label: "Conductividad", unit: "µS/cm",   dec: 0, warn: 1500, crit: 2500, anomaly: true },
    turb:  { label: "Turbidez",      unit: "NTU",     dec: 0, warn: 100,  crit: 250,  anomaly: true },
    color: { label: "Color 620 nm",  unit: "m⁻¹",     dec: 1, warn: 3.0,  crit: 6.0,  anomaly: true,
             help: "Coeficiente de absorción a 620 nm; la NOM-001 usa 436, 525 y 620 nm para el color verdadero." },
    temp:  { label: "Temperatura",   unit: "°C",      dec: 1, warn: 25,   crit: 30,   anomaly: false },
    nivel: { label: "Nivel",         unit: "m",       dec: 2, warn: 2.0,  crit: 2.8,  anomaly: false }
  },

  // ---------- Dependencias ----------
  dependencias: {
    ambiental: { label: "Autoridad ambiental", icon: "shield-check" },
    limpia:    { label: "Limpia municipal",    icon: "truck" },
    pc:        { label: "Protección Civil",    icon: "siren" },
    brigadas:  { label: "Brigadas ciudadanas", icon: "users" }
  },

  // ---------- Tipos de caso y a quién se asignan ----------
  tiposCaso: {
    descarga:   { label: "Posible descarga ilegal", icon: "droplets",       dep: "ambiental" },
    basura:     { label: "Basura acumulada",        icon: "trash-2",        dep: "limpia" },
    inundacion: { label: "Riesgo de inundación",    icon: "cloud-rain",     dep: "pc" },
    recurrente: { label: "Punto crítico recurrente", icon: "map-pin",       dep: "brigadas" }
  },

  estadosCaso: ["Nuevo", "En atención", "Inspección programada", "Cerrado"],

  // Días sin visita de Protección Civil tras los que un nodo se muestra en gris
  staleDays: 7,

  // Velocidad del agua del Atoyac (m/s), lenta en estiaje y rápida en crecida: da cuánto tarda en recorrer
  // cada tramo. Igual que VEL_MIN_MS y VEL_MAX_MS en server/motor.py (con servidor, el tiempo lo manda él).
  rio: { velMin: 0.3, velMax: 2.0 },

  // ---------- Roles y permisos ----------
  // Solo hay dos roles: Administración, que entra a esta plataforma y lo ve todo, y ciudadanía, que reporta
  // desde la app (con cuenta o de forma anónima). Con servidor, los permisos llegan con la sesión y el servidor
  // los hace cumplir en cada petición; estos juegos solo se usan en la demo sin servidor.
  // deps = casos de qué dependencias atiende (Administración los canaliza a todas).
  roles: {
    publico:   { label: "Ciudadanía",     staff: false, deps: [], permisos: [] },
    ciudadano: { label: "Ciudadanía",     staff: false, deps: [], permisos: [] },
    admin:     { label: "Administración", staff: true,  deps: ["ambiental", "limpia", "pc", "brigadas"],
                 permisos: ["casos", "reportes", "validar", "nodos", "recoleccion", "barreras", "prediccion", "usuarios", "config"] }
  },
  // Nombre corto de cada permiso (la descripción larga la manda el servidor)
  permisoLabels: { casos: "Casos", reportes: "Reportes de la app", validar: "Validar reportes", nodos: "Nodos", recoleccion: "Recolección",
    barreras: "Barreras", prediccion: "Predicción", usuarios: "Usuarios", config: "Configuración" },
  // Vistas que necesitan el servidor (no aparecen al abrir index.html con doble clic)
  serverOnly: ["recoleccion", "usuarios", "estacion", "riesgo", "informes", "red"],

  // Menú lateral por grupos, en este orden. Cada vista pide `permiso` (sin él es pública) o `personal`
  // (cualquier cuenta de una dependencia). Un grupo sin vistas permitidas no aparece.
  navGroups: [
    { label: "Monitoreo del río", items: ["resumen", "mapa", "riesgo", "estacion", "nodos", "prediccion"] },
    { label: "Atención",          items: ["casos", "reportes", "recoleccion"] },
    { label: "Datos abiertos",    items: ["transparencia", "informes"] },
    { label: "Administración",    items: ["red", "usuarios", "config"] }
  ],
  nav: {
    resumen:       { label: "Resumen",              icon: "layout-dashboard" },
    mapa:          { label: "Mapa",                 icon: "map" },
    riesgo:        { label: "Riesgo del agua",      icon: "heart-pulse" },
    estacion:      { label: "Estación piloto",      icon: "factory" },
    casos:         { label: "Casos",                icon: "folder-open",         permiso: "casos" },
    nodos:         { label: "Nodos",                icon: "activity",            permiso: "nodos" },
    reportes:      { label: "Reportes de la app",   icon: "smartphone",          permiso: "reportes" },
    recoleccion:   { label: "Recolección",          icon: "hard-drive-download", permiso: "recoleccion" },
    prediccion:    { label: "Predicción",           icon: "trending-up",         permiso: "prediccion" },
    transparencia: { label: "Transparencia",        icon: "scale" },
    informes:      { label: "Informes y descargas", icon: "file-down" },
    red:           { label: "Red de nodos",         icon: "network",             permiso: "config" },
    usuarios:      { label: "Usuarios",             icon: "users",               permiso: "usuarios" },
    config:        { label: "Configuración y demo", icon: "sliders-horizontal",  permiso: "config" }
  },
  // App ciudadana: con servidor vive en /app/; sin servidor, en la carpeta vecina
  appCiudadana: location.protocol === "file:" ? "../app-ciudadana/index.html" : "/app/"
};
// Orden plano de las vistas (rutas y permisos), sacado de los grupos del menú
VA.config.navOrder = VA.config.navGroups.flatMap(g => g.items);
