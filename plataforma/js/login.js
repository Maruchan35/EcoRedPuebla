/* =========================================================
   Inicio de sesión. El servidor responde con una cookie HttpOnly:
   la contraseña y el token nunca se guardan en el navegador.
   ========================================================= */
(function () {
  const $ = id => document.getElementById(id);
  const icons = () => { if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 2 } }); };
  const params = new URLSearchParams(location.search);
  // Tras entrar solo se vuelve a una vista de esta misma página (#/...), nunca a otra dirección
  const wanted = params.get("ir") || "";
  const dest = "./" + (/^#\/[\w\-/%.]*$/.test(wanted) ? wanted : "#/resumen");
  const ROLE = { admin: ["shield-check", "Administración"], ambiental: ["droplets", "Autoridad ambiental"], limpia: ["truck", "Limpia municipal"],
    pc: ["siren", "Protección Civil"], tec: ["wrench", "Tecnológicos"], ciudadano: ["user", "Ciudadanía"] };

  const form = $("loginForm"), errEl = $("loginErr"), btn = $("loginBtn"), notice = $("notice");
  function note(text) { notice.textContent = text; notice.hidden = false; }
  function fail(text) { errEl.textContent = text; errEl.hidden = false; }

  async function post(path, body) {
    let r;
    try { r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-VA": "1" }, body: JSON.stringify(body) }); }
    catch (e) { throw new Error("No hay conexión con el servidor. Revisa que esté encendido."); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* sin JSON */ }
    if (!r.ok) throw new Error(data && typeof data.detail === "string" ? data.detail : "No se pudo iniciar sesión (" + r.status + ").");
    return data;
  }

  // Mostrar u ocultar la contraseña
  $("showPass").addEventListener("click", () => {
    const inp = $("clave"), show = inp.type === "password";
    inp.type = show ? "text" : "password";
    $("showPass").setAttribute("aria-pressed", show);
    $("showPass").setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
    $("showPass").innerHTML = `<i data-lucide="${show ? "eye-off" : "eye"}" aria-hidden="true"></i>`;
    icons();
  });

  form.addEventListener("submit", async e => {
    e.preventDefault();
    errEl.hidden = true;
    const cuenta = $("cuenta").value.trim(), clave = $("clave").value;
    if (!cuenta) { fail("Escribe tu correo o teléfono."); $("cuenta").focus(); return; }
    if (!clave) { fail("Escribe tu contraseña."); $("clave").focus(); return; }
    btn.disabled = true;
    try { await post("/api/auth/entrar", { cuenta, clave }); location.replace(dest); }
    catch (err) { fail(err.message); $("clave").select(); btn.disabled = false; }
  });

  function demoButtons(list) {
    const box = $("demoList");
    list.forEach(c => {
      const [ic, label] = ROLE[c.rol] || ["user", c.rol];
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn btn-secondary";
      const i = document.createElement("i"); i.setAttribute("data-lucide", ic); i.setAttribute("aria-hidden", "true");
      const s = document.createElement("span"); s.textContent = label;
      b.append(i, s);
      b.addEventListener("click", async () => {
        errEl.hidden = true; b.disabled = true;
        try { await post("/api/auth/demo", { cuenta: c.cuenta }); location.replace(dest); }
        catch (err) { fail(err.message); b.disabled = false; }
      });
      box.appendChild(b);
    });
    $("demoBox").hidden = false;
    icons();
  }

  icons();
  if (location.protocol === "file:") {
    note("Abriste el archivo con doble clic. Para iniciar sesión, enciende el servidor (iniciar.bat) y entra a http://localhost:8000. Sin servidor solo funciona la demo sin cuentas (index.html).");
    form.querySelectorAll("input, button").forEach(el => { el.disabled = true; });
    return;
  }
  if (params.has("expirada")) note("Tu sesión terminó. Vuelve a entrar para continuar.");
  fetch("/api/auth/yo", { credentials: "same-origin" }).then(r => r.json()).then(d => {
    if (d.usuario) { location.replace(dest); return; }           // ya hay sesión: directo a la plataforma
    if (d.cuentas_demo && d.cuentas_demo.length) demoButtons(d.cuentas_demo);
  }).catch(() => note("No hay conexión con el servidor. Revisa que esté encendido."));
  $("cuenta").focus();
})();
