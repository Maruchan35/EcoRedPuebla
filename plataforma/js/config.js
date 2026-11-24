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

  // ---------- Roles: qué menú ve cada quien y qué casos le tocan ----------
  // El servidor decide qué datos entrega a cada rol; aquí solo se arma el menú.
  roles: {
    publico:   { label: "Ciudadanía",          deps: [],                                   nav: ["resumen", "mapa", "transparencia"] },
    ciudadano: { label: "Ciudadanía",          deps: [],                                   nav: ["resumen", "mapa", "transparencia"] },
    ambiental: { label: "Autoridad ambiental", deps: ["ambiental"],                        nav: ["resumen", "mapa", "casos", "nodos", "reportes", "prediccion", "transparencia"] },
    limpia:    { label: "Limpia municipal",    deps: ["limpia", "brigadas"],               nav: ["resumen", "mapa", "casos", "reportes", "transparencia"] },
    pc:        { label: "Protección Civil",    deps: ["pc"],                               nav: ["resumen", "mapa", "casos", "nodos", "recoleccion", "prediccion", "transparencia"] },
    tec:       { label: "Tecnológicos",        deps: [],                                   nav: ["resumen", "mapa", "nodos", "recoleccion", "transparencia"] },
    admin:     { label: "Administración",      deps: ["ambiental", "limpia", "pc", "brigadas"], nav: ["resumen", "mapa", "casos", "nodos", "reportes", "recoleccion", "prediccion", "transparencia", "usuarios", "config"] }
  },
  // Vistas que necesitan el servidor (no aparecen al abrir index.html con doble clic)
  serverOnly: ["recoleccion", "usuarios"],
  // Roles que pueden validar o descartar reportes de la app
  reportEditors: ["ambiental", "limpia", "pc", "admin"],

  nav: {
    resumen:       { label: "Resumen",            icon: "layout-dashboard" },
    mapa:          { label: "Mapa",               icon: "map" },
    casos:         { label: "Casos",              icon: "folder-open" },
    nodos:         { label: "Nodos",              icon: "activity" },
    reportes:      { label: "Reportes de la app", icon: "smartphone" },
    recoleccion:   { label: "Recolección",        icon: "hard-drive-download" },
    prediccion:    { label: "Predicción",         icon: "trending-up" },
    transparencia: { label: "Transparencia",      icon: "scale" },
    usuarios:      { label: "Usuarios",           icon: "users" },
    config:        { label: "Configuración y demo", icon: "sliders-horizontal" }
  }
};
