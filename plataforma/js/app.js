/* =========================================================
   Aplicación: sesión, rutas, menú por rol y avisos en vivo.

   Con servidor, el rol sale de la sesión y los casos los crea
   el análisis por lote del servidor. Sin servidor (demo de
   respaldo) el rol se elige con "Ver como" y los casos se
   crean aquí mismo: detecta → confirma → actúa.
   ========================================================= */
(function () {
  const C = VA.config, E = VA.engine, { esc, icon, fmt, toast, refreshIcons } = VA.ui;
  const S = () => VA.store;
  const MOCK = VA.api.USE_MOCK;

  // ---------- Estado global ----------
  VA.state = { role: "publico", perms: [], live: true, focus: null };
  VA.can = permiso => VA.state.perms.includes(permiso);
  let current = null, currentName = "";
  const lastAnom = {};                    // última anomalía por nodo (demo sin servidor)
  let caseSeq = 20, sampleSeq = 20;

  // Vistas que esta persona puede abrir: las públicas y las de sus permisos
  const navOf = () => C.navOrder.filter(k => (!C.nav[k].permiso || VA.can(C.nav[k].permiso))
    && (!C.nav[k].personal || C.roles[VA.state.role].staff) && (!MOCK || !C.serverOnly.includes(k)));

  // Rol y permisos de quien mira: con servidor salen de su sesión (y pueden cambiar si Administración
  // los ajusta); en la demo sin servidor, del selector "Ver como". Devuelve true si algo cambió.
  function applySession() {
    const before = VA.state.role + "|" + VA.state.perms.join(",");
    if (!MOCK) {
      const u = VA.session.user;
      VA.state.role = u && C.roles[u.rol] ? u.rol : "publico";
      VA.state.perms = u ? (u.permisos || []).slice() : [];
    } else {
      VA.state.perms = C.roles[VA.state.role].permisos.slice();
    }
    return before !== VA.state.role + "|" + VA.state.perms.join(",");
  }

  // ---------- Menú según los permisos ----------
  function renderNav() {
    const r = C.roles[VA.state.role];
    const pending = VA.can("casos") ? S().cases.filter(c => r.deps.includes(c.dep) && c.status === "Nuevo").length : 0;
    const permitidas = new Set(navOf());
    const item = k => {
      const n = C.nav[k];
      const b = k === "casos" && pending ? `<span class="nav-badge" aria-label="${pending} casos nuevos">${pending}</span>` : "";
      return `<li><a href="#/${k}" data-route="${k}">${icon(n.icon)}<span>${esc(n.label)}</span>${b}</a></li>`;
    };
    const grupos = C.navGroups.map(g => ({ label: g.label, items: g.items.filter(k => permitidas.has(k)) })).filter(g => g.items.length);
    // Quien no es personal de una dependencia llega a reportar: el acceso a la app ciudadana va primero
    const app = r.staff ? "" : `<li class="nav-cta"><a href="${C.appCiudadana}">${icon("smartphone")}<span>Reportar un problema</span></a></li>`;
    document.getElementById("nav").innerHTML = app + grupos.map((g, i) => `<li class="nav-group">
        <span class="nav-section" id="navg${i}">${esc(g.label)}</span>
        <ul aria-labelledby="navg${i}">${g.items.map(item).join("")}</ul></li>`).join("");
    markActive();
    refreshIcons();
  }
  function markActive() {
    document.querySelectorAll("#nav a").forEach(a => a.toggleAttribute("aria-current", a.dataset.route === currentName));
    document.querySelectorAll("#nav a[aria-current]").forEach(a => a.setAttribute("aria-current", "page"));
  }

  // ---------- Rutas (#/vista/parámetro) ----------
  function route() {
    const [, name = "resumen", param] = (location.hash || "#/resumen").split("/");
    const allowed = navOf();
    // Un enlace a una vista de gobierno sin sesión (por ejemplo desde una notificación) lleva al inicio de sesión
    if (!MOCK && !VA.session.user && C.nav[name] && !allowed.includes(name)) {
      location.href = "login.html?ir=" + encodeURIComponent(location.hash);
      return;
    }
    const view = allowed.includes(name) && VA.views[name] ? name : "resumen";
    if (view !== name) {
      // La dirección debe decir lo que se ve; si no, un enlace a una sección sin permiso se queda en la barra
      history.replaceState(null, "", "#/" + view);
      if (C.nav[name]) toast("warn", "Sin acceso a esa sección", `Tu cuenta no tiene permiso para «${C.nav[name].label}». Te mostramos el resumen.`);
    }
    // Mismo módulo de casos: solo abrir el detalle sin redibujar la lista
    if (view === "casos" && currentName === "casos" && param) { VA.views.openCase(param); return; }
    if (current && current.destroy) current.destroy();
    const main = document.getElementById("main");
    main.innerHTML = "";
    currentName = view;
    current = VA.views[view](main, param ? decodeURIComponent(param) : null) || {};
    document.getElementById("topbarTitle").textContent = C.nav[view].label;
    document.title = C.nav[view].label + " · Vigía Atoyac";
    markActive();
    refreshIcons();
    closeMenu();
    // Foco al contenido tras cambiar de vista, salvo que la vista haya abierto un panel (enlace directo a un caso)
    if (!document.querySelector(".drawer")) main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }

  // ---------- Recepción de avisos ----------
  function onMsg(msg) {
    if (msg.tipo === "sync") {                  // con servidor: los datos ya se recargaron
      (msg.avisos || []).slice(0, 3).forEach(a => toast(a.kind || "info", a.title, a.msg, a.kind === "crit" ? 9000 : 6500));
      const changed = applySession();
      if (changed) toast("info", "Tus permisos cambiaron", "Administración ajustó lo que puedes ver; el menú ya está actualizado.");
      if (changed || msg.origen === "ajustes" || msg.origen === "reinicio") { currentName = ""; renderNav(); route(); return; }
    }
    else if (msg.tipo === "lectura") handleReading(msg);
    else if (msg.tipo === "barrera") handleBarrier(msg);
    else if (msg.tipo === "reporte") handleReport(msg);
    emit(msg);
  }
  function emit(msg) {
    if (current && current.update) current.update(msg);
    if (msg.tipo !== "lectura" || msg.caseChanged) renderNav();
  }

  // =========================================================
  // Demo sin servidor: el navegador hace de nodo y de servidor
  // =========================================================
  function handleReading({ nodo, lectura }) {
    const hist = S().history[nodo];
    const anom = E.detectAnomalies(hist.concat([lectura]), lectura);
    lectura.anom = anom.map(a => a.param);
    hist.push(lectura);
    if (hist.length > 120) hist.shift();
    if (anom.length) onAnomaly(nodo, lectura, anom);
    // Nivel crítico en un nodo → riesgo de inundación
    if (E.paramStatus("nivel", lectura.nivel) === "crit") floodCase(S().nodes.find(n => n.id === nodo), lectura.nivel);
  }

  function handleBarrier({ barrera, fill, nivel }) {
    const b = S().barriers.find(x => x.id === barrera);
    b.fill = fill; b.nivel = nivel;
    if (fill >= 90 && !S().cases.some(c => c.barrier === b.id && c.type === "basura" && c.status !== "Cerrado")) {
      newCase({ type: "basura", priority: "Alta", barrier: b.id, lat: b.lat, lng: b.lng, estimate: "Barrera llena", confidence: 0.97,
        summary: `La barrera de ${b.name} llegó a ${fmt.num(fill)}% de llenado. Se envió la ruta a la cuadrilla.`, reports: [],
        timeline: [ev("Barrera " + b.id, `Llenado ${fmt.num(fill)}%`), ev("Sistema", "Caso asignado a Limpia municipal con ruta de recolección")] });
      toast("warn", "Barrera llena", `${b.name}: ${fmt.num(fill)}%. Caso enviado a Limpia municipal.`);
    }
    if (nivel >= b.nivelMax * 0.85) floodCase(b, nivel);
  }

  function handleReport({ reporte }) {
    S().reports.unshift(reporte);
    toast("info", "Nuevo reporte desde la app", `${reporte.cat} cerca de ${nearestName(reporte.lat, reporte.lng)}.`);
  }

  // Descarga: anomalía → localización → fusión → caso
  function onAnomaly(nodeId, r, anom) {
    const now = Date.now();
    lastAnom[nodeId] = now;
    const node = S().nodes.find(n => n.id === nodeId);
    const recentIds = new Set(Object.entries(lastAnom).filter(([id, t]) => id !== nodeId && now - t < 90000).map(([id]) => id));
    const open = S().cases.find(c => c.type === "descarga" && c.status !== "Cerrado" && now - c.t < 5 * 60000 && c.auto);
    if (open) {
      // Mismo evento: actualizar pico o confirmar aguas abajo
      Object.keys(open.peak).forEach(k => { open.peak[k] = k === "ph" ? (Math.abs(r[k] - 7) > Math.abs(open.peak[k] - 7) ? r[k] : open.peak[k]) : Math.max(open.peak[k], r[k]); });
      if (open.node !== nodeId && !open.confirmedAt?.includes(nodeId)) {
        open.confirmedAt = (open.confirmedAt || []).concat(nodeId);
        open.timeline.push(ev("Sistema", `La anomalía llegó aguas abajo a ${node.id} · ${node.name}`));
        emit({ tipo: "caso", caseChanged: true });
      }
      return;
    }
    const loc = E.localize(nodeId, recentIds);
    const kind = E.classifyDischarge(r, node.base);
    const t = loc.tramo && S().tramos.find(x => x.id === loc.tramo);
    const mid = t ? t.points[Math.floor(t.points.length / 2)] : [node.lat, node.lng];
    // Reportes cerca del tramo probable o del nodo que detectó (sin duplicar)
    const near = [...new Map([...E.fuseReports(mid[0], mid[1], S().reports, now), ...E.fuseReports(node.lat, node.lng, S().reports, now)].map(x => [x.id, x])).values()];
    const conf = E.confidence(anom, near);
    near.forEach(x => { if (x.status === "Recibido") x.status = "Validado"; });
    const sample = "M-" + String(++sampleSeq).padStart(4, "0");
    const params = anom.map(a => a.param === "ph" ? "pH" : C.params[a.param].label.toLowerCase()).join(", ");
    newCase({
      type: "descarga", priority: conf >= 0.75 || E.readingStatus(r) === "crit" ? "Alta" : "Media", node: nodeId, tramo: loc.tramo,
      lat: mid[0], lng: mid[1], estimate: kind.label, confidence: conf, sample, auto: true,
      summary: `Cambio brusco de ${params} en ${node.name}. ${loc.text}. ${kind.why}${near.length ? ` Coincide con ${near.length} reporte(s) ciudadano(s) cercano(s).` : ""}`,
      reports: near.map(x => x.id), peak: { color: r.color, cond: r.cond, ph: r.ph, turb: r.turb },
      timeline: [
        ev("Nodo " + nodeId, `Anomalía detectada (${params})`),
        ev("Nodo " + nodeId, `Carrusel tomó la muestra ${sample}`),
        ...(near.length ? [ev("Sistema", `Cruce con ${near.length} reporte(s) de la app: confianza ${fmt.pct(conf)}`)] : []),
        ev("Sistema", `Tramo probable: ${loc.text}. Caso asignado a Autoridad ambiental`)
      ]
    });
    toast("crit", "Posible descarga " + kind.label.toLowerCase(), `${loc.text}. Confianza ${fmt.pct(conf)}. Muestra ${sample} tomada.`, 9000);
  }

  function floodCase(place, nivel) {
    const now = Date.now();
    if (S().cases.some(c => c.type === "inundacion" && c.status !== "Cerrado" && now - c.t < 5 * 60000)) return;
    newCase({ type: "inundacion", priority: "Alta", barrier: place.id.startsWith("B") ? place.id : undefined, node: place.id.startsWith("N") ? place.id : undefined,
      lat: place.lat, lng: place.lng, estimate: "Nivel alto", confidence: 0.95,
      summary: `El nivel del agua llegó a ${fmt.num(nivel, 2)} m en ${place.name}. Se avisó a los vecinos suscritos en la app.`, reports: [],
      timeline: [ev(place.id, `Nivel ${fmt.num(nivel, 2)} m`), ev("Sistema", "Alerta temprana enviada a Protección Civil y a vecinos suscritos")] });
    toast("crit", "Riesgo de inundación", `${place.name}: nivel ${fmt.num(nivel, 2)} m. Alerta enviada.`, 9000);
  }

  function newCase(c) {
    const tipo = C.tiposCaso[c.type];
    const full = Object.assign({ id: "VA-2026-" + String(++caseSeq).padStart(4, "0"), dep: tipo.dep, status: "Nuevo", t: Date.now() }, c);
    S().cases.unshift(full);
    VA.api.saveCase(full);
    emit({ tipo: "caso", caseChanged: true });
    return full;
  }
  const ev = (who, what) => ({ t: Date.now(), who, what });
  function nearestName(lat, lng) {
    const pts = [...S().nodes, ...S().barriers];
    pts.sort((a, b) => E.km(lat, lng, a.lat, a.lng) - E.km(lat, lng, b.lat, b.lng));
    return pts[0].name;
  }

  // ---------- Acciones de demo (botones data-demo) ----------
  document.addEventListener("click", async e => {
    const b = e.target.closest("[data-demo]"); if (!b) return;
    const a = b.dataset.demo;
    if (MOCK) {
      if (a === "descarga") { VA.api.simulate.descarga("N3"); toast("info", "Simulación iniciada", "Entra una descarga textil antes de Xoxtla (N3)."); }
      if (a === "reporte") VA.api.simulate.reporte(onMsg);
      if (a === "barrera") { VA.api.simulate.barreraLlena("B1"); toast("info", "Simulación iniciada", "La barrera de Xaltonac se está llenando."); }
      if (a === "crecida") { VA.api.simulate.crecida(); toast("info", "Simulación iniciada", "Lluvia fuerte: sube el nivel en Puebla sur y en la barranca del Conde."); }
      return;
    }
    // Con servidor: se simula la visita de Protección Civil y el archivo pasa por el análisis real
    b.disabled = true;
    try {
      if (a === "reporte") await VA.api.demo.reporte();
      if (a === "descarga") { const r = await VA.api.demo.visita("N3", "descarga"); toast("info", "Visita simulada a N3", `${fmt.num(r.nuevas)} lecturas descargadas de la microSD; ${r.eventos} evento(s) encontrado(s).`); }
      if (a === "vecino") { const r = await VA.api.demo.visita("N2", "normal"); toast("info", "Visita simulada a N2", `${fmt.num(r.nuevas)} lecturas descargadas; sin anomalías aguas arriba.`); }
      if (a === "crecida") { const r = await VA.api.demo.visita("N5", "crecida"); toast("info", "Visita simulada a N5", `${fmt.num(r.nuevas)} lecturas descargadas; el nodo registró nivel crítico.`); }
      if (a === "barrera") await VA.api.demo.barrera("B1");
      if (a === "reiniciar") await VA.api.demo.reiniciar();
      // Con el WebSocket abierto, el servidor avisa a todos los paneles (este incluido); si está caído, se recarga aquí
      if (!VA.api.online()) { await VA.api.refresh(); onMsg({ tipo: "sync", caseChanged: true, origen: a === "reiniciar" ? "reinicio" : "demo", avisos: [] }); }
    } catch (err) { toast("warn", "No se pudo simular", err.message); }
    finally { b.disabled = false; }
  });

  // ---------- Barra superior: estado de conexión y cuenta ----------
  const liveBtn = document.getElementById("liveBtn"), liveText = document.getElementById("liveText");
  function setConnected(on) {
    liveBtn.classList.toggle("paused", !on);
    liveText.textContent = on ? "Conectado" : "Reconectando…";
    liveBtn.title = on ? "Conectado al servidor: los avisos llegan al momento" : "Sin conexión con el servidor; se reintenta solo";
  }
  if (MOCK) {
    liveBtn.addEventListener("click", () => {
      VA.state.live = !VA.state.live;
      VA.api.setPaused(!VA.state.live);
      liveBtn.classList.toggle("paused", !VA.state.live);
      liveBtn.setAttribute("aria-pressed", VA.state.live);
      liveText.textContent = VA.state.live ? "En vivo" : "Pausado";
    });
  } else {
    liveBtn.disabled = true; liveBtn.removeAttribute("aria-pressed");
    liveText.textContent = "Conectando…";
  }

  function renderUserArea() {
    const el = document.getElementById("userArea"), u = VA.session.user;
    if (MOCK) {
      // Demo sin servidor: no hay cuentas, el rol se elige aquí
      el.innerHTML = `<div class="role-picker"><label for="roleSelect">Ver como</label><select id="roleSelect">
        ${["publico", "ambiental", "limpia", "pc", "tec", "admin"].map(k => `<option value="${k}">${esc(C.roles[k].label)}${k === "publico" ? " (público)" : ""}</option>`).join("")}</select></div>`;
      const sel = document.getElementById("roleSelect");
      sel.value = VA.state.role;
      sel.addEventListener("change", () => {
        VA.state.role = sel.value;
        applySession();
        try { localStorage.setItem("va-role", sel.value); } catch (e) { /* sin almacenamiento */ }
        renderNav(); currentName = ""; route();
        toast("info", "Vista cambiada", "Ahora ves la plataforma como " + C.roles[VA.state.role].label + ".");
      });
      return;
    }
    if (!u) {
      // En pantallas angostas solo queda el icono: el nombre accesible va en aria-label
      el.innerHTML = `<a class="btn btn-secondary" href="${C.appCiudadana}" aria-label="Reportar un problema en la App Ciudadana" title="Reportar un problema">${icon("smartphone")}<span>Reportar</span></a>
        <a class="btn btn-primary" href="login.html" aria-label="Iniciar sesión" title="Iniciar sesión">${icon("log-in")}<span>Iniciar sesión</span></a>`;
      return;
    }
    el.innerHTML = `<div class="user-menu">
      <button class="user-btn" id="userBtn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="userPanel">
        <span class="user-avatar" aria-hidden="true">${icon("circle-user")}</span>
        <span class="user-text"><span class="user-name">${esc(u.nombre)}</span><span class="user-role">${esc(C.roles[u.rol].label)}</span></span>
        ${icon("chevron-down")}
      </button>
      <div class="user-panel" id="userPanel" hidden>
        <div class="user-panel-head"><strong>${esc(u.nombre)}</strong><span>${esc(u.cuenta)}</span></div>
        <button class="btn btn-ghost" type="button" id="pwdBtn">${icon("key-round")}Cambiar contraseña</button>
        <button class="btn btn-ghost" type="button" id="logoutBtn">${icon("log-out")}Cerrar sesión</button>
      </div></div>`;
    const btn = document.getElementById("userBtn"), panel = document.getElementById("userPanel");
    const toggle = open => { panel.hidden = !open; btn.setAttribute("aria-expanded", open); };
    btn.addEventListener("click", () => toggle(panel.hidden));
    document.addEventListener("click", e => { if (!e.target.closest(".user-menu")) toggle(false); });
    el.addEventListener("keydown", e => { if (e.key === "Escape" && !panel.hidden) { toggle(false); btn.focus(); } });
    document.getElementById("logoutBtn").addEventListener("click", () => VA.api.logout());
    document.getElementById("pwdBtn").addEventListener("click", () => { toggle(false); VA.views.passwordDialog(); });
  }

  const menuBtn = document.getElementById("menuBtn"), sidebar = document.getElementById("sidebar"), backdrop = document.getElementById("sidebarBackdrop");
  function closeMenu() { sidebar.classList.remove("open"); menuBtn.setAttribute("aria-expanded", "false"); backdrop.hidden = true; }
  menuBtn.addEventListener("click", () => {
    const open = !sidebar.classList.contains("open");
    sidebar.classList.toggle("open", open); menuBtn.setAttribute("aria-expanded", open); backdrop.hidden = !open;
    if (open) sidebar.querySelector("a").focus();
  });
  backdrop.addEventListener("click", closeMenu);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && sidebar.classList.contains("open")) { closeMenu(); menuBtn.focus(); } });
  document.addEventListener("click", e => { if (e.target.closest("[data-reload]")) location.reload(); });

  // ---------- Arranque ----------
  VA.app = { emit };
  VA.api.loadAll().then(() => {
    if (MOCK) {
      let saved = "admin";
      try { saved = localStorage.getItem("va-role") || "admin"; } catch (e) { /* almacenamiento no disponible */ }
      VA.state.role = C.roles[saved] ? saved : "admin";
    }
    applySession();
    document.getElementById("footMode").textContent = MOCK ? "Demo sin servidor · datos simulados" : VA.session.demo ? "Datos de demostración" : "";
    renderUserArea();
    renderNav();
    window.addEventListener("hashchange", route);
    route();
    VA.api.connect(onMsg, setConnected);
  }).catch(err => {
    document.getElementById("main").innerHTML = `<div class="banner crit">${icon("octagon-alert")}<div><strong>No se pudo cargar la información.</strong> ${esc(err.message)}
      <br><button class="btn btn-secondary" type="button" data-reload>Reintentar</button></div></div>`;
    refreshIcons();
  });
})();
