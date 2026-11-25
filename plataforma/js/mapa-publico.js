/* =========================================================
   Mapa 3D público (/mapa): el mismo mapa de la plataforma, sin el
   panel de datos. La App Ciudadana lo muestra en su pestaña «Mapa».
   ========================================================= */
(function () {
  const el = document.getElementById("mapa3d");
  if (VA.map.is3d) {
    document.getElementById("leyenda").insertAdjacentHTML("beforeend",
      `<span><span class="col-swatch" aria-hidden="true"></span>Columna más alta = más cerca del límite</span>
       <span class="map-hint">Gira o inclina con dos dedos (en computadora, clic derecho y arrastrar)</span>`);
  }
  VA.api.loadAll().then(() => {
    const m = VA.map.create(el, { zoom: 11, reports: true, heat: true, tramoLabels: true, reveal: true });
    // Con servidor, cada aviso llega cuando los datos ya se recargaron: solo falta repintar
    VA.api.connect(msg => { if (msg.tipo === "sync") m.update(); });
    VA.ui.refreshIcons();
  }).catch(err => {
    el.innerHTML = `<p class="mapa-publico-error">No se pudo cargar el mapa: ${VA.ui.esc(err.message)}</p>`;
  });
})();
