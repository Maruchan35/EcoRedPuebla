/* =========================================================
   EcoRed Puebla · Orquestador de la App Ciudadana (PWA)
   Mobile-First, sin filtros innecesarios y CSP-safe.
   ========================================================= */
import {
  conectarEventosWS,
  entrarApp,
  entrarPlataforma,
  obtenerApiBase,
  enviarReporte,
  leerSesionLocal,
  marcarNotificacionesLeidas,
  obtenerEstadoCuenca,
  obtenerFotoReporteUrl,
  obtenerMisReportes,
  obtenerNotificaciones,
  registrarCiudadano,
  salirApp,
  obtenerRiesgo,
  verReportePorFolio,
  verificarSesion,
} from "./api.js";
import {
  crearControladorCamara,
  crearMiniMapaUbicacion,
  iniciarDictadoVoz,
  obtenerGpsDispositivo,
  PRECISION_MAX_M,
  procesarArchivoFoto,
  ZOOM_EXACTO,
} from "./camera-gps.js";
import { CATEGORIAS, REFERENCIAS_CUENCA, estaEnPuebla } from "./config.js";
import { encolarReporte, listarCola, sincronizarCola } from "./offline-queue.js";
import { analizarImagenLocal, inferirCategoriaAutomatica } from "./vision-local.js";

const STORAGE_FOLIOS = "ecored_folios_locales";

