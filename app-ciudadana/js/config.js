/* =========================================================
   EcoRed Puebla · Configuración y catálogos compartidos
   Alineado a plataforma/server/main.py y plataforma/server/motor.py
   ========================================================= */
export const CONFIG = {
  APP_NAME: "EcoRed Puebla",
  CENTER: [19.12, -98.29],
  DEFAULT_ZOOM: 11,
  // Caja válida en plataforma/server/main.py (AREA)
  AREA: {
    latMin: 17.8,
    latMax: 20.9,
    lngMin: -99.2,
    lngMax: -96.7,
  },
  MAX_FOTO_BYTES: 5 * 1024 * 1024,
  MAP_TILES_URL: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
  MAP_ATTRIBUTION: "Tiles &copy; Esri, HERE, Garmin, OpenStreetMap contributors",
  POLL_NOTIF_MS: 20000,
};

// Categorías exactas aceptadas por POST /api/reportes (motor.CATEGORIAS)
export const CATEGORIAS = [
  {
    id: "Agua de color",
    label: "Agua de color",
    hint: "Tintes textiles, tonos azules, rojos u oscuros",
    icon: "droplets",
    pesoCalor: 1.0,
    dependencia: "Autoridad ambiental",
  },
  {
    id: "Espuma",
    label: "Espuma",
    hint: "Espuma blanca o amarillenta persistente",
    icon: "cloud-rain",
    pesoCalor: 0.85,
    dependencia: "Autoridad ambiental",
  },
  {
    id: "Descarga de tubería",
    label: "Descarga de tubería",
    hint: "Tubo o ducto vertiendo líquido al cauce",
    icon: "pipette",
    pesoCalor: 1.0,
    dependencia: "Autoridad ambiental",
  },
  {
    id: "Basura",
    label: "Basura",
    hint: "Plásticos, llantas, escombro o taponamiento",
    icon: "trash-2",
    pesoCalor: 0.72,
    dependencia: "Limpia municipal",
  },
  {
    id: "Mal olor",
    label: "Mal olor",
    hint: "Olor químico, solvente o drenaje intenso",
    icon: "wind",
    pesoCalor: 0.68,
    dependencia: "Autoridad ambiental",
  },
  {
    id: "Animal muerto",
    label: "Animal muerto",
    hint: "Fauna muerta en orilla, río o barranca",
    icon: "alert-triangle",
    pesoCalor: 0.78,
    dependencia: "Limpia municipal",
  },
];

// Puntos de referencia de la cuenca del Alto Atoyac para pruebas o ajuste rápido
export const REFERENCIAS_CUENCA = [
  { id: "ref-xoxtla", nombre: "Xoxtla (Puente Río Atoyac)", lat: 19.1835, lng: -98.3050 },
  { id: "ref-texmelucan", nombre: "San Martín Texmelucan (Atoyac)", lat: 19.2842, lng: -98.4368 },
  { id: "ref-huejotzingo", nombre: "Huejotzingo (Corredor industrial)", lat: 19.1560, lng: -98.3970 },
  { id: "ref-puebla-poniente", nombre: "Puebla Poniente (Echeverría)", lat: 19.0436, lng: -98.2485 },
  { id: "ref-alseseca", nombre: "Barranca Río Alseseca", lat: 19.0195, lng: -98.1765 },
];

export const SEM_META = {
  ok: { label: "Bien", icon: "check-circle-2", cls: "badge-ok", color: "#15803D" },
  warn: { label: "Atención", icon: "alert-circle", cls: "badge-warn", color: "#B45309" },
  crit: { label: "Crítico", icon: "alert-octagon", cls: "badge-crit", color: "#B91C1C" },
  off: { label: "Sin visita reciente", icon: "help-circle", cls: "badge-off", color: "#475569" },
};

export function estaEnPuebla(lat, lng) {
  return (
    Number.isFinite(lat) &&
    Number.isFinite(lng) &&
    lat >= CONFIG.AREA.latMin &&
    lat <= CONFIG.AREA.latMax &&
    lng >= CONFIG.AREA.lngMin &&
    lng <= CONFIG.AREA.lngMax
  );
}
