/* =========================================================
   Adaptador de API REST + WebSocket hacia plataforma/server/main.py
   Usa Authorization: Bearer <token> (origen: "app").
   ========================================================= */

const STORAGE_TOKEN = "ecored_token";
const STORAGE_USER = "ecored_usuario";
const STORAGE_CACHE_ESTADO = "ecored_cache_estado";
const STORAGE_API_BASE = "ecored_api_base";

export function obtenerApiBase() {
  const guardado = localStorage.getItem(STORAGE_API_BASE);
  if (guardado) return guardado.replace(/\/+$/, "");
  // Si se sirve desde FastAPI (/app/) usa mismo origen ("")
  if (window.location.port === "8000" || window.location.pathname.startsWith("/app")) {
    return "";
  }
  return "";
}

export function guardarToken(token, usuario) {
  if (token) localStorage.setItem(STORAGE_TOKEN, token);
  if (usuario) localStorage.setItem(STORAGE_USER, JSON.stringify(usuario));
}

export function limpiarSesion() {
  localStorage.removeItem(STORAGE_TOKEN);
  localStorage.removeItem(STORAGE_USER);
}

export function leerSesionLocal() {
  const token = localStorage.getItem(STORAGE_TOKEN) || "";
  let usuario = null;
  try {
    const raw = localStorage.getItem(STORAGE_USER);
    if (raw) usuario = JSON.parse(raw);
  } catch {
    usuario = null;
  }
  return { token, usuario };
}

async function pedirJson(ruta, opts = {}) {
  const { token } = leerSesionLocal();
  const headers = new Headers(opts.headers || {});
  // Si en el mismo navegador hay una sesión de la plataforma (cookie), el servidor exige esta cabecera
  // en los envíos; sin ella un reporte anónimo sería rechazado con 403
  if (!headers.has("X-VA")) headers.set("X-VA", "1");
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  let resp;
  try {
    resp = await fetch(`${obtenerApiBase()}${ruta}`, {
      method: opts.method || "GET",
      headers,
      body: opts.json !== undefined ? JSON.stringify(opts.json) : opts.body,
    });
  } catch (netErr) {
    const err = new Error("Sin conexión con el servidor de EcoRed Puebla.");
    err.esRed = true;
    throw err;
  }

  let payload = null;
  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    payload = await resp.json().catch(() => null);
  }
  if (!resp.ok) {
    const msg = (payload && payload.detail) || `Error del servidor (${resp.status})`;
    const err = new Error(msg);
    err.status = resp.status;
    throw err;
  }
  return payload;
}

export async function entrarApp(cuenta, clave) {
  const res = await pedirJson("/api/auth/entrar", {
    method: "POST",
    json: { cuenta, clave, origen: "app" },
  });
  guardarToken(res.token, res.usuario);
  return res;
}

export async function registrarCiudadano(nombre, cuenta, clave) {
  const res = await pedirJson("/api/auth/registro", {
    method: "POST",
    json: { nombre, cuenta, clave, origen: "app" },
  });
  guardarToken(res.token, res.usuario);
  return res;
}

export async function salirApp() {
  try {
    await pedirJson("/api/auth/salir", { method: "POST" });
  } catch {
    // Aunque falle red, limpiamos localmente
  } finally {
    limpiarSesion();
  }
}

export async function verificarSesion() {
  const { token } = leerSesionLocal();
  if (!token) return null;
  try {
    const res = await pedirJson("/api/auth/yo");
    if (!res || !res.usuario) {
      limpiarSesion();
      return null;
    }
    guardarToken(token, res.usuario);
    return res.usuario;
  } catch (err) {
    if (err.status === 401) limpiarSesion();
    return leerSesionLocal().usuario;
  }
}

export async function enviarReporte(datos) {
  const form = new FormData();
  form.append("cat", datos.cat);
  form.append("lat", String(datos.lat));
  form.append("lng", String(datos.lng));
  form.append("texto", (datos.texto || "").slice(0, 500));
  form.append("anonimo", datos.anonimo ? "true" : "false");
  form.append("voz", datos.voz ? "true" : "false");
  // Lugar del suceso: "gps" con su margen en metros (5 o menos) o "mapa" si se marcó a mano
  if (datos.ubicacion) form.append("ubicacion", datos.ubicacion);
  if (datos.precision_m !== null && datos.precision_m !== undefined) form.append("precision_m", String(datos.precision_m));

  if (datos.ia_etiqueta) {
    form.append("ia_etiqueta", datos.ia_etiqueta);
    if (datos.ia_confianza !== null && datos.ia_confianza !== undefined) {
      form.append("ia_confianza", String(datos.ia_confianza));
    }
  }
  if (datos.fotoBlob) {
    form.append("foto", datos.fotoBlob, datos.fotoNombre || "evidencia.jpg");
  }

  return pedirJson("/api/reportes", { method: "POST", body: form });
}

export async function obtenerEstadoCuenca() {
  try {
    const data = await pedirJson("/api/estado");
    try {
      localStorage.setItem(STORAGE_CACHE_ESTADO, JSON.stringify({ guardadoEn: Date.now(), data }));
    } catch {
      // Ignora cuota llena
    }
    return { data, desdeCache: false, guardadoEn: Date.now() };
  } catch (err) {
    const raw = localStorage.getItem(STORAGE_CACHE_ESTADO);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { data: parsed.data, desdeCache: true, guardadoEn: parsed.guardadoEn };
    }
    throw err;
  }
}

export async function obtenerMisReportes() {
  return pedirJson("/api/reportes?mios=true");
}

// Riesgo para la salud por contacto con el agua, por tramo (público)
export async function obtenerRiesgo() {
  return pedirJson("/api/riesgo");
}

export async function verReportePorFolio(folio) {
  return pedirJson(`/api/reportes/${encodeURIComponent(folio.trim().toUpperCase())}`);
}

export async function obtenerFotoReporteUrl(folio) {
  const { token } = leerSesionLocal();
  if (!token) return null;
  const resp = await fetch(`${obtenerApiBase()}/api/reportes/${encodeURIComponent(folio)}/foto`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) return null;
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

export async function obtenerNotificaciones() {
  const { token } = leerSesionLocal();
  if (!token) return [];
  return pedirJson("/api/notificaciones");
}

export async function marcarNotificacionesLeidas() {
  const { token } = leerSesionLocal();
  if (!token) return;
  return pedirJson("/api/notificaciones/leidas", { method: "POST" });
}

export function conectarEventosWS(onEvento, onEstadoConexion) {
  let ws = null;
  let activo = true;
  let timer = null;

  function abrir() {
    if (!activo) return;
    const base = obtenerApiBase();
    let wsUrl;
    if (base.startsWith("http")) {
      wsUrl = `${base.replace(/^http/, "ws")}/ws/eventos`;
    } else {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${proto}//${window.location.host}/ws/eventos`;
    }
    try {
      ws = new WebSocket(wsUrl);
    } catch {
      onEstadoConexion?.(false);
      timer = setTimeout(abrir, 5000);
      return;
    }

    ws.onopen = () => onEstadoConexion?.(true);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        onEvento?.(msg);
      } catch {
        // Ignorar mensajes no JSON
      }
    };
    ws.onerror = () => onEstadoConexion?.(false);
    ws.onclose = () => {
      onEstadoConexion?.(false);
      if (activo) timer = setTimeout(abrir, 5000);
    };
  }

  abrir();
  return () => {
    activo = false;
    if (timer) clearTimeout(timer);
    if (ws) ws.close();
  };
}
