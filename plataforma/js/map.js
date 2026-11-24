/* =========================================================
   Mapa (Leaflet): tramos con semáforo, nodos, barreras,
   reportes ciudadanos y mapa de calor.
   ========================================================= */
(function () {
  const { esc, fmt, badge } = VA.ui;
  const colors = { ok: "#15803D", warn: "#D97706", crit: "#DC2626", off: "#64748B" };
  const CENTER = [19.12, -98.29];

  const lastOf = id => { const h = VA.store.history[id]; return h && h.length ? h[h.length - 1] : null; };
  // Sin internet en el río: si Protección Civil no ha descargado el nodo en varios días, sus datos ya no describen el presente
  const isStale = n => !!n.lastSync && Date.now() - n.lastSync > VA.config.staleDays * 86400000;
  function nodeStatus(n) { const r = lastOf(n.id); return !r || isStale(n) ? "off" : VA.engine.readingStatus(r); }
  function tramoStatus(t) { const n = VA.store.nodes.find(n => n.id === t.to); return n ? nodeStatus(n) : "off"; }
  function barrierStatus(b) {
    if (b.nivel >= b.nivelMax * 0.85 || b.fill >= 90) return "crit";
    if (b.nivel >= b.nivelMax * 0.6 || b.fill >= 70) return "warn";
    return "ok";
  }

  function nodePopup(n) {
    const r = lastOf(n.id), s = nodeStatus(n);
    const canOpen = VA.config.roles[VA.state.role].nav.includes("nodos");
    return `<strong>${esc(n.id)} · ${esc(n.name)}</strong><br>${badge(s)}<br>` + (r ? `
      pH ${fmt.num(r.ph, 2)} · Cond. ${fmt.num(r.cond)} µS/cm<br>
      Turbidez ${fmt.num(r.turb)} NTU · Color ${fmt.num(r.color, 1)} m⁻¹<br>
      Nivel ${fmt.num(r.nivel, 2)} m<br>` : "Todavía no hay lecturas de este nodo.<br>") +
      (n.lastSync ? `<span class="muted">Datos de la visita de ${fmt.ago(n.lastSync)}</span><br>` : "") +
      (canOpen ? `<a href="#/nodos/${n.id}">Ver lecturas</a>` : "");
  }
  function barrierPopup(b) {
    return `<strong>${esc(b.id)} · ${esc(b.name)}</strong><br>${badge(barrierStatus(b))}<br>
      Llenado ${fmt.num(b.fill)}% · Nivel ${fmt.num(b.nivel, 2)} m<br>Último vaciado ${fmt.ago(b.lastEmptied)}`;
  }
  function reportPopup(r) {
    return `<strong>${esc(r.cat)}</strong> · ${esc(r.id)}<br>${r.text ? esc(r.text) + "<br>" : ""}
      <span class="muted">${fmt.ago(r.t)} · ${esc(r.status)}${r.anonymous ? " · anónimo" : ""}</span>`;
  }

  // Crea un mapa en el contenedor. opts: {heat, reports, days, interactive}
  function create(el, opts = {}) {
    const map = L.map(el, { zoomControl: true, scrollWheelZoom: opts.scroll !== false }).setView(CENTER, 11);
    // Encuadre automático con todos los nodos y barreras
    const bounds = L.latLngBounds([...VA.store.nodes, ...VA.store.barriers].map(p => [p.lat, p.lng]));
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 18, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
    }).addTo(map);

    const groups = { tramos: L.layerGroup().addTo(map), nodos: L.layerGroup().addTo(map), barreras: L.layerGroup().addTo(map),
      reportes: L.layerGroup(), calor: null };
    const refs = { tramos: {}, nodos: {}, barreras: {} };

    // Tramos: línea con color + etiqueta de texto (no solo color)
    VA.store.tramos.forEach(t => {
      const s = tramoStatus(t);
      const line = L.polyline(t.points, { color: colors[s], weight: 7, opacity: 0.85 }).addTo(groups.tramos);
      line.bindTooltip(`${t.id} · ${VA.engine.semLabel[s]}`, { permanent: !!opts.tramoLabels, direction: "center", className: "tramo-label" });
      line.bindPopup(`<strong>${esc(t.id)} · ${esc(t.name)}</strong><br>${badge(s)}`);
      refs.tramos[t.id] = line;
    });
    // Nodos
    VA.store.nodes.forEach(n => {
      const m = L.marker([n.lat, n.lng], { icon: nodeIcon(n), title: `${n.id} ${n.name}`, keyboard: true, riseOnHover: true }).addTo(groups.nodos);
      m.bindPopup(() => nodePopup(n));
      refs.nodos[n.id] = m;
    });
    // Barreras
    VA.store.barriers.forEach(b => {
      const m = L.marker([b.lat, b.lng], { icon: barrierIcon(b), title: `${b.id} ${b.name}`, keyboard: true }).addTo(groups.barreras);
      m.bindPopup(() => barrierPopup(b));
      refs.barreras[b.id] = m;
    });

    const api = { map, groups, refs, days: opts.days || 7 };
    api.setReports = function (show) {
      groups.reportes.clearLayers();
      if (!show) { map.removeLayer(groups.reportes); return; }
      const since = Date.now() - api.days * 86400000;
      VA.store.reports.filter(r => r.t >= since).forEach(r => {
        L.marker([r.lat, r.lng], { icon: L.divIcon({ className: "", html: '<div class="report-pin"></div>', iconSize: [14, 14] }), title: r.cat, keyboard: true })
          .bindPopup(reportPopup(r)).addTo(groups.reportes);
      });
      groups.reportes.addTo(map);
    };
    api.setHeat = function (show) {
      if (groups.calor) { map.removeLayer(groups.calor); groups.calor = null; }
      if (!show || !L.heatLayer) return;
      const since = Date.now() - api.days * 86400000;
      const pts = VA.store.reports.filter(r => r.t >= since).map(r => [r.lat, r.lng, 0.6]);
      VA.store.nodes.forEach(n => { const s = nodeStatus(n); if (s === "warn" || s === "crit") pts.push([n.lat, n.lng, s === "crit" ? 1 : 0.7]); });
      VA.store.barriers.forEach(b => { const s = barrierStatus(b); if (s !== "ok") pts.push([b.lat, b.lng, s === "crit" ? 1 : 0.6]); });
      groups.calor = L.heatLayer(pts, { radius: 28, blur: 22, maxZoom: 14, minOpacity: 0.35,
        gradient: { 0.25: "#1D4ED8", 0.5: "#22C55E", 0.75: "#F59E0B", 1: "#DC2626" } }).addTo(map);
    };
    api.setLayer = function (name, show) {
      if (name === "reportes") return api.setReports(show);
      if (name === "calor") return api.setHeat(show);
      if (show) groups[name].addTo(map); else map.removeLayer(groups[name]);
    };
    // Refresca colores sin recrear el mapa (se llama con cada lectura)
    api.update = function () {
      VA.store.tramos.forEach(t => { const s = tramoStatus(t); refs.tramos[t.id].setStyle({ color: colors[s] }); refs.tramos[t.id].setTooltipContent(`${t.id} · ${VA.engine.semLabel[s]}`); });
      VA.store.nodes.forEach(n => refs.nodos[n.id].setIcon(nodeIcon(n)));
      VA.store.barriers.forEach(b => refs.barreras[b.id].setIcon(barrierIcon(b)));
    };
    api.focus = (lat, lng, z = 14) => map.setView([lat, lng], z);

    if (opts.reports) api.setReports(true);
    if (opts.heat) api.setHeat(true);
    // Si la vista cambia antes de 50 ms (por ejemplo al reiniciar la demo), el mapa ya no existe
    let alive = true;
    map.on("unload", () => { alive = false; });
    setTimeout(() => { if (!alive) return; map.invalidateSize(); if (bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30], animate: false }); }, 50);
    return api;
  }

  function nodeIcon(n) {
    const s = nodeStatus(n);
    return L.divIcon({ className: "", iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -14],
      html: `<div class="node-pin ${s}" aria-hidden="true">${n.id}</div>` });
  }
  function barrierIcon(b) {
    const s = barrierStatus(b);
    return L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -12],
      html: `<div class="square-pin ${s}" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg></div>` });
  }

  VA.map = { create, nodeStatus, tramoStatus, barrierStatus, isStale, lastOf, colors };
})();
