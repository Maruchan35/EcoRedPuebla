/* =========================================================
   Mapa interactivo y Mapa de Calor 2D (Leaflet + leaflet.heat)
   Muestra puntos calientes de ríos, barrancas y zonas de recarga.
   ========================================================= */
import { CATEGORIAS, CONFIG, SEM_META } from "./config.js";

function esc(txt) {
  return String(txt ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function haceCuanto(ts) {
  if (!ts) return "sin fecha";
  const mins = Math.max(1, Math.round((Date.now() - ts) / 60000));
  if (mins < 60) return `hace ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `hace ${hrs} h`;
  const dias = Math.round(hrs / 24);
  return `hace ${dias} día${dias === 1 ? "" : "s"}`;
}

function pesoCategoria(cat) {
  const found = CATEGORIAS.find((c) => c.id === cat);
  return found ? found.pesoCalor : 0.7;
}

function estadoNodo(nodo, history, params, staleDays) {
  const arr = history?.[nodo.id] || [];
  const last = arr.length ? arr[arr.length - 1] : null;
  const viejo = !nodo.lastSync || Date.now() - nodo.lastSync > (staleDays || 7) * 86400000;
  if (!last || viejo) return "off";
  if (Array.isArray(last.anom) && last.anom.length > 0) return "crit";
  if (params) {
    if (last.ph < params.ph?.critMin || last.ph > params.ph?.critMax || last.cond >= params.cond?.crit || last.turb >= params.turb?.crit || last.color >= params.color?.crit) {
      return "crit";
    }
    if (last.ph < params.ph?.min || last.ph > params.ph?.max || last.cond >= params.cond?.warn || last.turb >= params.turb?.warn || last.color >= params.color?.warn) {
      return "warn";
    }
  }
  return "ok";
}

export function crearMapaCalor(contenedorId) {
  const L = window.L;
  if (!L) return null;

  const map = L.map(contenedorId, { zoomControl: true, scrollWheelZoom: true }).setView(CONFIG.CENTER, CONFIG.DEFAULT_ZOOM);
  L.tileLayer(CONFIG.MAP_TILES_URL, { maxZoom: 19, attribution: CONFIG.MAP_ATTRIBUTION }).addTo(map);

  const capaTramos = L.layerGroup().addTo(map);
  const capaNodos = L.layerGroup().addTo(map);
  const capaReportes = L.layerGroup().addTo(map);
  let capaCalor = null;
  let mostrarCalor = true;
  let mostrarReportes = true;
  let mostrarRed = true;
  let ultimoEstado = null;

  function render() {
    if (!ultimoEstado) return;
    const { nodes = [], tramos = [], barriers = [], history = {}, reports = [], cases = [], params = null, staleDays = 7 } = ultimoEstado;

    capaTramos.clearLayers();
    capaNodos.clearLayers();
    capaReportes.clearLayers();
    if (capaCalor) {
      map.removeLayer(capaCalor);
      capaCalor = null;
    }

    // 1. Tramos del río y nodos de referencia
    if (mostrarRed) {
      const estadoPorNodo = {};
      nodes.forEach((n) => {
        estadoPorNodo[n.id] = estadoNodo(n, history, params, staleDays);
      });

      tramos.forEach((t) => {
        const sem = estadoPorNodo[t.to] || "off";
        const meta = SEM_META[sem] || SEM_META.off;
        const line = L.polyline(t.points, { color: meta.color, weight: 6, opacity: 0.8 });
        line.bindPopup(`<strong>${esc(t.id)} · ${esc(t.name)}</strong><br>Estado: <strong>${esc(meta.label)}</strong>`);
        line.bindTooltip(`${t.id}: ${meta.label}`, { sticky: true });
        line.addTo(capaTramos);
      });

      nodes.forEach((n) => {
        const sem = estadoPorNodo[n.id] || "off";
        const meta = SEM_META[sem] || SEM_META.off;
        const marker = L.circleMarker([n.lat, n.lng], {
          radius: 7,
          color: "#0F172A",
          weight: 2,
          fillColor: meta.color,
          fillOpacity: 0.95,
        });
        marker.bindPopup(
          `<strong>${esc(n.id)} · ${esc(n.name)}</strong><br>Estado: <strong>${esc(meta.label)}</strong><br>` +
          `<span class="small muted">Última visita: ${esc(haceCuanto(n.lastSync))}</span>`
        );
        marker.addTo(capaNodos);
      });

      barriers.forEach((b) => {
        const crit = b.fill >= 90 || b.nivel >= b.nivelMax * 0.85;
        const warn = !crit && (b.fill >= 70 || b.nivel >= b.nivelMax * 0.6);
        const col = crit ? "#B91C1C" : warn ? "#B45309" : "#0E7490";
        const marker = L.circleMarker([b.lat, b.lng], {
          radius: 6,
          color: "#FFFFFF",
          weight: 2,
          fillColor: col,
          fillOpacity: 0.95,
        });
        marker.bindPopup(
          `<strong>Barrera ${esc(b.id)} · ${esc(b.name)}</strong><br>` +
          `Llenado: ${Math.round(b.fill)}% · Nivel: ${Number(b.nivel).toFixed(2)} m`
        );
        marker.addTo(capaNodos);
      });
    }

    // 2. Reportes ciudadanos y casos activos en el mapa de calor
    const puntosCalor = [];

    reports.forEach((r) => {
      const pesoBase = pesoCategoria(r.cat);
      const boostIa = r.ai && r.ai.conf ? 0.15 * r.ai.conf : 0;
      const intensidad = Math.min(1.0, pesoBase + boostIa);
      puntosCalor.push([r.lat, r.lng, intensidad]);

      if (mostrarReportes) {
        const esCritico = r.cat === "Agua de color" || r.cat === "Descarga de tubería";
        const color = r.status === "Atendido" ? "#15803D" : esCritico ? "#B91C1C" : "#B45309";
        const marker = L.circleMarker([r.lat, r.lng], {
          radius: r.mine ? 9 : 7,
          color: r.mine ? "#0F172A" : "#FFFFFF",
          weight: r.mine ? 2.5 : 1.8,
          fillColor: color,
          fillOpacity: 0.9,
        });
        const iaHtml = r.ai
          ? `<br><span class="small">IA: <strong>${esc(r.ai.label)}</strong> (${Math.round(r.ai.conf * 100)} %)</span>`
          : "";
        const textoHtml = r.text ? `<br>${esc(r.text)}` : "";
        const mineTag = r.mine ? " · Tuyo" : "";
        marker.bindPopup(
          `<strong>${esc(r.cat)}</strong> (${esc(r.id)}${mineTag})<br>` +
          `Estado: <strong>${esc(r.status)}</strong> · ${esc(haceCuanto(r.t))}` +
          iaHtml +
          textoHtml
        );
        marker.addTo(capaReportes);
      }
    });

    // Nodos críticos y casos abiertos también aportan peso térmico
    cases.filter((c) => c.status !== "Cerrado").forEach((c) => {
      if (Number.isFinite(c.lat) && Number.isFinite(c.lng)) {
        puntosCalor.push([c.lat, c.lng, c.priority === "Alta" ? 0.95 : 0.65]);
      }
    });

    // 3. Capa de Mapa de Calor (leaflet.heat) solo cuando el contenedor es visible y tiene dimensiones reales
    const tam = map.getSize();
    if (mostrarCalor && typeof L.heatLayer === "function" && puntosCalor.length > 0 && tam && tam.x > 0 && tam.y > 0) {
      capaCalor = L.heatLayer(puntosCalor, {
        radius: 28,
        blur: 22,
        maxZoom: 15,
        max: 1.0,
        gradient: {
          0.25: "#0E7490",
          0.55: "#F59E0B",
          0.8: "#EA580C",
          1.0: "#B91C1C",
        },
      }).addTo(map);
    }

    return {
      totalReportes: reports.length,
      puntosCalor: puntosCalor.length,
    };
  }

  return {
    actualizar(estado) {
      ultimoEstado = estado;
      return render();
    },
    fijarCapas({ calor, reportes, red }) {
      if (calor !== undefined) mostrarCalor = calor;
      if (reportes !== undefined) mostrarReportes = reportes;
      if (red !== undefined) mostrarRed = red;
      return render();
    },
    centrarEn(lat, lng, zoom = 14) {
      map.setView([lat, lng], zoom);
    },
    ajustarCuenca() {
      if (ultimoEstado && ultimoEstado.nodes && ultimoEstado.nodes.length) {
        const pts = ultimoEstado.nodes.map((n) => [n.lat, n.lng]);
        map.fitBounds(L.latLngBounds(pts).pad(0.16));
      } else {
        map.setView(CONFIG.CENTER, CONFIG.DEFAULT_ZOOM);
      }
    },
    ocultarCalorTemporal() {
      if (capaCalor) {
        map.removeLayer(capaCalor);
        capaCalor = null;
      }
    },
    invalidarTamano() {
      if (capaCalor) {
        map.removeLayer(capaCalor);
        capaCalor = null;
      }
      map.invalidateSize();
      if (ultimoEstado) render();
      requestAnimationFrame(() => {
        map.invalidateSize();
        if (ultimoEstado && !capaCalor && mostrarCalor) render();
      });
    },
  };
}
