/* =========================================================
   Captura de cámara, compresión JPEG, EXIF GPS, mini-mapa y voz
   ========================================================= */
import { CONFIG, REFERENCIAS_CUENCA, estaEnPuebla } from "./config.js";
import { extraerExifGps } from "./exif.js";

export async function comprimirImagen(archivoOBlob, maxLado = 1280, calidad = 0.84) {
  const url = URL.createObjectURL(archivoOBlob);
  try {
    const img = await new Promise((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("No se pudo abrir la fotografía."));
      el.src = url;
    });

    let { width, height } = img;
    if (width > maxLado || height > maxLado) {
      const ratio = Math.min(maxLado / width, maxLado / height);
      width = Math.max(1, Math.round(width * ratio));
      height = Math.max(1, Math.round(height * ratio));
    }

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, width, height);

    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("Error al comprimir la imagen."))),
        "image/jpeg",
        calidad
      );
    });
    return blob;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function procesarArchivoFoto(file) {
  let exifGps = null;
  if (file.type === "image/jpeg" || /\.jpe?g$/i.test(file.name || "")) {
    try {
      const buf = await file.slice(0, 256 * 1024).arrayBuffer();
      exifGps = extraerExifGps(buf);
    } catch {
      exifGps = null;
    }
  }
  const blobComprimido = await comprimirImagen(file);
  const previewUrl = URL.createObjectURL(blobComprimido);
  return {
    blob: blobComprimido,
    nombre: (file.name || "captura.jpg").replace(/\.[^.]+$/, "") + ".jpg",
    previewUrl,
    exifGps,
  };
}

export function crearControladorCamara({ modalEl, videoEl, errorEl, onCaptura }) {
  let stream = null;

  function detener() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    videoEl.srcObject = null;
    modalEl.hidden = true;
  }

  async function abrir() {
    errorEl.hidden = true;
    errorEl.textContent = "";
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      errorEl.textContent = "Este navegador no permite cámara en vivo aquí (usa HTTPS o el botón de cámara nativa).";
      errorEl.hidden = false;
      modalEl.hidden = false;
      return;
    }

    modalEl.hidden = false;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      videoEl.srcObject = stream;
      await videoEl.play();
    } catch {
      errorEl.textContent = "No se pudo acceder a la cámara. Verifica permisos o usa «Subir o tomar foto».";
      errorEl.hidden = false;
    }
  }

  async function tomarFoto() {
    if (!stream || !videoEl.videoWidth) return;
    const w = videoEl.videoWidth;
    const h = videoEl.videoHeight;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d").drawImage(videoEl, 0, 0, w, h);

    const rawBlob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    detener();
    if (!rawBlob) return;
    const blob = await comprimirImagen(rawBlob);
    const previewUrl = URL.createObjectURL(blob);
    onCaptura({
      blob,
      nombre: `camara-${Date.now()}.jpg`,
      previewUrl,
      exifGps: null,
    });
  }

  return { abrir, detener, tomarFoto };
}

// El reporte marca el lugar del suceso: GPS con 5 m o menos de margen, o el punto marcado a mano con el mapa
// a nivel de calle (zoom 18: unos 0.6 m por píxel en Puebla), donde se puede atinar a pocos metros
export const PRECISION_MAX_M = 5;
export const ZOOM_EXACTO = 18;

