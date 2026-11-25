/* =========================================================
   Inicio de sesión. El servidor responde con una cookie HttpOnly:
   la contraseña y el token nunca se guardan en el navegador.

   Paso 1: cuenta y contraseña.
   Paso 2 (solo si Administración le dio una contraseña temporal):
   la persona crea la suya antes de ver cualquier dato.
   ========================================================= */
(function () {
  const $ = id => document.getElementById(id);
  const icons = () => { if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 2 } }); };
  const params = new URLSearchParams(location.search);
  // Tras entrar solo se vuelve a una vista de esta misma página (#/...), nunca a otra dirección
  const wanted = params.get("ir") || "";
  const dest = "./" + (/^#\/[\w\-/%.]*$/.test(wanted) ? wanted : "#/resumen");

  const form = $("loginForm"), errEl = $("loginErr"), btn = $("loginBtn"), notice = $("notice");
  let temporal = "";                       // la contraseña temporal recién escrita (solo en memoria, para el paso 2)

  function note(text) { notice.textContent = text; notice.hidden = false; }
  function fail(el, text) { el.textContent = text; el.hidden = false; }

  async function send(path, body) {
    let r;
    try { r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-VA": "1" }, body: JSON.stringify(body) }); }
    catch (e) { throw new Error("No hay conexión con el servidor. Revisa que esté encendido."); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* sin JSON */ }
    if (!r.ok) throw new Error(data && typeof data.detail === "string" ? data.detail : "No se pudo completar (" + r.status + ").");
    return data;
  }

  // Mostrar u ocultar cualquier contraseña de la página
  document.querySelectorAll("[data-show]").forEach(b => b.addEventListener("click", () => {
    const inp = $(b.dataset.show), show = inp.type === "password";
    inp.type = show ? "text" : "password";
    b.setAttribute("aria-pressed", show);
    b.setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
    b.innerHTML = `<i data-lucide="${show ? "eye-off" : "eye"}" aria-hidden="true"></i>`;
    icons();
  }));

  // ---------- Paso 1 ----------
  form.addEventListener("submit", async e => {
    e.preventDefault();
    errEl.hidden = true;
    const cuenta = $("cuenta").value.trim(), clave = $("clave").value;
    if (!cuenta) { fail(errEl, "Escribe tu correo o teléfono."); $("cuenta").focus(); return; }
    if (!clave) { fail(errEl, "Escribe tu contraseña."); $("clave").focus(); return; }
    btn.disabled = true;
    try {
      const r = await send("/api/auth/entrar", { cuenta, clave });
      if (r.usuario && r.usuario.cambiar_clave) { temporal = clave; showChange(r.usuario, false); return; }
      location.replace(dest);
    } catch (err) { fail(errEl, err.message); $("clave").select(); btn.disabled = false; }
  });

  // ---------- Paso 2: crear su propia contraseña ----------
  function showChange(user, askCurrent) {
    $("stepLogin").hidden = true;
    $("stepChange").hidden = false;
    $("changeUser").value = user.cuenta;                     // para que el gestor de contraseñas la guarde con su cuenta
    $("changeIntro").textContent = `Hola, ${user.nombre}. Entraste con una contraseña temporal que te dio Administración. Antes de continuar, crea una que solo tú conozcas.`;
    $("actualField").hidden = !askCurrent;
    $("clActual").required = askCurrent;
    $("changeTitle").focus();
    icons();
  }

  // Indicador sencillo de qué tan difícil de adivinar es la contraseña
  function strength(p) {
    if (!p) return [0, ""];
    let s = 0;
    if (p.length >= 8) s++;
    if (p.length >= 12) s++;
    if (/[a-zñ]/.test(p) && /[A-ZÑ]/.test(p)) s++;
    if (/\d/.test(p)) s++;
    if (/[^\wñÑ]/.test(p)) s++;
    if (p.length < 8) return [1, "Muy corta: usa al menos 8 caracteres."];
    return s <= 2 ? [2, "Aceptable. Más larga o con números y símbolos es más segura."] : s === 3 ? [3, "Buena."] : [4, "Muy buena."];
  }
  $("clNueva").addEventListener("input", () => {
    const [lvl, text] = strength($("clNueva").value);
    $("meterBar").style.width = (lvl * 25) + "%";
    $("meterBar").dataset.level = lvl;
    $("meterText").textContent = text;
  });

  $("changeForm").addEventListener("submit", async e => {
    e.preventDefault();
    const err = $("changeErr"), actual = $("actualField").hidden ? temporal : $("clActual").value;
    const nueva = $("clNueva").value, repite = $("clRepite").value;
    err.hidden = true;
    const msg = !actual ? "Escribe la contraseña temporal." : nueva.length < 8 ? "La contraseña nueva debe tener al menos 8 caracteres."
      : nueva === actual ? "La contraseña nueva debe ser distinta de la temporal." : nueva !== repite ? "Las dos contraseñas nuevas no coinciden." : "";
    if (msg) { fail(err, msg); return; }
    $("changeBtn").disabled = true;
    try {
      await send("/api/auth/clave", { actual, nueva });
      temporal = "";
      location.replace(dest);
    } catch (ex) { fail(err, ex.message); $("changeBtn").disabled = false; }
  });

  $("changeCancel").addEventListener("click", async () => {
    temporal = "";
    try { await send("/api/auth/salir", {}); } catch (e) { /* aunque falle, se regresa al paso 1 */ }
    location.replace("login.html");
  });

  // ---------- Arranque ----------
  icons();
  if (location.protocol === "file:") {
    note("Abriste el archivo con doble clic. Para iniciar sesión, enciende el servidor (iniciar.bat) y entra a http://localhost:8000. Sin servidor solo funciona la demo sin cuentas (index.html).");
    form.querySelectorAll("input, button").forEach(el => { el.disabled = true; });
    return;
  }
  if (params.has("expirada")) note("Tu sesión terminó o se cerró desde Administración. Vuelve a entrar para continuar.");
  fetch("/api/auth/yo", { credentials: "same-origin" }).then(r => r.json()).then(d => {
    if (!d.usuario) return;
    if (d.usuario.cambiar_clave) { showChange(d.usuario, true); return; }   // volvió a la página sin terminar el paso 2
    location.replace(dest);                                                 // ya hay sesión: directo a la plataforma
  }).catch(() => note("No hay conexión con el servidor. Revisa que esté encendido."));
  $("cuenta").focus();
})();
