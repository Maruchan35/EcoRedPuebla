/* =========================================================
   Capa de datos (API). Las vistas solo leen de VA.store y
   llaman a VA.api; aquí se decide de dónde salen los datos.

   - Con servidor (http://localhost:8000): sesión real, datos de la
     base, cambios guardados y avisos por WebSocket.
   - Sin servidor (doble clic en index.html, o ?demo en la URL):
     datos simulados en el navegador. Es el plan B de la presentación.

   Referencia de la API: /api/docs (con el servidor encendido).
   ========================================================= */
(function () {
  const USE_MOCK = location.protocol === "file:" || /[?&]demo(=|&|$)/.test(location.search);
  const C = VA.config;

  VA.store = { nodes: [], tramos: [], barriers: [], history: {}, reports: [], cases: [], dailyIndex: {}, categorias: [], basura: null, estaciones: [] };
  VA.session = { user: null, demo: USE_MOCK, mock: USE_MOCK };

  // ---------- HTTP ----------
  // La cabecera X-VA acompaña a la cookie de sesión: el servidor rechaza cambios que no la traigan.
  async function http(method, path, body) {
    const opt = { method, headers: { "X-VA": "1" }, credentials: "same-origin" };
    if (body instanceof FormData) opt.body = body;
    else if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    let r;
    try { r = await fetch(path, opt); }
    catch (e) { throw Object.assign(new Error("No hay conexión con el servidor."), { status: 0 }); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* respuesta sin JSON */ }
    if (r.status === 401 && VA.session.user) { sessionExpired(); }
    // Cuenta con contraseña temporal: el servidor no entrega nada hasta que la cambie
    if (r.status === 403 && r.headers.get("X-VA-Accion") === "cambiar-clave") {
      location.href = "login.html?cambiar=1&ir=" + encodeURIComponent(location.hash || "#/resumen");
    }
    if (!r.ok) {
      const msg = data && typeof data.detail === "string" ? data.detail : "El servidor respondió con un error (" + r.status + ").";
      throw Object.assign(new Error(msg), { status: r.status });
    }
    return data;
  }
  function sessionExpired() {
    VA.session.user = null;
    location.href = "login.html?expirada=1&ir=" + encodeURIComponent(location.hash || "#/resumen");
  }

  // Actualiza una lista sin cambiar los objetos que ya existen (el mapa y los paneles guardan referencias)
  function mergeById(target, incoming) {
    const old = new Map(target.map(o => [o.id, o]));
    target.length = 0;
    incoming.forEach(n => {
      const o = old.get(n.id);
      if (!o) { target.push(n); return; }
      Object.keys(o).forEach(k => { if (!(k in n)) delete o[k]; });
      target.push(Object.assign(o, n));
    });
  }
  function applyState(d) {
    const s = VA.store;
    ["nodes", "tramos", "barriers", "reports", "cases"].forEach(k => mergeById(s[k], d[k]));
    s.history = d.history; s.dailyIndex = d.dailyIndex; s.categorias = d.categorias;
    s.basura = d.basura || null; s.estaciones = d.estaciones || [];
    Object.entries(d.params || {}).forEach(([k, v]) => { if (C.params[k]) Object.assign(C.params[k], v); });
    if (d.staleDays) C.staleDays = d.staleDays;
    // La sesión se cerró del lado del servidor (cuenta desactivada, contraseña cambiada en otro equipo, expiró)
    if (VA.session.user && !d.usuario) { sessionExpired(); return; }
    VA.session.user = d.usuario; VA.session.demo = !!d.demo;
  }

  // ---------- Carga inicial y recarga ----------
  async function loadAll() {
    if (USE_MOCK) {
      const d = VA.data;
      Object.assign(VA.store, { nodes: d.nodes, tramos: d.tramos, barriers: d.barriers, history: d.history,
        reports: d.reports, cases: d.cases, dailyIndex: d.dailyIndex, categorias: d.categorias });
      return VA.store;
    }
    applyState(await http("GET", "/api/estado"));
    return VA.store;
  }
  const refresh = () => USE_MOCK ? Promise.resolve(VA.store) : loadAll();

  // ---------- Sesión ----------
  async function logout() {
    try { await http("POST", "/api/auth/salir", {}); } catch (e) { /* aunque falle, se sale de la vista */ }
    location.href = "./";
  }
  const changePassword = (actual, nueva) => http("POST", "/api/auth/clave", { actual, nueva });

  // ---------- Casos ----------
  // accion: atender | inspeccion | lab | cerrar. Devuelve cuántas personas reciben aviso en la app.
  async function caseAction(c, accion, lab) {
    const linked = c.reports.map(id => VA.store.reports.find(r => r.id === id)).filter(Boolean);
    if (!USE_MOCK) {
      const res = await http("PATCH", "/api/casos/" + encodeURIComponent(c.id), { accion, lab });
      const notified = res.notified || 0; delete res.notified;
      Object.assign(c, res);
      await refresh();
      return { notified };
    }
    const who = C.dependencias[c.dep].label, ev = what => c.timeline.push({ t: Date.now(), who, what });
    if (accion === "atender") { c.status = "En atención"; ev("Caso en atención"); }
    if (accion === "inspeccion") { c.status = "Inspección programada"; ev("Inspección programada"); }
    if (accion === "lab") { c.lab = lab; ev("Resultado de laboratorio capturado"); }
    if (accion === "cerrar") {
      c.status = "Cerrado"; c.closedAt = Date.now(); ev("Caso cerrado; se avisó a quienes reportaron");
      const br = c.barrier && VA.store.barriers.find(b => b.id === c.barrier);
      if (br && c.type === "basura") { br.fill = 5; br.lastEmptied = Date.now(); }
    }
    return { notified: linked.length };
  }
  // Solo la demo sin servidor crea casos en el navegador; con servidor los crea el análisis por lote
  async function saveCase(c) { return c; }

  // ---------- Reportes ----------
  async function reportStatus(r, estado) {
    if (USE_MOCK) { r.status = estado; return { notified: !r.anonymous }; }
    const res = await http("PATCH", "/api/reportes/" + encodeURIComponent(r.id), { estado });
    const notified = !!res.notified; delete res.notified;
    Object.assign(r, res);
    return { notified };
  }
  const photoUrl = r => "/api/reportes/" + encodeURIComponent(r.id) + "/foto";

  // ---------- Umbrales ----------
  async function saveThresholds(params) {
    const saved = USE_MOCK ? params : await http("PUT", "/api/ajustes/umbrales", { params });
    Object.entries(saved).forEach(([k, v]) => Object.assign(C.params[k], v));
  }

  // ---------- Usuarios y recolección (solo con servidor) ----------
  const users = {
    list: () => http("GET", "/api/usuarios"),
    catalog: () => http("GET", "/api/permisos"),
    accesses: () => http("GET", "/api/accesos?limite=60"),
    create: d => http("POST", "/api/usuarios", d),
    update: (id, d) => http("PATCH", "/api/usuarios/" + id, d)
  };
  // ---------- Series para gráficas y estación piloto (solo con servidor) ----------
  const series = (nodo, dias = 7, agrupar = "hora") => USE_MOCK ? Promise.resolve(null)
    : http("GET", `/api/series?nodo=${encodeURIComponent(nodo)}&dias=${dias}&agrupar=${agrupar}`);
  const estacion = (nodo = "N3", dias = 7) => USE_MOCK ? Promise.resolve(null)
    : http("GET", `/api/estacion?nodo=${encodeURIComponent(nodo)}&dias=${dias}`);

  const batches = {
    list: () => http("GET", "/api/lotes"),
    upload: form => http("POST", "/api/sincronizacion", form),
    sampleUrl: (nodo, evento) => `/api/sincronizacion/ejemplo?nodo=${encodeURIComponent(nodo)}&evento=${encodeURIComponent(evento)}&horas=8`
  };

  // ---------- Avisos en tiempo real ----------
  // onMsg recibe en la demo sin servidor: {tipo:"lectura"|"barrera"|"reporte", ...}
  //              con servidor: {tipo:"sync", origen, aviso?} cuando ya se recargaron los datos
  let timer = null, socket = null, paused = false, retry = null, poll = null, pending = null;
  const injections = {};     // eventos simulados activos por nodo/barrera
  let statusCb = () => {};

  function connect(onMsg, onStatus) {
    statusCb = onStatus || statusCb;
    if (!USE_MOCK) { openSocket(onMsg); return; }
    const { gauss } = VA.data;
    timer = setInterval(() => {
      if (paused) return;
      const t = Date.now();
      VA.store.nodes.forEach(n => {
        const b = n.base, inj = injections[n.id];
        let f = { ph: 0, cond: 1, turb: 1, color: 1, nivel: 0 };
        if (inj && inj.ticks > 0) {
          if (inj.delay > 0) { inj.delay--; }
          else { f = inj.f; inj.ticks--; }
        }
        onMsg({ tipo: "lectura", nodo: n.id, lectura: {
          t,
          ph: +(b.ph + f.ph + gauss() * 0.06).toFixed(2),
          cond: Math.round(b.cond * f.cond + gauss() * b.cond * 0.025),
          turb: Math.max(1, Math.round(b.turb * f.turb + gauss() * b.turb * 0.06)),
          color: +Math.max(0.2, b.color * f.color + gauss() * 0.12).toFixed(2),
          temp: +(b.temp + gauss() * 0.15).toFixed(1),
          nivel: +(b.nivel + f.nivel + gauss() * 0.02).toFixed(2)
        }});
      });
      VA.store.barriers.forEach(br => {
        const inj = injections[br.id];
        let fill = br.fill + (Math.random() < 0.15 ? 1 : 0);
        if (br._base == null) br._base = br.nivel;
        let nivel = Math.max(0.2, br.nivel + (br._base - br.nivel) * 0.2 + (Math.random() - 0.5) * 0.04);
        if (inj && inj.ticks > 0) { inj.ticks--; fill = Math.max(fill, inj.fill || 0); nivel = Math.max(nivel, inj.nivel || 0); }
        onMsg({ tipo: "barrera", barrera: br.id, fill: Math.min(100, fill), nivel: +nivel.toFixed(2) });
      });
    }, C.telemetryIntervalMs);
  }

  function openSocket(onMsg) {
    // Varios avisos seguidos (un lote crea varios casos) se juntan en una sola recarga
    const sync = msg => {
      pending = pending || { tipo: "sync", caseChanged: true, avisos: [] };
      if (msg && msg.aviso) pending.avisos.push(msg.aviso);
      if (msg && msg.tipo) pending.origen = msg.tipo;
      clearTimeout(sync.t);
      sync.t = setTimeout(async () => {
        const out = pending; pending = null;
        try { await refresh(); } catch (e) { return; }
        onMsg(out);
      }, 250);
    };
    try { socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/eventos"); }
    catch (e) { socket = null; }
    if (socket) {
      socket.onopen = () => { statusCb(true); clearInterval(poll); poll = null; };
      socket.onmessage = e => { try { sync(JSON.parse(e.data)); } catch (err) { /* mensaje ilegible */ } };
      socket.onclose = () => {
        statusCb(false);
        clearTimeout(retry); retry = setTimeout(() => openSocket(onMsg), 4000);
        // Mientras no haya WebSocket, se pregunta cada 20 s para no quedarse con datos viejos
        if (!poll) poll = setInterval(() => sync(null), 20000);
      };
    }
  }

  function setPaused(p) { paused = p; }
  const online = () => !!socket && socket.readyState === 1;

  // ---------- Simulaciones para la demo ----------
  const simulate = {
    // Descarga textil que entra antes de nodeId y baja hacia el siguiente nodo
    descarga(nodeId) {
      const i = VA.store.nodes.findIndex(n => n.id === nodeId);
      const strong = { ph: 1.9, cond: 2.7, turb: 1.6, color: 3.2, nivel: 0 };
      const weak = { ph: 1.0, cond: 1.9, turb: 1.3, color: 2.2, nivel: 0 };
      injections[nodeId] = { ticks: 10, delay: 0, f: strong };
      const next = VA.store.nodes[i + 1];
      if (next) injections[next.id] = { ticks: 8, delay: 3, f: weak };
    },
    barreraLlena(barrierId) { injections[barrierId] = { ticks: 6, fill: 94 }; },
    crecida() {
      injections["B3"] = { ticks: 8, nivel: 2.1, fill: 0 };
      const n5 = VA.store.nodes.find(n => n.id === "N5");
      injections["N5"] = { ticks: 8, delay: 0, f: { ph: 0, cond: 0.9, turb: 2.4, color: 1, nivel: 1.7 } };
      return n5;
    },
    // Un reporte que llega desde la app móvil
    reporte(onMsg) {
      // En la orilla del tramo que llega a Xoxtla (N3), a unos 800 m del puente
      const pts = (VA.store.tramos.find(t => t.to === "N3") || VA.store.tramos[0]).points, p = pts[Math.floor(pts.length * 0.8)];
      const r = { id: "R-" + (1300 + Math.floor(Math.random() * 600)), cat: "Agua de color",
        ai: { label: "Agua de color", conf: 0.93 }, lat: p[0], lng: p[1], t: Date.now(),
        status: "Recibido", anonymous: false, voice: false, text: "Foto desde la app: agua azul en la orilla del río." };
      onMsg({ tipo: "reporte", reporte: r });
    }
  };
  // Con servidor: la simulación pasa por el mismo camino que los datos reales (archivo → análisis → casos)
  const demo = {
    reporte: () => http("POST", "/api/demo/reporte", {}),
    visita: (nodo, evento) => http("POST", "/api/demo/visita", { nodo, evento }),
    barrera: barrera => http("POST", "/api/demo/barrera", { barrera }),
    reiniciar: () => http("POST", "/api/demo/reiniciar", {})
  };

  VA.api = { USE_MOCK, http, loadAll, refresh, logout, changePassword, caseAction, saveCase, reportStatus, photoUrl,
    saveThresholds, users, batches, series, estacion, connect, setPaused, online, simulate, demo };
})();
