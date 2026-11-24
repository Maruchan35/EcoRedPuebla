/* =========================================================
   Utilidades de interfaz: formato, íconos, insignias,
   avisos (toasts) y panel lateral accesible.
   ========================================================= */
(function () {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name, extra = "") => `<i data-lucide="${name}" aria-hidden="true" ${extra}></i>`;
  const refreshIcons = () => { if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 2 } }); };

  // ---------- Formato (es-MX) ----------
  const nf = {};
  const fmt = {
    num(v, dec = 0) {
      if (v == null || isNaN(v)) return "—";
      nf[dec] = nf[dec] || new Intl.NumberFormat("es-MX", { minimumFractionDigits: dec, maximumFractionDigits: dec });
      return nf[dec].format(v);
    },
    time: t => new Date(t).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    hm: t => new Date(t).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" }),
    date: t => new Date(t).toLocaleString("es-MX", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
    day: t => new Date(t).toLocaleDateString("es-MX", { day: "numeric", month: "short" }),
    ago(t) {
      const s = Math.round((Date.now() - t) / 1000);
      if (s < 60) return "hace " + Math.max(s, 1) + " s";
      const m = Math.round(s / 60); if (m < 60) return "hace " + m + " min";
      const h = Math.round(m / 60); if (h < 48) return "hace " + h + " h";
      return "hace " + Math.round(h / 24) + " días";
    },
    pct: v => Math.round(v * 100) + "%",
    param(key, v) { const p = VA.config.params[key]; return fmt.num(v, p.dec) + (p.unit ? " " + p.unit : ""); }
  };

  // ---------- Semáforo: siempre ícono + texto ----------
  function badge(status, text) {
    const E = VA.engine;
    return `<span class="badge ${status}">${icon(E.semIcon[status] || "circle")}${esc(text || E.semLabel[status])}</span>`;
  }
  const statusClass = { "Nuevo": "crit", "En atención": "warn", "Inspección programada": "info", "Cerrado": "ok",
    "Recibido": "neutral", "Validado": "info", "Atendido": "ok", "Descartado": "neutral" };
  const statusIcon = { "Nuevo": "circle-dot", "En atención": "loader", "Inspección programada": "calendar-check", "Cerrado": "circle-check",
    "Recibido": "inbox", "Validado": "badge-check", "Atendido": "circle-check", "Descartado": "circle-slash" };
  const stateBadge = s => `<span class="badge ${statusClass[s] || "neutral"}">${icon(statusIcon[s] || "circle")}${esc(s)}</span>`;
  const prioBadge = p => `<span class="badge ${p === "Alta" ? "crit" : p === "Media" ? "warn" : "neutral"}">${icon(p === "Alta" ? "chevrons-up" : "chevron-up")}${esc(p)}</span>`;

  // ---------- Avisos (toasts) en región aria-live ----------
  function toast(kind, title, msg, ms = 6500) {
    const root = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = "toast " + kind;
    const ic = { crit: "octagon-alert", warn: "triangle-alert", ok: "circle-check", info: "info" }[kind] || "info";
    el.innerHTML = `${icon(ic)}<div><div class="toast-title">${esc(title)}</div><div class="toast-msg">${esc(msg)}</div></div>`;
    root.appendChild(el);
    refreshIcons();
    setTimeout(() => el.remove(), ms);
  }

  // ---------- Panel lateral accesible (Esc, foco atrapado y regreso de foco) ----------
  let lastFocus = null, onCloseCb = null;
  function openDrawer(html, { label, onClose } = {}) {
    closeDrawer(true);
    lastFocus = document.activeElement; onCloseCb = onClose || null;
    const root = document.getElementById("drawerRoot");
    root.innerHTML = `<div class="drawer-backdrop" data-close></div>
      <section class="drawer" role="dialog" aria-modal="true" aria-label="${esc(label || "Detalle")}">${html}</section>`;
    refreshIcons();
    const dlg = root.querySelector(".drawer");
    const focusables = () => [...dlg.querySelectorAll("button, a[href], select, input, textarea, [tabindex]:not([tabindex='-1'])")].filter(e => !e.disabled);
    (focusables()[0] || dlg).focus();
    root.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => closeDrawer()));
    dlg.addEventListener("keydown", e => {
      if (e.key === "Escape") { e.preventDefault(); closeDrawer(); }
      if (e.key === "Tab") {
        const f = focusables(); if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    });
    return dlg;
  }
  function closeDrawer(silent) {
    const root = document.getElementById("drawerRoot");
    if (!root.innerHTML) return;
    root.innerHTML = "";
    if (!silent && onCloseCb) onCloseCb();
    if (!silent && lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }

  // Esc cierra el panel aunque el foco haya quedado fuera de él
  document.addEventListener("keydown", e => { if (e.key === "Escape" && document.querySelector(".drawer")) closeDrawer(); });

  VA.ui = { esc, icon, refreshIcons, fmt, badge, stateBadge, prioBadge, toast, openDrawer, closeDrawer };
})();
