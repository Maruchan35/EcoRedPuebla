/* =========================================================
   Mapa 3D (MapLibre GL): relieve real del terreno, tramos con
   semáforo, columnas 3D por nodo y barrera, reportes
   ciudadanos y mapa de calor.

   Todo sin API key: calles de OpenFreeMap, satélite de Esri y
   relieve de Terrain Tiles (AWS). La biblioteca está en vendor/
   (versión CSP: su procesamiento corre en un worker de este mismo
   sitio). Si el equipo no tiene WebGL se usa el mapa plano de
   Leaflet con la misma interfaz:
     create(el, opts) → { map, update, setLayer, setReports, setHeat, focus, days }
   opts: { reports, heat, tramoLabels, scroll, reveal, days }
   ========================================================= */
(function () {
  const { esc, fmt, badge, icon, refreshIcons } = VA.ui;
  const colors = { ok: "#15803D", warn: "#D97706", crit: "#DC2626", off: "#64748B" };
  const CENTER = [19.12, -98.29];
  const reduceMotion = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);

  // ---------- Estado de cada punto (igual en 2D y en 3D) ----------
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
  // Qué tan cerca está la última lectura de su umbral de atención (1 = justo en el umbral; 0 = sin datos al día).
  // Es la altura de la columna 3D de cada nodo: más alta, más contaminación.
  function pressure(n) {
    const r = lastOf(n.id), P = VA.config.params;
    if (!r || isStale(n)) return 0;
    let p = 0;
    ["cond", "turb", "color", "nivel"].forEach(k => { if (r[k] != null && P[k] && P[k].warn) p = Math.max(p, r[k] / P[k].warn); });
    if (r.ph != null) {
      const mid = (P.ph.min + P.ph.max) / 2, half = Math.max(0.1, (P.ph.max - P.ph.min) / 2);
      p = Math.max(p, Math.abs(r.ph - mid) / half);
    }
    return Math.min(p, 3);
  }

  // ---------- Ventanas emergentes ----------
  function nodePopup(n) {
    const r = lastOf(n.id), s = nodeStatus(n);
    const canOpen = !!(VA.can && VA.can("nodos"));
    return `<strong>${esc(n.id)} · ${esc(n.name)}</strong><br>${badge(s)}<br>` + (r ? `
      pH ${fmt.num(r.ph, 2)} · Cond. ${fmt.num(r.cond)} µS/cm<br>
      Turbidez ${fmt.num(r.turb)} NTU · Color ${fmt.num(r.color, 1)} m⁻¹<br>
      Nivel ${fmt.num(r.nivel, 2)} m<br>
      ${s !== "off" ? `<span class="muted">Columna: ${fmt.num(pressure(n), 1)} veces el umbral de atención</span><br>` : ""}` : "Todavía no hay lecturas de este nodo.<br>") +
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
  // Duración legible: "40 min", "2.5 h", "17 h"
  const dur = h => h < 1 ? Math.max(5, Math.round(h * 12) * 5) + " min" : fmt.num(h, h < 10 ? 1 : 0) + " h";
  function tramoPopup(t) {
    return `<strong>${esc(t.id)} · ${esc(t.name)}</strong><br>${badge(tramoStatus(t))}` +
      (t.km ? `<br>${fmt.num(t.km, 1)} km de cauce<br><span class="muted">El agua tarda de ${dur(t.transitH[0])} (crecida) a ${dur(t.transitH[1])} (estiaje) en recorrerlo</span>` : "");
  }

  // =========================================================
  // 3D (MapLibre GL)
  // =========================================================
  const STYLE = "https://tiles.openfreemap.org/styles/positron";
  const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
  // Si no carga el estilo de calles (sin internet), el río, los nodos y las columnas se dibujan sobre un fondo liso
  const FALLBACK = { version: 8, glyphs: GLYPHS, sources: {}, layers: [{ id: "fondo", type: "background", paint: { "background-color": "#EEF2F5" } }] };
  const DEM_TILES = ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"];
  const DEM_ATTR = 'Relieve: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noopener">Terrain Tiles (Mapzen, AWS)</a>';
  const SAT_TILES = ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"];
  const SAT_ATTR = "Imágenes © Esri, Maxar, Earthstar Geographics";
  const PITCH = 58, BEARING = -28, EXAGGERATION = 1.6;
  const LOCALE = {
    "NavigationControl.ZoomIn": "Acercar", "NavigationControl.ZoomOut": "Alejar",
    "NavigationControl.ResetBearing": "Orientar al norte (arrastra para girar e inclinar)",
    "FullscreenControl.Enter": "Pantalla completa", "FullscreenControl.Exit": "Salir de pantalla completa",
    "AttributionControl.ToggleAttribution": "Mostrar u ocultar los créditos del mapa", "AttributionControl.MapFeedback": "Comentarios sobre el mapa",
    "CooperativeGesturesHandler.WindowsHelpText": "Usa Ctrl + rueda del mouse para acercar el mapa",
    "CooperativeGesturesHandler.MacHelpText": "Usa ⌘ + rueda del mouse para acercar el mapa",
    "CooperativeGesturesHandler.MobileHelpText": "Usa dos dedos para mover el mapa",
    "Map.Title": "Mapa", "Marker.Title": "Marcador", "Popup.Close": "Cerrar", "LogoControl.Title": "MapLibre",
    "ScaleControl.Meters": "m", "ScaleControl.Kilometers": "km",
    "TerrainControl.Enable": "Activar relieve", "TerrainControl.Disable": "Desactivar relieve"
  };

  const hasWebGL = (() => {
    if (!window.maplibregl) return false;
    try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); }
    catch (e) { return false; }
  })();
  if (hasWebGL && maplibregl.setWorkerUrl) maplibregl.setWorkerUrl("vendor/maplibre/maplibre-gl-csp-worker.js");
  // Al cambiar de vista con el mapa todavía cargando, MapLibre cancela sus descargas: es esperado, no un error
  window.addEventListener("unhandledrejection", e => { if (e.reason && e.reason.name === "AbortError") e.preventDefault(); });

  const fc = features => ({ type: "FeatureCollection", features });
  const point = (lng, lat, props) => ({ type: "Feature", properties: props, geometry: { type: "Point", coordinates: [lng, lat] } });
  // Polígono de `r` metros alrededor de un punto (círculo con muchos lados o cuadrado con 4) para las columnas
  function ring(lat, lng, r, sides) {
    const dLat = r / 111320, dLng = r / (111320 * Math.cos(lat * Math.PI / 180)), pts = [];
    for (let i = 0; i <= sides; i++) {
      const a = (i % sides) / sides * 2 * Math.PI + (sides === 4 ? Math.PI / 4 : 0);
      pts.push([lng + Math.cos(a) * dLng, lat + Math.sin(a) * dLat]);
    }
    return [pts];
  }

  function create3d(el, opts) {
    const state = { is3d: true, sat: false, loaded: false, fallback: false, moved: false };
    const vis = { tramos: true, nodos: true, barreras: true, reportes: !!opts.reports, calor: !!opts.heat };
    const queue = [];
    const whenReady = fn => { if (state.loaded) fn(); else queue.push(fn); };

    const map = new maplibregl.Map({
      container: el, style: STYLE, center: [CENTER[1], CENTER[0]], zoom: 11, maxPitch: 75,
      attributionControl: { compact: true }, locale: LOCALE, fadeDuration: 150,
      cooperativeGestures: opts.scroll === false            // en tarjetas: la rueda del mouse no secuestra la página
    });
    const api = { map, days: opts.days || 7 };
    el.vaMap = map;                                        // para revisar el mapa desde la consola del navegador
    // Si se sale de la vista con el mapa todavía cargando, MapLibre cancela las descargas y el estilo (ya separado
    // del mapa) avisa el error sin nadie que lo escuche, así que lo escribe en la consola. No es un fallo: se escucha ahí.
    const quitar = map.remove.bind(map);
    map.remove = () => {
      try { if (map.style && map.style.on) map.style.on("error", () => {}); } catch (e) { /* sin estilo todavía */ }
      quitar();
    };

    // ---------- Encuadre: toda la cuenca, inclinada y mirando río abajo ----------
    const pts = [...VA.store.nodes, ...VA.store.barriers];
    const bounds = pts.length ? pts.reduce((b, p) => b.extend([p.lng, p.lat]), new maplibregl.LngLatBounds([pts[0].lng, pts[0].lat], [pts[0].lng, pts[0].lat])) : null;
    // Con el mapa inclinado lo lejano se ve más chico: se mide en pantalla dónde caen los puntos y se ajusta
    // el acercamiento hasta que la cuenca llene el recuadro (dos pasadas bastan)
    function homeCamera(in3d) {
      const base = bounds && map.cameraForBounds(bounds, { padding: 40, bearing: in3d ? BEARING : 0 });
      if (!base) return null;
      let cam = { center: base.center, zoom: base.zoom, bearing: in3d ? BEARING : 0, pitch: in3d ? PITCH : 0 };
      if (!in3d) return cam;
      const saved = { center: map.getCenter(), zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() };
      const box = map.getContainer(), padX = 56, padTop = 70, padBottom = 40;
      for (let i = 0; i < 2; i++) {
        map.jumpTo(cam);
        const xy = pts.map(p => map.project([p.lng, p.lat]));
        const xs = xy.map(q => q.x), ys = xy.map(q => q.y);
        const w = Math.max(1, Math.max(...xs) - Math.min(...xs)), h = Math.max(1, Math.max(...ys) - Math.min(...ys));
        const k = Math.min((box.clientWidth - 2 * padX) / w, (box.clientHeight - padTop - padBottom) / h);
        const mid = map.unproject([(Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2 - (padTop - padBottom) / 2]);
        cam = Object.assign({}, cam, { center: mid, zoom: Math.min(13, cam.zoom + Math.log2(k)) });
      }
      map.jumpTo(saved);
      return cam;
    }
    function home(animate) {
      const cam = homeCamera(state.is3d);
      if (cam) animate && !reduceMotion ? map.easeTo(Object.assign(cam, { duration: 1600 })) : map.jumpTo(cam);
      state.atHome = true;
    }
    map.on("movestart", e => { if (e.originalEvent) state.atHome = false; });   // la persona movió el mapa
    // El mapa grande entra desde arriba y se inclina al cargar; el resto ya aparece en 3D
    const revealing = opts.reveal && !reduceMotion;
    const first = homeCamera(!revealing);
    if (first) map.jumpTo(first);
    state.atHome = true;

    // ---------- Marcadores HTML: se pueden enfocar con teclado y quedan sobre el relieve ----------
    const pop = new maplibregl.Popup({ offset: 16, maxWidth: "300px", className: "va-popup" });
    function openPopup(lngLat, html) { pop.setLngLat(lngLat).setHTML(html).addTo(map); refreshIcons(); }
    const markers = { nodos: {}, barreras: {} };
    function makeMarker(group, item, popupOf) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "map-marker";
      b.addEventListener("click", e => { e.stopPropagation(); openPopup([item.lng, item.lat], popupOf(item)); });
      // opacityWhenCovered "1": MapLibre atenúa los marcadores que cree tapados por el relieve y con las
      // columnas encima se equivoca; el río va por el fondo del valle, así que siempre se muestran completos
      markers[group][item.id] = { b, m: new maplibregl.Marker({ element: b, anchor: "center", opacityWhenCovered: "1" })
        .setLngLat([item.lng, item.lat]).addTo(map) };
    }
    VA.store.nodes.forEach(n => makeMarker("nodos", n, nodePopup));
    VA.store.barriers.forEach(b => makeMarker("barreras", b, barrierPopup));
    const trash = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>';
    function paintMarkers() {
      VA.store.nodes.forEach(n => {
        const x = markers.nodos[n.id]; if (!x) return;
        const s = nodeStatus(n);
        x.b.innerHTML = `<span class="node-pin ${s}" aria-hidden="true">${esc(n.id)}</span>`;
        x.b.setAttribute("aria-label", `Nodo ${n.id}, ${n.name}: ${VA.engine.semLabel[s]}`);
        x.b.hidden = !vis.nodos;
      });
      VA.store.barriers.forEach(b => {
        const x = markers.barreras[b.id]; if (!x) return;
        const s = barrierStatus(b);
        x.b.innerHTML = `<span class="square-pin ${s}" aria-hidden="true">${trash}</span>`;
        x.b.setAttribute("aria-label", `Barrera ${b.id}, ${b.name}: ${VA.engine.semLabel[s]}, ${fmt.num(b.fill)}% llena`);
        x.b.hidden = !vis.barreras;
      });
    }
    paintMarkers();

    // ---------- Datos de las capas ----------
    const tramosData = () => fc(VA.store.tramos.map(t => {
      const s = tramoStatus(t);
      return { type: "Feature", properties: { id: t.id, color: colors[s], label: `${t.id} · ${VA.engine.semLabel[s]}` },
        geometry: { type: "LineString", coordinates: t.points.map(p => [p[1], p[0]]) } };
    }));
    function columnsData() {
      const f = [];
      VA.store.nodes.forEach(n => {
        const s = nodeStatus(n);
        // Alturas exageradas a propósito (como el relieve): a escala de la cuenca una columna de 300 m no se vería
        f.push({ type: "Feature", properties: { kind: "nodo", id: n.id, color: colors[s], h: s === "off" ? 500 : Math.round(700 + Math.min(pressure(n), 2.5) * 2400) },
          geometry: { type: "Polygon", coordinates: ring(n.lat, n.lng, 260, 28) } });
      });
      VA.store.barriers.forEach(b => {
        const s = barrierStatus(b);
        f.push({ type: "Feature", properties: { kind: "barrera", id: b.id, color: colors[s], h: Math.round(300 + Math.min(100, b.fill || 0) * 32) },
          geometry: { type: "Polygon", coordinates: ring(b.lat, b.lng, 200, 4) } });
      });
      return fc(f);
    }
    const since = () => Date.now() - api.days * 86400000;
    const reportsData = () => fc(VA.store.reports.filter(r => r.t >= since()).map(r => point(r.lng, r.lat, { id: r.id })));
    function heatData() {
      const f = VA.store.reports.filter(r => r.t >= since()).map(r => point(r.lng, r.lat, { w: 0.6 }));
      VA.store.nodes.forEach(n => { const s = nodeStatus(n); if (s === "warn" || s === "crit") f.push(point(n.lng, n.lat, { w: s === "crit" ? 1 : 0.7 })); });
      VA.store.barriers.forEach(b => { const s = barrierStatus(b); if (s !== "ok") f.push(point(b.lng, b.lat, { w: s === "crit" ? 1 : 0.6 })); });
      return fc(f);
    }
    const setData = (id, data) => { const s = map.getSource(id); if (s) s.setData(data); };

    // ---------- Capas propias sobre el mapa base ----------
    function addLayers() {
      const layers = map.getStyle().layers || [];
      const below = (layers.find(l => l.type === "symbol") || {}).id;        // los nombres de calles y colonias quedan encima
      const hsBelow = layers.some(l => l.id === "waterway") ? "waterway" : below;

      // Relieve: terreno 3D (una fuente) y sombreado (otra, como recomienda MapLibre)
      map.addSource("va-dem", { type: "raster-dem", tiles: DEM_TILES, encoding: "terrarium", tileSize: 256, maxzoom: 14, attribution: DEM_ATTR });
      map.addSource("va-dem-sombra", { type: "raster-dem", tiles: DEM_TILES, encoding: "terrarium", tileSize: 256, maxzoom: 14 });
      map.addLayer({ id: "va-relieve", type: "hillshade", source: "va-dem-sombra",
        paint: { "hillshade-exaggeration": 0.5, "hillshade-shadow-color": "#4B5B6B", "hillshade-highlight-color": "#FFFFFF", "hillshade-accent-color": "#7B8B99" } }, hsBelow);
      // Satélite (apagado al inicio)
      map.addSource("va-sat", { type: "raster", tiles: SAT_TILES, tileSize: 256, maxzoom: 19, attribution: SAT_ATTR });
      map.addLayer({ id: "va-sat", type: "raster", source: "va-sat", layout: { visibility: "none" } }, below);
      // Edificios en 3D al acercarse a la ciudad
      if (map.getSource("openmaptiles")) {
        map.addLayer({ id: "va-edificios", type: "fill-extrusion", source: "openmaptiles", "source-layer": "building", minzoom: 14,
          paint: { "fill-extrusion-color": "#D7DCE3", "fill-extrusion-height": ["coalesce", ["get", "render_height"], 6],
            "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0], "fill-extrusion-opacity": 0.85 } }, below);
      }
      // Mapa de calor: reportes de la app y puntos en alerta
      map.addSource("va-calor", { type: "geojson", data: heatData() });
      map.addLayer({ id: "va-calor", type: "heatmap", source: "va-calor", maxzoom: 16, paint: {
        "heatmap-weight": ["get", "w"],
        "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 9, 0.8, 14, 1.6],
        "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 9, 18, 12, 34, 15, 60],
        "heatmap-opacity": 0.6,
        "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(29,78,216,0)", 0.2, "rgba(29,78,216,0.55)", 0.45, "#22C55E", 0.7, "#F59E0B", 1, "#DC2626"]
      } }, below);
      // Tramos del río con el color del semáforo (se pegan al relieve)
      map.addSource("va-tramos", { type: "geojson", data: tramosData() });
      map.addLayer({ id: "va-tramos-borde", type: "line", source: "va-tramos", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#FFFFFF", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 7, 14, 15], "line-opacity": 0.9 } }, below);
      map.addLayer({ id: "va-tramos", type: "line", source: "va-tramos", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 9, 4, 14, 9], "line-opacity": 0.95 } }, below);
      // Columnas 3D: nodos (cilindros, altura = qué tan cerca del umbral) y barreras (prismas, altura = llenado)
      map.addSource("va-columnas", { type: "geojson", data: columnsData() });
      // Se desvanecen al acercarse a nivel calle (ahí estorban y se ve el puente real)
      map.addLayer({ id: "va-columnas", type: "fill-extrusion", source: "va-columnas", maxzoom: 14, paint: {
        "fill-extrusion-color": ["get", "color"],
        "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 10, ["get", "h"], 12, ["*", ["get", "h"], 0.6], 14, ["*", ["get", "h"], 0.2]],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": ["interpolate", ["linear"], ["zoom"], 12, 0.88, 13.8, 0],
        "fill-extrusion-vertical-gradient": true
      } }, below);
      // Reportes ciudadanos
      map.addSource("va-reportes", { type: "geojson", data: reportsData() });
      map.addLayer({ id: "va-reportes", type: "circle", source: "va-reportes", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 4, 14, 7], "circle-color": "#0369A1",
        "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 2, "circle-pitch-alignment": "map"
      } });
      // Nombre y estado de cada tramo sobre la línea
      map.addLayer({ id: "va-tramos-etiqueta", type: "symbol", source: "va-tramos",
        layout: { "symbol-placement": "line-center", "text-field": ["get", "label"], "text-font": ["Noto Sans Bold"], "text-size": 12 },
        paint: { "text-color": "#0F172A", "text-halo-color": "#FFFFFF", "text-halo-width": 2 } });
      // Cielo con bruma hacia el horizonte (se ve al inclinar el mapa)
      try {
        map.setSky({ "sky-color": "#9CCBEA", "sky-horizon-blend": 0.6, "horizon-color": "#E6F1F8", "horizon-fog-blend": 0.75,
          "fog-color": "#F1F5F9", "fog-ground-blend": 0.85 });
      } catch (e) { /* versión sin cielo */ }
    }

    // Un solo manejador de clic: gana lo que está más arriba (reporte > columna > tramo).
    // Se registra una vez: sigue sirviendo si el estilo se cambia por el fondo liso.
    const visibles = ids => ids.filter(id => map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none");
    const puntoEn = p => { const capas = visibles(["va-reportes", "va-columnas"]); return capas.length ? map.queryRenderedFeatures(p, { layers: capas })[0] : null; };
    // Con relieve, MapLibre no detecta el clic sobre líneas pegadas al terreno: se mide la distancia en pantalla
    function tramoEn(p) {
      if (!vis.tramos || !state.loaded) return null;
      let mejor = null, dmin = 9;                                     // tolerancia en px
      VA.store.tramos.forEach(t => {
        const xy = t.points.map(q => map.project([q[1], q[0]]));
        for (let k = 0; k < xy.length - 1; k++) {
          const a = xy[k], b = xy[k + 1], dx = b.x - a.x, dy = b.y - a.y, L = dx * dx + dy * dy;
          const u = L ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L)) : 0;
          const d = Math.hypot(p.x - (a.x + u * dx), p.y - (a.y + u * dy));
          if (d < dmin) { dmin = d; mejor = t; }
        }
      });
      return mejor;
    }
    map.on("click", e => {
      // La App Ciudadana marca aquí el lugar del suceso: el toque elige el punto en vez de abrir ventanas
      if (opts.alElegir) { opts.alElegir(e.lngLat.lat, e.lngLat.lng, map.getZoom()); return; }
      const f = puntoEn(e.point);
      if (f) {
        const id = f.properties.id;
        if (f.layer.id === "va-reportes") { const r = VA.store.reports.find(x => x.id === id); if (r) openPopup(e.lngLat, reportPopup(r)); }
        else {
          const it = f.properties.kind === "nodo" ? VA.store.nodes.find(x => x.id === id) : VA.store.barriers.find(x => x.id === id);
          if (it) openPopup([it.lng, it.lat], f.properties.kind === "nodo" ? nodePopup(it) : barrierPopup(it));
        }
        return;
      }
      const t = tramoEn(e.point);
      if (t) openPopup(e.lngLat, tramoPopup(t));
    });
    map.on("mousemove", e => { map.getCanvas().style.cursor = puntoEn(e.point) || tramoEn(e.point) ? "pointer" : ""; });

    // ---------- Visibilidad según capas elegidas, 2D/3D y satélite ----------
    function applyVisibility() {
      paintMarkers();
      if (!state.loaded) return;
      const show = (id, on) => { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none"); };
      show("va-tramos", vis.tramos); show("va-tramos-borde", vis.tramos); show("va-tramos-etiqueta", vis.tramos && !!opts.tramoLabels);
      show("va-reportes", vis.reportes); show("va-calor", vis.calor);
      const kinds = [vis.nodos && "nodo", vis.barreras && "barrera"].filter(Boolean);
      show("va-columnas", state.is3d && kinds.length > 0);
      if (map.getLayer("va-columnas")) map.setFilter("va-columnas", ["in", ["get", "kind"], ["literal", kinds]]);
      show("va-edificios", state.is3d);
      show("va-sat", state.sat);
    }
    function set3d(on) {
      state.is3d = on;
      if (state.loaded && map.getSource("va-dem")) map.setTerrain(on ? { source: "va-dem", exaggeration: EXAGGERATION } : null);
      applyVisibility();
      ctrl.sync();
    }

    // ---------- Botones: 3D, satélite y volver a la cuenca ----------
    const ctrl = {
      onAdd() {
        const box = document.createElement("div");
        box.className = "maplibregl-ctrl maplibregl-ctrl-group va-ctrl";
        box.innerHTML = `<button type="button" data-v="3d" title="Relieve del terreno y columnas en 3D">3D</button>
          <button type="button" data-v="sat" title="Imagen de satélite">Satélite</button>
          <button type="button" data-v="home" title="Ver toda la cuenca" aria-label="Ver toda la cuenca">${icon("locate-fixed")}</button>`;
        box.addEventListener("click", e => {
          const b = e.target.closest("button"); if (!b) return;
          if (b.dataset.v === "3d") {
            set3d(!state.is3d);
            // Si nadie ha movido el mapa, se vuelve a encuadrar toda la cuenca; si no, solo cambia la inclinación
            if (state.atHome) { home(true); return; }
            const cam = { pitch: state.is3d ? PITCH : 0, bearing: state.is3d ? BEARING : 0 };
            reduceMotion ? map.jumpTo(cam) : map.easeTo(Object.assign(cam, { duration: 1000 }));
          }
          if (b.dataset.v === "sat") { state.sat = !state.sat; applyVisibility(); ctrl.sync(); }
          if (b.dataset.v === "home") home(true);
        });
        this.box = box;
        this.sync();
        return box;
      },
      onRemove() { if (this.box) this.box.remove(); },
      sync() {
        if (!this.box) return;
        this.box.querySelector('[data-v="3d"]').setAttribute("aria-pressed", state.is3d);
        this.box.querySelector('[data-v="sat"]').setAttribute("aria-pressed", state.sat);
      }
    };
    map.addControl(ctrl, "top-left");
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    if (opts.reveal) map.addControl(new maplibregl.FullscreenControl({ container: el }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    refreshIcons();

    // ---------- Carga ----------
    // Las capas propias se agregan en cuanto llega el estilo (no hay que esperar a que bajen todas las teselas).
    // Sin internet el estilo de calles no llega: se cambia a un fondo liso para no dejar el mapa en blanco.
    const toFallback = () => { if (!state.loaded && !state.fallback) { state.fallback = true; map.setStyle(FALLBACK); } };
    const failTimer = setTimeout(toFallback, 15000);
    map.on("error", e => { if (!state.loaded && e && e.error && /\/styles\//.test(String(e.error.url || ""))) toFallback(); });
    map.on("style.load", () => {
      clearTimeout(failTimer);
      try { addLayers(); } catch (err) { console.error("No se pudieron agregar las capas del mapa", err); }
      const first = !state.loaded;
      state.loaded = true;
      set3d(state.is3d);
      if (!first) return;
      queue.splice(0).forEach(fn => fn());
      if (revealing && !state.moved) home(true);
    });
    // Si el recuadro cambia de tamaño (pestaña en segundo plano, barra lateral, letras que tardan), el lienzo se ajusta
    const ro = window.ResizeObserver && new ResizeObserver(() => {
      const c = map.getCanvas();
      if (Math.abs(c.clientWidth - el.clientWidth) > 1 || Math.abs(c.clientHeight - el.clientHeight) > 1) map.resize();
    });
    if (ro) ro.observe(el);
    map.on("remove", () => { clearTimeout(failTimer); if (ro) ro.disconnect(); });

    // ---------- Interfaz común con el mapa 2D ----------
    api.update = () => {
      paintMarkers();
      whenReady(() => { setData("va-tramos", tramosData()); setData("va-columnas", columnsData()); });
    };
    api.setReports = show => { vis.reportes = !!show; whenReady(() => { setData("va-reportes", reportsData()); applyVisibility(); }); };
    api.setHeat = show => { vis.calor = !!show; whenReady(() => { setData("va-calor", heatData()); applyVisibility(); }); };
    api.setLayer = (name, show) => {
      if (name === "reportes") return api.setReports(show);
      if (name === "calor") return api.setHeat(show);
      vis[name] = !!show;
      applyVisibility();
    };
    api.focus = (lat, lng, z = 14) => {
      state.moved = true; state.atHome = false;
      map.flyTo({ center: [lng, lat], zoom: z, pitch: state.is3d ? PITCH : 0, bearing: state.is3d ? BEARING : 0, duration: reduceMotion ? 0 : 1400 });
    };
    return api;
  }

  // =========================================================
  // 2D (Leaflet): respaldo para equipos sin WebGL
  // =========================================================
  function create2d(el, opts) {
    const map = L.map(el, { zoomControl: true, scrollWheelZoom: opts.scroll !== false }).setView(CENTER, 11);
    const bounds = L.latLngBounds([...VA.store.nodes, ...VA.store.barriers].map(p => [p.lat, p.lng]));
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    const groups = { tramos: L.layerGroup().addTo(map), nodos: L.layerGroup().addTo(map), barreras: L.layerGroup().addTo(map),
      reportes: L.layerGroup(), calor: null };
    const refs = { tramos: {}, nodos: {}, barreras: {} };
    VA.store.tramos.forEach(t => {
      const s = tramoStatus(t);
      const line = L.polyline(t.points, { color: colors[s], weight: 7, opacity: 0.85 }).addTo(groups.tramos);
      line.bindTooltip(`${t.id} · ${VA.engine.semLabel[s]}`, { permanent: !!opts.tramoLabels, direction: "center", className: "tramo-label" });
      line.bindPopup(() => tramoPopup(t));
      refs.tramos[t.id] = line;
    });
    VA.store.nodes.forEach(n => {
      const m = L.marker([n.lat, n.lng], { icon: nodeIcon(n), title: `${n.id} ${n.name}`, keyboard: true, riseOnHover: true }).addTo(groups.nodos);
      m.bindPopup(() => nodePopup(n));
      refs.nodos[n.id] = m;
    });
    VA.store.barriers.forEach(b => {
      const m = L.marker([b.lat, b.lng], { icon: barrierIcon(b), title: `${b.id} ${b.name}`, keyboard: true }).addTo(groups.barreras);
      m.bindPopup(() => barrierPopup(b));
      refs.barreras[b.id] = m;
    });
    map.on("popupopen", refreshIcons);

    const api = { map, days: opts.days || 7 };
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

  function create(el, opts = {}) {
    if (hasWebGL) {
      try { return create3d(el, opts); }
      catch (err) { console.warn("Mapa 3D no disponible; se usa el mapa plano.", err); el.innerHTML = ""; }
    }
    return create2d(el, opts);
  }

  VA.map = { create, nodeStatus, tramoStatus, barrierStatus, isStale, lastOf, colors, pressure, is3d: hasWebGL };
})();
