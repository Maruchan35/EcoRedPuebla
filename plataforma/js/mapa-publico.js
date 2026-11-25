/* =========================================================
   Mapa 3D público (/mapa): el mismo mapa de la plataforma, sin el
   panel de datos. La App Ciudadana lo muestra en su pestaña «Mapa».

   Con ?elegir=1&lat=…&lng=… sirve para marcar el lugar del suceso
   de un reporte: cada toque se manda a la app con postMessage
   ({tipo:"va-punto", lat, lng, exacto}) y la app puede mover el
   pin con {tipo:"va-ir", lat, lng}.

   Con ?previa=1 se oculta la leyenda: así lo muestra la portada.
   ========================================================= */
(function () {
  const el = document.getElementById("mapa3d");
  const q = new URLSearchParams(location.search);
  const elegir = q.has("elegir") && VA.map.is3d;
  const ZOOM_EXACTO = 17;                    // en 3D, a este acercamiento el toque cae a pocos metros del punto
  let m = null, pin = null;

  if (q.has("previa")) document.body.classList.add("mapa-previa");   // vista previa de la portada: solo el mapa
  if (elegir) document.body.classList.add("mapa-elegir");
  else if (VA.map.is3d) {
    document.getElementById("leyenda").insertAdjacentHTML("beforeend",
      `<span><span class="col-swatch" aria-hidden="true"></span>Columna más alta = más cerca del límite</span>
       <span class="map-hint">Gira o inclina con dos dedos (en computadora, clic derecho y arrastrar)</span>`);
  }

  function ponerPin(lat, lng) {
    if (!pin) pin = new maplibregl.Marker({ color: "#0369A1" }).setLngLat([lng, lat]).addTo(m.map);
    else pin.setLngLat([lng, lat]);
  }

  // Toque en el mapa: si está lejos, primero se acerca ahí para que la persona afine el punto (igual que el mapa plano)
  function alElegir(lat, lng, zoom) {
    const exacto = zoom >= ZOOM_EXACTO;
    ponerPin(lat, lng);
    if (!exacto) m.focus(lat, lng, ZOOM_EXACTO);
    parent.postMessage({ tipo: "va-punto", lat: +lat.toFixed(6), lng: +lng.toFixed(6), exacto }, location.origin);
  }

  VA.api.loadAll().then(() => {
    m = VA.map.create(el, elegir ? { zoom: 11, tramoLabels: false, alElegir }
      : { zoom: 11, reports: true, heat: true, tramoLabels: true, reveal: true });
    // Si el 3D no arrancó (equipo sin WebGL útil), el mapa quedó plano: la app vuelve a su propio mapa plano
    if (elegir && !(window.maplibregl && m.map instanceof maplibregl.Map)) {
      parent.postMessage({ tipo: "va-sin-3d" }, location.origin);
      return;
    }
    if (elegir) {
      const lat = parseFloat(q.get("lat")), lng = parseFloat(q.get("lng"));
      if (Number.isFinite(lat) && Number.isFinite(lng)) {
        ponerPin(lat, lng);
        // Directo al punto, sin vuelo: el relieve, al terminar de cargar, cortaría la animación
        m.map.jumpTo({ center: [lng, lat], zoom: 16, pitch: 55 });
      }
      // La app movió el pin (GPS, referencia o mapa plano): se refleja aquí sin quitarle a la persona su vista
      window.addEventListener("message", ev => {
        const d = ev.data || {};
        if (ev.origin !== location.origin || ev.source !== parent || d.tipo !== "va-ir") return;
        if (!Number.isFinite(d.lat) || !Number.isFinite(d.lng)) return;
        ponerPin(d.lat, d.lng);
        if (!m.map.getBounds().contains([d.lng, d.lat])) m.focus(d.lat, d.lng, Math.max(16, m.map.getZoom()));
      });
    }
    // Con servidor, cada aviso llega cuando los datos ya se recargaron: solo falta repintar
    VA.api.connect(msg => { if (msg.tipo === "sync") m.update(); });
    VA.ui.refreshIcons();
  }).catch(err => {
    el.innerHTML = `<p class="mapa-publico-error">No se pudo cargar el mapa: ${VA.ui.esc(err.message)}</p>`;
  });
})();