export function crearMiniMapaUbicacion(contenedorId, { onCambio }) {
  const L = window.L;
  if (!L) return null;

  const inicial = REFERENCIAS_CUENCA[0];
  const map = L.map(contenedorId, { zoomControl: true, scrollWheelZoom: false }).setView(
    [inicial.lat, inicial.lng],
    13
  );
  L.tileLayer(CONFIG.MAP_TILES_URL, { maxZoom: 19, attribution: CONFIG.MAP_ATTRIBUTION }).addTo(map);

  const marker = L.marker([inicial.lat, inicial.lng], { draggable: true }).addTo(map);
  // Marcado a mano: solo cuenta como el punto exacto con el mapa a nivel de calle; si está más lejos,
  // primero se acerca ahí para que la persona afine el pin
  const marcarAMano = (lat, lng) => {
    const exacto = map.getZoom() >= ZOOM_EXACTO;
    // Sin animación: así el siguiente toque ya ve el zoom nuevo aunque llegue enseguida
    if (!exacto) map.setView([lat, lng], ZOOM_EXACTO, { animate: false });
    onCambio(Number(lat.toFixed(6)), Number(lng.toFixed(6)), exacto ? "marcado en el mapa" : "acerca el mapa",
      { origen: exacto ? "mapa" : null });
  };
  marker.on("dragend", () => {
    const pos = marker.getLatLng();
    marcarAMano(pos.lat, pos.lng);
  });
  map.on("click", (e) => {
    marker.setLatLng(e.latlng);
    marcarAMano(e.latlng.lat, e.latlng.lng);
  });

  return {
    fijar(lat, lng, fuente, zoom = 15, info = {}) {
      marker.setLatLng([lat, lng]);
      map.setView([lat, lng], zoom);
      onCambio(Number(lat.toFixed(6)), Number(lng.toFixed(6)), fuente, info);
    },
    invalidarTamano() {
      setTimeout(() => map.invalidateSize(), 80);
    },
  };
}

// La primera lectura del GPS suele traer 10–60 m de margen: se sigue escuchando hasta bajar a 5 m o menos
// (o hasta `maxMs`) y se devuelve la mejor lectura. `onAvance` recibe cada mejora para mostrarla.
export function obtenerGpsDispositivo({ onAvance, maxMs = 30000 } = {}) {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("Tu navegador no soporta geolocalización. Marca el punto exacto en el mapa."));
      return;
    }
    let mejor = null;
    let vigilancia = null;
    let reloj = null;
    let terminado = false;
    const terminar = (fin) => {
      if (terminado) return;
      terminado = true;
      if (vigilancia !== null) navigator.geolocation.clearWatch(vigilancia);
      clearTimeout(reloj);
      fin();
    };
    vigilancia = navigator.geolocation.watchPosition(
      (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(6));
        const lng = Number(pos.coords.longitude.toFixed(6));
        const precision = Math.max(1, Math.round(pos.coords.accuracy || 999));
        if (!mejor || precision < mejor.precision) {
          mejor = { lat, lng, precision, dentroPuebla: estaEnPuebla(lat, lng) };
          onAvance?.(mejor);
        }
        if (mejor.precision <= PRECISION_MAX_M) terminar(() => resolve(mejor));
      },
      (err) => {
        if (err.code === 1) terminar(() => reject(new Error("Permiso de ubicación denegado. Marca el punto exacto en el mapa.")));
        // Sin señal por un momento: se sigue esperando hasta el tiempo límite
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: maxMs }
    );
    reloj = setTimeout(() => terminar(() => (mejor
      ? resolve(mejor)
      : reject(new Error("No se obtuvo señal GPS. Sal a cielo abierto o marca el punto exacto en el mapa.")))), maxMs);
  });
}

export function iniciarDictadoVoz({ onTexto, onEstado, onError }) {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) {
    onError("El dictado por voz no está disponible en este navegador. Puedes escribir tu descripción.");
    return null;
  }
  const rec = new Speech();
  rec.lang = "es-MX";
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  rec.onstart = () => onEstado(true);
  rec.onend = () => onEstado(false);
  rec.onerror = () => {
    onEstado(false);
    onError("No se pudo capturar audio. Verifica el permiso de micrófono o escribe el texto.");
  };
  rec.onresult = (event) => {
    const transcript = event.results?.[0]?.[0]?.transcript || "";
    if (transcript.trim()) onTexto(transcript.trim());
  };

  rec.start();
  return rec;
}
