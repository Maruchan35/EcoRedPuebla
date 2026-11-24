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
  const isAdmin = () => role() === "admin";
  const demoOn = () => MOCK || VA.session.demo;
  const canSeeCases = () => C.roles[role()].deps.length > 0;
  const visibleCases = () => S().cases.filter(c => C.roles[role()].deps.includes(c.dep));
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
  // Botones de simulación: solo Administración, y solo con datos de demostración
  function demoBar() {
    if (!isAdmin() || !demoOn()) return "";
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
  function resumen(main) {
    function kpisHtml() {
      const nodes = S().nodes, low = nodes.filter(n => n.battery != null && n.battery < 25).length;
      const st = S().tramos.map(VA.map.tramoStatus);
      const crit = st.filter(s => s === "crit").length, warn = st.filter(s => s === "warn").length, off = st.filter(s => s === "off").length;
      const fresh = nodes.filter(n => VA.map.nodeStatus(n) !== "off").length, old = nodes.length - fresh;
      const vis = canSeeCases() ? visibleCases() : S().cases;
      const open = openCases(vis).length;
      const closed30 = S().cases.filter(c => c.closedAt && Date.now() - c.closedAt < 30 * DAY);
      const rep7 = S().reports.filter(r => Date.now() - r.t < 7 * DAY).length;
      const closed = S().cases.filter(c => c.closedAt);
      return [
        MOCK ? kpi("Nodos en línea", "radio-tower", `${nodes.length}/${nodes.length}`, low ? `${low} con batería baja` : "Todos con batería suficiente", low ? "warn" : "ok")
             : kpi("Nodos con datos al día", "radio-tower", `${fresh}/${nodes.length}`,
                 old ? `${old} con más de ${C.staleDays} días sin visita` : low ? `${low} con batería baja` : "Todos visitados esta semana", old || low ? "warn" : "ok"),
        kpi("Tramos con alerta", "waves", `${crit + warn}`, `${crit} crítico${crit === 1 ? "" : "s"} · ${warn} en atención${off ? ` · ${off} sin datos` : ""}`, crit ? "crit" : warn ? "warn" : "ok"),
        canSeeCases() ? kpi("Casos abiertos", "folder-open", open, `de ${C.roles[role()].label.toLowerCase()}`, open ? "warn" : "ok")
                      : kpi("Casos atendidos (30 días)", "circle-check", closed30.length, "Ver detalle en Transparencia", "ok"),
        kpi("Reportes ciudadanos", "smartphone", rep7, "Últimos 7 días desde la app"),
        kpi("Tiempo promedio de atención", "timer", closed.length ? fmt.num(avgDays(closed), 1) + " días" : "—", "Casos cerrados")
      ].join("");
    }
    function recentHtml() {
      const list = (canSeeCases() ? visibleCases() : S().cases).slice().sort((a, b) => b.t - a.t).slice(0, 6);
      if (!list.length) return `<p class="empty">Todavía no hay casos.</p>`;
      return `<ul class="list">${list.map(c => {
        const tone = c.status === "Cerrado" ? "ok" : c.priority === "Alta" ? "crit" : "warn";
        const title = canSeeCases() ? `<a href="#/casos/${c.id}">${esc(caseType(c).label)}</a>` : esc(caseType(c).label);
        return `<li><span class="li-icon ${tone}">${icon(caseType(c).icon)}</span><div class="li-main">
          <div class="li-title">${title}</div><div class="li-meta">${esc(casePlace(c))} · ${fmt.ago(c.t)}</div></div>
          <div>${stateBadge(c.status)}</div></li>`;
      }).join("")}</ul>`;
    }
    const guest = !MOCK && !VA.session.user;
    main.innerHTML = `
      ${pageHead("Resumen de la cuenca", `Alto Atoyac y barrancas de la capital · <span id="updAgo">actualizado ${fmt.hm(Date.now())}</span>`)}
      ${guest ? `<div class="banner">${icon("info")}<div>Estás viendo la <strong>vista pública</strong>: semáforo del río, mapa y transparencia.
        El personal de las dependencias entra con su cuenta desde <a href="login.html">Iniciar sesión</a>.</div></div>` : ""}
      ${demoBar()}
      <section class="kpis" id="kpis" aria-label="Indicadores principales">${kpisHtml()}</section>
      <div class="grid-2">
        <section class="card" aria-labelledby="mapTitle">
          <div class="card-head"><h2 id="mapTitle">Semáforo del río</h2><a class="btn btn-ghost" href="#/mapa">${icon("maximize-2")}Abrir mapa</a></div>
          <div class="legend"><span><i style="background:#15803D"></i>Bien</span><span><i style="background:#D97706"></i>Atención</span><span><i style="background:#DC2626"></i>Crítico</span>
            ${MOCK ? "" : `<span><i style="background:#64748B"></i>Sin datos recientes</span>`}
            <span><span class="node-pin ok" style="width:18px;height:18px;border-width:2px;font-size:0"></span>Nodo</span><span><span class="square-pin ok" style="width:16px;height:16px;border-width:2px"></span>Barrera</span></div>
          <div class="map" id="miniMap" role="region" aria-label="Mapa del río con el estado de cada tramo. La tabla Estado por tramo tiene la misma información."></div>
        </section>
        <section class="card" aria-labelledby="recentTitle">
          <div class="card-head"><h2 id="recentTitle">${canSeeCases() ? "Casos recientes" : "Avisos recientes"}</h2>${canSeeCases() ? `<a class="btn btn-ghost" href="#/casos">Ver todos</a>` : ""}</div>
          <div class="card-body" id="recent">${recentHtml()}</div>
        </section>
      </div>
      <section class="card" aria-labelledby="tramosTitle">
        <div class="card-head"><h2 id="tramosTitle">Estado por tramo</h2><span class="muted small">${MOCK ? "Valores del nodo al final de cada tramo" : "Última lectura descargada del nodo al final de cada tramo"}</span></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Tramo</th><th>Semáforo</th><th>pH</th><th>Cond. (µS/cm)</th><th>Turbidez (NTU)</th><th>Color 620 nm (m⁻¹)</th></tr></thead>
          <tbody id="tramoBody">${tramoRows()}</tbody></table></div>
      </section>`;
    const m = VA.map.create(document.getElementById("miniMap"), { tramoLabels: false, scroll: false });
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
        }
        refreshIcons();
      },
      destroy() { m.map.remove(); }
    };
  }

  // =========================================================
  // MAPA
  // =========================================================
  function mapa(main) {
    const layers = { tramos: true, nodos: true, barreras: true, reportes: true, calor: true };
    const chip = (k, label, ic) => `<button class="chip" type="button" data-layer="${k}" aria-pressed="${layers[k]}">${icon(ic)}${label}</button>`;
    main.innerHTML = `
      ${pageHead("Mapa de la cuenca", "Tramos, nodos, barreras, reportes de la app y mapa de calor de las zonas más afectadas")}
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
          <span><span class="report-pin"></span>Reporte ciudadano${canSeeCases() || role() === "tec" ? "" : " (ubicación aproximada)"}</span>
          <span>Mapa de calor: baja <span class="heat-scale" aria-hidden="true"></span> alta concentración de reportes y alertas</span>
        </div>
      </section>
      <details class="card"><summary class="card-body" style="cursor:pointer;font-weight:700">Lista de puntos del mapa (alternativa en texto)</summary>
        <div class="card-body table-wrap" id="pointList"></div></details>`;
    const m = VA.map.create(document.getElementById("bigMap"), { zoom: 11, reports: true, heat: true, tramoLabels: true });
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
    if (!c || c.public) { toast("warn", "Caso no disponible", `${id} no existe o pertenece a otra dependencia.`); return; }
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
        `<a class="btn btn-secondary" href="#/mapa">${icon("map")}Ver en el mapa</a>`)}
      ${demoBar()}
      <section class="node-cards" id="cards" aria-label="Nodos de la red">${S().nodes.map(card).join("")}</section>
      <section class="card" id="detail" aria-labelledby="detTitle"></section>`;
    function renderDetail() {
      if (chart) { chart.destroy(); chart = null; }
      document.getElementById("detail").innerHTML = detail();
      const canvas = document.getElementById("telChart");
      if (canvas) chart = VA.charts.telemetry(canvas, sel, key);
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
      destroy() { if (chart) chart.destroy(); }
    };
  }

  // =========================================================
  // REPORTES DE LA APP
  // =========================================================
  function reportes(main) {
    const f = { cat: "", estado: "" };
    const canEdit = C.reportEditors.includes(role());
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
          <td>Cerca de ${esc(placeName(r.lat, r.lng))}</td><td>${stateBadge(r.status)}</td><td>${fmt.ago(r.t)}</td>
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
              <span class="help" id="upHelp">Columnas: t, ph, cond, turb, color, temp, nivel (y opcionales bateria, muestra, hash). Máximo 5 MB.</span></div>
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
        form.reset();
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
    let sel = withData.some(t => t.id === "T3") ? "T3" : withData[0].id, chart = null;
    main.innerHTML = `
      ${pageHead("Predicción por tramo", "Cómo estará la calidad del agua los próximos 5 días si la tendencia sigue igual")}
      <section class="card">
        <div class="card-head"><h2 id="pTitle"></h2>
          <div class="chips" role="group" aria-label="Tramo">${withData.map(t => `<button class="chip" type="button" data-t="${t.id}" aria-pressed="${t.id === sel}">${t.id}</button>`).join("")}</div></div>
        <div class="card-body"><div class="banner" id="pSummary"></div></div>
        <div class="card-body"><div class="chart-box"><canvas id="fcChart" role="img" aria-label="Índice de calidad real y pronosticado"></canvas></div></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Día</th><th>Índice pronosticado</th><th>Rango 95%</th><th>Semáforo</th></tr></thead><tbody id="fcBody"></tbody></table></div>
        <div class="card-foot">Modelo de demostración: tendencia de los últimos 10 días con banda de confianza de 95% sobre un índice de ejemplo. En producción: Random Forest entrenado con datos de Conagua (RENAMECA), la red propia y el pronóstico de lluvia. El índice resume pH, conductividad, turbidez, color y oxígeno (0 = muy mala, 100 = buena).</div>
      </section>`;
    function render() {
      const t = S().tramos.find(x => x.id === sel), series = S().dailyIndex[sel], fc = E.forecast(series, 5);
      document.getElementById("pTitle").textContent = `${t.id} · ${t.name}`;
      const now = series[series.length - 1].v, end = fc.points[fc.points.length - 1];
      const sNow = E.indexStatus(now), sEnd = E.indexStatus(end.v);
      const firstChange = fc.points.find(p => E.indexStatus(p.v) !== sNow);
      const sumEl = document.getElementById("pSummary");
      sumEl.className = "banner" + (sEnd === "crit" ? " crit" : "");
      sumEl.innerHTML = `${icon(fc.slope < 0 ? "trending-down" : "trending-up")}<div><strong>Hoy: ${now} (${E.semLabel[sNow]}).</strong> ${
        firstChange ? `Si la tendencia sigue, pasa a <strong>${E.semLabel[E.indexStatus(firstChange.v)]}</strong> el ${fmt.day(firstChange.t)}.` : `Se mantiene en ${E.semLabel[sNow]} los próximos 5 días.`}
        ${sEnd === "crit" ? " La vida acuática de este tramo estaría en riesgo." : ""}</div>`;
      document.getElementById("fcBody").innerHTML = fc.points.map(p => `<tr><td>${fmt.day(p.t)}</td><td class="num">${p.v}</td><td class="num">${p.lo}–${p.hi}</td><td>${badge(E.indexStatus(p.v))}</td></tr>`).join("");
      if (chart) chart.destroy();
      chart = VA.charts.forecast(document.getElementById("fcChart"), series, fc);
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
        ${demoOn() ? kpi("Basura retirada", "trash-2", fmt.num(1420) + " kg", "Barreras y jornadas (cifra de ejemplo)") : ""}
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
    let list = [];
    main.innerHTML = `
      ${pageHead("Usuarios", "Cuentas del personal de cada dependencia y de la ciudadanía registrada en la app")}
      <section class="card" aria-labelledby="newTitle">
        <div class="card-head"><h2 id="newTitle">Nueva cuenta</h2></div>
        <form class="card-body form-grid cols" id="newForm" novalidate>
          <div class="field"><label for="nuNombre">Nombre</label><input id="nuNombre" type="text" required minlength="2" maxlength="80" autocomplete="off"></div>
          <div class="field"><label for="nuCuenta">Correo o teléfono</label><input id="nuCuenta" type="text" required maxlength="120" autocomplete="off" inputmode="email"></div>
          <div class="field"><label for="nuRol">Rol</label><select id="nuRol">${roleOptions("ambiental")}</select></div>
          ${passField("nuClave", "Contraseña temporal", { help: "Mínimo 8 caracteres. Pídele que la cambie al entrar." })}
          <p class="form-error" id="nuErr" role="alert" hidden></p>
          <div class="btn-row"><button class="btn btn-primary" type="submit">${icon("user-plus")}Crear cuenta</button></div>
        </form>
      </section>
      <section class="card" aria-labelledby="usTitle">
        <div class="card-head"><h2 id="usTitle">Cuentas</h2><span class="muted small" id="usCount"></span></div>
        <div class="card-body table-wrap"><table class="data"><thead><tr><th>Nombre</th><th>Cuenta</th><th>Rol</th><th>Estado</th><th>Último acceso</th><th><span class="sr-only">Acciones</span></th></tr></thead>
          <tbody id="usBody"><tr><td colspan="6" class="empty">Cargando…</td></tr></tbody></table></div>
      </section>`;
    wirePassToggles(main);
    const me = VA.session.user;
    function rows() {
      document.getElementById("usCount").textContent = `${list.filter(u => u.activo).length} activas de ${list.length}`;
      document.getElementById("usBody").innerHTML = list.map(u => `<tr>
        <td><strong>${esc(u.nombre)}</strong>${u.id === me.id ? ` <span class="badge info">Tú</span>` : ""}${u.demo ? ` <span class="badge neutral">Demo</span>` : ""}</td>
        <td>${esc(u.cuenta)}</td>
        <td><label class="sr-only" for="rol_${u.id}">Rol de ${esc(u.nombre)}</label><select id="rol_${u.id}" data-rol="${u.id}"${u.id === me.id ? " disabled" : ""}>${roleOptions(u.rol)}</select></td>
        <td>${u.activo ? badge("ok", "Activa") : badge("neutral", "Desactivada")}</td>
        <td>${u.ultimo_acceso ? fmt.date(u.ultimo_acceso) : `<span class="muted">Nunca</span>`}</td>
        <td><div class="btn-row nowrap">
          <button class="btn btn-ghost" type="button" data-pass="${u.id}">${icon("key-round")}Contraseña</button>
          ${u.id === me.id ? "" : `<button class="btn ${u.activo ? "btn-danger" : "btn-secondary"}" type="button" data-toggle="${u.id}">${icon(u.activo ? "user-x" : "user-check")}${u.activo ? "Desactivar" : "Reactivar"}</button>`}
        </div></td></tr>`).join("");
      main.querySelectorAll("[data-rol]").forEach(s => s.addEventListener("change", () => change(+s.dataset.rol, { rol: s.value }, "Rol actualizado")));
      main.querySelectorAll("[data-toggle]").forEach(b => b.addEventListener("click", () => { const u = list.find(x => x.id === +b.dataset.toggle); change(u.id, { activo: !u.activo }, u.activo ? "Cuenta desactivada" : "Cuenta reactivada"); }));
      main.querySelectorAll("[data-pass]").forEach(b => b.addEventListener("click", () => resetDialog(list.find(x => x.id === +b.dataset.pass))));
      refreshIcons();
    }
    async function load() {
      try { list = await VA.api.users.list(); if (document.getElementById("usBody")) rows(); }
      catch (err) { const b = document.getElementById("usBody"); if (b) b.innerHTML = `<tr><td colspan="6" class="empty">${esc(err.message)}</td></tr>`; }
    }
    async function change(id, data, okTitle) {
      try {
        const u = await VA.api.users.update(id, data);
        Object.assign(list.find(x => x.id === id), u);
        toast("ok", okTitle, `${u.nombre}: el cambio aplica de inmediato y cierra sus sesiones abiertas.`);
      } catch (err) { fail(err); }
      rows();
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
        try { await VA.api.users.update(u.id, { clave: val }); VA.ui.closeDrawer(); toast("ok", "Contraseña actualizada", `${u.nombre} debe entrar con la nueva contraseña.`); }
        catch (ex) { err.textContent = ex.message; err.hidden = false; }
      });
    }
    document.getElementById("newForm").addEventListener("submit", async e => {
      e.preventDefault();
      const err = document.getElementById("nuErr"), v = id => document.getElementById(id).value.trim();
      const data = { nombre: v("nuNombre"), cuenta: v("nuCuenta"), rol: v("nuRol"), clave: document.getElementById("nuClave").value };
      err.hidden = true;
      const bad = data.nombre.length < 2 ? ["nuNombre", "Escribe el nombre de la persona."] : !data.cuenta ? ["nuCuenta", "Escribe un correo o un teléfono de 10 dígitos."]
        : data.clave.length < 8 ? ["nuClave", "La contraseña debe tener al menos 8 caracteres."] : null;
      if (bad) { err.textContent = bad[1]; err.hidden = false; document.getElementById(bad[0]).focus(); return; }
      try {
        const u = await VA.api.users.create(data);
        e.target.reset();
        toast("ok", "Cuenta creada", `${u.nombre} ya puede entrar como ${C.roles[u.rol].label}.`);
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

  VA.views = { resumen, mapa, casos, nodos, reportes, recoleccion, prediccion, transparencia, usuarios, config, openCase, passwordDialog };
})();
