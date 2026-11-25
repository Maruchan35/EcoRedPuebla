/* EcoRed Puebla · Portada pública (inicio.html)
   Dibuja los íconos, trae las cifras públicas y el aviso del río, y carga la vista previa del mapa
   solo en pantallas anchas y cuando está por verse (en el celular no gasta datos). */
(function () {
  "use strict";

  if (window.lucide) window.lucide.createIcons();

  var fmt = new Intl.NumberFormat("es-MX");
  function poner(id, valor) {
    var el = document.getElementById(id);
    if (el) el.textContent = valor;
  }
  function json(ruta) {
    return fetch(ruta, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }

  // ---------- Cifras (api/metricas): si no hay servidor, la banda se oculta en vez de mostrar guiones ----------
  var banda = document.getElementById("cifras");
  json("api/metricas").then(function (m) {
    poner("cifraNodos", fmt.format(m.nodos.total));
    poner("cifraTramos", fmt.format(Object.keys(m.tramos_detalle || {}).length));
    poner("cifraReportes", fmt.format(m.reportes.total));
    poner("cifraCasos", fmt.format(m.casos.cerrados));
    var nota = document.getElementById("cifrasNota");
    if (nota && m.demo) nota.hidden = false;
  }).catch(function () {
    if (banda) banda.hidden = true;
  });

  // ---------- Aviso del río (api/riesgo): sin respuesta se queda el texto fijo ----------
  json("api/riesgo").then(function (d) {
    if (d && d.mensaje) poner("rioMensaje", d.mensaje);
  }).catch(function () {});

  // ---------- Vista previa del mapa 3D ----------
  var marco = document.getElementById("mapaMarco");
  var lienzo = document.getElementById("mapaLienzo");
  var ancha = window.matchMedia("(min-width: 960px)");
  function cargarMapa() {
    if (!marco || !lienzo || marco.dataset.cargado || !ancha.matches) return;
    marco.dataset.cargado = "1";
    var f = document.createElement("iframe");
    f.src = "mapa?previa=1";
    f.title = "Vista previa del mapa 3D del Alto Atoyac";
    f.tabIndex = -1;
    f.setAttribute("aria-hidden", "true");
    lienzo.appendChild(f);
  }
  if (marco && "IntersectionObserver" in window) {
    var visor = new IntersectionObserver(function (entradas) {
      if (entradas.some(function (e) { return e.isIntersecting; })) {
        cargarMapa();
        if (marco.dataset.cargado) visor.disconnect();
      }
    }, { rootMargin: "400px 0px" });
    visor.observe(marco);
  } else {
    cargarMapa();
  }
})();
