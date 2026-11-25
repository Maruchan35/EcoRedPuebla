/* =========================================================
   Gráficas (Chart.js). Reglas: nunca solo color (línea sólida =
   medido, punteada = pronóstico o salida tratada), umbrales
   rotulados y una tabla o texto equivalente en cada vista.
   ========================================================= */
(function () {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  Chart.defaults.font.family = '"Source Sans 3", system-ui, sans-serif';
  Chart.defaults.font.size = 13;
  Chart.defaults.color = "#475569";
  Chart.defaults.borderColor = "#E2E8F0";
  Chart.defaults.animation = reduced ? false : { duration: 250 };
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.tooltip.backgroundColor = "#0F172A";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;

  const ACCENT = "#0369A1", WATER = "#0E7490", ANOM = "#DC2626", WARN = "#D97706", FC = "#B45309", OK = "#15803D", SLATE = "#64748B";
  const fmt = () => VA.ui.fmt;
  // Eje de tiempo compacto: el eje dice solo el día y la ventana emergente la fecha y hora completas
  function ejeTiempo(puntos, { porDia = false } = {}) {
    const ts = puntos.map(x => x.t);
    return {
      labels: ts,
      x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, callback: (v, i) => fmt().day(ts[i]) } },
      title: items => (porDia ? fmt().day : fmt().date)(ts[items[0].dataIndex])
    };
  }

  // ---------- Telemetría de un parámetro (lecturas crudas de la última descarga) ----------
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
      const label = span > 20 * 3600000 ? fmt().date : span > 10 * 60000 ? fmt().hm : fmt().time;
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

  // ---------- Serie de días u horas (medianas del servidor) con umbral y horas con anomalía ----------
  function series(canvas, puntos, key, { porDia = false } = {}) {
    const p = VA.config.params[key];
    const thr = key === "ph" ? p.max : p.warn, crit = key === "ph" ? p.critMax : p.crit;
    const eje = ejeTiempo(puntos, { porDia });
    return new Chart(canvas, {
      type: "line",
      data: { labels: eje.labels, datasets: [
        { label: `${p.label}${p.unit ? " (" + p.unit + ")" : ""} · mediana ${porDia ? "diaria" : "por hora"}`, data: puntos.map(x => x[key] ?? null),
          borderColor: WATER, backgroundColor: "rgba(14,116,144,.08)", fill: true, tension: 0.3, borderWidth: 2, spanGaps: false,
          pointRadius: puntos.map(x => (x.anom ? 5 : 0)), pointStyle: "triangle", pointBackgroundColor: ANOM, pointBorderColor: "#fff" },
        { label: key === "ph" ? `Máximo normal (${thr})` : `Umbral de atención (${thr})`, data: puntos.map(() => thr), borderColor: WARN, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 },
        { label: key === "ph" ? `Crítico (${crit})` : `Crítico (${crit})`, data: puntos.map(() => crit), borderColor: ANOM, borderDash: [2, 4], borderWidth: 1.5, pointRadius: 0 }
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: eje.x, y: { title: { display: true, text: p.unit || p.label } } },
        plugins: { legend: { position: "bottom" },
          tooltip: { callbacks: { title: eje.title, afterBody: it => { const x = puntos[it[0].dataIndex]; return x && x.anom ? `${x.anom} lectura(s) con anomalía` : ""; } } } }
      }
    });
  }

  // ---------- Perfil del río: cómo cambia un parámetro de nodo en nodo, río abajo ----------
  function profile(canvas, nodos, key, { umbral, critico, etiqueta, unidad, dec = 0 } = {}) {
    return new Chart(canvas, {
      type: "line",
      data: { labels: nodos.map(n => [n.id, `km ${fmt().num(n.km, 0)}`]), datasets: [
        { label: etiqueta, data: nodos.map(n => n.v), borderColor: ACCENT, backgroundColor: "rgba(3,105,161,.1)", fill: true, tension: 0.25, borderWidth: 2.5,
          pointRadius: 6, pointHoverRadius: 8, pointBackgroundColor: nodos.map(n => VA.map.colors[n.s] || SLATE), pointBorderColor: "#fff", pointBorderWidth: 2,
          segment: { borderDash: ctx => (nodos[ctx.p1DataIndex] && nodos[ctx.p1DataIndex].s === "off" ? [5, 5] : undefined) } },
        ...(umbral != null ? [{ label: `Atención (${fmt().num(umbral, dec)})`, data: nodos.map(() => umbral), borderColor: WARN, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 }] : []),
        ...(critico != null ? [{ label: `Crítico (${fmt().num(critico, dec)})`, data: nodos.map(() => critico), borderColor: ANOM, borderDash: [2, 4], borderWidth: 1.5, pointRadius: 0 }] : [])
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: { grid: { display: false }, ticks: { autoSkip: false, maxRotation: 0, font: { size: 12 } } },
          y: { beginAtZero: key !== "ph", title: { display: true, text: unidad || etiqueta } } },
        plugins: { legend: { position: "bottom" },
          tooltip: { callbacks: { label: c => c.datasetIndex === 0 ? ` ${nodos[c.dataIndex].name}: ${fmt().num(c.raw, dec)} ${unidad || ""}${nodos[c.dataIndex].s === "off" ? " (dato viejo)" : ""}` : ` ${c.dataset.label}` } } }
      }
    });
  }

  // ---------- Estación: entrada (sólida) contra salida tratada (punteada) ----------
  function inOut(canvas, puntos, key, { etiqueta, unidad, dec = 1 } = {}) {
    const sal = key + "_sal", eje = ejeTiempo(puntos);
    return new Chart(canvas, {
      type: "line",
      data: { labels: eje.labels, datasets: [
        { label: `Entrada (río)`, data: puntos.map(x => x[key] ?? null), borderColor: FC, backgroundColor: "rgba(180,83,9,.08)", borderWidth: 2, tension: 0.3, pointRadius: 0, fill: "+1" },
        { label: `Salida tratada`, data: puntos.map(x => x[sal] ?? null), borderColor: OK, borderDash: [6, 4], borderWidth: 2.5, tension: 0.3, pointRadius: 0, fill: false }
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: eje.x, y: { beginAtZero: key !== "ph", title: { display: true, text: unidad ? `${etiqueta} (${unidad})` : etiqueta } } },
        plugins: { legend: { position: "bottom" },
          tooltip: { callbacks: { title: eje.title, label: c => ` ${c.dataset.label}: ${fmt().num(c.raw, dec)} ${unidad || ""}`,
            afterBody: it => { const x = puntos[it[0].dataIndex]; return x && x[key] && x[sal] != null && key !== "ph" ? `Removido: ${fmt().pct(1 - x[sal] / x[key])}` : ""; } } } }
      }
    });
  }

  // ---------- Estación: lodos del sedimentador y presión de filtros (dientes de sierra del mantenimiento) ----------
  function operation(canvas, puntos) {
    const eje = ejeTiempo(puntos);
    return new Chart(canvas, {
      type: "line",
      data: { labels: eje.labels, datasets: [
        { label: "Lodos en el sedimentador (%)", data: puntos.map(x => x.lodos ?? null), borderColor: "#7C3AED", borderWidth: 2, tension: 0.2, pointRadius: 0, yAxisID: "y" },
        { label: "Presión en filtros (kPa)", data: puntos.map(x => x.dp_filtro ?? null), borderColor: ACCENT, borderDash: [5, 3], borderWidth: 2, tension: 0.1, pointRadius: 0, yAxisID: "y2" },
        { label: "Retrolavado (24 kPa)", data: puntos.map(() => 24), borderColor: ANOM, borderDash: [2, 4], borderWidth: 1.2, pointRadius: 0, yAxisID: "y2" }
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: eje.x,
          y: { min: 0, max: 100, title: { display: true, text: "Lodos (%)" } },
          y2: { position: "right", min: 0, max: 30, grid: { drawOnChartArea: false }, title: { display: true, text: "Presión (kPa)" } } },
        plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { title: eje.title } } }
      }
    });
  }

  // ---------- Energía: potencia del panel solar ----------
  function energy(canvas, puntos) {
    const eje = ejeTiempo(puntos);
    return new Chart(canvas, {
      type: "line",
      data: { labels: eje.labels, datasets: [
        { label: "Panel solar (W)", data: puntos.map(x => x.solar ?? null), borderColor: "#CA8A04", backgroundColor: "rgba(234,179,8,.18)", fill: true, borderWidth: 1.5, tension: 0.35, pointRadius: 0 },
        { label: "Caudal tratado (L/s × 100)", data: puntos.map(x => (x.caudal != null ? x.caudal * 100 : null)), borderColor: WATER, borderDash: [4, 3], borderWidth: 1.5, tension: 0.2, pointRadius: 0 }
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: eje.x, y: { min: 0, title: { display: true, text: "W" } } },
        plugins: { legend: { position: "bottom" },
          tooltip: { callbacks: { title: eje.title, label: c => c.datasetIndex === 1 ? ` Caudal: ${fmt().num(c.raw / 100, 2)} L/s` : ` Solar: ${fmt().num(c.raw)} W` } } }
      }
    });
  }

  // ---------- Pronóstico: real (sólida), pronóstico (punteada) y rango probable ----------
  function forecast(canvas, series, fc) {
    const labels = [...series.map(p => fmt().day(p.t)), ...fc.points.map(p => fmt().day(p.t))];
    const n = series.length;
    const pad = Array(n - 1).fill(null);
    const last = series[n - 1].v;
    return new Chart(canvas, {
      type: "line",
      data: { labels, datasets: [
        { label: "Índice medido", data: [...series.map(p => p.v), ...fc.points.map(() => null)], borderColor: ACCENT, borderWidth: 2.5, pointRadius: 2, tension: 0.2 },
        { label: "Pronóstico", data: [...pad, last, ...fc.points.map(p => p.v)], borderColor: FC, borderDash: [7, 5], borderWidth: 2.5, pointRadius: 3, pointStyle: "rectRot", tension: 0.2 },
        { label: "Rango probable (80%)", data: [...pad, last, ...fc.points.map(p => p.hi)], borderColor: "rgba(180,83,9,.25)", borderWidth: 1, pointRadius: 0, fill: "+1", backgroundColor: "rgba(245,158,11,.15)" },
        { label: "Rango bajo", data: [...pad, last, ...fc.points.map(p => p.lo)], borderColor: "rgba(180,83,9,.25)", borderWidth: 1, pointRadius: 0, fill: false },
        { label: "Bien (70)", data: labels.map(() => 70), borderColor: "rgba(21,128,61,.5)", borderDash: [2, 4], borderWidth: 1, pointRadius: 0 },
        { label: "Crítico (40)", data: labels.map(() => 40), borderColor: "rgba(220,38,38,.5)", borderDash: [2, 4], borderWidth: 1, pointRadius: 0 }
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { y: { min: 0, max: 100, title: { display: true, text: "Índice de calidad (0–100)" } }, x: { ticks: { maxTicksLimit: 10 }, grid: { display: false } } },
        plugins: { legend: { position: "bottom", labels: { filter: i => i.text !== "Rango bajo" } } }
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
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${fmt().num(c.raw, 1)} ${unit}` } } },
        scales: { x: { grid: { display: horizontal } }, y: { grid: { display: !horizontal } } }
      }
    });
  }

  // ---------- Línea mínima (sparkline) en SVG: sin ejes, solo la forma de la tendencia ----------
  function spark(values, { w = 120, h = 32, color = ACCENT, area = true } = {}) {
    const v = values.filter(x => x != null && !isNaN(x));
    if (v.length < 2) return "";
    const min = Math.min(...v), max = Math.max(...v), r = max - min || 1;
    const pts = values.map((x, i) => x == null ? null : [i * (w - 4) / (values.length - 1) + 2, h - 3 - (x - min) / r * (h - 6)]).filter(Boolean);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const last = pts[pts.length - 1];
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true" focusable="false">
      ${area ? `<path d="${d} L${last[0].toFixed(1)} ${h} L${pts[0][0].toFixed(1)} ${h} Z" fill="${color}" opacity=".12"/>` : ""}
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.6" fill="${color}"/></svg>`;
  }

  VA.charts = { telemetry, series, profile, inOut, operation, energy, forecast, bars, spark };
})();
