/* =========================================================
   Vistas de la plataforma. Cada vista recibe el contenedor
   principal y devuelve { update(msg), destroy() } para recibir
   avisos en vivo y limpiar mapas y gráficas al salir.

   msg.tipo === "sync"    → con servidor: los datos se recargaron
   msg.tipo === "lectura" → demo sin servidor: llegó una lectura
   ========================================================= */
(function () {
  const { esc, icon, fmt, badge, stateBadge, prioBadge, refreshIcons, toast } = VA.ui;
  const C = VA.config, E = VA.engine;
  const S = () => VA.store;
  const MOCK = VA.api.USE_MOCK;
  const DAY = 86400000;

  // ---------- Ayudas compartidas ----------
  const lastReading = id => VA.map.lastOf(id);
  const role = () => VA.state.role;
  const demoOn = () => MOCK || VA.session.demo;
  const canSeeCases = () => VA.can("casos") && C.roles[role()].deps.length > 0;
  const visibleCases = () => canSeeCases() ? S().cases.filter(c => C.roles[role()].deps.includes(c.dep)) : [];
  const openCases = list => list.filter(c => c.status !== "Cerrado");
  const caseType = c => C.tiposCaso[c.type];
  const fail = (err, title = "No se pudo guardar") => toast("warn", title, err && err.message ? err.message : String(err));
  function placeName(lat, lng) {
    const pts = [...S().nodes.map(n => ({ name: n.name, lat: n.lat, lng: n.lng })), ...S().barriers.map(b => ({ name: b.name, lat: b.lat, lng: b.lng }))];
    pts.sort((a, b) => E.km(lat, lng, a.lat, a.lng) - E.km(lat, lng, b.lat, b.lng));
    return pts.length ? pts[0].name : "la cuenca";
  }
  function casePlace(c) {
    const t = c.tramo && S().tramos.find(t => t.id === c.tramo);
    if (t) return t.id + " · " + t.name;
    const b = c.barrier && S().barriers.find(b => b.id === c.barrier);
    if (b) return b.name;
    return "Cerca de " + placeName(c.lat, c.lng);
  }
  const avgDays = list => list.length ? list.reduce((s, c) => s + (c.closedAt - c.t), 0) / list.length / DAY : 0;
  function pageHead(title, sub, actions = "") {
    return `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p>${sub}</p>` : ""}</div>${actions ? `<div class="btn-row">${actions}</div>` : ""}</div>`;
  }
  function kpi(label, ic, value, note, tone = "") {
    return `<div class="card kpi ${tone}"><div class="kpi-label">${icon(ic)}${esc(label)}</div>
      <div class="kpi-value">${value}</div>${note ? `<div class="kpi-note">${note}</div>` : ""}</div>`;
  }
  // Botones de simulación: solo con el permiso de configuración, y solo con datos de demostración
  function demoBar() {
    if (!VA.can("config") || !demoOn()) return "";
    const b = (a, ic, label) => `<button class="btn btn-secondary" type="button" data-demo="${a}">${icon(ic)}${label}</button>`;
    return `<div class="card demo-panel no-print"><div class="card-body demo-row">
      <strong>Modo demo</strong>
      ${b("reporte", "smartphone", "Reporte desde la app")}
      ${MOCK ? b("descarga", "droplets", "Simular descarga en Xoxtla")
             : b("descarga", "hard-drive-download", "Visita a N3 (trae una descarga)") + b("vecino", "hard-drive-download", "Visita a N2 (confirma el tramo)")}
      ${b("barrera", "trash-2", "Barrera llena")}
      ${b("crecida", "cloud-rain", MOCK ? "Crecida" : "Visita a N5 (trae una crecida)")}
      ${MOCK ? "" : b("reiniciar", "rotate-ccw", "Reiniciar demo")}
    </div></div>`;
  }
  function tramoRows() {
    return S().tramos.map(t => {
      const r = lastReading(t.to), s = VA.map.tramoStatus(t);
      const v = (k, d) => r && s !== "off" ? fmt.num(r[k], d) : "—";
      return `<tr><td><strong>${esc(t.id)}</strong><span class="sub">${esc(t.name)}</span></td><td>${badge(s)}</td>
        <td class="num">${v("ph", 2)}</td><td class="num">${v("cond")}</td><td class="num">${v("turb")}</td><td class="num">${v("color", 1)}</td></tr>`;
    }).join("");
  }
  // Campo de contraseña con botón para mostrarla (se usa en usuarios y en "Cambiar contraseña")
  function passField(id, label, { help = "", auto = "new-password" } = {}) {
    return `<div class="field"><label for="${id}">${esc(label)}</label>
      <div class="pass-wrap"><input id="${id}" type="password" autocomplete="${auto}" required minlength="8" maxlength="128"${help ? ` aria-describedby="${id}Help"` : ""}>
        <button class="btn btn-ghost btn-icon" type="button" data-show="${id}" aria-label="Mostrar contraseña" aria-pressed="false">${icon("eye")}</button></div>
      ${help ? `<span class="help" id="${id}Help">${esc(help)}</span>` : ""}</div>`;
  }
  function wirePassToggles(root) {
    root.querySelectorAll("[data-show]").forEach(b => b.addEventListener("click", () => {
      const inp = root.querySelector("#" + b.dataset.show), show = inp.type === "password";
      inp.type = show ? "text" : "password";
      b.setAttribute("aria-pressed", show); b.setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
      b.innerHTML = icon(show ? "eye-off" : "eye"); refreshIcons();
    }));
  }

  // =========================================================
  // RESUMEN
  // =========================================================
  // ---------- Ayudas del centro de operaciones ----------
  const diaLocal = t => Math.floor((t - 6 * 3600000) / DAY);            // día en hora del centro
  // Cuántos elementos cayeron en cada uno de los últimos `dias` días (el último es hoy)
  function porDia(items, getT, dias = 30) {
    const hoy = diaLocal(Date.now()), arr = Array(dias).fill(0);
    items.forEach(x => { const k = hoy - diaLocal(getT(x)); if (k >= 0 && k < dias) arr[dias - 1 - k]++; });
    return arr;
  }
  // Índice de la cuenca por día: promedio de los tramos con dato ese día
  function indiceCuenca(dias = 30) {
    const porD = {};
    Object.values(S().dailyIndex || {}).forEach(serie => serie.forEach(p => { (porD[diaLocal(p.t)] = porD[diaLocal(p.t)] || []).push(p.v); }));
    const hoy = diaLocal(Date.now());
    return Array.from({ length: dias }, (_, k) => { const v = porD[hoy - (dias - 1 - k)]; return v ? v.reduce((a, b) => a + b, 0) / v.length : null; });
  }
  // Chip de variación: verde si mejora, rojo si empeora (con flecha y texto, no solo color)
  function delta(actual, antes, { mejorSiSube = true, unidad = "", pct = false, dec = 0, texto = "vs. semana anterior" } = {}) {
    if (actual == null || antes == null || isNaN(actual) || isNaN(antes)) return "";
    const dif = pct ? (antes ? (actual - antes) / antes * 100 : 0) : actual - antes;
    if (Math.abs(dif) < (pct ? 3 : Math.pow(10, -dec))) return `<span class="delta flat">${icon("minus")}Sin cambio ${texto}</span>`;
    const sube = dif > 0, bien = sube === mejorSiSube;
    const v = pct ? `${fmt.num(Math.abs(dif))}%` : `${fmt.num(Math.abs(dif), dec)}${unidad}`;
    return `<span class="delta ${bien ? "good" : "bad"}">${icon(sube ? "arrow-up-right" : "arrow-down-right")}${sube ? "+" : "−"}${v} ${texto}</span>`;
  }
  function kpi2(label, ic, value, unit, note, tone = "", { spark = "", chip = "", id = "" } = {}) {
    return `<div class="card kpi2 ${tone}"${id ? ` id="${id}"` : ""}><div class="kpi-label">${icon(ic)}${esc(label)}</div>
      <div class="kpi-row"><div class="kpi-value">${value}${unit ? `<small>${esc(unit)}</small>` : ""}</div>${spark}</div>
      ${chip}${note ? `<div class="kpi-note muted">${note}</div>` : ""}</div>`;
  }
  // Frescura de los datos: los nodos no tienen internet; lo que se ve es de su última descarga
  function frescura() {
    const ns = S().nodes, con = ns.filter(n => n.lastSync);
    if (MOCK) return `<span class="fresh"><span class="dot" aria-hidden="true"></span>Simulación en el navegador · <strong>en vivo</strong></span>`;
    if (!con.length) return `<span class="fresh off"><span class="dot" aria-hidden="true"></span>Sin datos de los nodos todavía</span>`;
    const ult = con.reduce((a, b) => (b.lastSync > a.lastSync ? b : a));
    const alDia = ns.filter(n => !VA.map.isStale(n) && n.lastSync).length;
    return `<span class="fresh ${alDia < ns.length ? "warn" : ""}" title="Los nodos guardan sin internet; sus datos llegan con cada visita de Protección Civil">
      <span class="dot" aria-hidden="true"></span>Última descarga: <strong>${esc(ult.id)}, ${fmt.ago(ult.lastSync)}</strong> · ${alDia} de ${ns.length} nodos al día</span>`;
  }
  // Simulaciones de la demo en un menú compacto (solo Configuración)
  function demoMenu() {
    if (!VA.can("config") || !demoOn()) return "";
    const b = (a, ic, label) => `<button class="btn btn-ghost" type="button" data-demo="${a}">${icon(ic)}${label}</button>`;
    return `<details class="demo-menu no-print"><summary class="btn btn-secondary">${icon("flask-conical")}Simular</summary>
      <div class="demo-pop" role="group" aria-label="Simulaciones de la demo"><p>Pasan por el mismo camino que los datos reales: archivo → análisis → casos.</p>
        ${b("reporte", "smartphone", "Reporte desde la app")}
        ${MOCK ? b("descarga", "droplets", "Descarga en Xoxtla") : b("descarga", "hard-drive-download", "Visita a N3 (trae una descarga)") + b("vecino", "hard-drive-download", "Visita a N2 (confirma el tramo)")}
        ${b("barrera", "trash-2", "Barrera llena")}
        ${b("crecida", "cloud-rain", MOCK ? "Crecida" : "Visita a N5 (trae una crecida)")}
        ${MOCK ? "" : b("reiniciar", "rotate-ccw", "Reiniciar demo (90 días)")}</div></details>`;
  }
  // Franja de 30 días por tramo: cada celda es un día con el color de su índice
  function heatHtml(dias = 30) {
    const hoy = diaLocal(Date.now());
    const filas = S().tramos.map(t => {
      const serie = S().dailyIndex[t.id] || [], porD = {};
      serie.forEach(p => { porD[diaLocal(p.t)] = p.v; });
      const celdas = Array.from({ length: dias }, (_, k) => {
        const d = hoy - (dias - 1 - k), v = porD[d];
        if (v == null) return `<i title="${fmt.day((d * DAY) + 6 * 3600000)}: sin datos"></i>`;
        const s = E.indexStatus(v);
        return `<i class="${s}${(s === "ok" && v < 80) || (s === "warn" && v >= 55) ? " l" : ""}" title="${fmt.day((d * DAY) + 6 * 3600000)}: índice ${v} (${E.semLabel[s]})"></i>`;
      }).join("");
      const ult = serie.length ? serie[serie.length - 1] : null;
      const viejo = ult && diaLocal(Date.now()) - diaLocal(ult.t) > 2;
      return `<div class="heat-row"><div class="heat-name">${esc(t.id)} · ${esc(t.name.split(" → ")[1] || t.name)}<span>${t.km ? fmt.num(t.km, 1) + " km de cauce" : ""}</span></div>
        <div class="heat-cells" role="img" aria-label="${esc(t.id)}: índice de calidad de los últimos ${dias} días">${celdas}</div>
        <div class="heat-now"${viejo ? ` title="Último dato del ${fmt.day(ult.t)}"` : ""}>${ult ? (viejo ? `<span class="muted">${ult.v}*</span>` : ult.v) : "—"}</div></div>`;
    }).join("");
    return `${filas}<div class="heat-axis"><span></span><div><span>hace ${dias} días</span><span>hoy</span></div><span>último</span></div>
      <div class="heat-legend"><span><i style="background:#22C55E"></i>Bien (70+)</span><span><i style="background:#F59E0B"></i>Atención (40–69)</span>
        <span><i style="background:#DC2626"></i>Crítico (menos de 40)</span><span><i style="background:#E2E8F0"></i>Sin datos</span><span>* dato de hace días: nodo sin visita</span></div>`;
  }
  const PERFIL = { cond: ["Conductividad", "µS/cm", 0], turb: ["Turbidez", "NTU", 0], color: ["Color 620 nm", "m⁻¹", 1], ph: ["pH", "", 2] };
  // Promedio móvil (para que las mini gráficas muestren la tendencia y no el ruido de cada hora)
  function movil(vals, n) {
    return vals.map((_, i) => { const w = vals.slice(Math.max(0, i - n + 1), i + 1).filter(v => v != null); return w.length ? w.reduce((a, b) => a + b, 0) / w.length : null; });
  }

  // =========================================================
  // RESUMEN (centro de operaciones)
  // =========================================================
  function resumen(main) {
    let est = null, perfilKey = "cond", perfil = null;
    function kpisHtml() {
      const now = Date.now();
      // 1. Índice de la cuenca (promedio del último dato de cada tramo)
      const serieI = indiceCuenca(30), ult = S().tramos.map(t => (S().dailyIndex[t.id] || []).slice(-1)[0]).filter(Boolean);
      const indice = ult.length ? Math.round(ult.reduce((a, p) => a + p.v, 0) / ult.length) : null;
      const hace7 = serieI.slice(0, 23).filter(v => v != null).slice(-1)[0];
      const sI = indice != null ? E.indexStatus(indice) : "neutral";
      // 2. Tramos en alerta
      const st = S().tramos.map(t => ({ t, s: VA.map.tramoStatus(t) }));
      const alerta = st.filter(x => x.s === "warn" || x.s === "crit"), sin = st.filter(x => x.s === "off");
      // 3. Casos abiertos
      const vis = canSeeCases() ? visibleCases() : S().cases, abiertos = openCases(vis);
      const nuevos = porDia(vis, c => c.t, 30), sem = nuevos.slice(-7).reduce((a, b) => a + b, 0), semAnt = nuevos.slice(-14, -7).reduce((a, b) => a + b, 0);
      const cerrados = S().cases.filter(c => c.closedAt && now - c.closedAt < 60 * DAY);
      // 4. Reportes
      const rep = porDia(S().reports, r => r.t, 30), r7 = rep.slice(-7).reduce((a, b) => a + b, 0), r7a = rep.slice(-14, -7).reduce((a, b) => a + b, 0);
      const out = [
        kpi2("Índice de calidad del río", "gauge", indice ?? "—", "/100", `Promedio de ${ult.length} tramos · ${indice != null ? E.semLabel[sI] : "sin datos"}`, sI,
          { spark: VA.charts.spark(serieI, { color: "#0369A1" }), chip: delta(indice, hace7, { texto: "vs. hace 7 días" }) }),
        kpi2("Tramos en alerta", "waves", alerta.length, `de ${st.length}`,
          (alerta.map(x => `${x.t.id} ${E.semLabel[x.s].toLowerCase()}`).concat(sin.map(x => `${x.t.id} sin datos recientes`)).join(" · ")) || "Todos los tramos en bien",
          alerta.some(x => x.s === "crit") ? "crit" : alerta.length ? "warn" : "ok"),
        kpi2(canSeeCases() ? "Casos abiertos" : "Casos en atención", "folder-open", abiertos.length, "",
          `${abiertos.filter(c => c.priority === "Alta").length} de alta prioridad · atención promedio ${cerrados.length ? fmt.num(avgDays(cerrados), 1) + " días" : "—"}`,
          abiertos.length ? "warn" : "ok", { spark: VA.charts.spark(nuevos, { color: "#B45309" }), chip: delta(sem, semAnt, { mejorSiSube: false, unidad: Math.abs(sem - semAnt) === 1 ? " nuevo" : " nuevos", texto: "vs. sem. pasada" }) }),
        kpi2("Reportes ciudadanos", "smartphone", r7, "en 7 días", `${S().reports.filter(r => r.status === "Recibido").length} sin revisar · desde la app`, "",
          { spark: VA.charts.spark(rep, { color: "#0E7490" }), chip: delta(r7, r7a, { pct: true, mejorSiSube: false, texto: "vs. sem. pasada" }) })
      ];
      if (S().estaciones && S().estaciones.length) {
        const k = est && est.kpis;
        out.push(kpi2(`Agua tratada · ${S().estaciones[0].codigo}`, "factory", k ? fmt.num(k.m3Dia, 1) : "…", "m³/día",
          k ? `Remueve ${fmt.pct(k.remocion.turb)} de la turbidez y ${fmt.pct(k.remocion.color)} del color` : "Cargando la estación piloto…",
          k ? (k.remocion.turb >= 0.8 ? "ok" : "warn") : "neutral",
          { id: "kpiEst", spark: est ? VA.charts.spark(movil(est.serie.slice(-96).map(p => (p.turb && p.turb_sal != null ? 100 * (1 - p.turb_sal / p.turb) : null)), 6), { color: "#15803D" }) : "" }));
      }
      if (S().basura) {
        out.push(kpi2("Basura retirada", "trash-2", fmt.num(S().basura.kg30), "kg en 30 días",
          `${S().basura.vaciados30} vaciados de barreras · ${fmt.num(S().basura.kg90 / 1000, 1)} t en 90 días`, "ok"));
      }
      return out.join("");
    }
    function recentHtml() {
      const list = (canSeeCases() ? visibleCases() : S().cases).slice().sort((a, b) => (b.closedAt ? 0 : 1) - (a.closedAt ? 0 : 1) || b.t - a.t).slice(0, 6);
      if (!list.length) return `<p class="empty">Todavía no hay casos.</p>`;
      return `<ul class="list">${list.map(c => {
        const tone = c.status === "Cerrado" ? "ok" : c.priority === "Alta" ? "crit" : "warn";
        const title = canSeeCases() ? `<a href="#/casos/${c.id}">${esc(caseType(c).label)}</a>` : esc(caseType(c).label);
        return `<li><span class="li-icon ${tone}">${icon(caseType(c).icon)}</span><div class="li-main">
          <div class="li-title">${title} <span class="muted small">${esc(c.id)}</span></div><div class="li-meta">${esc(casePlace(c))} · ${fmt.ago(c.t)}</div></div>
          <div>${stateBadge(c.status)}</div></li>`;
      }).join("")}</ul>`;
    }
    function perfilNodos() {
      let km = 0;
      return S().nodes.map((n, i) => {
        if (i > 0) { const t = S().tramos.find(x => x.to === n.id); km += t && t.km ? t.km : E.km(S().nodes[i - 1].lat, S().nodes[i - 1].lng, n.lat, n.lng); }
        const r = lastReading(n.id);
        return { id: n.id, name: n.name, km, v: r ? r[perfilKey] : null, s: VA.map.nodeStatus(n) };
      });
    }
    function dibujaPerfil() {
      if (perfil) perfil.destroy();
      const p = C.params[perfilKey], [et, un, dec] = PERFIL[perfilKey];
      perfil = VA.charts.profile(document.getElementById("perfil"), perfilNodos(), perfilKey,
        { umbral: perfilKey === "ph" ? p.max : p.warn, critico: perfilKey === "ph" ? p.critMax : p.crit, etiqueta: et, unidad: un, dec });
    }
    function estacionHtml() {
      if (!est || !est.kpis) return `<p class="empty">Cargando la estación piloto…</p>`;
      const k = est.kpis, ult = est.serie[est.serie.length - 1] || {};
      const fila = (nombre, a, b, un, dec) => {
        const max = Math.max(a || 0, b || 0) || 1;
        return `<div class="io-item"><div class="io-name">${nombre}</div><div class="io-vals"><b>${fmt.num(b, dec)}</b><s>de ${fmt.num(a, dec)} ${un}</s></div>
          <div class="io-bar" aria-hidden="true"><i class="in" style="width:${(a / max * 100).toFixed(0)}%"></i><i class="out" style="width:${(b / max * 100).toFixed(0)}%"></i></div></div>`;
      };
      return `<div class="io">${fila("Turbidez (NTU)", ult.turb, ult.turb_sal, "", 1)}${fila("Color 620 nm (m⁻¹)", ult.color, ult.color_sal, "", 2)}
          ${fila("Conductividad (µS/cm)", ult.cond, ult.cond_sal, "", 0)}${fila("pH", ult.ph, ult.ph_sal, "", 2)}</div>
        <p class="small muted" style="margin:10px 0 0">Barra naranja: agua del río que entra · verde: lo que sale tratado. Lodos ${fmt.num(k.lodos)}% · filtros ${fmt.num(k.dp, 1)} de 24 kPa
          ${k.horasRetrolavado != null ? `(retrolavado en ~${fmt.num(k.horasRetrolavado)} h)` : ""} · ${fmt.num(k.energiaWhDia)} Wh de sol al día.</p>`;
    }
    const guest = !MOCK && !VA.session.user;
    const hayEst = !MOCK && S().estaciones && S().estaciones.length;
    main.innerHTML = `
      <div class="ops-head"><div><h1>Centro de monitoreo del Alto Atoyac</h1>
        <p>Calidad del río por tramo, casos de cada dependencia y reportes de la ciudadanía · <span id="updAgo">actualizado ${fmt.hm(Date.now())}</span></p></div>
        <div class="ops-actions"><span id="fresh">${frescura()}</span>${demoMenu()}</div></div>
      ${guest ? `<div class="banner">${icon("info")}<div>Estás viendo la <strong>vista pública</strong>: semáforo del río, mapa, estación piloto y transparencia.
        El personal de las dependencias entra con su cuenta desde <a href="login.html">Iniciar sesión</a>.</div></div>` : ""}
      <section class="kpis-6" id="kpis" aria-label="Indicadores principales">${kpisHtml()}</section>
      <div class="grid-ops">
        <section class="card" aria-labelledby="mapTitle">
          <div class="card-head"><h2 id="mapTitle">Semáforo del río</h2><a class="btn btn-ghost" href="#/mapa">${icon("maximize-2")}Abrir mapa</a></div>
          <div class="legend"><span><i style="background:#15803D"></i>Bien</span><span><i style="background:#D97706"></i>Atención</span><span><i style="background:#DC2626"></i>Crítico</span>
            ${MOCK ? "" : `<span><i style="background:#64748B"></i>Sin datos recientes</span>`}
            <span><span class="node-pin ok" style="width:18px;height:18px;border-width:2px;font-size:0"></span>Nodo</span><span><span class="square-pin ok" style="width:16px;height:16px;border-width:2px"></span>Barrera</span>
            ${VA.map.is3d ? `<span><span class="col-swatch" aria-hidden="true"></span>Columna más alta = más cerca del umbral</span>` : ""}</div>
          <div class="map" id="miniMap" role="region" aria-label="Mapa del río con el estado de cada tramo. La franja de calidad diaria y la tabla por tramo tienen la misma información."></div>
        </section>
        <section class="card" aria-labelledby="perfTitle">
          <div class="card-head"><h2 id="perfTitle">Perfil del río</h2>
            <div class="seg" role="group" aria-label="Parámetro del perfil">${Object.keys(PERFIL).map(k => `<button type="button" data-perf="${k}" aria-pressed="${k === perfilKey}">${esc(PERFIL[k][0].split(" ")[0])}</button>`).join("")}</div></div>
          <p class="card-sub">Del nacimiento (N1) a la presa (N6), por kilómetro de cauce: así se ve cómo se acumula la contaminación río abajo.</p>
          <div class="card-body"><div class="chart-box md"><canvas id="perfil" role="img" aria-label="Valor del parámetro elegido en cada nodo, de río arriba a río abajo"></canvas></div></div>
        </section>
      </div>
      <div class="grid-ops">
        <section class="card" aria-labelledby="heatTitle">
          <div class="card-head"><h2 id="heatTitle">Calidad diaria por tramo</h2><a class="btn btn-ghost" href="#/prediccion">${icon("trending-up")}Ver pronóstico</a></div>
          <p class="card-sub">Índice de 0 a 100 calculado con la mediana diaria de pH, conductividad, turbidez y color del nodo al final de cada tramo.</p>
          <div class="card-body heat" id="heat">${heatHtml()}</div>
        </section>
        <section class="card" aria-labelledby="recentTitle">
          <div class="card-head"><h2 id="recentTitle">${canSeeCases() ? "Casos que requieren atención" : "Casos recientes"}</h2>${canSeeCases() ? `<a class="btn btn-ghost" href="#/casos">Ver todos</a>` : `<a class="btn btn-ghost" href="#/transparencia">Transparencia</a>`}</div>
          <div class="card-body" id="recent">${recentHtml()}</div>
        </section>
      </div>
      <div class="${hayEst ? "grid-ops-even" : ""}">
        ${hayEst ? `<section class="card" aria-labelledby="estTitle">
          <div class="card-head"><h2 id="estTitle">${esc(S().estaciones[0].nombre)} (${esc(S().estaciones[0].codigo)})</h2><a class="btn btn-ghost" href="#/estacion">${icon("factory")}Ver estación</a></div>
          <p class="card-sub">Entra agua del río junto al nodo ${esc(S().estaciones[0].nodo)} y sale tratada: último dato descargado.</p>
          <div class="card-body" id="estBody">${estacionHtml()}</div></section>` : ""}
        <section class="card" aria-labelledby="tramosTitle">
          <div class="card-head"><h2 id="tramosTitle">Estado por tramo</h2><span class="muted small">${MOCK ? "Valores del nodo al final de cada tramo" : "Última lectura descargada"}</span></div>
          <div class="card-body table-wrap"><table class="data"><thead><tr><th>Tramo</th><th>Semáforo</th><th>pH</th><th>Cond.</th><th>Turb.</th><th>Color</th></tr></thead>
            <tbody id="tramoBody">${tramoRows()}</tbody></table></div>
        </section>
      </div>`;
    const m = VA.map.create(document.getElementById("miniMap"), { tramoLabels: false, scroll: false });
    dibujaPerfil();
    main.querySelectorAll("[data-perf]").forEach(b => b.addEventListener("click", () => {
      perfilKey = b.dataset.perf; main.querySelectorAll("[data-perf]").forEach(x => x.setAttribute("aria-pressed", x === b)); dibujaPerfil();
    }));
    let vivo = true;
    async function cargaEstacion() {
      if (!hayEst) return;
      try { est = await VA.api.estacion(S().estaciones[0].nodo); } catch (e) { est = null; }
      if (!vivo) return;
      const k = document.getElementById("kpis"); if (k) k.innerHTML = kpisHtml();
      const b = document.getElementById("estBody"); if (b) b.innerHTML = estacionHtml();
      refreshIcons();
    }
    cargaEstacion();
    let lastKpi = 0;
    return {
      update(msg) {
        m.update();
        document.getElementById("tramoBody").innerHTML = tramoRows();
        const u = document.getElementById("updAgo"); if (u) u.textContent = "actualizado " + fmt.time(Date.now());
        if (Date.now() - lastKpi > 2500 || msg.tipo !== "lectura") {
          lastKpi = Date.now();
          document.getElementById("kpis").innerHTML = kpisHtml();
          document.getElementById("recent").innerHTML = recentHtml();
          document.getElementById("heat").innerHTML = heatHtml();
          document.getElementById("fresh").innerHTML = frescura();
          dibujaPerfil();
          if (msg.tipo === "sync") cargaEstacion();
        }
        refreshIcons();
      },
      destroy() { vivo = false; m.map.remove(); if (perfil) perfil.destroy(); }
    };
  }

  // =========================================================
  // ESTACIÓN PILOTO (la estructura del render: captación → tratamiento → río)
  // =========================================================
  function estacion(main) {
    const meta = (S().estaciones || [])[0];
    if (MOCK || !meta) {
      main.innerHTML = pageHead("Estación piloto", "") + `<p class="empty">La estación piloto necesita el servidor (sus datos llegan con las visitas a ${meta ? esc(meta.nodo) : "N3"}).</p>`;
      return {};
    }
    let data = null, key = "turb", charts = [], vivo = true;
    const IO = { turb: ["Turbidez", "NTU", 1], color: ["Color 620 nm", "m⁻¹", 2], cond: ["Conductividad", "µS/cm", 0], ph: ["pH", "", 2] };
    const meter = (v, max, malo = 0.85, medio = 0.65) => {
      const f = Math.max(0, Math.min(1, (v || 0) / max)), tono = f >= malo ? "crit" : f >= medio ? "warn" : "";
      return `<div class="meter ${tono}" role="img" aria-label="${fmt.num(f * 100)}%"><span style="width:${(f * 100).toFixed(0)}%"></span></div>`;
    };
    function etapas() {
      const k = data.kpis, u = data.serie[data.serie.length - 1] || {};
      const purga = data.mantenimiento.find(m => m.tipo === "purga");
      const parado = !k.caudal;
      return `<div class="flow">
        <div class="stage"><span class="sensor" title="Sensor de entrada (agua del río)">S1</span><span class="stage-n">1 · Captación</span><h3>${icon("waves")}Compuerta y rejilla</h3>
          <div class="big">${fmt.num(k.caudal, 2)}<small>L/s</small></div><p>Toma agua del Atoyac por gravedad. Nivel del río: ${fmt.num(k.nivelRio, 2)} m.</p></div>
        <div class="stage"><span class="stage-n">2 · Tamiz rotatorio</span><h3>${icon("cog")}Cribado fino</h3>
          <div class="big">${parado ? "En pausa" : "Girando"}</div><p>Retira hojas, plásticos y sólidos de más de 2 mm antes del sedimentador.</p></div>
        <div class="stage"><span class="stage-n">3 · Sedimentador</span><h3>${icon("cylinder")}Lodos</h3>
          <div class="big">${fmt.num(k.lodos)}<small>% lleno</small></div>${meter(k.lodos, 100, 0.9, 0.75)}
          <p>Se purga los lunes a las 10:00${purga ? ` · última purga ${fmt.ago(purga.t)}` : ""}.</p></div>
        <div class="stage"><span class="stage-n">4 · Filtros</span><h3>${icon("layers")}Grava, arena, carbón</h3>
          <div class="big">${fmt.num(k.dp, 1)}<small>de 24 kPa</small></div>${meter(k.dp, 24)}
          <div class="meter-label"><span>Carbón activado</span><span>${k.carbonDias != null ? `${fmt.num(k.carbonDias)} de ${k.carbonCada} días` : "—"}</span></div>
          ${k.carbonDias != null ? meter(k.carbonDias, k.carbonCada, 0.92, 0.8) : ""}
          <p>${k.horasRetrolavado != null ? `Retrolavado automático en ~${fmt.num(k.horasRetrolavado)} h` : "Presión estable"}.</p></div>
        <div class="stage"><span class="stage-n">5 · Humedal artificial</span><h3>${icon("sprout")}Tule, carrizo, alcatraz</h3>
          <div class="big">${esc(data.area_humedal_m2)}<small>m²</small></div><p>Las raíces filtran y las bacterias degradan lo que queda. Remoción total de turbidez: ${fmt.pct(k.remocion.turb)}.</p></div>
        <div class="stage"><span class="sensor" title="Sensor de salida (agua tratada)">S2</span><span class="stage-n">6 · Descarga al río</span><h3>${icon("droplets")}Agua tratada</h3>
          <div class="big">${fmt.num(u.turb_sal, 1)}<small>NTU</small></div><p>Color ${fmt.num(u.color_sal, 2)} m⁻¹ · pH ${fmt.num(u.ph_sal, 2)} · vuelve al Atoyac sobre un lecho de grava.</p></div>
      </div>`;
    }
    function kpis() {
      const k = data.kpis;
      return [
        kpi2("Caudal tratado", "waves", fmt.num(k.caudal, 2), "L/s", `Nivel del río ${fmt.num(k.nivelRio, 2)} m`, k.caudal ? "ok" : "warn",
          { spark: VA.charts.spark(data.serie.slice(-72).map(p => p.caudal), { color: "#0E7490" }) }),
        kpi2("Agua tratada", "glass-water", fmt.num(k.m3Dia, 1), "m³/día", `${k.diaBase ? `Día completo del ${fmt.day(k.diaBase)}` : "Estimado con las horas disponibles"} · ${fmt.num(k.m3Periodo, 0)} m³ en la semana`, "ok"),
        kpi2("Remoción de turbidez", "filter", fmt.pct(k.remocion.turb), "", `${fmt.pct(k.remocionPeriodo.turb)} promedio de la semana`, k.remocion.turb >= 0.8 ? "ok" : "warn",
          { spark: VA.charts.spark(data.serie.slice(-72).map(p => p.turb && p.turb_sal != null ? 100 * (1 - p.turb_sal / p.turb) : null), { color: "#15803D" }) }),
        kpi2("Remoción de color", "palette", fmt.pct(k.remocion.color), "", k.carbonDias != null && k.carbonCada - k.carbonDias < 5
          ? `El carbón activado ya rinde menos: cambio en ${fmt.num(Math.max(0, k.carbonCada - k.carbonDias))} días` : "Tintes textiles atrapados en el carbón activado",
          k.remocion.color >= 0.55 ? "ok" : "warn",
          { spark: VA.charts.spark(data.eficienciaColorDiaria.map(([, e]) => e), { color: "#7C3AED" }) }),
        kpi2("Sólidos retenidos", "package", fmt.num(k.solidosKgDia, 2), "kg/día", "Lodo que ya no llega a la presa de Valsequillo", "ok"),
        kpi2("Energía solar", "sun", fmt.num(k.energiaWhDia), "Wh/día", `Batería del nodo ${k.bateria != null ? k.bateria + "%" : "—"} · sin conexión a la red`, "ok",
          { spark: VA.charts.spark(data.serie.slice(-72).map(p => p.solar), { color: "#CA8A04" }) })
      ].join("");
    }
    function mantenimiento() {
      const ic = { purga: "cylinder", retrolavado: "refresh-ccw", carbon: "layers" };
      return data.mantenimiento.length ? `<ul class="maint">${data.mantenimiento.map(m => `<li>${icon(ic[m.tipo] || "wrench")}<div>${esc(m.texto)}<time>${m.tipo === "carbon" ? fmt.day(m.t) : fmt.date(m.t)} · ${fmt.ago(m.t)}</time></div></li>`).join("")}</ul>`
        : `<p class="empty">Sin eventos de mantenimiento en el periodo.</p>`;
    }
    function dibuja() {
      charts.forEach(c => c.destroy()); charts = [];
      const [et, un, dec] = IO[key];
      charts.push(VA.charts.inOut(document.getElementById("ioChart"), data.serie, key, { etiqueta: et, unidad: un, dec }));
      charts.push(VA.charts.operation(document.getElementById("opChart"), data.serie));
      charts.push(VA.charts.energy(document.getElementById("enChart"), data.serie));
    }
    function render() {
      const k = data.kpis;
      if (!k) { main.querySelector("#estBody").innerHTML = `<p class="empty">La estación todavía no tiene datos. Llegan con la primera visita a ${esc(meta.nodo)}.</p>`; return; }
      main.querySelector("#estBody").innerHTML = `
        <section class="kpis-6" aria-label="Indicadores de la estación">${kpis()}</section>
        <section class="card" aria-labelledby="flowTitle"><div class="card-head"><h2 id="flowTitle">Cómo trata el agua</h2>
          <span class="muted small">Último dato: ${fmt.date(data.hasta)} (${fmt.ago(data.hasta)})</span></div>
          <div class="card-body">${etapas()}</div></section>
        <div class="grid-ops-even">
          <section class="card" aria-labelledby="ioTitle"><div class="card-head"><h2 id="ioTitle">Entrada contra salida</h2>
            <div class="seg" role="group" aria-label="Parámetro">${Object.keys(IO).map(x => `<button type="button" data-io="${x}" aria-pressed="${x === key}">${esc(IO[x][0].split(" ")[0])}</button>`).join("")}</div></div>
            <p class="card-sub">Mediana por hora, últimos 7 días. La salida responde horas después: el agua tarda en cruzar el humedal.</p>
            <div class="card-body"><div class="chart-box md"><canvas id="ioChart" role="img" aria-label="Agua del río que entra y agua tratada que sale"></canvas></div>
            <p class="small muted" style="margin:8px 0 0">Remoción de la semana: turbidez ${fmt.pct(k.remocionPeriodo.turb)} · color ${fmt.pct(k.remocionPeriodo.color)} · conductividad ${fmt.pct(k.remocionPeriodo.cond)} (las sales disueltas casi no se quitan con plantas).</p></div></section>
          <section class="card" aria-labelledby="opTitle"><div class="card-head"><h2 id="opTitle">Operación</h2></div>
            <p class="card-sub">Los lodos suben con la turbidez y bajan con cada purga; los filtros se tapan y se retrolavan solos a 24 kPa.</p>
            <div class="card-body"><div class="chart-box md"><canvas id="opChart" role="img" aria-label="Nivel de lodos y presión de los filtros"></canvas></div></div></section>
        </div>
        <div class="grid-ops">
          <section class="card" aria-labelledby="enTitle"><div class="card-head"><h2 id="enTitle">Energía y caudal</h2></div>
            <p class="card-sub">Funciona solo con su panel solar; de noche usa la batería.</p>
            <div class="card-body"><div class="chart-box sm"><canvas id="enChart" role="img" aria-label="Potencia del panel solar y caudal tratado"></canvas></div></div></section>
          <section class="card" aria-labelledby="mtTitle"><div class="card-head"><h2 id="mtTitle">Bitácora de mantenimiento</h2></div>
            <p class="card-sub">Detectada en los datos de los sensores.</p><div class="card-body">${mantenimiento()}</div></section>
        </div>`;
      main.querySelectorAll("[data-io]").forEach(b => b.addEventListener("click", () => {
        key = b.dataset.io; main.querySelectorAll("[data-io]").forEach(x => x.setAttribute("aria-pressed", x === b));
        charts[0].destroy(); const [et, un, dec] = IO[key];
        charts[0] = VA.charts.inOut(document.getElementById("ioChart"), data.serie, key, { etiqueta: et, unidad: un, dec });
      }));
      dibuja();
      refreshIcons();
    }
    main.innerHTML = `
      ${pageHead(`${meta.nombre} (${meta.codigo})`, `Capta agua del Atoyac junto al nodo ${esc(meta.nodo)}, la limpia con sedimentación, filtros y un humedal artificial, y la regresa al río.`,
        `<a class="btn btn-secondary" href="#/nodos/${esc(meta.nodo)}">${icon("activity")}Nodo ${esc(meta.nodo)}</a>`)}
      ${demoOn() ? `<div class="note-sim">${icon("flask-conical")}<div><strong>Estructura en diseño.</strong> Estos datos salen del modelo de la estación (simulación con patrones reales del río),
        en el mismo formato que mandarán sus sensores de entrada (S1) y salida (S2) en el archivo de la microSD.</div></div>` : ""}
      <div id="estBody" style="display:grid;gap:var(--space-4)"><p class="empty">Cargando la estación…</p></div>`;
    async function carga() {
      try { data = await VA.api.estacion(meta.nodo, 7); } catch (err) { if (vivo) main.querySelector("#estBody").innerHTML = `<div class="banner crit">${icon("octagon-alert")}<div>${esc(err.message)}</div></div>`; refreshIcons(); return; }
      if (vivo) render();
    }
    carga();
    return {
      update(msg) { if (msg.tipo === "sync") carga(); },
      destroy() { vivo = false; charts.forEach(c => c.destroy()); }
    };
  }

  // =========================================================
  // MAPA
  // =========================================================
  function mapa(main) {
    const layers = { tramos: true, nodos: true, barreras: true, reportes: true, calor: true };
    const chip = (k, label, ic) => `<button class="chip" type="button" data-layer="${k}" aria-pressed="${layers[k]}">${icon(ic)}${label}</button>`;
    main.innerHTML = `
      ${pageHead("Mapa de la cuenca", VA.map.is3d ? "Relieve en 3D del Alto Atoyac: tramos, nodos, barreras, reportes de la app y mapa de calor de las zonas más afectadas"
        : "Tramos, nodos, barreras, reportes de la app y mapa de calor de las zonas más afectadas")}
      <section class="card">
        <div class="map-toolbar" role="group" aria-label="Capas del mapa">
          ${chip("tramos", "Tramos", "waves")}${chip("nodos", "Nodos", "radio-tower")}${chip("barreras", "Barreras", "trash-2")}
          ${chip("reportes", "Reportes", "smartphone")}${chip("calor", "Mapa de calor", "flame")}
          <span class="topbar-spacer"></span>
          <label for="days" class="small"><strong>Periodo:</strong> últimos <span id="daysOut">7</span> días</label>
          <input id="days" type="range" min="1" max="7" value="7" style="width:160px" aria-describedby="daysOut">
        </div>
        <div class="map map-lg" id="bigMap" role="region" aria-label="Mapa interactivo. La lista de puntos debajo tiene la misma información."></div>
        <div class="legend">
          <span><i style="background:#15803D"></i>Bien</span><span><i style="background:#D97706"></i>Atención</span><span><i style="background:#DC2626"></i>Crítico</span>
          ${MOCK ? "" : `<span><i style="background:#64748B"></i>Sin datos recientes</span>`}
          <span><span class="report-pin"></span>Reporte ciudadano${C.roles[role()].staff ? "" : " (ubicación aproximada)"}</span>
          <span>Mapa de calor: baja <span class="heat-scale" aria-hidden="true"></span> alta concentración de reportes y alertas</span>
          ${VA.map.is3d ? `<span><span class="col-swatch" aria-hidden="true"></span>Columnas 3D: en nodos, qué tan cerca está la lectura de su umbral; en barreras, cuánto se llenaron</span>
          <span class="map-hint">${icon("rotate-3d")}Para girar o inclinar: clic derecho y arrastrar (o Ctrl + arrastrar; en pantalla táctil, dos dedos)</span>` : ""}
        </div>
      </section>
      <details class="card"><summary class="card-body" style="cursor:pointer;font-weight:700">Lista de puntos del mapa (alternativa en texto)</summary>
        <div class="card-body table-wrap" id="pointList"></div></details>`;
    const m = VA.map.create(document.getElementById("bigMap"), { zoom: 11, reports: true, heat: true, tramoLabels: true, reveal: true });
    if (VA.state.focus) { m.focus(VA.state.focus[0], VA.state.focus[1]); VA.state.focus = null; }
    main.querySelectorAll("[data-layer]").forEach(b => b.addEventListener("click", () => {
      const k = b.dataset.layer; layers[k] = !layers[k]; b.setAttribute("aria-pressed", layers[k]); m.setLayer(k, layers[k]);
    }));
    const days = document.getElementById("days");
    days.addEventListener("input", () => { m.days = +days.value; document.getElementById("daysOut").textContent = days.value; if (layers.reportes) m.setReports(true); if (layers.calor) m.setHeat(true); });
    function list() {
      document.getElementById("pointList").innerHTML = `<table class="data"><thead><tr><th>Punto</th><th>Tipo</th><th>Estado</th></tr></thead><tbody>
        ${S().nodes.map(n => `<tr><td>${esc(n.id)} · ${esc(n.name)}</td><td>Nodo de sensores</td><td>${badge(VA.map.nodeStatus(n))}</td></tr>`).join("")}
        ${S().barriers.map(b => `<tr><td>${esc(b.id)} · ${esc(b.name)}</td><td>Barrera (${fmt.num(b.fill)}% llena)</td><td>${badge(VA.map.barrierStatus(b))}</td></tr>`).join("")}
      </tbody></table>`;
    }
    list();
    let lastHeat = 0;
    return {
      update(msg) {
        m.update();
        const all = msg.tipo === "sync";
        if ((msg.tipo === "reporte" || all) && layers.reportes) m.setReports(true);
        if (layers.calor && (all || Date.now() - lastHeat > 6000)) { lastHeat = Date.now(); m.setHeat(true); }
        if (msg.tipo !== "lectura") list();
        refreshIcons();
      },
      destroy() { m.map.remove(); }
    };
  }

  // =========================================================
  // CASOS (lista + detalle en panel lateral)
  // =========================================================
  function casos(main, param) {
    if (!canSeeCases()) { main.innerHTML = pageHead("Casos", "Esta vista es solo para las dependencias que atienden casos."); return {}; }
    const f = { tipo: "", estado: "abiertos", q: "" };
    let sort = { key: "t", dir: -1 };
    const prioRank = { Alta: 3, Media: 2, Baja: 1 };
    main.innerHTML = `
      ${pageHead("Casos", `Asignados a: ${esc(C.roles[role()].deps.map(d => C.dependencias[d].label).join(", "))}`)}
      <section class="card"><div class="card-body filters">
        <div class="field"><label for="fTipo">Tipo</label><select id="fTipo"><option value="">Todos</option>${Object.entries(C.tiposCaso).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("")}</select></div>
        <div class="field"><label for="fEstado">Estado</label><select id="fEstado"><option value="abiertos">Abiertos</option><option value="">Todos</option>${C.estadosCaso.map(s => `<option>${esc(s)}</option>`).join("")}</select></div>
        <div class="field"><label for="fQ">Buscar</label><input id="fQ" type="search" placeholder="Folio o lugar"></div>
      </div>
      <div class="table-wrap"><table class="data" id="caseTable"><thead><tr>
        <th scope="col">Folio</th><th scope="col">Tipo</th><th scope="col">Lugar</th>
        <th scope="col" aria-sort="none" data-sort="priority"><button type="button">Prioridad ${icon("arrow-up-down")}</button></th>
        <th scope="col">Estado</th><th scope="col">Confianza</th>
        <th scope="col" aria-sort="descending" data-sort="t"><button type="button">Creado ${icon("arrow-up-down")}</button></th>
      </tr></thead><tbody id="caseBody"></tbody></table></div></section>`;
    function rows() {
      let list = visibleCases().filter(c =>
        (!f.tipo || c.type === f.tipo) &&
        (f.estado === "abiertos" ? c.status !== "Cerrado" : !f.estado || c.status === f.estado) &&
        (!f.q || (c.id + " " + casePlace(c)).toLowerCase().includes(f.q.toLowerCase())));
      list.sort((a, b) => sort.dir * (sort.key === "priority" ? prioRank[a.priority] - prioRank[b.priority] : a.t - b.t));
      document.getElementById("caseBody").innerHTML = list.length ? list.map(c => `
        <tr class="clickable" data-id="${c.id}"><td><a href="#/casos/${c.id}"><strong>${esc(c.id)}</strong></a></td>
          <td>${esc(caseType(c).label)}<span class="sub">${esc(C.dependencias[c.dep].label)}</span></td>
          <td>${esc(casePlace(c))}${c.locPending ? `<span class="sub">Tramo por confirmar</span>` : ""}</td><td>${prioBadge(c.priority)}</td><td>${stateBadge(c.status)}</td>
          <td class="num">${c.confidence != null ? fmt.pct(c.confidence) : "—"}</td><td>${fmt.date(c.t)}<span class="sub">${fmt.ago(c.t)}</span></td></tr>`).join("")
        : `<tr><td colspan="7" class="empty">No hay casos con estos filtros.</td></tr>`;
      main.querySelectorAll("tr.clickable").forEach(tr => tr.addEventListener("click", e => { if (e.target.tagName !== "A") location.hash = "#/casos/" + tr.dataset.id; }));
      refreshIcons();
    }
    document.getElementById("fTipo").addEventListener("change", e => { f.tipo = e.target.value; rows(); });
    document.getElementById("fEstado").addEventListener("change", e => { f.estado = e.target.value; rows(); });
    document.getElementById("fQ").addEventListener("input", e => { f.q = e.target.value; rows(); });
    main.querySelectorAll("th[data-sort]").forEach(th => th.querySelector("button").addEventListener("click", () => {
      const k = th.dataset.sort; sort = { key: k, dir: sort.key === k ? -sort.dir : -1 };
      main.querySelectorAll("th[data-sort]").forEach(x => x.setAttribute("aria-sort", "none"));
      th.setAttribute("aria-sort", sort.dir === 1 ? "ascending" : "descending"); rows();
    }));
    rows();
    if (param) openCase(param);
    return {
      update(msg) {
        if (msg.tipo === "lectura" && !msg.caseChanged) return;
        rows();
        // Si hay un caso abierto y llegó información nueva (otro nodo, otro reporte), se vuelve a dibujar,
        // salvo que la persona esté escribiendo el resultado de laboratorio
        const open = document.querySelector(".drawer[data-case]"), lab = document.getElementById("labText");
        if (msg.tipo === "sync" && open && !(lab && lab.value.trim())) openCase(open.dataset.case);
      },
      destroy() { VA.ui.closeDrawer(true); }
    };
  }

  function openCase(id) {
    const c = S().cases.find(x => x.id === id);
    if (!c || c.public) {
      toast("warn", "Caso no disponible", `${id} no existe o pertenece a otra dependencia.`);
      if (location.hash.startsWith("#/casos/")) history.replaceState(null, "", "#/casos");
      return;
    }
    const t = caseType(c), canAct = C.roles[role()].deps.includes(c.dep);
    const linked = c.reports.map(rid => S().reports.find(r => r.id === rid)).filter(Boolean);
    const node = c.node && S().nodes.find(n => n.id === c.node);
    const peak = c.peak ? Object.entries(c.peak).filter(([k]) => C.params[k]).map(([k, v]) => {
      const p = C.params[k], base = node ? node.base[k] : null;
      return `<tr><td>${esc(p.label)}</td><td class="num"><strong>${fmt.param(k, v)}</strong></td><td class="num">${base != null ? fmt.param(k, base) : "—"}</td><td>${badge(E.paramStatus(k, v))}</td></tr>`;
    }).join("") : "";
    const evidence = r => r.photo && !MOCK
      ? `<a class="photo" href="${VA.api.photoUrl(r)}" target="_blank" rel="noopener"><img src="${VA.api.photoUrl(r)}" alt="Foto del reporte ${esc(r.id)}: ${esc(r.cat)}" loading="lazy"><span>${esc(r.cat)} · ${esc(r.id)}</span></a>`
      : `<div class="photo-ph">${icon(r.voice ? "mic" : "image")}${esc(r.cat)}<br>${esc(r.id)} · ${fmt.ago(r.t)}</div>`;
    const html = `
      <div class="drawer-head"><div>
        <div class="muted small">${esc(t.label)} · ${esc(C.dependencias[c.dep].label)}</div>
        <h2 style="font-size:1.35rem">${esc(c.id)}</h2>
        <div class="btn-row" style="margin-top:8px">${stateBadge(c.status)}${prioBadge(c.priority)}</div>
      </div><button class="btn btn-ghost btn-icon" data-close aria-label="Cerrar detalle">${icon("x")}</button></div>
      <div class="drawer-body">
        <p style="margin:0">${esc(c.summary)}</p>
        <dl class="facts">
          <div><dt>Lugar</dt><dd>${esc(casePlace(c))}${c.locPending ? `<div class="small muted">Tramo probable; se confirma al descargar el nodo de aguas arriba.</div>` : ""}</dd></div>
          <div><dt>Creado</dt><dd>${fmt.date(c.t)} (${fmt.ago(c.t)})</dd></div>
          ${c.eventT ? `<div><dt>Hora real del evento</dt><dd>${fmt.date(c.eventT)}</dd></div>` : ""}
          <div><dt>Tipo estimado</dt><dd>${esc(c.estimate)}</dd></div>
          <div><dt>Confianza</dt><dd>${fmt.pct(c.confidence)}<div class="confidence" role="img" aria-label="Confianza ${fmt.pct(c.confidence)}"><span style="width:${c.confidence * 100}%"></span></div></dd></div>
          ${c.sample ? `<div><dt>Muestra física</dt><dd>${icon("flask-conical")} ${esc(c.sample)}</dd></div>` : ""}
          <div><dt>Reportes vinculados</dt><dd>${c.reports.length}</dd></div>
          ${c.confirmedAt && c.confirmedAt.length ? `<div><dt>También se vio aguas abajo en</dt><dd>${esc(c.confirmedAt.join(", "))}</dd></div>` : ""}
        </dl>
        ${peak ? `<section><h3>Lecturas en el evento</h3><div class="table-wrap"><table class="data"><thead><tr><th>Parámetro</th><th>Pico</th><th>Normal del nodo</th><th>Estado</th></tr></thead><tbody>${peak}</tbody></table></div></section>` : ""}
        ${linked.length ? `<section><h3>Evidencia ciudadana</h3><div class="evidence-grid" style="margin-top:8px">${linked.map(evidence).join("")}</div></section>` : ""}
        <section><h3>Historial</h3><ol class="timeline" style="margin-top:10px">${c.timeline.slice().sort((a, b) => a.t - b.t).map(e => `
          <li><div class="t-when">${fmt.date(e.t)} · ${esc(e.who)}</div><div>${esc(e.what)}</div></li>`).join("")}</ol></section>
        ${c.type === "descarga" ? `<section><h3>Resultado de laboratorio</h3>
          ${c.lab ? `<p>${esc(c.lab)}</p>` : `<p class="muted">Pendiente.</p>`}
          ${canAct && c.status !== "Cerrado" ? `<div class="field"><label for="labText">Capturar resultado</label>
            <textarea id="labText" maxlength="2000" aria-describedby="labHelp"></textarea><span class="help" id="labHelp">Ejemplo: DQO 410 mg/L, color 620 nm 9.2 m⁻¹. Fuera de norma.</span>
            <span class="help" id="labErr" style="color:var(--crit)" hidden>Escribe el resultado antes de guardar.</span></div>` : ""}</section>` : ""}
      </div>
      <div class="drawer-foot">
        ${canAct && c.status === "Nuevo" ? `<button class="btn btn-primary" data-act="atender">${icon("play")}Atender</button>` : ""}
        ${canAct && c.type === "descarga" && c.status !== "Cerrado" && c.status !== "Inspección programada" ? `<button class="btn btn-secondary" data-act="inspeccion">${icon("calendar-check")}Programar inspección</button>` : ""}
        ${canAct && c.type === "descarga" && c.status !== "Cerrado" ? `<button class="btn btn-secondary" data-act="lab">${icon("flask-conical")}Guardar laboratorio</button>` : ""}
        ${canAct && c.status !== "Cerrado" ? `<button class="btn btn-secondary" data-act="cerrar">${icon("circle-check")}Cerrar caso</button>` : ""}
        <button class="btn btn-ghost" data-act="pdf">${icon("file-down")}Evidencia en PDF</button>
        ${!canAct ? `<span class="muted small" style="align-self:center">Solo ${esc(C.dependencias[c.dep].label)} puede actualizar este caso.</span>` : ""}
      </div>`;
    const dlg = VA.ui.openDrawer(html, { label: "Caso " + c.id, onClose: () => { if (location.hash.startsWith("#/casos/")) history.replaceState(null, "", "#/casos"); } });
    dlg.dataset.case = c.id;
    dlg.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", async () => {
      const a = b.dataset.act;
      if (a === "pdf") { window.print(); return; }
      let lab;
      if (a === "lab") {
        const ta = dlg.querySelector("#labText"), err = dlg.querySelector("#labErr");
        if (!ta.value.trim()) { err.hidden = false; ta.setAttribute("aria-invalid", "true"); ta.focus(); return; }
        lab = ta.value.trim();
      }
      b.disabled = true;
      try {
        const res = await VA.api.caseAction(c, a, lab);
        if (a === "cerrar") toast("ok", "Caso cerrado", res.notified ? `${c.id}: ${res.notified} persona${res.notified === 1 ? " recibe" : "s reciben"} el aviso en la app.` : `${c.id}: no había reportes con cuenta ligada a quién avisar.`);
        VA.app.emit({ tipo: "caso", caseChanged: true });
        openCase(c.id);
      } catch (err) { fail(err); b.disabled = false; }
    }));
  }

  // =========================================================
  // NODOS
  // =========================================================
  function nodos(main, param) {
    if (!S().nodes.length) { main.innerHTML = pageHead("Nodos", "Todavía no hay nodos registrados."); return {}; }
    let sel = param && S().nodes.some(n => n.id === param) ? param : (S().nodes.some(n => n.id === "N3") ? "N3" : S().nodes[0].id);
    let key = "color", chart = null;
    const keys = Object.keys(C.params);
    const calDays = n => n.calibrated ? Math.round((Date.now() - n.calibrated) / DAY) : null;
    function card(n) {
      const r = lastReading(n.id), s = VA.map.nodeStatus(n), cd = calDays(n);
      const m = k => { const st = r ? E.paramStatus(k, r[k]) : "ok"; return `<div class="metric"><dt>${esc(C.params[k].label)}</dt><dd class="${st === "ok" ? "" : st}">${r ? fmt.num(r[k], C.params[k].dec) : "—"}</dd></div>`; };
      return `<button class="card node-card" type="button" data-node="${n.id}" aria-pressed="${n.id === sel}">
        <h3><span>${esc(n.id)} · ${esc(n.name)}</span>${badge(s)}</h3>
        <dl class="metrics">${["ph", "cond", "turb", "color", "temp", "nivel"].map(m).join("")}</dl>
        <div class="node-foot">${n.battery != null ? `<span>${icon(n.battery < 25 ? "battery-low" : "battery-full")}${n.battery}%</span>` : ""}
          ${n.lastSync ? `<span>${icon("hard-drive-download")}Descargado ${fmt.ago(n.lastSync)}</span>` : n.signal != null ? `<span>${icon("signal")}${n.signal} dBm</span>` : `<span>${icon("hard-drive-download")}Sin visitas</span>`}
          ${cd != null ? `<span>${icon("wrench")}Calibrado hace ${cd} d</span>` : ""}</div></button>`;
    }
    function currentValues() {
      const r = lastReading(sel);
      return keys.map(k => `<div>${esc(C.params[k].label)}<strong>${r ? fmt.param(k, r[k]) : "—"}</strong></div>`).join("");
    }
    function detail() {
      const n = S().nodes.find(x => x.id === sel), cd = calDays(n), old = VA.map.isStale(n);
      const hist = S().history[sel] || [];
      const needs = (n.battery != null && n.battery < 25) || (cd != null && cd > 21);
      const last8 = hist.slice(-8).reverse();
      const stamp = hist.length && hist[hist.length - 1].t - hist[0].t > 10 * 60000 ? fmt.date : fmt.time;
      return `
        <div class="card-head"><h2 id="detTitle">${esc(n.id)} · ${esc(n.name)}</h2>
          <div class="chips" role="group" aria-label="Parámetro a graficar">${keys.map(k => `<button class="chip" type="button" data-key="${k}" aria-pressed="${k === key}">${esc(C.params[k].label)}</button>`).join("")}</div></div>
        ${old ? `<div class="card-body" style="padding-bottom:0"><div class="banner warn">${icon("hard-drive-download")}<div><strong>Más de ${C.staleDays} días sin visita.</strong> Estos datos son de ${fmt.date(hist.length ? hist[hist.length - 1].t : n.lastSync)}; el semáforo de este tramo queda en gris hasta la siguiente descarga.</div></div></div>` : ""}
        ${needs ? `<div class="card-body" style="padding-bottom:0"><div class="banner">${icon("wrench")}<div><strong>Requiere mantenimiento.</strong> ${n.battery != null ? `Batería ${n.battery}% · ` : ""}calibración hace ${cd} días. Asignado a ${esc(n.tec || "el Tecnológico del tramo")}.</div></div></div>` : ""}
        ${hist.length ? `
        <div class="current-values" style="margin-top:12px" aria-live="off">${currentValues()}</div>
        ${MOCK ? "" : `<div class="card-body" style="padding-bottom:0"><h3 style="font-size:.95rem;margin:0 0 6px">Últimos 7 días con datos · mediana por hora</h3>
          <div class="chart-box sm"><canvas id="serieChart" role="img" aria-label="${esc(C.params[key].label)} en ${esc(n.name)}, mediana por hora de los últimos 7 días con datos"></canvas></div></div>
          <h3 style="font-size:.95rem;margin:14px var(--space-4) 0">Lecturas de la última descarga</h3>`}
        <div class="card-body"><div class="chart-box"><canvas id="telChart" role="img" aria-label="Gráfica de ${esc(C.params[key].label)} en ${esc(n.name)}. Los triángulos rojos marcan anomalías."></canvas></div>
          <p class="muted small" style="margin-top:8px">${esc(C.params[key].help || "")} ${MOCK
            ? "La demo sin servidor manda una lectura cada 3 s. El nodo real guarda una cada 10 min, y una por minuto cuando detecta una anomalía."
            : `Lecturas de la última descarga. El nodo guarda una cada 10 min, y una por minuto cuando detecta una anomalía. Los triángulos rojos son las anomalías que encontró el análisis al subir el archivo. <a href="/api/abiertos/lecturas.csv?nodo=${encodeURIComponent(n.id)}&dias=7">Descargar 7 días en CSV</a>.`}</p></div>
        <details class="card-body"><summary style="cursor:pointer;font-weight:700">Últimas lecturas (tabla)</summary>
          <div class="table-wrap"><table class="data"><thead><tr><th>Hora</th>${keys.map(k => `<th>${esc(C.params[k].label)}</th>`).join("")}<th>Anomalía</th></tr></thead><tbody>
          ${last8.map(x => `<tr><td>${stamp(x.t)}</td>${keys.map(k => `<td class="num">${fmt.num(x[k], C.params[k].dec)}</td>`).join("")}<td>${x.anom && x.anom.length ? badge("crit", x.anom.map(k => C.params[k].label).join(", ")) : "—"}</td></tr>`).join("")}
          </tbody></table></div></details>` : `<p class="empty">Este nodo todavía no tiene lecturas. Aparecerán cuando Protección Civil suba su primer archivo en Recolección.</p>`}`;
    }
    main.innerHTML = `
      ${pageHead("Nodos", MOCK ? "Telemetría simulada de la red de sensores del río" : "Los nodos miden sin internet; aquí se ve lo que traía cada uno en su última descarga",
        `${(S().estaciones || []).length ? `<a class="btn btn-secondary" href="#/estacion">${icon("factory")}Estación piloto</a>` : ""}<a class="btn btn-secondary" href="#/mapa">${icon("map")}Ver en el mapa</a>`)}
      <section class="node-cards" id="cards" aria-label="Nodos de la red">${S().nodes.map(card).join("")}</section>
      <section class="card" id="detail" aria-labelledby="detTitle"></section>`;
    const series = {};                                   // medianas por hora ya pedidas, por nodo
    let chart2 = null;
    async function dibujaSerie() {
      if (MOCK) return;
      const nodo = sel, k = key;
      if (!series[nodo]) {
        try { series[nodo] = await VA.api.series(nodo, 7, "hora"); } catch (e) { return; }
      }
      const cv = document.getElementById("serieChart");
      if (!cv || nodo !== sel || k !== key) return;
      if (chart2) chart2.destroy();
      chart2 = VA.charts.series(cv, series[nodo].puntos || [], k);
    }
    function renderDetail() {
      if (chart) { chart.destroy(); chart = null; }
      if (chart2) { chart2.destroy(); chart2 = null; }
      document.getElementById("detail").innerHTML = detail();
      const canvas = document.getElementById("telChart");
      if (canvas) chart = VA.charts.telemetry(canvas, sel, key);
      dibujaSerie();
      document.querySelectorAll("[data-key]").forEach(b => b.addEventListener("click", () => { key = b.dataset.key; renderDetail(); }));
      refreshIcons();
    }
    document.getElementById("cards").addEventListener("click", e => {
      const b = e.target.closest("[data-node]"); if (!b) return;
      sel = b.dataset.node; history.replaceState(null, "", "#/nodos/" + sel);
      document.querySelectorAll("[data-node]").forEach(x => x.setAttribute("aria-pressed", x.dataset.node === sel));
      renderDetail();
    });
    renderDetail();
    return {
      update(msg) {
        if (msg.tipo === "sync") {                // llegó un lote: todo puede haber cambiado
          Object.keys(series).forEach(k => delete series[k]);
          if (!S().nodes.some(n => n.id === sel)) sel = S().nodes[0].id;
          document.getElementById("cards").innerHTML = S().nodes.map(card).join("");
          renderDetail();
          return;
        }
        if (msg.tipo !== "lectura") return;
        const el = document.querySelector(`[data-node="${msg.nodo}"]`);
        if (el) { const focused = document.activeElement === el; el.outerHTML = card(S().nodes.find(n => n.id === msg.nodo)); if (focused) document.querySelector(`[data-node="${msg.nodo}"]`).focus(); }
        if (msg.nodo === sel && chart) {
          chart.refresh();
          const cv = document.querySelector(".current-values");
          if (cv) cv.innerHTML = currentValues();
        }
        refreshIcons();
      },
      destroy() { if (chart) chart.destroy(); if (chart2) chart2.destroy(); }
    };
  }

  // =========================================================
  // REPORTES DE LA APP
  // =========================================================
  function reportes(main) {
    const f = { cat: "", estado: "" };
    const canEdit = VA.can("validar");
    main.innerHTML = `
      ${pageHead("Reportes de la app", "Llegan al momento desde la app móvil ciudadana (Android y iOS) con foto, ubicación o nota de voz")}
      ${demoBar()}
      <section class="kpis" id="repKpis" aria-label="Resumen de reportes"></section>
      <section class="card"><div class="card-body filters">
        <div class="chips" role="group" aria-label="Filtrar por categoría">
          <button class="chip" type="button" data-cat="" aria-pressed="true">Todas</button>
          ${S().categorias.map(c => `<button class="chip" type="button" data-cat="${esc(c)}" aria-pressed="false">${esc(c)}</button>`).join("")}
        </div>
        <div class="field"><label for="rEstado">Estado</label><select id="rEstado"><option value="">Todos</option>${["Recibido", "Validado", "En atención", "Atendido", "Descartado"].map(s => `<option>${s}</option>`).join("")}</select></div>
      </div>
      <div class="table-wrap"><table class="data"><thead><tr><th>Reporte</th><th>Clasificación IA</th><th>Lugar</th><th>Estado</th><th>Recibido</th><th><span class="sr-only">Acciones</span></th></tr></thead>
        <tbody id="repBody"></tbody></table></div></section>`;
    function kpis() {
      const all = S().reports, now = Date.now();
      const hoy = all.filter(r => now - r.t < DAY).length, pend = all.filter(r => r.status === "Recibido").length;
      const at = all.filter(r => r.status === "Atendido").length;
      document.getElementById("repKpis").innerHTML = [
        kpi("Últimas 24 horas", "smartphone", hoy, "Reportes recibidos"),
        kpi("Por revisar", "inbox", pend, "En estado Recibido", pend ? "warn" : "ok"),
        kpi("Atendidos", "circle-check", at, `de ${all.length} en los últimos 30 días`, "ok"),
        kpi("Con foto", "image", all.filter(r => r.photo).length, "Evidencia enviada desde la app")
      ].join("");
    }
    function rows() {
      kpis();
      const list = S().reports.filter(r => (!f.cat || r.cat === f.cat) && (!f.estado || r.status === f.estado));
      document.getElementById("repBody").innerHTML = list.length ? list.map(r => `
        <tr><td><strong>${esc(r.id)}</strong> ${r.voice ? `<span class="badge info">${icon("mic")}Voz</span>` : ""}${r.anonymous ? ` <span class="badge neutral">${icon("eye-off")}Anónimo</span>` : ""}
            ${r.photo && !MOCK ? ` <a class="badge info" href="${VA.api.photoUrl(r)}" target="_blank" rel="noopener">${icon("image")}Ver foto</a>` : ""}<span class="sub">${esc(r.text)}</span></td>
          <td>${r.ai ? `${esc(r.ai.label)}<span class="sub">Confianza ${fmt.pct(r.ai.conf)}</span>` : `<span class="muted">Sin clasificar</span>`}</td>
          <td>Cerca de ${esc(placeName(r.lat, r.lng))}${r.loc ? `<span class="sub">${r.loc === "gps" ? `GPS ±${fmt.num(r.precision, 1)} m` : "Punto marcado en el mapa"}</span>` : ""}</td><td>${stateBadge(r.status)}</td><td>${fmt.ago(r.t)}</td>
          <td><div class="btn-row nowrap">
            ${r.status === "Recibido" && canEdit ? `<button class="btn btn-secondary" data-val="${r.id}">${icon("badge-check")}Validar</button><button class="btn btn-ghost" data-desc="${r.id}">Descartar</button>` : ""}
            <button class="btn btn-ghost btn-icon" data-map="${r.id}" aria-label="Ver ${esc(r.id)} en el mapa">${icon("map-pin")}</button></div></td></tr>`).join("")
        : `<tr><td colspan="6" class="empty">No hay reportes con estos filtros.</td></tr>`;
      main.querySelectorAll("[data-val]").forEach(b => b.addEventListener("click", () => setStatus(b, b.dataset.val, "Validado")));
      main.querySelectorAll("[data-desc]").forEach(b => b.addEventListener("click", () => setStatus(b, b.dataset.desc, "Descartado")));
      main.querySelectorAll("[data-map]").forEach(b => b.addEventListener("click", () => { const r = S().reports.find(x => x.id === b.dataset.map); VA.state.focus = [r.lat, r.lng]; location.hash = "#/mapa"; }));
      refreshIcons();
    }
    async function setStatus(btn, id, st) {
      const r = S().reports.find(x => x.id === id);
      btn.disabled = true;
      try {
        const res = await VA.api.reportStatus(r, st);
        toast("ok", "Reporte " + st.toLowerCase(), id + (res.notified ? ": quien lo envió recibe el aviso en la app." : ": estado actualizado (reporte sin cuenta ligada)."));
      } catch (err) { fail(err); }
      rows();
    }
    main.querySelectorAll("[data-cat]").forEach(b => b.addEventListener("click", () => {
      f.cat = b.dataset.cat; main.querySelectorAll("[data-cat]").forEach(x => x.setAttribute("aria-pressed", x === b)); rows();
    }));
    document.getElementById("rEstado").addEventListener("change", e => { f.estado = e.target.value; rows(); });
    rows();
    return { update(msg) { if (msg.tipo === "reporte" || msg.caseChanged) rows(); } };
  }

  // =========================================================
  // RECOLECCIÓN (solo con servidor): visitas y archivo de la microSD
  // =========================================================
  function recoleccion(main) {
    const integ = v => !v || v === "sin_huella" ? badge("neutral", "Sin huella") : v === "verificada" ? badge("ok", "Huella verificada") : badge("crit", "Alterado desde la fila " + v.split(":")[1]);
    // Qué nodo conviene visitar primero: días sin descarga, reportes sin atender cerca y batería baja
    function ruta() {
      return S().nodes.map(n => {
        const dias = n.lastSync ? (Date.now() - n.lastSync) / DAY : null;
        const cerca = S().reports.filter(r => r.status === "Recibido" && Date.now() - r.t < 3 * DAY && E.km(n.lat, n.lng, r.lat, r.lng) <= C.fusionRadiusKm).length;
        const baja = n.battery != null && n.battery < 25;
        const motivos = [];
        if (dias == null) motivos.push("nunca se ha descargado");
        else if (dias > C.staleDays) motivos.push(`${Math.floor(dias)} días sin visita`);
        if (cerca) motivos.push(`${cerca} reporte${cerca === 1 ? "" : "s"} sin revisar cerca`);
        if (baja) motivos.push(`batería ${n.battery}%`);
        return { n, dias, motivos, puntos: Math.min(dias == null ? 14 : dias, 14) * 2 + cerca * 3 + (baja ? 6 : 0) };
      }).sort((a, b) => b.puntos - a.puntos);
    }
    function rutaRows() {
      return ruta().map((x, i) => `<tr><td class="num">${i + 1}</td><td><strong>${esc(x.n.id)}</strong> · ${esc(x.n.name)}<span class="sub">${esc(x.n.tec || "")}</span></td>
        <td>${x.n.lastSync ? fmt.date(x.n.lastSync) + `<span class="sub">${fmt.ago(x.n.lastSync)}</span>` : "—"}</td>
        <td>${x.motivos.length ? x.motivos.map(m => `<span class="badge ${/días|nunca/.test(m) ? "crit" : "warn"}">${esc(m)}</span>`).join(" ") : `<span class="muted">Visita de rutina</span>`}</td>
        <td class="num">${x.n.battery != null ? x.n.battery + "%" : "—"}</td></tr>`).join("");
    }
    // El nodo que tiene estación piloto escribe además las columnas de la planta
    const ayudaCsv = id => {
      const est = (S().estaciones || []).find(e => e.nodo === id);
      return "Columnas: t, ph, cond, turb, color, temp, nivel (y opcionales bateria, muestra, hash)." +
        (est ? ` En este nodo está la ${esc(est.nombre)} (${esc(est.codigo)}): el archivo también puede traer caudal, turb_sal, color_sal, cond_sal, ph_sal, lodos, dp_filtro y solar.` : "") +
        " Máximo 5 MB.";
    };
    main.innerHTML = `
      ${pageHead("Recolección", "En el río no hay internet: cada nodo guarda sus lecturas en la microSD y aquí se suben después de la visita")}
      ${demoBar()}
      <section class="card" aria-labelledby="rutaTitle">
        <div class="card-head"><h2 id="rutaTitle">Ruta sugerida de visitas</h2><span class="muted small">Primero los nodos con más días sin descarga, reportes cercanos o batería baja</span></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Orden</th><th>Nodo</th><th>Última descarga</th><th>Por qué visitarlo</th><th>Batería</th></tr></thead>
          <tbody id="rutaBody">${rutaRows()}</tbody></table></div>
      </section>
      <div class="grid-2-even">
        <section class="card" aria-labelledby="upTitle">
          <div class="card-head"><h2 id="upTitle">Subir archivo del nodo</h2></div>
          <form class="card-body form-grid" id="upForm" novalidate>
            <div class="field"><label for="upNodo">Nodo visitado</label>
              <select id="upNodo" required>${S().nodes.map(n => `<option value="${n.id}">${esc(n.id)} · ${esc(n.name)}</option>`).join("")}</select></div>
            <div class="field"><label for="upFile">Archivo CSV de la microSD</label>
              <input id="upFile" type="file" accept=".csv,text/csv" required aria-describedby="upHelp">
              <span class="help" id="upHelp">${ayudaCsv(S().nodes[0] && S().nodes[0].id)}</span></div>
            <fieldset class="checks"><legend>Lista de campo</legend>
              <label><input type="checkbox" id="ckLimpieza"> Limpié las sondas</label>
              <label><input type="checkbox" id="ckCalibracion"> Calibré el nodo</label>
              <label><input type="checkbox" id="ckFrascos"> Recogí los frascos con muestra</label></fieldset>
            <p class="form-error" id="upErr" role="alert" hidden></p>
            <div class="btn-row"><button class="btn btn-primary" type="submit" id="upBtn">${icon("upload")}Subir y analizar</button></div>
          </form>
          <div class="card-body" id="upResult" aria-live="polite"></div>
        </section>
        <section class="card" aria-labelledby="exTitle">
          <div class="card-head"><h2 id="exTitle">Archivo de ejemplo</h2></div>
          <div class="card-body form-grid">
            <p class="muted" style="margin:0">Genera un CSV con el formato exacto que debe escribir el nodo, con valores simulados. Sirve para probar la carga y como referencia para el firmware.</p>
            <div class="field"><label for="exNodo">Nodo</label><select id="exNodo">${S().nodes.map(n => `<option value="${n.id}">${esc(n.id)} · ${esc(n.name)}</option>`).join("")}</select></div>
            <div class="field"><label for="exEvento">Contenido</label><select id="exEvento"><option value="normal">8 horas normales</option><option value="descarga">Con una descarga textil</option><option value="crecida">Con una crecida</option></select></div>
            <div class="btn-row"><a class="btn btn-secondary" id="exLink" href="#" download>${icon("download")}Descargar CSV de ejemplo</a></div>
          </div>
        </section>
      </div>
      <section class="card" aria-labelledby="lotTitle">
        <div class="card-head"><h2 id="lotTitle">Archivos recibidos</h2></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Recibido</th><th>Nodo</th><th>Archivo</th><th>Lecturas</th><th>Periodo</th><th>Integridad</th><th>Eventos</th><th>Subió</th></tr></thead>
          <tbody id="lotBody"><tr><td colspan="8" class="empty">Cargando…</td></tr></tbody></table></div>
      </section>`;
    const exLink = document.getElementById("exLink");
    const setEx = () => { exLink.href = VA.api.batches.sampleUrl(document.getElementById("exNodo").value, document.getElementById("exEvento").value); };
    document.getElementById("exNodo").addEventListener("change", setEx);
    document.getElementById("exEvento").addEventListener("change", setEx);
    setEx();
    const upNodo = document.getElementById("upNodo");
    const setAyuda = () => { document.getElementById("upHelp").innerHTML = ayudaCsv(upNodo.value); };
    upNodo.addEventListener("change", setAyuda);

    async function lotes() {
      const body = document.getElementById("lotBody"); if (!body) return;
      try {
        const list = await VA.api.batches.list();
        if (!document.getElementById("lotBody")) return;       // la vista cambió mientras cargaba
        body.innerHTML = list.length ? list.map(l => `<tr><td>${fmt.date(l.uploaded)}<span class="sub">${fmt.ago(l.uploaded)}</span></td>
          <td><strong>${esc(l.node)}</strong></td><td>${esc(l.file || "—")}</td>
          <td class="num">${fmt.num(l.new)}<span class="sub">de ${fmt.num(l.rows)}${l.invalid ? ` · ${l.invalid} descartadas` : ""}</span></td>
          <td>${l.from ? `${fmt.date(l.from)} a ${fmt.date(l.to)}` : "—"}</td><td>${integ(l.integrity)}</td>
          <td>${l.events ? `${l.events} ` : "0 "}${l.cases.map(id => canSeeCases() ? `<a href="#/casos/${esc(id)}">${esc(id)}</a>` : esc(id)).join(", ")}</td><td>${esc(l.by || "—")}</td></tr>`).join("")
          : `<tr><td colspan="8" class="empty">Todavía no se ha subido ningún archivo.</td></tr>`;
        refreshIcons();
      } catch (err) { body.innerHTML = `<tr><td colspan="8" class="empty">${esc(err.message)}</td></tr>`; }
    }
    lotes();

    const form = document.getElementById("upForm"), errEl = document.getElementById("upErr"), out = document.getElementById("upResult");
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const file = document.getElementById("upFile").files[0], nodo = document.getElementById("upNodo").value;
      errEl.hidden = true; out.innerHTML = "";
      if (!file) { errEl.textContent = "Elige el archivo CSV que descargaste del nodo."; errEl.hidden = false; document.getElementById("upFile").focus(); return; }
      if (file.size > 5 * 1024 * 1024) { errEl.textContent = "El archivo pesa más de 5 MB. Súbelo en partes."; errEl.hidden = false; return; }
      const fd = new FormData();
      fd.append("nodo", nodo); fd.append("archivo", file);
      fd.append("limpieza", document.getElementById("ckLimpieza").checked); fd.append("calibracion", document.getElementById("ckCalibracion").checked);
      fd.append("frascos", document.getElementById("ckFrascos").checked);
      const btn = document.getElementById("upBtn"); btn.disabled = true;
      try {
        const r = await VA.api.batches.upload(fd);
        const casos = [...r.casos, ...r.casos_actualizados];
        out.innerHTML = `<div class="banner ${r.integridad.startsWith("alterada") ? "crit" : ""}">${icon(r.eventos ? "octagon-alert" : "circle-check")}<div>
          <strong>${esc(nodo)}: ${fmt.num(r.nuevas)} lecturas nuevas guardadas.</strong>
          ${r.duplicadas ? ` ${fmt.num(r.duplicadas)} ya estaban en la base.` : ""}${r.invalidas ? ` ${fmt.num(r.invalidas)} filas se descartaron por fecha o valores imposibles.` : ""}
          <br>Periodo: ${fmt.date(r.desde)} a ${fmt.date(r.hasta)} · ${integ(r.integridad)}
          <br>${r.eventos ? `El análisis encontró <strong>${r.eventos} posible${r.eventos === 1 ? "" : "s"} descarga${r.eventos === 1 ? "" : "s"}</strong>.` : "El análisis no encontró descargas."}
          ${r.turbidez_por_lluvia ? " La turbidez subió junto con el nivel del agua: se tomó como lodo arrastrado por la lluvia, no como descarga." : ""}
          ${casos.length ? ` Casos abiertos o actualizados: ${casos.map(id => canSeeCases() ? `<a href="#/casos/${esc(id)}">${esc(id)}</a>` : esc(id)).join(", ")}.` : ""}</div></div>`;
        form.reset(); setAyuda();
        await VA.api.refresh();
        VA.app.emit({ tipo: "sync", caseChanged: true });
      } catch (err) { errEl.textContent = err.message; errEl.hidden = false; }
      finally { btn.disabled = false; refreshIcons(); }
    });
    return { update(msg) { if (msg.tipo !== "sync") return; const rb = document.getElementById("rutaBody"); if (rb) rb.innerHTML = rutaRows(); lotes(); refreshIcons(); } };
  }

  // =========================================================
  // PREDICCIÓN
  // =========================================================
  function prediccion(main) {
    const withData = S().tramos.filter(t => (S().dailyIndex[t.id] || []).length >= 3);
    if (!withData.length) { main.innerHTML = pageHead("Predicción por tramo", "") + `<p class="empty">Todavía no hay suficiente historial para pronosticar. Se necesitan al menos tres días de datos por tramo.</p>`; return {}; }
    let sel = withData.some(t => t.id === "T2") ? "T2" : withData[0].id, chart = null;
    const DIAS_SEM = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
    main.innerHTML = `
      ${pageHead("Pronóstico por tramo", "Cómo estará la calidad del agua la próxima semana, con lo que han medido los nodos")}
      <section class="card">
        <div class="card-head"><h2 id="pTitle"></h2>
          <div class="chips" role="group" aria-label="Tramo">${withData.map(t => `<button class="chip" type="button" data-t="${t.id}" aria-pressed="${t.id === sel}">${t.id}</button>`).join("")}</div></div>
        <div class="card-body"><div class="banner" id="pSummary"></div></div>
        <div class="card-body"><div class="chart-box"><canvas id="fcChart" role="img" aria-label="Índice de calidad medido (30 días) y pronosticado (7 días)"></canvas></div></div>
        <div class="grid-ops-even" style="padding:0 var(--space-4) var(--space-4)">
          <div class="table-wrap"><table class="data"><thead><tr><th>Día</th><th>Índice</th><th>Rango probable</th><th>Semáforo</th></tr></thead><tbody id="fcBody"></tbody></table></div>
          <div class="small" id="pModel"></div>
        </div>
      </section>`;
    function render() {
      const t = S().tramos.find(x => x.id === sel), series = S().dailyIndex[sel];
      const ultimo = series[series.length - 1];
      const atraso = Math.max(0, diaLocal(Date.now()) - diaLocal(ultimo.t));          // días sin datos (nodo sin visita)
      const fc = E.forecast(series, 7 + atraso);
      const futuro = fc.points.slice(atraso);
      document.getElementById("pTitle").textContent = `${t.id} · ${t.name}`;
      const now = ultimo.v, end = futuro[futuro.length - 1];
      const sNow = E.indexStatus(now), sEnd = E.indexStatus(end.v);
      const firstChange = futuro.find(p => E.indexStatus(p.v) !== sNow);
      const sumEl = document.getElementById("pSummary");
      sumEl.className = "banner" + (sEnd === "crit" ? " crit" : atraso > 2 ? " warn" : "");
      sumEl.innerHTML = `${icon(fc.slope < -0.5 ? "trending-down" : fc.slope > 0.5 ? "trending-up" : "minus")}<div><strong>Último índice: ${now} (${E.semLabel[sNow]})</strong>${atraso ? `, del ${fmt.day(ultimo.t)}` : ""}.
        ${atraso > 2 ? `El nodo ${esc(t.to)} lleva ${atraso} días sin visita: el pronóstico arranca de su último dato y su rango es más ancho.` : ""}
        ${firstChange ? `Pasaría a <strong>${E.semLabel[E.indexStatus(firstChange.v)]}</strong> el ${fmt.day(firstChange.t)}.` : `Se mantiene en ${E.semLabel[sNow]} la próxima semana.`}
        ${sEnd === "crit" ? " La vida acuática de este tramo estaría en riesgo." : ""}</div>`;
      document.getElementById("fcBody").innerHTML = futuro.map(p => `<tr><td>${fmt.day(p.t)}</td><td class="num">${p.v}</td><td class="num">${p.lo}–${p.hi}</td><td>${badge(E.indexStatus(p.v))}</td></tr>`).join("");
      // El efecto de cada día de la semana sale del propio historial (la industria descarga más entre semana)
      const efecto = fc.weekly || [], n = series.slice(-90).length, base = series.slice(-90)[0].t;
      const porDiaSem = efecto.map((v, i) => ({ d: (new Date(base + i * DAY).getDay() + 6) % 7, v })).sort((a, b) => a.d - b.d);
      const peor = porDiaSem.length ? porDiaSem.reduce((a, b) => (b.v < a.v ? b : a)) : null;
      document.getElementById("pModel").innerHTML = `<p><strong>Cómo se calcula.</strong> Holt-Winters: nivel actual + tendencia (amortiguada) + efecto de cada día de la semana,
        ajustado con ${n} días medidos. No es una caja negra: cada parte se puede explicar.</p>
        <p>Tendencia: <strong>${fc.slope > 0 ? "+" : ""}${fmt.num(fc.slope, 1)} puntos por semana</strong>${peor ? ` · el día que peor sale es el <strong>${DIAS_SEM[peor.d]}</strong> (${fmt.num(peor.v, 1)} puntos)` : ""}.
        Error típico de un día adelante: ±${fmt.num(fc.sd || 0, 1)} puntos; el rango probable cubre el 80% de los casos.</p>
        <p class="muted">Con más meses de datos se agregará la lluvia pronosticada (Conagua/SMN) para anticipar crecidas.</p>`;
      if (chart) chart.destroy();
      chart = VA.charts.forecast(document.getElementById("fcChart"), series.slice(-30), { ...fc, points: fc.points });
      refreshIcons();
    }
    main.querySelectorAll("[data-t]").forEach(b => b.addEventListener("click", () => {
      sel = b.dataset.t; main.querySelectorAll("[data-t]").forEach(x => x.setAttribute("aria-pressed", x === b)); render();
    }));
    render();
    return { destroy() { if (chart) chart.destroy(); } };
  }

  // =========================================================
  // TRANSPARENCIA (vista pública)
  // =========================================================
  function transparencia(main) {
    const charts = [];
    const closed = S().cases.filter(c => c.closedAt);
    const byDep = Object.keys(C.dependencias).map(d => ({ d, list: closed.filter(c => c.dep === d) })).filter(x => x.list.length);
    const cats = S().categorias.map(c => ({ c, n: S().reports.filter(r => r.cat === c).length }));
    main.innerHTML = `
      ${pageHead("Transparencia", "Cuánto tarda cada dependencia en atender y qué reporta la ciudadanía. Sin datos personales.")}
      <section class="kpis">
        ${kpi("Casos atendidos", "circle-check", closed.length, "Cerrados en la plataforma", "ok")}
        ${kpi("Casos abiertos", "folder-open", openCases(S().cases).length, "En proceso", "warn")}
        ${kpi("Reportes ciudadanos", "smartphone", S().reports.length, "Desde la app, últimos 30 días")}
        ${kpi("Tiempo promedio de atención", "timer", closed.length ? fmt.num(avgDays(closed), 1) + " días" : "—", "De los casos cerrados")}
        ${S().basura ? kpi("Basura retirada", "trash-2", fmt.num(S().basura.kg90) + " kg", `De las barreras en 90 días · ${fmt.num(S().basura.kg30)} kg en el último mes`) : ""}
      </section>
      <div class="grid-2-even">
        <section class="card"><div class="card-head"><h2>Tiempo promedio de atención</h2></div>
          <div class="card-body">${byDep.length ? `<div class="chart-box sm"><canvas id="tDep" role="img" aria-label="Días promedio de atención por dependencia"></canvas></div>
          <p class="small muted">${byDep.map(x => `${esc(C.dependencias[x.d].label)}: ${fmt.num(avgDays(x.list), 1)} días`).join(" · ")}</p>` : `<p class="empty">Aún no hay casos cerrados.</p>`}</div></section>
        <section class="card"><div class="card-head"><h2>Reportes por categoría</h2></div>
          <div class="card-body"><div class="chart-box sm"><canvas id="tCat" role="img" aria-label="Número de reportes por categoría"></canvas></div>
          <p class="small muted">${cats.map(x => `${esc(x.c)}: ${x.n}`).join(" · ")}</p></div></section>
      </div>
      <section class="card"><div class="card-head"><h2>Casos públicos</h2></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Folio</th><th>Tipo</th><th>Lugar</th><th>Dependencia</th><th>Estado</th><th>Días</th></tr></thead><tbody>
        ${S().cases.slice().sort((a, b) => b.t - a.t).map(c => `<tr><td>${esc(c.id)}</td><td>${esc(caseType(c).label)}</td><td>${esc(casePlace(c))}</td><td>${esc(C.dependencias[c.dep].label)}</td><td>${stateBadge(c.status)}</td>
          <td class="num">${fmt.num(((c.closedAt || Date.now()) - c.t) / DAY, 1)}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">Todavía no hay casos.</td></tr>`}
        </tbody></table></div></section>`;
    if (byDep.length) charts.push(VA.charts.bars(document.getElementById("tDep"), byDep.map(x => C.dependencias[x.d].label), byDep.map(x => +avgDays(x.list).toFixed(1)), { unit: "días" }));
    charts.push(VA.charts.bars(document.getElementById("tCat"), cats.map(x => x.c), cats.map(x => x.n), { unit: "reportes", color: "#0E7490" }));
    return { destroy() { charts.forEach(c => c.destroy()); } };
  }

  // =========================================================
  // USUARIOS (Administración, solo con servidor)
  // =========================================================
  function usuarios(main) {
    const roleOptions = sel => Object.entries(C.roles).filter(([k]) => k !== "publico").map(([k, v]) => `<option value="${k}"${k === sel ? " selected" : ""}>${esc(v.label)}</option>`).join("");
    const fixedPerms = rol => rol === "admin" || rol === "ciudadano";
    const RESULT = { ok: ["ok", "Entró"], clave: ["warn", "Contraseña incorrecta"], desactivada: ["neutral", "Cuenta desactivada"], bloqueo: ["crit", "Bloqueada por intentos"] };
    let list = [], cat = null;
    main.innerHTML = `
      ${pageHead("Usuarios", "Cuentas del personal, qué puede usar cada persona y bitácora de accesos")}
      <section class="card" aria-labelledby="newTitle">
        <div class="card-head"><h2 id="newTitle">Nueva cuenta</h2></div>
        <form class="card-body form-grid cols" id="newForm" novalidate>
          <div class="field"><label for="nuNombre">Nombre</label><input id="nuNombre" type="text" required minlength="2" maxlength="80" autocomplete="off"></div>
          <div class="field"><label for="nuCuenta">Correo o teléfono</label><input id="nuCuenta" type="text" required maxlength="120" autocomplete="off" inputmode="email"></div>
          <div class="field"><label for="nuRol">Rol</label><select id="nuRol">${roleOptions("ambiental")}</select></div>
          ${passField("nuClave", "Contraseña temporal", { help: "Mínimo 8 caracteres. Al entrar por primera vez, el sistema le pide crear la suya." })}
          <fieldset class="perm-set"><legend>Qué podrá usar</legend><div class="perm-grid" id="nuPerms"><p class="small muted">Cargando permisos…</p></div></fieldset>
          <p class="form-error" id="nuErr" role="alert" hidden></p>
          <div class="btn-row"><button class="btn btn-primary" type="submit">${icon("user-plus")}Crear cuenta</button></div>
        </form>
      </section>
      <section class="card" aria-labelledby="usTitle">
        <div class="card-head"><h2 id="usTitle">Cuentas</h2><span class="muted small" id="usCount"></span></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Persona</th><th>Rol</th><th>Puede usar</th><th>Estado</th><th>Último acceso</th><th><span class="sr-only">Acciones</span></th></tr></thead>
          <tbody id="usBody"><tr><td colspan="6" class="empty">Cargando…</td></tr></tbody></table></div>
      </section>
      <section class="card" aria-labelledby="logTitle">
        <div class="card-head"><h2 id="logTitle">Bitácora de accesos</h2><span class="muted small">Últimos intentos de inicio de sesión, correctos y fallidos</span></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Cuándo</th><th>Cuenta</th><th>Resultado</th><th>Desde</th></tr></thead>
          <tbody id="logBody"><tr><td colspan="4" class="empty">Cargando…</td></tr></tbody></table></div>
      </section>`;
    wirePassToggles(main);
    const me = VA.session.user;

    // Casillas de permisos: las que trae el rol vienen marcadas; Administración y ciudadanía no se ajustan
    const grantable = () => Object.keys(cat.permisos).filter(p => !cat.solo_admin.includes(p));
    function permGrid(prefix, rol, selected) {
      if (fixedPerms(rol)) return `<p class="small muted">${rol === "admin" ? "Administración tiene acceso a todo, incluidas las cuentas y la configuración."
        : "La ciudadanía reporta desde la app; en la plataforma solo ve la vista pública."}</p>`;
      const preset = cat.por_rol[rol] || [];
      return grantable().map(p => `<label class="perm-item" for="${prefix}_${p}"><input type="checkbox" id="${prefix}_${p}" value="${p}"${selected.includes(p) ? " checked" : ""}>
        <span><strong>${esc(C.permisoLabels[p] || p)}</strong>${preset.includes(p) ? ` <span class="perm-tag">del rol</span>` : ""}<span class="sub">${esc(cat.permisos[p])}</span></span></label>`).join("");
    }
    const checkedIn = root => [...root.querySelectorAll('input[type="checkbox"]:checked')].map(i => i.value);
    function newPerms() {
      if (!cat) return;
      const rol = document.getElementById("nuRol").value;
      document.getElementById("nuPerms").innerHTML = permGrid("np", rol, cat.por_rol[rol] || []);
    }
    document.getElementById("nuRol").addEventListener("change", newPerms);

    function permSummary(u) {
      if (u.rol === "admin") return `<span class="perm-all">Todo</span>`;
      if (u.rol === "ciudadano") return `<span class="muted">App ciudadana</span>`;
      const names = u.permisos.map(p => C.permisoLabels[p] || p);
      return (names.length ? esc(names.join(" · ")) : `<span class="muted">Solo vista pública</span>`) + (u.permisos_propios ? ` <span class="badge warn">Ajustados</span>` : "");
    }
    function rows() {
      document.getElementById("usCount").textContent = `${list.filter(u => u.activo).length} activas de ${list.length}`;
      document.getElementById("usBody").innerHTML = list.map(u => `<tr>
        <td><strong>${esc(u.nombre)}</strong>${u.id === me.id ? ` <span class="badge info">Tú</span>` : ""}${u.demo ? ` <span class="badge neutral">Demo</span>` : ""}<span class="sub">${esc(u.cuenta)}</span></td>
        <td><label class="sr-only" for="rol_${u.id}">Rol de ${esc(u.nombre)}</label><select id="rol_${u.id}" data-rol="${u.id}"${u.id === me.id ? " disabled" : ""}>${roleOptions(u.rol)}</select></td>
        <td class="perm-cell">${permSummary(u)}</td>
        <td>${u.activo ? badge("ok", "Activa") : badge("neutral", "Desactivada")}${u.cambiar_clave ? `<span class="sub">Debe cambiar su contraseña temporal</span>` : ""}</td>
        <td>${u.ultimo_acceso ? fmt.date(u.ultimo_acceso) : `<span class="muted">Nunca</span>`}</td>
        <td><div class="btn-row user-actions">
          ${fixedPerms(u.rol) ? "" : `<button class="btn btn-ghost" type="button" data-perms="${u.id}">${icon("list-checks")}Permisos</button>`}
          <button class="btn btn-ghost" type="button" data-pass="${u.id}">${icon("key-round")}Contraseña</button>
          ${u.id === me.id ? "" : `<button class="btn ${u.activo ? "btn-danger" : "btn-secondary"}" type="button" data-toggle="${u.id}">${icon(u.activo ? "user-x" : "user-check")}${u.activo ? "Desactivar" : "Reactivar"}</button>`}
        </div></td></tr>`).join("");
      main.querySelectorAll("[data-rol]").forEach(s => s.addEventListener("change", () =>
        change(+s.dataset.rol, { rol: s.value }, "Rol actualizado", "tiene los permisos de su nuevo rol y se cerraron sus sesiones abiertas.")));
      main.querySelectorAll("[data-toggle]").forEach(b => b.addEventListener("click", () => {
        const u = list.find(x => x.id === +b.dataset.toggle);
        change(u.id, { activo: !u.activo }, u.activo ? "Cuenta desactivada" : "Cuenta reactivada", u.activo ? "ya no puede entrar y se cerraron sus sesiones." : "ya puede volver a entrar.");
      }));
      main.querySelectorAll("[data-pass]").forEach(b => b.addEventListener("click", () => resetDialog(list.find(x => x.id === +b.dataset.pass))));
      main.querySelectorAll("[data-perms]").forEach(b => b.addEventListener("click", () => permDialog(list.find(x => x.id === +b.dataset.perms))));
      refreshIcons();
    }
    function logRows(items) {
      document.getElementById("logBody").innerHTML = items.length ? items.map(a => {
        const [k, text] = RESULT[a.resultado] || ["neutral", a.resultado];
        return `<tr><td>${fmt.date(a.t)}</td><td>${esc(a.cuenta)}${a.nombre ? `<span class="sub">${esc(a.nombre)}</span>` : ""}</td><td>${badge(k, text)}</td><td>${esc(a.ip || "—")}</td></tr>`;
      }).join("") : `<tr><td colspan="4" class="empty">Todavía no hay inicios de sesión registrados.</td></tr>`;
      refreshIcons();
    }
    async function load() {
      try {
        const [l, c, log] = await Promise.all([VA.api.users.list(), cat ? cat : VA.api.users.catalog(), VA.api.users.accesses()]);
        list = l; cat = c;
        if (!document.getElementById("usBody")) return;               // ya se salió de la vista
        rows(); logRows(log);
        if (document.getElementById("nuPerms").querySelector(".muted") || !document.getElementById("nuPerms").children.length) newPerms();
      } catch (err) {
        ["usBody", "logBody"].forEach(id => { const b = document.getElementById(id); if (b) b.innerHTML = `<tr><td colspan="7" class="empty">${esc(err.message)}</td></tr>`; });
      }
    }
    async function change(id, data, okTitle, okMsg) {
      try {
        const u = await VA.api.users.update(id, data);
        Object.assign(list.find(x => x.id === id), u);
        toast("ok", okTitle, `${u.nombre} ${okMsg}`);
        VA.ui.closeDrawer(true);
      } catch (err) { fail(err); }
      rows();
    }
    function permDialog(u) {
      const deps = C.roles[u.rol].deps.map(d => C.dependencias[d].label).join(", ");
      const dlg = VA.ui.openDrawer(`
        <div class="drawer-head"><div><div class="muted small">${esc(C.roles[u.rol].label)} · ${esc(u.cuenta)}</div><h2 style="font-size:1.35rem">Permisos de ${esc(u.nombre)}</h2></div>
          <button class="btn btn-ghost btn-icon" data-close aria-label="Cerrar">${icon("x")}</button></div>
        <form class="drawer-body form-grid" id="pmForm" novalidate>
          <p class="small muted" style="margin:0">Resumen, Mapa y Transparencia siempre están disponibles.${deps ? ` Los casos que ve y atiende son los de ${esc(deps)}.` : ""}
            El cambio aplica al momento: su menú se actualiza solo.</p>
          <fieldset class="perm-set"><legend>Qué puede usar</legend><div class="perm-grid one">${permGrid("pm", u.rol, u.permisos)}</div></fieldset>
          <div class="btn-row"><button class="btn btn-primary" type="submit">${icon("save")}Guardar permisos</button>
            <button class="btn btn-secondary" type="button" id="pmReset">${icon("rotate-ccw")}Usar los del rol</button></div>
        </form>`, { label: "Permisos de " + u.nombre });
      dlg.querySelector("#pmForm").addEventListener("submit", e => {
        e.preventDefault();
        change(u.id, { permisos: checkedIn(dlg) }, "Permisos actualizados", "ya ve solo los módulos marcados.");
      });
      dlg.querySelector("#pmReset").addEventListener("click", () => change(u.id, { permisos_del_rol: true }, "Permisos del rol", `volvió a los permisos de ${C.roles[u.rol].label}.`));
    }
    function resetDialog(u) {
      const dlg = VA.ui.openDrawer(`
        <div class="drawer-head"><div><div class="muted small">${esc(u.cuenta)}</div><h2 style="font-size:1.35rem">Nueva contraseña para ${esc(u.nombre)}</h2></div>
          <button class="btn btn-ghost btn-icon" data-close aria-label="Cerrar">${icon("x")}</button></div>
        <form class="drawer-body form-grid" id="rpForm" novalidate>
          ${passField("rpClave", "Contraseña temporal", { help: "Mínimo 8 caracteres. Al guardarla se cierran las sesiones abiertas de esta cuenta." })}
          <p class="form-error" id="rpErr" role="alert" hidden></p>
          <div class="btn-row"><button class="btn btn-primary" type="submit">${icon("save")}Guardar contraseña</button></div>
        </form>`, { label: "Nueva contraseña" });
      wirePassToggles(dlg);
      dlg.querySelector("#rpForm").addEventListener("submit", async e => {
        e.preventDefault();
        const err = dlg.querySelector("#rpErr"), val = dlg.querySelector("#rpClave").value;
        if (val.length < 8) { err.textContent = "La contraseña debe tener al menos 8 caracteres."; err.hidden = false; return; }
        try {
          const nu = await VA.api.users.update(u.id, { clave: val });
          Object.assign(u, nu); VA.ui.closeDrawer(); rows();
          toast("ok", "Contraseña temporal asignada", u.id === me.id ? "Tu contraseña quedó cambiada." : `${u.nombre} entra con ella y el sistema le pide crear una propia.`);
        }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      });
    }
    document.getElementById("newForm").addEventListener("submit", async e => {
      e.preventDefault();
      const err = document.getElementById("nuErr"), v = id => document.getElementById(id).value.trim();
      const data = { nombre: v("nuNombre"), cuenta: v("nuCuenta"), rol: v("nuRol"), clave: document.getElementById("nuClave").value };
      if (cat && !fixedPerms(data.rol)) data.permisos = checkedIn(document.getElementById("nuPerms"));
      err.hidden = true;
      const bad = data.nombre.length < 2 ? ["nuNombre", "Escribe el nombre de la persona."] : !data.cuenta ? ["nuCuenta", "Escribe un correo o un teléfono de 10 dígitos."]
        : data.clave.length < 8 ? ["nuClave", "La contraseña debe tener al menos 8 caracteres."] : null;
      if (bad) { err.textContent = bad[1]; err.hidden = false; document.getElementById(bad[0]).focus(); return; }
      try {
        const u = await VA.api.users.create(data);
        e.target.reset();
        newPerms();
        toast("ok", "Cuenta creada", `${u.nombre} ya puede entrar como ${C.roles[u.rol].label}.` + (u.cambiar_clave ? " Al hacerlo, el sistema le pedirá cambiar la contraseña temporal." : ""));
        await load();
      } catch (ex) { err.textContent = ex.message; err.hidden = false; }
    });
    load();
    return { destroy() { VA.ui.closeDrawer(true); } };
  }

  // Panel "Cambiar contraseña" (menú de la cuenta)
  function passwordDialog() {
    const dlg = VA.ui.openDrawer(`
      <div class="drawer-head"><div><div class="muted small">${esc(VA.session.user.cuenta)}</div><h2 style="font-size:1.35rem">Cambiar contraseña</h2></div>
        <button class="btn btn-ghost btn-icon" data-close aria-label="Cerrar">${icon("x")}</button></div>
      <form class="drawer-body form-grid" id="pwForm" novalidate>
        ${passField("pwActual", "Contraseña actual", { auto: "current-password" })}
        ${passField("pwNueva", "Contraseña nueva", { help: "Mínimo 8 caracteres." })}
        ${passField("pwRepite", "Repite la contraseña nueva")}
        <p class="form-error" id="pwErr" role="alert" hidden></p>
        <div class="btn-row"><button class="btn btn-primary" type="submit">${icon("save")}Guardar</button></div>
      </form>`, { label: "Cambiar contraseña" });
    wirePassToggles(dlg);
    dlg.querySelector("#pwForm").addEventListener("submit", async e => {
      e.preventDefault();
      const err = dlg.querySelector("#pwErr"), v = id => dlg.querySelector("#" + id).value;
      const msg = !v("pwActual") ? "Escribe tu contraseña actual." : v("pwNueva").length < 8 ? "La contraseña nueva debe tener al menos 8 caracteres."
        : v("pwNueva") !== v("pwRepite") ? "Las dos contraseñas nuevas no coinciden." : "";
      if (msg) { err.textContent = msg; err.hidden = false; return; }
      try { await VA.api.changePassword(v("pwActual"), v("pwNueva")); VA.ui.closeDrawer(); toast("ok", "Contraseña cambiada", "Se cerraron tus sesiones en otros dispositivos."); }
      catch (ex) { err.textContent = ex.message; err.hidden = false; }
    });
  }

  // =========================================================
  // CONFIGURACIÓN Y DEMO (administración)
  // =========================================================
  function config(main) {
    const ps = C.params;
    main.innerHTML = `
      ${pageHead("Configuración y demo", "Umbrales del semáforo, simulaciones para la presentación y conexión con el servidor")}
      ${demoBar()}
      <section class="card"><div class="card-head"><h2>Umbrales del semáforo</h2></div>
        <form class="card-body" id="thrForm" novalidate>
          <div class="table-wrap"><table class="data"><thead><tr><th>Parámetro</th><th>Atención desde</th><th>Crítico desde</th></tr></thead><tbody>
          ${Object.entries(ps).filter(([k]) => k !== "ph").map(([k, p]) => `<tr><td><strong>${esc(p.label)}</strong><span class="sub">${esc(p.unit)}</span></td>
            <td><label class="sr-only" for="w_${k}">${esc(p.label)}: atención</label><input type="number" step="any" id="w_${k}" value="${p.warn}"></td>
            <td><label class="sr-only" for="c_${k}">${esc(p.label)}: crítico</label><input type="number" step="any" id="c_${k}" value="${p.crit}"></td></tr>`).join("")}
          <tr><td><strong>pH</strong><span class="sub">Rango normal</span></td>
            <td><label class="sr-only" for="phmin">pH mínimo normal</label><input type="number" step="any" id="phmin" value="${ps.ph.min}"> a <label class="sr-only" for="phmax">pH máximo normal</label><input type="number" step="any" id="phmax" value="${ps.ph.max}"></td>
            <td><label class="sr-only" for="phcmin">pH crítico bajo</label><input type="number" step="any" id="phcmin" value="${ps.ph.critMin}"> / <label class="sr-only" for="phcmax">pH crítico alto</label><input type="number" step="any" id="phcmax" value="${ps.ph.critMax}"></td></tr>
          </tbody></table></div>
          <p class="form-error" id="thrErr" role="alert" hidden></p>
          <button class="btn btn-primary" type="submit">${icon("save")}Guardar umbrales</button>
        </form></section>
      <section class="card"><div class="card-head"><h2>Conexión con el servidor</h2></div><div class="card-body">
        ${MOCK ? `<p>Modo actual: <strong>demo sin servidor</strong> (datos simulados en el navegador). Nada de lo que hagas aquí se guarda.</p>
          <p class="small muted">Para la versión completa con inicio de sesión, inicia el servidor (<code>iniciar.bat</code>) y abre <code>http://localhost:8000</code>.</p>`
        : `<p>Modo actual: <strong>servidor conectado</strong>${VA.session.demo ? " con datos de demostración" : ""}. Los cambios se guardan en la base de datos.</p>
          <p class="small muted">Referencia de la API para la app móvil y el firmware: <a href="/api/docs" target="_blank" rel="noopener">/api/docs</a> · Indicadores públicos: <a href="/api/metricas" target="_blank" rel="noopener">/api/metricas</a></p>`}
      </div></section>`;
    document.getElementById("thrForm").addEventListener("submit", async e => {
      e.preventDefault();
      const err = document.getElementById("thrErr"); let ok = true;
      const v = id => +document.getElementById(id).value;
      Object.keys(ps).filter(k => k !== "ph").forEach(k => {
        const bad = !(v("c_" + k) > v("w_" + k));
        document.getElementById("c_" + k).setAttribute("aria-invalid", bad); if (bad) ok = false;
      });
      if (!ok) { err.textContent = "Revisa los valores: el umbral crítico debe ser mayor que el de atención."; err.hidden = false; return; }
      err.hidden = true;
      const next = { ph: { min: v("phmin"), max: v("phmax"), critMin: v("phcmin"), critMax: v("phcmax") } };
      Object.keys(ps).filter(k => k !== "ph").forEach(k => { next[k] = { warn: v("w_" + k), crit: v("c_" + k) }; });
      try {
        await VA.api.saveThresholds(next);
        toast("ok", "Umbrales guardados", "El semáforo ya usa los nuevos valores" + (MOCK ? "." : " para todas las personas conectadas."));
      } catch (ex) { err.textContent = ex.message; err.hidden = false; }
    });
    return {};
  }

  VA.views = { resumen, mapa, estacion, casos, nodos, reportes, recoleccion, prediccion, transparencia, usuarios, config, openCase, passwordDialog };
})();
