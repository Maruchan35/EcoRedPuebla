/* =========================================================
   Datos de demostración (sin servidor).
   Nodos, cauce y barreras salen de js/cauce.js: el cauce real
   del Atoyac (OpenStreetMap), igual que en el servidor.
   ========================================================= */
(function () {
  // Generador pseudoaleatorio con semilla: la demo se ve igual cada vez
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rnd = mulberry32(20261123);
  const gauss = () => { let u = 0, v = 0; while (!u) u = rnd(); while (!v) v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  const now = Date.now();
  const H = 3600 * 1000, D = 24 * H;

  // ---------- Nodos (ordenados de aguas arriba a aguas abajo, cada uno sobre un puente del Atoyac) ----------
  const G = VA.cauce;
  const at = id => ({ lat: G.nodos[id][0], lng: G.nodos[id][1] });
  const nodes = [
    { id: "N1", name: "San Martín Texmelucan · puente MEX 117", ...at("N1"), battery: 92, signal: -88, calibrated: now - 6 * D, tec: "TecNM San Martín Texmelucan",
      base: { ph: 7.4, cond: 650, turb: 35, color: 1.6, temp: 17.5, nivel: 0.9 } },
    { id: "N2", name: "Huejotzingo · puente Atoyac", ...at("N2"), battery: 81, signal: -95, calibrated: now - 9 * D, tec: "TecNM San Martín Texmelucan",
      base: { ph: 7.3, cond: 780, turb: 42, color: 2.0, temp: 17.9, nivel: 1.0 } },
    { id: "N3", name: "San Miguel Xoxtla · puente", ...at("N3"), battery: 74, signal: -101, calibrated: now - 12 * D, tec: "TecNM Puebla",
      base: { ph: 7.2, cond: 980, turb: 55, color: 3.4, temp: 18.4, nivel: 1.1 } },
    { id: "N4", name: "Cuautlancingo · autopista México–Puebla", ...at("N4"), battery: 18, signal: -104, calibrated: now - 27 * D, tec: "TecNM Puebla",
      base: { ph: 7.1, cond: 1100, turb: 60, color: 3.5, temp: 18.8, nivel: 1.2 } },
    { id: "N5", name: "Puebla capital · Vía Atlixcáyotl", ...at("N5"), battery: 88, signal: -90, calibrated: now - 4 * D, tec: "Instituto Tecnológico de Puebla",
      base: { ph: 7.2, cond: 1150, turb: 70, color: 2.2, temp: 19.1, nivel: 1.3 } },
    { id: "N6", name: "Entrada a Valsequillo", ...at("N6"), battery: 95, signal: -86, calibrated: now - 2 * D, tec: "Instituto Tecnológico de Puebla",
      base: { ph: 7.5, cond: 1200, turb: 50, color: 2.0, temp: 19.6, nivel: 1.4 } }
  ];

  // ---------- Tramos entre nodos: siguen el cauce real ----------
  const kmEntre = (a, b) => {
    const r = Math.PI / 180, dLat = (b[0] - a[0]) * r, dLng = (b[1] - a[1]) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLng / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.sqrt(h));
  };
  const tramos = G.tramos.map((pts, i) => {
    const km = pts.slice(1).reduce((s, p, k) => s + kmEntre(pts[k], p), 0), V = VA.config.rio;
    return { id: "T" + (i + 1), from: nodes[i].id, to: nodes[i + 1].id, points: pts,
      name: nodes[i].name.split(" · ")[0] + " → " + nodes[i + 1].name.split(" · ")[0],
      km: +km.toFixed(1), transitH: [+(km * 1000 / V.velMax / 3600).toFixed(2), +(km * 1000 / V.velMin / 3600).toFixed(1)] };
  });
  // Punto del cauce a cierta fracción del largo de un tramo (0 = nodo de arriba, 1 = nodo de abajo)
  function enTramo(i, f) {
    const p = tramos[i].points, len = [];
    for (let k = 0; k < p.length - 1; k++) len.push(Math.hypot(p[k + 1][0] - p[k][0], (p[k + 1][1] - p[k][1]) * Math.cos(p[k][0] * Math.PI / 180)));
    let meta = len.reduce((a, b) => a + b, 0) * f;
    for (let k = 0; k < len.length; k++) {
      if (meta <= len[k] && len[k] > 0) { const t = meta / len[k]; return [p[k][0] + t * (p[k + 1][0] - p[k][0]), p[k][1] + t * (p[k + 1][1] - p[k][1])]; }
      meta -= len[k];
    }
    return p[p.length - 1];
  }

  // ---------- Barreras sobre barrancas de la capital ----------
  const bat = id => ({ lat: G.barreras[id][0], lng: G.barreras[id][1] });
  const barriers = [
    { id: "B1", name: "Barranca Xaltonac", ...bat("B1"), fill: 46, nivel: 0.6, nivelMax: 2.2, lastEmptied: now - 2 * D },
    { id: "B2", name: "Río Alseseca", ...bat("B2"), fill: 81, nivel: 0.9, nivelMax: 2.5, lastEmptied: now - 5 * D },
    { id: "B3", name: "Barranca del Conde", ...bat("B3"), fill: 28, nivel: 0.5, nivelMax: 2.0, lastEmptied: now - 1 * D }
  ];

  // ---------- Historial de telemetría (lecturas cada 3 s en la demo) ----------
  const history = {};
  nodes.forEach(n => {
    const arr = [];
    for (let i = 47; i >= 0; i--) {
      const b = n.base;
      arr.push({
        t: now - i * VA.config.telemetryIntervalMs,
        ph: +(b.ph + gauss() * 0.06).toFixed(2),
        cond: Math.round(b.cond + gauss() * b.cond * 0.025),
        turb: Math.max(1, Math.round(b.turb + gauss() * b.turb * 0.06)),
        color: +Math.max(0.2, b.color + gauss() * 0.12).toFixed(2),
        temp: +(b.temp + gauss() * 0.15).toFixed(1),
        nivel: +(b.nivel + gauss() * 0.02).toFixed(2)
      });
    }
    history[n.id] = arr;
  });

  // ---------- Reportes de la app ciudadana ----------
  const categorias = ["Agua de color", "Espuma", "Basura", "Descarga de tubería", "Mal olor", "Animal muerto"];
  const estadosRep = ["Recibido", "Validado", "En atención", "Atendido"];
  // En la orilla del río (a unas decenas de metros del cauce) o junto a una barrera
  const pick = arr => arr[Math.floor(rnd() * arr.length)];
  const reports = [];
  for (let i = 0; i < 34; i++) {
    const nearBarrier = rnd() < 0.25;
    const a = nearBarrier ? (b => [b.lat, b.lng])(pick(barriers)) : pick(pick(tramos).points);
    let cat = categorias[Math.floor(rnd() * categorias.length)];
    if (nearBarrier && rnd() < 0.7) cat = "Basura";
    const st = estadosRep[Math.floor(rnd() * estadosRep.length)];
    reports.push({
      id: "R-" + String(1201 + i),
      cat,
      ai: { label: cat, conf: +(0.72 + rnd() * 0.26).toFixed(2) },
      lat: a[0] + (rnd() - 0.5) * 0.0012,
      lng: a[1] + (rnd() - 0.5) * 0.0012,
      t: now - Math.floor(rnd() * 7 * D),
      status: st,
      anonymous: rnd() < 0.35,
      voice: rnd() < 0.2,
      text: {
        "Agua de color": "El agua bajó azul oscuro y con olor a químico.",
        "Espuma": "Mucha espuma blanca junto al puente.",
        "Basura": "Bolsas, llantas y plástico atorados en la orilla.",
        "Descarga de tubería": "Un tubo descarga agua gris directo al río.",
        "Mal olor": "Olor muy fuerte desde la mañana.",
        "Animal muerto": "Hay peces muertos en la orilla."
      }[cat]
    });
  }
  // Dos reportes recientes en el tramo que llega a Xoxtla (sirven para la fusión en la demo)
  const [r40, r41] = [enTramo(1, 0.75), enTramo(1, 0.97)];
  reports.push({ id: "R-1240", cat: "Agua de color", ai: { label: "Agua de color", conf: 0.94 }, lat: r40[0], lng: r40[1], t: now - 40 * 60 * 1000, status: "Recibido", anonymous: false, voice: true, text: "Nota de voz: «el río viene azul, como tinta, desde hace rato»." });
  reports.push({ id: "R-1241", cat: "Espuma", ai: { label: "Espuma", conf: 0.88 }, lat: r41[0], lng: r41[1], t: now - 25 * 60 * 1000, status: "Recibido", anonymous: true, voice: false, text: "Espuma y agua oscura bajo el puente." });
  reports.sort((x, y) => y.t - x.t);

  // ---------- Casos ----------
  const ev = (dt, who, what) => ({ t: now - dt, who, what });
  const ll = p => ({ lat: p[0], lng: p[1] });
  const cases = [
    { id: "VA-2026-0007", type: "descarga", dep: "ambiental", status: "En atención", priority: "Alta", t: now - 20 * H, tramo: "T5", node: "N6",
      ...ll(enTramo(4, 0.5)), estimate: "Doméstica", confidence: 0.78, sample: "M-0019",
      summary: "Turbidez 3.4 veces arriba de lo normal y baja de color en el nodo de Valsequillo; el nodo de Puebla sur sin cambios.",
      reports: ["R-1203", "R-1219"], peak: { turb: 238, cond: 1420, color: 2.4, ph: 7.0 },
      timeline: [ev(20 * H, "Sistema", "Anomalía detectada en N6; muestra M-0019 tomada"), ev(19 * H, "Sistema", "Caso asignado a Autoridad ambiental"), ev(6 * H, "Autoridad ambiental", "En atención: se solicita inspección del colector")] },
    { id: "VA-2026-0006", type: "basura", dep: "limpia", status: "Nuevo", priority: "Media", t: now - 9 * H, barrier: null,
      ...ll(enTramo(3, 0.06)), estimate: "Residuo sólido", confidence: 0.86, summary: "Cinco reportes con foto de basura acumulada en la orilla, bajo el puente de la autopista México–Puebla.",
      reports: ["R-1207", "R-1212", "R-1222"], timeline: [ev(9 * H, "Sistema", "Agrupamiento de reportes; caso asignado a Limpia municipal")] },
    { id: "VA-2026-0005", type: "recurrente", dep: "brigadas", status: "Nuevo", priority: "Media", t: now - 30 * H,
      ...ll(enTramo(1, 0.85)), estimate: "Basura y espuma recurrentes", confidence: 0.8, summary: "Zona con reportes repetidos en las últimas tres semanas. Se propone jornada de limpieza.",
      reports: ["R-1205"], timeline: [ev(30 * H, "Sistema", "Punto crítico recurrente detectado; propuesta de jornada ciudadana")] },
    { id: "VA-2026-0002", type: "basura", dep: "limpia", status: "En atención", priority: "Alta", t: now - 2 * D, barrier: "B2",
      ...bat("B2"), estimate: "Barrera llena", confidence: 0.97, summary: "La barrera del río Alseseca llegó a 92% de llenado.",
      reports: [], timeline: [ev(2 * D, "Barrera B2", "Llenado 92%"), ev(2 * D - 2 * H, "Limpia municipal", "Cuadrilla asignada, ruta enviada")] },
    { id: "VA-2026-0001", type: "descarga", dep: "ambiental", status: "Inspección programada", priority: "Alta", t: now - 3 * D, tramo: "T2", node: "N3",
      ...ll(enTramo(1, 0.5)), estimate: "Textil", confidence: 0.91, sample: "M-0011",
      summary: "Color a 620 nm 3 veces arriba de lo normal y conductividad de 2,650 µS/cm en Xoxtla; el nodo de Huejotzingo sin cambios. Coincide con 3 reportes de agua azul.",
      reports: ["R-1201", "R-1214", "R-1226"], peak: { color: 7.8, cond: 2650, ph: 9.3, turb: 88 },
      timeline: [ev(3 * D, "Sistema", "Anomalía detectada en N3; muestra M-0011 tomada"), ev(3 * D - 10 * 60 * 1000, "Sistema", "Confianza alta por 3 reportes cercanos; caso asignado"), ev(2 * D, "Autoridad ambiental", "Inspección programada al tramo Huejotzingo → Xoxtla")] },
    { id: "VA-2026-0004", type: "descarga", dep: "ambiental", status: "Cerrado", priority: "Alta", t: now - 9 * D, tramo: "T4", node: "N5", closedAt: now - 6.5 * D,
      ...ll(enTramo(3, 0.5)), estimate: "Otra (industrial)", confidence: 0.74, sample: "M-0007", lab: "DQO 410 mg/L; fuera de norma. Se clausuró la descarga.",
      summary: "pH 5.6 y conductividad alta en Puebla sur.", reports: [], peak: { ph: 5.6, cond: 2310, color: 2.1, turb: 95 },
      timeline: [ev(9 * D, "Sistema", "Anomalía detectada en N5"), ev(8 * D, "Autoridad ambiental", "Inspección realizada"), ev(6.5 * D, "Autoridad ambiental", "Laboratorio confirma; caso cerrado")] },
    { id: "VA-2026-0003", type: "inundacion", dep: "pc", status: "Cerrado", priority: "Alta", t: now - 12 * D, barrier: "B3", closedAt: now - 11.8 * D,
      ...bat("B3"), estimate: "Nivel alto", confidence: 0.95, summary: "El nivel en la barranca del Conde llegó a 1.9 m con lluvia fuerte.",
      reports: [], timeline: [ev(12 * D, "Barrera B3", "Nivel 1.9 m"), ev(12 * D - 5 * 60 * 1000, "Protección Civil", "Alerta enviada a 214 vecinos suscritos"), ev(11.8 * D, "Protección Civil", "Nivel normalizado; caso cerrado")] },
    { id: "VA-2026-0008", type: "basura", dep: "limpia", status: "Cerrado", priority: "Media", t: now - 6 * D, barrier: "B1", closedAt: now - 5.6 * D,
      ...bat("B1"), estimate: "Barrera llena", confidence: 0.96, summary: "Barrera de Xaltonac al 88%. Se retiraron 140 kg.", reports: [],
      timeline: [ev(6 * D, "Barrera B1", "Llenado 88%"), ev(5.6 * D, "Limpia municipal", "Recolección: 140 kg; caso cerrado")] }
  ];

  // ---------- Índice diario de calidad por tramo (0 = muy mala, 100 = buena) ----------
  const dailyIndex = {};
  // [inicio, a la mitad, final] de los últimos 20 días; T3 empeora en los últimos 10
  const shape = { T1: [80, 79, 78], T2: [66, 63, 60], T3: [58, 54, 44], T4: [71, 70, 69], T5: [73, 72, 71] };
  tramos.forEach(t => {
    const [a, b, c] = shape[t.id], arr = [];
    for (let i = 0; i < 20; i++) {
      const base = i < 10 ? a + (b - a) * i / 9 : b + (c - b) * (i - 10) / 9;
      arr.push({ t: now - (20 - i) * D, v: Math.round(base + gauss() * 1.2) });
    }
    dailyIndex[t.id] = arr;
  });

  VA.data = { nodes, tramos, barriers, history, reports, cases, dailyIndex, categorias, rnd, gauss };
})();
