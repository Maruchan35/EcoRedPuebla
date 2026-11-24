/* =========================================================
   Cola persistente en IndexedDB para reportes tomados sin internet
   Guarda el Blob de la foto comprimida + GPS + clasificación IA local.
   ========================================================= */

const DB_NAME = "ecored_puebla_offline";
const DB_VERSION = 1;
const STORE = "cola_reportes";

function abrirBd() {
  return new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) {
      reject(new Error("IndexedDB no disponible"));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "localId" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("No se pudo abrir la cola offline"));
  });
}

export async function encolarReporte(registro) {
  const db = await abrirBd();
  const item = {
    localId: registro.localId || `pend-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    creadoEn: Date.now(),
    cat: registro.cat,
    lat: registro.lat,
    lng: registro.lng,
    texto: registro.texto || "",
    anonimo: Boolean(registro.anonimo),
    voz: Boolean(registro.voz),
    ia_etiqueta: registro.ia_etiqueta || "",
    ia_confianza: registro.ia_confianza ?? null,
    fotoBlob: registro.fotoBlob || null,
    fotoNombre: registro.fotoNombre || "reporte.jpg",
  };

  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(item);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error || new Error("Error guardando en cola local"));
  });
  db.close();
  window.dispatchEvent(new CustomEvent("ecored:cola-cambio"));
  return item;
}

export async function listarCola() {
  try {
    const db = await abrirBd();
    const items = await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return items.sort((a, b) => b.creadoEn - a.creadoEn);
  } catch {
    return [];
  }
}

export async function eliminarDeCola(localId) {
  const db = await abrirBd();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(localId);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
  window.dispatchEvent(new CustomEvent("ecored:cola-cambio"));
}

export async function sincronizarCola(enviarFn) {
  const pendientes = await listarCola();
  if (!pendientes.length) return { enviados: [], fallidos: 0 };

  const enviados = [];
  let fallidos = 0;

  for (const item of pendientes) {
    try {
      const respuesta = await enviarFn(item);
      await eliminarDeCola(item.localId);
      enviados.push({ localId: item.localId, respuesta });
    } catch (err) {
      // Si es un error de validación 4xx permanente, quitamos el bucle infinito solo si el servidor rechazó el formato
      if (err && err.status && err.status >= 400 && err.status < 500 && err.status !== 401 && err.status !== 429) {
        await eliminarDeCola(item.localId);
      }
      fallidos++;
    }
  }
  return { enviados, fallidos };
}
