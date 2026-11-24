/* =========================================================
   Gráficas (Chart.js): telemetría con anomalías marcadas,
   pronóstico con banda de confianza y barras.
   ========================================================= */
(function () {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  Chart.defaults.font.family = '"Source Sans 3", system-ui, sans-serif';
  Chart.defaults.font.size = 13;
  Chart.defaults.color = "#475569";
  Chart.defaults.borderColor = "#E2E8F0";
  Chart.defaults.animation = reduced ? false : { duration: 250 };
  Chart.defaults.plugins.legend.labels.usePointStyle = true;

  const ACCENT = "#0369A1", WATER = "#0E7490", ANOM = "#DC2626", WARN = "#D97706", FC = "#B45309";

  // ---------- Telemetría de un parámetro ----------
  function telemetry(canvas, nodeId, key) {
    const p = VA.config.params[key];
    const hist = () => VA.store.history[nodeId] || [];
    const chart = new Chart(canvas, {
      type: "line",
      data: { labels: [], datasets: [
        { label: p.label + (p.unit ? " (" + p.unit + ")" : ""), data: [], borderColor: WATER, backgroundColor: "rgba(14,116,144,.08)",
          fill: true, tension: 0.25, borderWidth: 2, pointRadius: [], pointStyle: [], pointBackgroundColor: [], pointBorderColor: [] },
        { label: "Umbral de atención", data: [], borderColor: WARN, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, fill: false }
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: { ticks: { maxTicksLimit: 6 }, grid: { display: false } }, y: { title: { display: true, text: p.unit || p.label } } },
        plugins: {
          legend: { position: "bottom", labels: { generateLabels: () => [
            { text: p.label + (p.unit ? " (" + p.unit + ")" : ""), fillStyle: WATER, strokeStyle: WATER, pointStyle: "line", lineWidth: 3 },
            { text: key === "ph" ? "Rango normal (máx. " + p.max + ")" : "Umbral de atención (" + p.warn + ")", fillStyle: WARN, strokeStyle: WARN, pointStyle: "dash", lineWidth: 2 },
            { text: "Anomalía detectada", fillStyle: ANOM, strokeStyle: ANOM, pointStyle: "triangle" }
          ] } },
          tooltip: { callbacks: { afterBody: items => { const r = hist()[items[0].dataIndex + offset()]; return r && r.anom && r.anom.includes(key) ? "Anomalía detectada" : ""; } } }
        }
      }
    });
    function offset() { return Math.max(0, hist().length - 36); }
    function refresh() {
      const h = hist().slice(-36);
      const ds = chart.data.datasets[0];
      // La demo sin servidor manda una lectura cada 3 s; los datos reales van cada 10 min y abarcan horas
      const span = h.length ? h[h.length - 1].t - h[0].t : 0;
      const label = span > 20 * 3600000 ? VA.ui.fmt.date : span > 10 * 60000 ? VA.ui.fmt.hm : VA.ui.fmt.time;
      chart.data.labels = h.map(r => label(r.t));
      ds.data = h.map(r => r[key]);
      ds.pointRadius = h.map(r => (r.anom && r.anom.includes(key) ? 7 : 0));
      ds.pointStyle = h.map(r => (r.anom && r.anom.includes(key) ? "triangle" : "circle"));
      ds.pointBackgroundColor = h.map(() => ANOM);
      ds.pointBorderColor = h.map(() => "#fff");
      const thr = key === "ph" ? p.max : p.warn;
      chart.data.datasets[1].data = h.map(() => thr);
      chart.data.datasets[1].label = key === "ph" ? "Rango normal (máx. " + p.max + ")" : "Umbral de atención (" + p.warn + ")";
      chart.update(reduced ? "none" : undefined);
    }
    refresh();
    return { chart, refresh, destroy: () => chart.destroy() };
  }

  // ---------- Pronóstico: real (sólida), pronóstico (punteada) y banda ----------
  function forecast(canvas, series, fc) {
    const labels = [...series.map(p => VA.ui.fmt.day(p.t)), ...fc.points.map(p => VA.ui.fmt.day(p.t))];
    const n = series.length;
    const pad = Array(n - 1).fill(null);
    const last = series[n - 1].v;
    return new Chart(canvas, {
      type: "line",
      data: { labels, datasets: [
        { label: "Índice real", data: [...series.map(p => p.v), ...fc.points.map(() => null)], borderColor: ACCENT, borderWidth: 2.5, pointRadius: 2, tension: 0.2 },
        { label: "Pronóstico", data: [...pad, last, ...fc.points.map(p => p.v)], borderColor: FC, borderDash: [7, 5], borderWidth: 2.5, pointRadius: 3, pointStyle: "rectRot", tension: 0.2 },
        { label: "Banda alta 95%", data: [...pad, last, ...fc.points.map(p => p.hi)], borderColor: "rgba(180,83,9,.25)", borderWidth: 1, pointRadius: 0, fill: "+1", backgroundColor: "rgba(245,158,11,.15)" },
        { label: "Banda baja 95%", data: [...pad, last, ...fc.points.map(p => p.lo)], borderColor: "rgba(180,83,9,.25)", borderWidth: 1, pointRadius: 0, fill: false }
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { y: { min: 0, max: 100, title: { display: true, text: "Índice de calidad (0–100)" } }, x: { ticks: { maxTicksLimit: 9 }, grid: { display: false } } },
        plugins: { legend: { position: "bottom", labels: { filter: i => !i.text.startsWith("Banda baja") } } }
      }
    });
  }

  // ---------- Barras horizontales ----------
  function bars(canvas, labels, values, { unit = "", color = ACCENT, horizontal = true } = {}) {
    return new Chart(canvas, {
      type: "bar",
      data: { labels, datasets: [{ label: unit, data: values, backgroundColor: color, borderRadius: 4, maxBarThickness: 28 }] },
      options: {
        indexAxis: horizontal ? "y" : "x", responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${VA.ui.fmt.num(c.raw, 1)} ${unit}` } } },
        scales: { x: { grid: { display: horizontal } }, y: { grid: { display: !horizontal } } }
      }
    });
  }

  VA.charts = { telemetry, forecast, bars };
})();