const state = {
  vistaActual: "reportar",
  usuario: null,
  foto: null,
  iaLocal: null,
  lat: REFERENCIAS_CUENCA[0].lat,
  lng: REFERENCIAS_CUENCA[0].lng,
  fuenteUbicacion: "referencia inicial",
  origenUbicacion: null,       // "gps" o "mapa" cuando el punto es el lugar exacto del suceso
  precisionUbicacion: null,    // margen del GPS en metros
  usoVoz: false,
  estadoCuenca: null,
  desdeCache: false,
  notificaciones: [],
  avisosVistosIds: new Set(),
  wsConectado: false,
  fotoBlobUrls: [],
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(txt) {
  return String(txt ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function refrescarIconos() {
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
}

function formatearFecha(ts) {
  if (!ts) return "Reciente";
  try {
    return new Intl.DateTimeFormat("es-MX", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(ts));
  } catch {
    return new Date(ts).toLocaleString();
  }
}

function toast(titulo, mensaje = "", tipo = "info") {
  const cont = $("#toastContainer");
  if (!cont) return;
  const item = document.createElement("div");
  item.className = `toast toast-${tipo}`;
  item.innerHTML = `<strong>${esc(titulo)}</strong>${mensaje ? `<p>${esc(mensaje)}</p>` : ""}`;
  cont.appendChild(item);
  setTimeout(() => item.remove(), 5000);
}

function leerFoliosLocales() {
  try {
    const raw = localStorage.getItem(STORAGE_FOLIOS);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function guardarFolioLocal(reporte) {
  const lista = leerFoliosLocales().filter((f) => f.id !== reporte.id);
  lista.unshift({
    id: reporte.id,
    cat: reporte.cat,
    t: reporte.t || Date.now(),
    status: reporte.status || "Recibido",
    lat: reporte.lat,
    lng: reporte.lng,
  });
  localStorage.setItem(STORAGE_FOLIOS, JSON.stringify(lista.slice(0, 20)));
}

// ---------- Navegación por hash ----------
let miniMapa = null;

function activarVista(vista, folioDirecto = null) {
  const permitidas = ["reportar", "mapa", "rio", "seguimiento"];
  const destino = permitidas.includes(vista) ? vista : "reportar";
  const cambio = state.vistaActual !== destino;
  state.vistaActual = destino;

  $$(".view-section").forEach((sec) => {
    sec.hidden = sec.dataset.view !== destino;
  });
  $$("[data-nav]").forEach((btn) => {
    const activo = btn.dataset.nav === destino;
    btn.classList.toggle("is-active", activo);
    btn.setAttribute("aria-current", activo ? "page" : "false");
  });

  if (destino === "reportar" && miniMapa) {
    miniMapa.invalidarTamano();
  }
  if (destino === "mapa") cargarMapa3d();
  if (destino === "seguimiento") {
    actualizarVistaSeguimiento(folioDirecto);
  }
  if (destino === "rio") {
    cargarRiesgo();
  }
  // Cada pestaña empieza arriba, con el foco en su título (antes quedaba a media página)
  if (cambio) {
    window.scrollTo({ top: 0 });
    document.querySelector(`.view-section[data-view="${destino}"] h1`)?.focus({ preventScroll: true });
  }
}

// ---------- El río: riesgo para la salud por contacto con el agua ----------
async function cargarRiesgo() {
  const alerta = $("#rioAlerta");
  const lista = $("#rioTramos");
  if (!alerta || !lista) return;
  let d = null;
  try {
    d = await obtenerRiesgo();
  } catch {
    d = null;
  }
  if (!d) {
    alerta.innerHTML = `<div class="alert alert-warn">No se pudo consultar el riesgo; revisa tu conexión. Mientras tanto: no te metas al río.</div>`;
    return;
  }
  alerta.innerHTML = `<div class="rio-hero ${esc(d.peor)}"><strong>${esc(d.mensaje)}</strong>
    <span>Los sensores miden pH, conductividad, turbidez, color y nivel. El riesgo nunca es bajo: el río recibe drenaje y descargas industriales sin tratar.</span></div>`;
  lista.innerHTML = d.tramos.map((t) => `<article class="rio-card ${esc(t.nivel)}">
      <span class="rio-nivel"><i data-lucide="${t.nivel === "extremo" ? "siren" : "triangle-alert"}" aria-hidden="true"></i>${esc(t.etiqueta)}</span>
      <h3>${esc(t.tramo)} · ${esc(t.nombre)}</h3>
      <p>${esc(t.resumen)}</p>
      <ul>${t.razones.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    </article>`).join("");
  $("#rioRecomendaciones").innerHTML = d.recomendaciones.map((r) => `<li>${esc(r)}</li>`).join("");
  $("#rioNoMide").innerHTML = d.noMide.map((r) => `<li>${esc(r)}</li>`).join("");
  refrescarIconos();
}

function leerRutaHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const partes = raw.split("/").filter(Boolean);
  if (partes[0] === "mapa") activarVista("mapa");
  else if (partes[0] === "rio") activarVista("rio");
  else if (partes[0] === "seguimiento") activarVista("seguimiento", partes[1] || null);
  else activarVista("reportar");
}

// ---------- Estado de red y cola offline ----------
async function actualizarIndicadorCola() {
  const cola = await listarCola();
  const btnSync = $("#btnSyncCola");
  const countEl = $("#colaPendientesCount");
  const netBadge = $("#estadoRedBadge");

  if (netBadge) {
    if (navigator.onLine) {
      netBadge.className = "status-pill is-online";
      netBadge.innerHTML = `<i data-lucide="wifi" aria-hidden="true"></i><span class="status-text">En línea</span>`;
    } else {
      netBadge.className = "status-pill is-offline";
      netBadge.innerHTML = `<i data-lucide="wifi-off" aria-hidden="true"></i><span class="status-text">Sin señal</span>`;
    }
  }

  if (btnSync && countEl) {
    countEl.textContent = String(cola.length);
    btnSync.hidden = cola.length === 0;
  }
  renderizarColaOffline(cola);
  refrescarIconos();
}

function renderizarColaOffline(cola) {
  const cont = $("#listaColaOffline");
  if (!cont) return;
  if (!cola.length) {
    cont.innerHTML = `<p class="small muted">No tienes reportes esperando conexión.</p>`;
    return;
  }
  cont.innerHTML = cola
    .map(
      (item) => `
      <div class="queue-item">
        <div>
          <strong>${esc(item.cat)}</strong>
          <p class="small muted">Guardado ${esc(formatearFecha(item.creadoEn))} · ${item.lat.toFixed(4)}, ${item.lng.toFixed(4)}</p>
        </div>
        <span class="badge badge-warn">Pendiente</span>
      </div>`
    )
    .join("");
}

async function intentarSincronizar(silencioso = false) {
  if (!navigator.onLine) {
    if (!silencioso) toast("Sin señal", "Conéctate a internet para enviar los reportes pendientes.", "warn");
    return;
  }
  const { enviados, fallidos } = await sincronizarCola(enviarReporte);
  if (enviados.length > 0) {
    enviados.forEach(({ respuesta }) => guardarFolioLocal(respuesta));
    toast(
      `Se enviaron ${enviados.length} reporte${enviados.length === 1 ? "" : "s"} pendiente${enviados.length === 1 ? "" : "s"}`,
      "Ya aparecen en el mapa de EcoRed Puebla.",
      "ok"
    );
    await cargarEstadoCuenca();
    if (state.vistaActual === "seguimiento") await actualizarVistaSeguimiento();
  } else if (!silencioso && fallidos > 0) {
    toast("No se pudo sincronizar", "El servidor no respondió. Se conservaron en tu dispositivo.", "warn");
  }
  await actualizarIndicadorCola();
}

// ---------- Paso 1: Foto + IA Local ----------
function inicializarSelectorOpcional() {
  const select = $("#catOverrideSelect");
  if (!select) return;
  select.innerHTML =
    `<option value="auto">Automática (según foto y nota)</option>` +
    CATEGORIAS.map((c) => `<option value="${esc(c.id)}">${esc(c.label)}</option>`).join("");
}

async function aplicarFotoCapturada(fotoData) {
  if (state.foto && state.foto.previewUrl) {
    URL.revokeObjectURL(state.foto.previewUrl);
  }
  state.foto = fotoData;

  const previewImg = $("#fotoPreviewImg");
  const previewBox = $("#fotoPreviewBox");
  const emptyFoto = $("#fotoEmptyState");
  if (previewImg && previewBox && emptyFoto) {
    previewImg.src = fotoData.previewUrl;
    previewBox.hidden = false;
    emptyFoto.hidden = true;
  }

  if (fotoData.exifGps && estaEnPuebla(fotoData.exifGps.lat, fotoData.exifGps.lng)) {
    // La foto no dice con qué margen se tomó su ubicación: se acerca el mapa ahí para que la persona confirme el punto
    miniMapa?.fijar(fotoData.exifGps.lat, fotoData.exifGps.lng, "metadatos GPS de la foto", ZOOM_EXACTO);
    toast("Ubicación leída de la foto", "Toca el punto exacto del suceso en el mapa para confirmarlo, o usa «Mi GPS».", "info");
  } else if (fotoData.exifGps) {
    toast("GPS de la foto fuera de Puebla", "Ajusta el punto en el mapa del Alto Atoyac.", "warn");
  }

  const iaBox = $("#iaDiagnosticoBox");
  if (iaBox) {
    iaBox.hidden = false;
    iaBox.innerHTML = `<p class="small muted">Analizando fotografía en el teléfono...</p>`;
  }
  const resultado = await analizarImagenLocal(fotoData.blob);
  state.iaLocal = resultado;

  if (iaBox) {
    const etiqueta = resultado.ia_etiqueta || "Análisis listo (clasificación automática al enviar)";
    const confTxt = resultado.ia_confianza ? ` · ${Math.round(resultado.ia_confianza * 100)} %` : "";
    const badgeCls = resultado.semaforo === "crit" ? "badge-crit" : resultado.ia_etiqueta ? "badge-warn" : "badge-info";
    const hallazgosHtml = resultado.hallazgos.length
      ? `<ul class="ia-list">${resultado.hallazgos.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>`
      : "";
    iaBox.innerHTML = `
      <div class="ia-head">
        <span class="badge ${badgeCls}">${esc(etiqueta)}${esc(confTxt)}</span>
        <span class="color-chip" title="Tono promedio detectado"><span class="color-swatch" style="background:${esc(resultado.colorHex)}"></span>${esc(resultado.colorHex)}</span>
      </div>
      <p class="small">${esc(resultado.resumen)}</p>
      ${hallazgosHtml}`;
  }
}

function limpiarFoto() {
  if (state.foto && state.foto.previewUrl) URL.revokeObjectURL(state.foto.previewUrl);
  state.foto = null;
  state.iaLocal = null;
  const previewBox = $("#fotoPreviewBox");
  const emptyFoto = $("#fotoEmptyState");
  const iaBox = $("#iaDiagnosticoBox");
  if (previewBox) previewBox.hidden = true;
  if (emptyFoto) emptyFoto.hidden = false;
  if (iaBox) {
    iaBox.hidden = true;
    iaBox.innerHTML = "";
  }
  const inputCam = $("#inputFotoCamara");
  if (inputCam) inputCam.value = "";
}

// ---------- Paso 2: Ubicación y referencias ----------
function actualizarEtiquetaUbicacion(lat, lng, fuente, info = {}) {
  state.lat = lat;
  state.lng = lng;
  state.fuenteUbicacion = fuente;
  state.origenUbicacion = info.origen || null;
  state.precisionUbicacion = info.precision ?? null;
  const coordsEl = $("#ubicacionCoords");
  const warnEl = $("#ubicacionAlerta");
  const precisionEl = $("#ubicacionPrecision");
  if (coordsEl) {
    coordsEl.textContent = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  }
  if (warnEl) {
    warnEl.hidden = estaEnPuebla(lat, lng);
  }
  if (precisionEl) {
    const exacta = ubicacionExacta();
    precisionEl.textContent = state.origenUbicacion === "gps" ? `GPS ±${state.precisionUbicacion} m`
      : state.origenUbicacion === "mapa" ? "Punto marcado en el mapa"
      : fuente === "acerca el mapa" ? "Afina el pin en el mapa"
      : "Falta el punto exacto";
    precisionEl.classList.toggle("ok", exacta);
    precisionEl.classList.toggle("warn", !exacta);
  }
  avisarPunto3d(lat, lng);
}

// ---------- Mapa del reporte en plano o en 3D ----------
// El 3D es el mismo de la plataforma (/mapa?elegir=1): el punto que se toca ahí vuelve con postMessage
function hayWebGL() {
  try {
    const c = document.createElement("canvas");
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function inicializarMapaReporte3d() {
  const grupo = $(".map-mode");
  const frame = $("#miniMapa3d");
  if (!grupo || !frame || !hayWebGL()) return;              // sin WebGL no hay 3D: queda el mapa plano
  grupo.hidden = false;
  grupo.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-modo]");
    if (btn) cambiarModoMapa(btn.dataset.modo);
  });
  window.addEventListener("message", (ev) => {
    const d = ev.data || {};
    if (ev.origin !== location.origin || ev.source !== frame.contentWindow) return;
    if (d.tipo === "va-sin-3d") {                             // el equipo no pudo dibujar el 3D: queda el plano
      cambiarModoMapa("2d");
      grupo.hidden = true;
      toast("El 3D no está disponible en este equipo", "Marca el punto en el mapa plano.", "warn");
      return;
    }
    if (d.tipo !== "va-punto" || !Number.isFinite(d.lat) || !Number.isFinite(d.lng)) return;
    // Mismo criterio que el mapa plano: el toque cuenta como lugar exacto solo con el mapa acercado
    miniMapa?.fijar(d.lat, d.lng, d.exacto ? "marcado en el mapa 3D" : "acerca el mapa", ZOOM_EXACTO,
      { origen: d.exacto ? "mapa" : null });
  });
}

function cambiarModoMapa(modo) {
  const en3d = modo === "3d";
  const frame = $("#miniMapa3d");
  $$(".map-mode [data-modo]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.modo === modo)));
  $("#miniMapaReporte").hidden = en3d;
  frame.hidden = !en3d;
  if (!en3d) {
    miniMapa?.invalidarTamano();
  } else if (!frame.getAttribute("src")) {
    frame.setAttribute("src", `../mapa?elegir=1&lat=${state.lat}&lng=${state.lng}`);
  } else {
    avisarPunto3d(state.lat, state.lng);
  }
}

// El pin del 3D sigue al del plano (GPS, referencia rápida o toque en el mapa plano)
function avisarPunto3d(lat, lng) {
  const frame = $("#miniMapa3d");
  if (frame && !frame.hidden && frame.getAttribute("src")) {
    frame.contentWindow?.postMessage({ tipo: "va-ir", lat, lng }, location.origin);
  }
}

// El reporte marca el lugar del suceso: vale el GPS con 20 m o menos de margen o el punto marcado a nivel de calle
function ubicacionExacta() {
  return (state.origenUbicacion === "gps" && state.precisionUbicacion !== null && state.precisionUbicacion <= PRECISION_MAX_M)
    || state.origenUbicacion === "mapa";
}

function inicializarReferencias() {
  const select = $("#referenciaSelect");
  if (!select) return;
  select.innerHTML =
    `<option value="">Elegir punto rápido de la cuenca...</option>` +
    REFERENCIAS_CUENCA.map((r) => `<option value="${esc(r.id)}">${esc(r.nombre)}</option>`).join("");

  select.addEventListener("change", () => {
    const ref = REFERENCIAS_CUENCA.find((r) => r.id === select.value);
    if (ref) {
      miniMapa?.fijar(ref.lat, ref.lng, `referencia: ${ref.nombre}`);
    }
  });
}

// ---------- Envío del reporte ----------
async function manejarEnvioReporte(ev) {
  ev.preventDefault();
  const errEl = $("#reporteError");
  errEl.hidden = true;

  const texto = ($("#descripcionInput")?.value || "").trim();
  const tieneFoto = Boolean(state.foto?.blob);
  const override = $("#catOverrideSelect")?.value || "auto";

  if (!tieneFoto && !texto && override === "auto") {
    errEl.textContent = "Toma o sube una fotografía (o escribe una breve nota) para enviar el reporte.";
    errEl.hidden = false;
    return;
  }
  if (!estaEnPuebla(state.lat, state.lng)) {
    errEl.textContent = "La ubicación debe estar dentro del estado de Puebla (ajusta el pin o elige una referencia).";
    errEl.hidden = false;
    return;
  }
  if (!ubicacionExacta()) {
    errEl.textContent = state.origenUbicacion === "gps"
      ? `El GPS marca ±${state.precisionUbicacion} m y el lugar del suceso necesita ${PRECISION_MAX_M} m o menos. Toca «Mi GPS» otra vez a cielo abierto, o acerca el mapa y mueve el pin al punto exacto.`
      : `Marca el lugar exacto del suceso: toca «Mi GPS» (${PRECISION_MAX_M} m o menos) o acerca el mapa y toca el punto exacto.`;
    errEl.hidden = false;
    return;
  }

  const categoriaFinal =
    override !== "auto"
      ? override
      : inferirCategoriaAutomatica({ iaResultado: state.iaLocal, texto, tieneFoto });

  const anonimo = Boolean($("#anonimoCheck")?.checked);
  const btn = $("#btnEnviarReporte");
  btn.disabled = true;
  btn.textContent = "Enviando reporte...";

  const payload = {
    cat: categoriaFinal,
    lat: state.lat,
    lng: state.lng,
    ubicacion: state.origenUbicacion,
    precision_m: state.origenUbicacion === "gps" ? state.precisionUbicacion : null,
    texto,
    anonimo,
    voz: state.usoVoz,
    ia_etiqueta: state.iaLocal?.ia_etiqueta || "",
    ia_confianza: state.iaLocal?.ia_confianza ?? null,
    fotoBlob: state.foto?.blob || null,
    fotoNombre: state.foto?.nombre || "evidencia.jpg",
  };

  try {
    const res = await enviarReporte(payload);
    guardarFolioLocal(res);
    mostrarResultadoEnvio(res, false);
    limpiarFormularioParcial();
    toast("Reporte recibido", `Folio asignado: ${res.id}`, "ok");
    cargarEstadoCuenca();
  } catch (err) {
    if (err.esRed || !navigator.onLine) {
      await encolarReporte(payload);
      await actualizarIndicadorCola();
      mostrarResultadoEnvio(
        {
          id: "Pendiente offline",
          cat: payload.cat,
          status: "En cola local",
          ai: payload.ia_etiqueta ? { label: payload.ia_etiqueta, conf: payload.ia_confianza || 0 } : null,
        },
        true
      );
      limpiarFormularioParcial();
      toast("Guardado sin internet", "Se enviará automáticamente cuando recuperes señal.", "warn");
    } else {
      errEl.textContent = err.message || "No se pudo enviar el reporte.";
      errEl.hidden = false;
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="send" aria-hidden="true"></i><span>Enviar reporte</span>`;
    refrescarIconos();
  }
}

function limpiarFormularioParcial() {
  limpiarFoto();
  if ($("#descripcionInput")) $("#descripcionInput").value = "";
  if ($("#catOverrideSelect")) $("#catOverrideSelect").value = "auto";
  state.usoVoz = false;
}

function mostrarResultadoEnvio(res, esOffline) {
  const box = $("#confirmacionEnvioBox");
  if (!box) return;
  const catInfo = CATEGORIAS.find((c) => c.id === res.cat);
  const dep = catInfo ? catInfo.dependencia : "Plataforma EcoRed Puebla";
  const iaTxt = res.ai ? `${res.ai.label} (${Math.round(res.ai.conf * 100)} %)` : `${res.cat} (registro automático)`;

  box.hidden = false;
  box.innerHTML = `
    <div class="confirm-head">
      <span class="badge ${esOffline ? "badge-warn" : "badge-ok"}">${esOffline ? "En cola sin señal" : "Recibido en plataforma"}</span>
      <strong class="folio-code">${esc(res.id)}</strong>
    </div>
    <p><strong>Canalizado a:</strong> ${esc(dep)}</p>
    <p class="small muted">Clasificación: ${esc(iaTxt)}</p>
    <div class="confirm-actions">
      ${esOffline ? "" : `<button type="button" class="btn btn-secondary" data-ver-folio="${esc(res.id)}">Seguir folio</button>`}
      <button type="button" class="btn btn-ghost" data-ir-mapa="1">Ver el mapa 3D</button>
    </div>`;

  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- Estado de la cuenca (queda guardado para usarlo sin señal) ----------
async function cargarEstadoCuenca() {
  try {
    const { data, desdeCache } = await obtenerEstadoCuenca();
    state.estadoCuenca = data;
    state.desdeCache = desdeCache;
  } catch {
    /* sin conexión ni copia guardada: se vuelve a pedir con el siguiente aviso del servidor */
  }
}

// ---------- Mapa 3D: el mismo de la plataforma (/mapa), se carga la primera vez que se abre «Mapa» ----------
function cargarMapa3d() {
  const frame = $("#mapa3dFrame");
  if (frame && !frame.getAttribute("src")) frame.setAttribute("src", "../mapa");
}

// ---------- Seguimiento y notificaciones ----------
function liberarBlobUrls() {
  state.fotoBlobUrls.forEach((u) => URL.revokeObjectURL(u));
  state.fotoBlobUrls = [];
}

function renderizarDetalleFolio(rep, fotoUrl = null) {
  const cont = $("#folioDetalleBox");
  if (!cont) return;
  if (!rep) {
    cont.hidden = true;
    return;
  }

  const pasos = ["Recibido", "Validado", "Atendido"];
  const descartado = rep.status === "Descartado";
  const idxActual = pasos.indexOf(rep.status);

  const timelineHtml = descartado
    ? `<p class="badge badge-off">Estado final: Descartado tras revisión</p>`
    : `<ol class="folio-steps">${pasos
        .map((p, i) => {
          const done = i <= (idxActual === -1 ? 0 : idxActual);
          return `<li class="${done ? "is-done" : ""}"><span>${esc(p)}</span></li>`;
        })
        .join("")}</ol>`;

  const iaTxt = rep.ai ? `${rep.ai.label} (${Math.round(rep.ai.conf * 100)} %)` : rep.cat;
  const fotoHtml = fotoUrl ? `<img class="folio-photo" src="${esc(fotoUrl)}" alt="Evidencia del reporte ${esc(rep.id)}">` : "";

  cont.hidden = false;
  cont.innerHTML = `
    <div class="ia-head">
      <div>
        <strong class="folio-code">${esc(rep.id)}</strong>
        <p class="small muted">${esc(rep.cat)} · ${esc(formatearFecha(rep.t))}</p>
      </div>
      <span class="badge ${rep.status === "Atendido" ? "badge-ok" : rep.status === "Validado" ? "badge-warn" : "badge-info"}">${esc(rep.status)}</span>
    </div>
    ${timelineHtml}
    <p class="small"><strong>Detección:</strong> ${esc(iaTxt)}</p>
    ${rep.text ? `<p class="small"><strong>Nota:</strong> ${esc(rep.text)}</p>` : ""}
    <p class="small muted">Coordenadas: ${Number(rep.lat).toFixed(4)}, ${Number(rep.lng).toFixed(4)}</p>
    ${fotoHtml}`;
}

async function buscarFolio(folio) {
  const limpio = (folio || "").trim().toUpperCase();
  const errEl = $("#folioError");
  if (errEl) errEl.hidden = true;
  if (!limpio) return;

  try {
    const rep = await verReportePorFolio(limpio);
    liberarBlobUrls();
    let fotoUrl = null;
    if (rep.photo && state.usuario) {
      fotoUrl = await obtenerFotoReporteUrl(rep.id);
      if (fotoUrl) state.fotoBlobUrls.push(fotoUrl);
    }
    renderizarDetalleFolio(rep, fotoUrl);
    guardarFolioLocal(rep);
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message || "No se encontró el folio solicitado.";
      errEl.hidden = false;
    }
  }
}

async function actualizarVistaSeguimiento(folioDirecto = null) {
  await actualizarIndicadorCola();
  if (folioDirecto) {
    if ($("#folioInput")) $("#folioInput").value = folioDirecto;
    await buscarFolio(folioDirecto);
  }

  const listaEl = $("#misReportesLista");
  if (listaEl) {
    listaEl.innerHTML = `<p class="small muted">Consultando reportes...</p>`;
    try {
      const items = state.usuario ? await obtenerMisReportes() : leerFoliosLocales();
      if (!items.length) {
        listaEl.innerHTML = `<p class="small muted">Aún no has enviado reportes desde este dispositivo.</p>`;
      } else {
        listaEl.innerHTML = items
          .map(
            (r) => `
          <button type="button" class="report-row" data-ver-folio="${esc(r.id)}">
            <div>
              <strong>${esc(r.id)} · ${esc(r.cat)}</strong>
              <p class="small muted">${esc(formatearFecha(r.t))}</p>
            </div>
            <span class="badge ${r.status === "Atendido" ? "badge-ok" : "badge-info"}">${esc(r.status)}</span>
          </button>`
          )
          .join("");
      }
    } catch {
      const locales = leerFoliosLocales();
      if (locales.length) {
        listaEl.innerHTML = locales
          .map(
            (r) => `
          <button type="button" class="report-row" data-ver-folio="${esc(r.id)}">
            <div><strong>${esc(r.id)} · ${esc(r.cat)}</strong><p class="small muted">${esc(formatearFecha(r.t))}</p></div>
            <span class="badge badge-info">${esc(r.status)}</span>
          </button>`
          )
          .join("");
      } else {
        listaEl.innerHTML = `<p class="small muted">No se pudieron cargar los reportes (sin conexión con el servidor).</p>`;
      }
    }
  }

  await cargarNotificaciones(false);
}

async function cargarNotificaciones(anunciarNuevas = true) {
  const cont = $("#notificacionesLista");
  const badgeBtn = $("#notifCountBadge");

  if (!state.usuario) {
    if (badgeBtn) badgeBtn.hidden = true;
    if (cont) {
      cont.innerHTML = `<p class="small muted">Inicia sesión para recibir avisos cuando atiendan tus reportes.</p>`;
    }
    return;
  }

  try {
    const lista = await obtenerNotificaciones();
    const noLeidas = lista.filter((n) => !n.leida);
    if (badgeBtn) {
      badgeBtn.textContent = String(noLeidas.length);
      badgeBtn.hidden = noLeidas.length === 0;
    }

    if (anunciarNuevas) {
      noLeidas.forEach((n) => {
        if (!state.avisosVistosIds.has(n.id)) {
          state.avisosVistosIds.add(n.id);
          toast(n.titulo, n.texto, "ok");
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification(n.titulo, { body: n.texto });
          }
        }
      });
    } else {
      lista.forEach((n) => state.avisosVistosIds.add(n.id));
    }

    if (cont) {
      if (!lista.length) {
        cont.innerHTML = `<p class="small muted">Sin avisos todavía. Te notificaremos aquí cuando atiendan tu reporte.</p>`;
      } else {
        cont.innerHTML = lista
          .map(
            (n) => `
          <article class="notif-item ${n.leida ? "" : "is-unread"}">
            <div class="notif-top">
              <strong>${esc(n.titulo)}</strong>
              <span class="small muted">${esc(formatearFecha(n.t))}</span>
            </div>
            <p class="small">${esc(n.texto)}</p>
            ${n.reporte ? `<button type="button" class="btn-link" data-ver-folio="${esc(n.reporte)}">Ver folio ${esc(n.reporte)}</button>` : ""}
          </article>`
          )
          .join("");
      }
    }
  } catch {
    if (cont) {
      cont.innerHTML = `<p class="small muted">No se pudieron consultar tus avisos en este momento.</p>`;
    }
  }
}

// ---------- Cuenta ciudadana ----------
function actualizarHeaderUsuario() {
  const btnCuenta = $("#btnCuenta");
  const anonHint = $("#sesionAnonimaInfo");
  if (state.usuario) {
    if (btnCuenta) {
      btnCuenta.innerHTML = `<i data-lucide="user-check" aria-hidden="true"></i><span>${esc(state.usuario.nombre.split(" ")[0])}</span>`;
    }
    if (anonHint) {
      anonHint.textContent = `Conectado como ${state.usuario.nombre}: recibirás avisos cuando se atienda tu folio.`;
    }
  } else {
    if (btnCuenta) {
      btnCuenta.innerHTML = `<i data-lucide="user" aria-hidden="true"></i><span>Cuenta</span>`;
    }
    if (anonHint) {
      anonHint.textContent = "Toma la foto y la IA identifica el daño automáticamente, incluso sin señal.";
    }
  }
  refrescarIconos();
}

function abrirModalCuenta() {
  const modal = $("#modalCuenta");
  if (!modal) return;
  const vistaLog = $("#cuentaVistaLogin");
  const vistaPerfil = $("#cuentaVistaPerfil");
  if (state.usuario) {
    vistaLog.hidden = true;
    vistaPerfil.hidden = false;
    $("#perfilNombre").textContent = state.usuario.nombre;
    $("#perfilCuenta").textContent = state.usuario.cuenta;
  } else {
    vistaLog.hidden = false;
    vistaPerfil.hidden = true;
  }
  $("#cuentaError").hidden = true;
  modal.hidden = false;
}

function cerrarModalCuenta() {
  const modal = $("#modalCuenta");
  if (modal) modal.hidden = true;
}

// «¿Qué somos?»: qué es EcoRed, cómo se atiende un reporte y el acceso de Administración
let focoAntesDeQueSomos = null;
function abrirQueSomos() {
  const modal = $("#modalQueSomos");
  if (!modal) return;
  focoAntesDeQueSomos = document.activeElement;
  modal.hidden = false;
  $("#tituloQueSomos")?.focus();
}

function cerrarQueSomos() {
  const modal = $("#modalQueSomos");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  if (focoAntesDeQueSomos && typeof focoAntesDeQueSomos.focus === "function") focoAntesDeQueSomos.focus();
}

function inicializarCuenta() {
  let modoRegistro = false;
  const tabEntrar = $("#tabAuthEntrar");
  const tabReg = $("#tabAuthRegistro");
  const campoNombre = $("#campoNombreRegistro");
  const submitBtn = $("#btnAuthSubmit");

  function fijarModo(registro) {
    modoRegistro = registro;
    tabEntrar.classList.toggle("is-active", !registro);
    tabReg.classList.toggle("is-active", registro);
    campoNombre.hidden = !registro;
    submitBtn.textContent = registro ? "Crear cuenta ciudadana" : "Iniciar sesión";
    $("#cuentaError").hidden = true;
  }

  tabEntrar?.addEventListener("click", () => fijarModo(false));
  tabReg?.addEventListener("click", () => fijarModo(true));
  $("#btnCuenta")?.addEventListener("click", abrirModalCuenta);
  $("#btnCerrarCuenta")?.addEventListener("click", cerrarModalCuenta);

  $("#formCuenta")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const errEl = $("#cuentaError");
    errEl.hidden = true;
    const cuenta = ($("#authCuenta").value || "").trim();
    const clave = $("#authClave").value || "";
    const nombre = ($("#authNombre").value || "").trim();

    try {
      const res = modoRegistro
        ? await registrarCiudadano(nombre, cuenta, clave)
        : await entrarApp(cuenta, clave);
      // Cuenta del personal (no ciudadana): su lugar es la plataforma de gobierno, con el menú de su rol
      if (res.usuario.rol !== "ciudadano") {
        submitBtn.disabled = true;
        toast("Cuenta del personal", "Abriendo la plataforma de gobierno con tu rol…", "info");
        if (!obtenerApiBase()) {
          await entrarPlataforma(cuenta, clave);              // misma contraseña: abre la sesión de la plataforma
          window.location.href = "/#/resumen";
        } else {
          window.location.href = `${obtenerApiBase()}/login.html`;   // la app vive en otro sitio: que entre ahí
        }
        return;
      }
      state.usuario = res.usuario;
      actualizarHeaderUsuario();
      cerrarModalCuenta();
      toast("Sesión iniciada", `Bienvenido, ${res.usuario.nombre}.`, "ok");
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
      }
      await cargarNotificaciones(false);
      if (state.vistaActual === "seguimiento") await actualizarVistaSeguimiento();
    } catch (err) {
      errEl.textContent = err.message || "Revisa los datos ingresados.";
      errEl.hidden = false;
      submitBtn.disabled = false;
    }
  });

  $("#btnCerrarSesion")?.addEventListener("click", async () => {
    await salirApp();
    state.usuario = null;
    actualizarHeaderUsuario();
    cerrarModalCuenta();
    await cargarNotificaciones(false);
    if (state.vistaActual === "seguimiento") await actualizarVistaSeguimiento();
    toast("Sesión cerrada", "Puedes seguir reportando de forma anónima.", "info");
  });
}

// ---------- Inicialización ----------
async function iniciar() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }

  inicializarSelectorOpcional();
  inicializarReferencias();
  inicializarCuenta();

  miniMapa = crearMiniMapaUbicacion("miniMapaReporte", {
    onCambio: actualizarEtiquetaUbicacion,
  });
  actualizarEtiquetaUbicacion(state.lat, state.lng, state.fuenteUbicacion);
  inicializarMapaReporte3d();


  const camCtrl = crearControladorCamara({
    modalEl: $("#modalCamara"),
    videoEl: $("#camaraVideo"),
    errorEl: $("#camaraError"),
    onCaptura: aplicarFotoCapturada,
  });

  $("#btnAbrirCamara")?.addEventListener("click", () => camCtrl.abrir());
  $("#btnCerrarCamara")?.addEventListener("click", () => camCtrl.detener());
  $("#btnCapturarCamara")?.addEventListener("click", () => camCtrl.tomarFoto());
  $("#btnQuitarFoto")?.addEventListener("click", limpiarFoto);

  const manejarInputArchivo = async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    try {
      const procesada = await procesarArchivoFoto(file);
      await aplicarFotoCapturada(procesada);
    } catch (err) {
      toast("No se pudo cargar la foto", err.message, "warn");
    }
  };
  $("#inputFotoCamara")?.addEventListener("change", manejarInputArchivo);

  $("#btnObtenerGps")?.addEventListener("click", async () => {
    const btn = $("#btnObtenerGps");
    const etiqueta = btn.querySelector("span");
    btn.disabled = true;
    try {
      // Cada lectura mejor mueve el pin; se detiene al bajar a PRECISION_MAX_M o menos (o a los 30 s con la mejor que hubo)
      const gps = await obtenerGpsDispositivo({
        onAvance: (lectura) => {
          if (etiqueta) etiqueta.textContent = `Afinando GPS… ±${lectura.precision} m`;
          if (lectura.dentroPuebla) {
            miniMapa?.fijar(lectura.lat, lectura.lng, `GPS ±${lectura.precision} m`, ZOOM_EXACTO,
              { origen: "gps", precision: lectura.precision });
          }
        },
      });
      if (!gps.dentroPuebla) {
        toast("GPS fuera de Puebla", "Tus coordenadas están fuera del Alto Atoyac. Marca el punto en el mapa.", "warn");
      } else if (gps.precision <= PRECISION_MAX_M) {
        toast("Lugar del suceso fijado", `GPS con ±${gps.precision} m de margen.`, "ok");
      } else {
        toast(`El GPS no bajó de ${PRECISION_MAX_M} m`, `Marca ±${gps.precision} m. Sal a cielo abierto y vuelve a intentar, o mueve el pin al punto exacto.`, "warn");
      }
    } catch (err) {
      toast("GPS no disponible", err.message, "warn");
    } finally {
      btn.disabled = false;
      if (etiqueta) etiqueta.textContent = "Mi GPS";
    }
  });

  let recVoz = null;
  $("#btnDictarVoz")?.addEventListener("click", () => {
    if (recVoz) {
      recVoz.stop();
      recVoz = null;
      return;
    }
    const btnVoz = $("#btnDictarVoz");
    recVoz = iniciarDictadoVoz({
      onEstado: (activo) => {
        btnVoz.classList.toggle("is-recording", activo);
        btnVoz.setAttribute("aria-pressed", activo ? "true" : "false");
        btnVoz.querySelector("span").textContent = activo ? "Escuchando..." : "Dictar";
      },
      onTexto: (txt) => {
        const input = $("#descripcionInput");
        input.value = input.value ? `${input.value} ${txt}` : txt;
        state.usoVoz = true;
      },
      onError: (msg) => toast("Nota de voz", msg, "warn"),
    });
  });

  $("#formReporte")?.addEventListener("submit", manejarEnvioReporte);
  $("#formBuscarFolio")?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    buscarFolio($("#folioInput")?.value);
  });
  $("#btnMarcarLeidas")?.addEventListener("click", async () => {
    await marcarNotificacionesLeidas();
    await cargarNotificaciones(false);
  });
  $("#btnSyncCola")?.addEventListener("click", () => intentarSincronizar(false));
  // El logo lleva a la portada del sitio; en la app instalada o sin señal la portada no está, así que se queda en Reportar
  $(".brand")?.addEventListener("click", (ev) => {
    const instalada = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
    if (instalada || !navigator.onLine) {
      ev.preventDefault();
      window.location.hash = "#/reportar";
    }
  });
  $("#btnQueSomos")?.addEventListener("click", abrirQueSomos);
  $("#btnCerrarQueSomos")?.addEventListener("click", cerrarQueSomos);
  $("#modalQueSomos")?.addEventListener("click", (ev) => {
    if (ev.target === ev.currentTarget) cerrarQueSomos();          // clic fuera del panel
  });
  $("#btnQueSomosReportar")?.addEventListener("click", () => {
    cerrarQueSomos();
    window.location.hash = "#/reportar";
  });

  document.addEventListener("click", (ev) => {
    const folioBtn = ev.target.closest("[data-ver-folio]");
    if (folioBtn) {
      window.location.hash = `#/seguimiento/${folioBtn.dataset.verFolio}`;
      return;
    }
    const mapBtn = ev.target.closest("[data-ir-mapa]");
    if (mapBtn) {
      window.location.hash = "#/mapa";
    }
  });

  $$("[data-nav]").forEach((btn) => {
    btn.addEventListener("click", () => {
      window.location.hash = `#/${btn.dataset.nav}`;
    });
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      camCtrl.detener();
      cerrarModalCuenta();
      cerrarQueSomos();
    }
  });

  window.addEventListener("hashchange", leerRutaHash);
  window.addEventListener("online", () => {
    actualizarIndicadorCola();
    intentarSincronizar(true);
  });
  window.addEventListener("offline", actualizarIndicadorCola);

  // Íconos de la página antes de esperar al servidor o a la cola sin señal: si eso tarda, no se quedan sin dibujar
  refrescarIconos();
  state.usuario = leerSesionLocal().usuario;
  actualizarHeaderUsuario();
  const verificado = await verificarSesion();
  state.usuario = verificado;
  actualizarHeaderUsuario();

  await actualizarIndicadorCola();
  leerRutaHash();
  cargarEstadoCuenca();
  cargarNotificaciones(false);

  conectarEventosWS(
    () => {
      cargarEstadoCuenca();
      cargarNotificaciones(true);
      if (state.vistaActual === "seguimiento" && $("#folioInput")?.value) {
        buscarFolio($("#folioInput").value);
      }
    },
    (conectado) => {
      state.wsConectado = conectado;
    }
  );
  setInterval(() => cargarNotificaciones(true), 20000);
  refrescarIconos();
}

document.addEventListener("DOMContentLoaded", iniciar);
