/* =========================================================
   Motor de reglas e IA (versión ligera en el navegador).
   Con servidor, el análisis oficial lo hace server/motor.py al subir cada lote;
   aquí queda el semáforo, el pronóstico y la demo sin servidor:
   - semáforo por umbrales
   - anomalías con z-score robusto (mediana y MAD)
   - huella del tipo de descarga
   - localización por nodos aguas arriba / aguas abajo
   - fusión con reportes ciudadanos
   - pronóstico simple con banda de confianza
   ========================================================= */
(function () {
  const P = () => VA.config.params;

  // ---------- Estadística básica ----------
  const median = a => { const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const mad = a => { const m = median(a); return median(a.map(x => Math.abs(x - m))); };
  function robustZ(series, x) {
    const m = median(series), d = mad(series) || 1e-6;
    return 0.6745 * (x - m) / d;
  }

  // ---------- Semáforo por umbrales ----------
  function paramStatus(key, v) {
    const p = P()[key];
    if (v == null || !p) return "ok";
    if (key === "ph") {
      if (v < p.critMin || v > p.critMax) return "crit";
      if (v < p.min || v > p.max) return "warn";
      return "ok";
    }
    if (v >= p.crit) return "crit";
    if (v >= p.warn) return "warn";
    return "ok";
  }
  const rank = { ok: 0, warn: 1, crit: 2, off: -1 };
  const worst = list => list.reduce((w, s) => (rank[s] > rank[w] ? s : w), "ok");
  function readingStatus(r) { return worst(Object.keys(P()).map(k => paramStatus(k, r[k]))); }

  // ---------- Anomalías (z-score robusto sobre la ventana reciente) ----------
  function detectAnomalies(hist, reading) {
    const win = hist.slice(-VA.config.anomalyWindow - 1, -1);
    if (win.length < 12) return [];
    const out = [];
    Object.entries(P()).forEach(([k, p]) => {
      if (!p.anomaly) return;
      const series = win.map(r => r[k]);
      const z = robustZ(series, reading[k]);
      // Además del z-score se pide un cambio real (evita alarmas por ruido del sensor)
      const m = median(series), diff = Math.abs(reading[k] - m);
      const bigEnough = k === "ph" ? diff >= 0.5 : diff >= Math.abs(m) * (k === "cond" ? 0.2 : 0.4);
      if (Math.abs(z) >= VA.config.anomalyZ && bigEnough) out.push({ param: k, z: +z.toFixed(1), value: reading[k] });
    });
    return out;
  }

  // ---------- Huella: tipo probable de descarga ----------
  function classifyDischarge(reading, base) {
    const color = reading.color / base.color, cond = reading.cond / base.cond, turb = reading.turb / base.turb;
    if (color >= 2 && (cond >= 1.5 || reading.ph > 8.8)) return { label: "Textil", why: "Color y conductividad altos a la vez (tintes y sales)." };
    if (turb >= 2 && color < 1.6) return { label: "Doméstica", why: "Sube la turbidez sin cambio fuerte de color." };
    return { label: "Otra (industrial)", why: "Cambio de pH o conductividad sin patrón textil ni doméstico." };
  }

  // ---------- Localización: ¿en qué tramo entró la descarga? ----------
  function localize(nodeId, anomalousIds) {
    const nodes = VA.store.nodes;
    const i = nodes.findIndex(n => n.id === nodeId);
    if (i <= 0) return { tramo: null, text: "Antes del primer nodo (aguas arriba de " + nodes[0].name + ")" };
    let j = i;
    while (j > 0 && anomalousIds.has(nodes[j - 1].id)) j--;
    if (j === 0) return { tramo: null, text: "Aguas arriba de " + nodes[0].name };
    const t = VA.store.tramos[j - 1];
    return { tramo: t.id, text: "Entre " + nodes[j - 1].name + " y " + nodes[j].name };
  }

  // ---------- Distancia y fusión con reportes ciudadanos ----------
  function km(aLat, aLng, bLat, bLng) {
    const R = 6371, toR = x => x * Math.PI / 180;
    const dLat = toR(bLat - aLat), dLng = toR(bLng - aLng);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(toR(aLat)) * Math.cos(toR(bLat)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  const relevant = new Set(["Agua de color", "Espuma", "Descarga de tubería", "Mal olor", "Animal muerto"]);
  function fuseReports(lat, lng, reports, nowMs) {
    const near = reports.filter(r => relevant.has(r.cat)
      && nowMs - r.t <= VA.config.fusionWindowH * 3600 * 1000
      && km(lat, lng, r.lat, r.lng) <= VA.config.fusionRadiusKm);
    return near;
  }
  function confidence(anomalies, nearReports) {
    let c = 0.5 + 0.1 * Math.min(anomalies.length, 3) + 0.1 * Math.min(nearReports.length, 3);
    return Math.min(0.97, +c.toFixed(2));
  }

  // ---------- Índice de calidad y pronóstico ----------
  function indexStatus(v) { return v >= 70 ? "ok" : v >= 40 ? "warn" : "crit"; }
  function forecast(series, days) {
    const last = series.slice(-10).map(p => p.v);
    const n = last.length, xs = last.map((_, i) => i);
    const mx = xs.reduce((a, b) => a + b, 0) / n, my = last.reduce((a, b) => a + b, 0) / n;
    const slope = xs.reduce((s, x, i) => s + (x - mx) * (last[i] - my), 0) / xs.reduce((s, x) => s + (x - mx) ** 2, 0);
    const icpt = my - slope * mx;
    const resid = last.map((y, i) => y - (icpt + slope * i));
    const sd = Math.sqrt(resid.reduce((s, r) => s + r * r, 0) / Math.max(1, n - 2)) || 2;
    const out = [];
    const t0 = series[series.length - 1].t;
    for (let h = 1; h <= days; h++) {
      const y = icpt + slope * (n - 1 + h);
      const band = 1.96 * sd * Math.sqrt(1 + h / 3);
      out.push({ t: t0 + h * 86400000, v: Math.round(Math.max(0, Math.min(100, y))),
        lo: Math.round(Math.max(0, y - band)), hi: Math.round(Math.min(100, y + band)) });
    }
    return { points: out, slope: +slope.toFixed(2) };
  }

  const semLabel = { ok: "Bien", warn: "Atención", crit: "Crítico", off: "Sin datos" };
  const semIcon = { ok: "circle-check", warn: "triangle-alert", crit: "octagon-alert", off: "wifi-off" };

  VA.engine = { median, mad, robustZ, paramStatus, readingStatus, worst, detectAnomalies, classifyDischarge,
    localize, km, fuseReports, confidence, indexStatus, forecast, semLabel, semIcon };
})();
