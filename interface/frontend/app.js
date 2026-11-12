/**
 * SIMBA · Web de monitorización con roles.
 * Panel de estado (sin IA), histórico, gestión de usuarios y asistente opcional en panel lateral.
 * Todo el contenido que llega del servidor se pinta con textContent (sin innerHTML con datos).
 */

const API = "/api";
const ROLE_LEVEL = { consulta: 0, dba: 1, administrador: 2 };
const ROLE_LABEL = { consulta: "Consulta", dba: "DBA", administrador: "Administrador" };
const SEV = {
    OK: { label: "Correcto", cls: "ok", order: 0 },
    INFO: { label: "Informativo", cls: "info", order: 1 },
    WARNING: { label: "A revisar", cls: "warn", order: 2 },
    CRITICAL: { label: "Prioritario", cls: "crit", order: 3 },
};
// Iconos del sprite SVG de index.html (#i-…)
const AREA_ICON = {
    CPU: "cpu", Bloqueos: "lock", Conexiones: "plug", Espacio: "disk", Sesiones: "sesiones",
    Errores: "alert", Esperas: "hourglass", "Operaciones largas": "gauge",
};
const AWR_MAX_MB = 20;

const state = {
    user: null,
    check: null,
    chatSessionId: sessionStorage.getItem("chatSessionId"),
    chat: JSON.parse(sessionStorage.getItem("chatHistory") || "[]"),
    busy: false,
};

// ========== Utilidades ==========
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
        if (c == null || c === false) continue;
        node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
}

function icon(name, cls = "ico") {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", cls);
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(NS, "use");
    use.setAttribute("href", `#i-${name}`);
    svg.append(use);
    return svg;
}

function can(role) {
    return state.user && ROLE_LEVEL[state.user.role] >= ROLE_LEVEL[role];
}

function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "medium" });
}

function ago(iso) {
    const mins = Math.floor((Date.now() - new Date(iso)) / 60000);
    if (isNaN(mins)) return "";
    if (mins < 1) return "hace menos de un minuto";
    if (mins < 60) return `hace ${mins} min`;
    const h = Math.floor(mins / 60);
    return h < 48 ? `hace ${h} h` : `hace ${Math.floor(h / 24)} días`;
}

function toast(message, kind = "ok") {
    const t = el("div", { class: `toast toast-${kind}`, text: message });
    $("toasts").append(t);
    setTimeout(() => t.remove(), 4000);
}

// Diálogo propio en lugar de prompt()/confirm(): enmascara contraseñas y respeta el tema.
// fields: [{ name, label, type, minlength }] -> resuelve con { name: valor } o null si se cancela.
function uiDialog({ title, message = "", fields = [], ok = "Aceptar", danger = false }) {
    const dlg = $("ui-dialog"), form = $("ui-dialog-form");
    $("ui-dialog-title").textContent = title;
    $("ui-dialog-msg").textContent = message;
    $("ui-dialog-msg").hidden = !message;
    $("ui-dialog-error").textContent = "";
    $("ui-dialog-ok").textContent = ok;
    dlg.classList.toggle("danger", danger);
    const inputs = fields.map((f) => el("input", {
        name: f.name, type: f.type || "text", required: true, minlength: f.minlength,
        autocomplete: f.type === "password" ? "new-password" : "off",
    }));
    $("ui-dialog-fields").replaceChildren(...fields.map((f, i) => el("label", {}, f.label, inputs[i])));
    return new Promise((resolve) => {
        const onClose = () => {
            form.removeEventListener("submit", onSubmit);
            resolve(dlg.returnValue === "ok" ? Object.fromEntries(inputs.map((i) => [i.name, i.value])) : null);
        };
        const onSubmit = (e) => {
            if (e.submitter?.value !== "ok") return;
            const bad = inputs.find((i) => !i.checkValidity());
            if (bad) { e.preventDefault(); $("ui-dialog-error").textContent = bad.validationMessage; bad.focus(); }
        };
        form.addEventListener("submit", onSubmit);
        dlg.addEventListener("close", onClose, { once: true });
        dlg.returnValue = "";
        dlg.showModal();
        (inputs[0] || $("ui-dialog-ok")).focus();
    });
}
const confirmDialog = (title, message, ok = "Eliminar") => uiDialog({ title, message, ok, danger: true }).then(Boolean);

function sevPill(sev) {
    const s = SEV[sev] || SEV.INFO;
    return el("span", { class: `sev-pill sev-${s.cls}`, text: s.label });
}

async function api(path, { method = "GET", body, headers = {}, raw = false } = {}) {
    const opts = { method, headers: { ...headers }, credentials: "same-origin" };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(API + path, opts);
    if (res.status === 401 && path !== "/auth/login") {
        showLogin();
        throw new Error("Sesión caducada");
    }
    if (raw) return res;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || `Error ${res.status}`);
    return data;
}

// ========== Arranque y sesión ==========
document.addEventListener("DOMContentLoaded", async () => {
    initTheme();
    bindEvents();
    try {
        state.user = await api("/auth/me");
        showApp();
    } catch {
        showLogin();
    }
});

function showLogin() {
    state.user = null;
    $("app-view").hidden = true;
    $("login-view").hidden = false;
    $("login-password").value = "";
    $("login-username").focus();
}

async function login(e) {
    e.preventDefault();
    $("login-error").textContent = "";
    try {
        state.user = await api("/auth/login", {
            method: "POST",
            body: { username: $("login-username").value.trim(), password: $("login-password").value },
        });
        showApp();
    } catch (err) {
        $("login-error").textContent = err.message;
    }
}

async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    sessionStorage.removeItem("chatHistory");
    sessionStorage.removeItem("chatSessionId");
    state.chat = [];
    state.chatSessionId = null;
    $("messages").replaceChildren();
    closeAssistant();
    showLogin();
}

function showApp() {
    $("login-view").hidden = true;
    $("app-view").hidden = false;
    $("user-name").textContent = state.user.username;
    $("user-avatar").textContent = (state.user.username || "?").charAt(0);
    $("user-role").textContent = ROLE_LABEL[state.user.role] || state.user.role;
    $("user-role").className = `role-badge role-${state.user.role}`;
    document.querySelectorAll("[data-min-role]").forEach((n) => {
        n.hidden = !can(n.dataset.minRole);
    });
    renderChat();
    switchView("estado");
    loadHealth(false);
    pollConnection();
}

// ========== Actualización en vivo ==========
// Un único temporizador de 5 s ejecuta las tareas vencidas. Se pausa con la pestaña oculta,
// reintenta con backoff si falla y la revisión de salud usa la caché del servidor (sin force).
const LIVE = {
    conn: { every: 15000, run: () => refreshConnection(), views: null },
    health: { every: 60000, run: () => loadHealth(false, true), views: ["estado", "sesiones"] },
    notifs: { every: 30000, run: () => loadNotifications(), views: null },
    queries: { every: 300000, run: () => loadQueries(true), views: ["queries"] },
};
const live = { timer: null, view: "estado", last: {}, fails: {}, busy: {}, connOk: null, updatedAt: null };

function pollConnection() {
    clearInterval(live.timer);
    live.last = { health: Date.now(), queries: Date.now() }; live.fails = {};
    liveTick();
    live.timer = setInterval(liveTick, 5000);
}

async function liveTick() {
    if (!state.user || document.hidden) return;
    const now = Date.now();
    for (const [name, t] of Object.entries(LIVE)) {
        if (live.busy[name] || (t.views && !t.views.includes(live.view))) continue;
        const wait = t.every * Math.min(2 ** (live.fails[name] || 0), 4);
        if (now - (live.last[name] || 0) < wait) continue;
        live.busy[name] = true;
        live.last[name] = now;
        try {
            await t.run();
            live.fails[name] = 0;
        } catch {
            live.fails[name] = (live.fails[name] || 0) + 1;
        } finally {
            live.busy[name] = false;
        }
    }
    renderLiveStamp();
}

// ---- Campana: avisos sobre las SQL en las que participa el usuario ----
const NOTIF_TEXT = {
    comentario: (n) => `${n.by} comentó: ${n.text}`,
    estado: (n) => `${n.by} ${n.text}`,
    prioridad: (n) => `${n.by} ${n.text}`,
    persona: (n) => `${n.by} ${n.text}`,
};
const notif = { items: [], unread: 0 };

async function loadNotifications() {
    const data = await api("/notifications");
    const grew = data.unread > notif.unread;
    notif.items = data.items;
    notif.unread = data.unread;
    renderBell();
    if (grew && !$("bell-panel").hidden) await markNotificationsRead();
}

function renderBell() {
    const badge = $("bell-badge");
    badge.hidden = !notif.unread;
    badge.textContent = notif.unread > 99 ? "99+" : String(notif.unread);
    $("bell-btn").title = notif.unread ? `${notif.unread} aviso(s) sin leer` : "Avisos sobre tus SQL";
    const panel = $("bell-panel");
    if (panel.hidden) return;
    panel.replaceChildren(
        el("div", { class: "bell-head" }, el("strong", { text: "Avisos" }),
            el("small", { class: "muted", text: "SQL donde eres responsable, comentaste o te mencionan (@usuario)" })),
        notif.items.length ? el("ul", { class: "bell-list" }, notif.items.map((n) =>
            el("li", { class: n.unread ? "unread" : "", tabindex: 0, role: "button",
                onclick: () => openNotification(n), onkeydown: (e) => { if (e.key === "Enter") openNotification(n); } },
                el("span", { class: "mono", text: n.sql_id }),
                el("span", { class: "bell-msg", text: (NOTIF_TEXT[n.kind] || NOTIF_TEXT.comentario)(n) }),
                el("small", { class: "muted", text: ago(n.at) }))))
            : el("p", { class: "muted bell-empty", text: "No tienes avisos." }));
}

async function markNotificationsRead() {
    if (!notif.unread) return;
    notif.items.forEach((n) => { n.unread = false; });
    notif.unread = 0;
    await api("/notifications/read", { method: "POST" }).catch(() => {});
    renderBell();
}

function toggleBell(open) {
    const panel = $("bell-panel");
    panel.hidden = !open;
    $("bell-btn").setAttribute("aria-expanded", String(open));
    if (!open) return;
    renderBell();
    setTimeout(() => { if (!panel.hidden) markNotificationsRead(); }, 1500);
}

async function openNotification(n) {
    toggleBell(false);
    switchView("queries");
    if (!queriesData) await loadQueries();
    const card = mergedBoard().find((c) => c.sql_id === n.sql_id);
    if (card) openSqlDetail(card);
    else toast(`${n.sql_id} ya no aparece en el tablero`, "error");
}

function resetLive(name) { live.last[name] = Date.now(); live.fails[name] = 0; }

async function refreshConnection() {
    try {
        const h = await api("/health");
        const ok = h.db_connected && h.llm_ready;
        $("conn-dot").className = `dot ${ok ? "dot-ok" : h.db_connected ? "dot-warn" : "dot-crit"}`;
        live.connText = ok ? "BD y asistente conectados"
            : h.db_connected ? "BD conectada · asistente no disponible" : "BD no conectada";
        live.updatedAt = Date.now();
        renderLiveStamp();
    } catch (err) {
        $("conn-dot").className = "dot dot-crit";
        live.connText = "Servidor no disponible · reintentando";
        renderLiveStamp();
        throw err;
    }
}

function renderLiveStamp() {
    if (!live.connText) return;
    const t = live.updatedAt ? new Date(live.updatedAt).toLocaleTimeString("es-ES") : "—";
    $("conn-text").textContent = `${live.connText} · en vivo ${t}`;
}

document.addEventListener("click", (e) => {
    if (!$("bell-panel").hidden && !e.target.closest(".bell-wrap")) toggleBell(false);
});
$("bell-btn").addEventListener("click", () => toggleBell($("bell-panel").hidden));

document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.user) { live.last = {}; liveTick(); }
});

// ========== Navegación ==========
function switchView(view) {
    live.view = view;
    document.querySelectorAll(".tab").forEach((t) => {
        t.classList.toggle("active", t.dataset.view === view);
        if (t.dataset.view === view) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
    });
    document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== `view-${view}`; });
    if (view === "sesiones") { SessionsDash.update(state.check); if (!state.check) loadHealth(false, true); }
    if (view === "historico") loadHistory();
    if (view === "queries") loadQueries();
    if (view === "usuarios") loadUsers();
    if (typeof AwrView !== "undefined") { if (view === "awr") AwrView.open(); else AwrView.close(); }
}

// ========== Estado ==========
async function loadHealth(force, silent = false) {
    const buttons = [$("refresh-btn"), $("force-btn")];
    if (!silent) {
        buttons.forEach((b) => { b.disabled = true; });
        $("overall-title").textContent = force ? "Ejecutando revisión en Oracle…" : "Cargando revisión…";
        resetLive("health");
    }
    live.busy.health = true;
    try {
        const check = await api(`/health-check${force ? "?force=true" : ""}`, { method: "POST" });
        const unchanged = silent && state.check && state.check.id === check.id && state.check.created_at === check.created_at;
        state.check = check;
        if (!unchanged) renderHealth();
        else $("overall-meta").textContent = $("overall-meta").textContent.replace(/\(hace [^)]*\)/, `(${ago(check.created_at)})`);
        SessionsDash.update(check);
        if (force) toast("Revisión nueva completada");
    } catch (err) {
        if (silent) throw err;
        $("overall-title").textContent = "No se pudo obtener la revisión";
        $("overall-meta").textContent = err.message;
    } finally {
        live.busy.health = false;
        if (!silent) buttons.forEach((b) => { b.disabled = false; });
    }
}

function groupByArea(findings) {
    const areas = new Map();
    for (const f of findings) {
        if (!areas.has(f.area)) areas.set(f.area, []);
        areas.get(f.area).push(f);
    }
    return [...areas.entries()]
        .map(([area, items]) => ({
            area,
            items: items.sort((a, b) => SEV[b.severity].order - SEV[a.severity].order),
            severity: items.reduce((m, f) => (SEV[f.severity].order > SEV[m].order ? f.severity : m), "OK"),
        }))
        .sort((a, b) => SEV[b.severity].order - SEV[a.severity].order || a.area.localeCompare(b.area));
}

const ui = { okOpen: false };
const AREA_LINKS = {
    Bloqueos: [{ label: "Ver sesiones", view: "sesiones" }],
    Sesiones: [{ label: "Ver sesiones", view: "sesiones" }, { label: "Listado completo →", href: "/inactivas", role: "dba" }],
    Esperas: [{ label: "Ver queries", view: "queries" }],
    "Operaciones largas": [{ label: "Ver queries", view: "queries" }],
    Errores: [{ label: "Ver histórico", view: "historico" }],
    Espacio: [{ label: "Ver histórico", view: "historico" }],
};

function renderHealth() {
    const c = state.check;
    EstadoPlus.add(c);
    if (!state.histSeeded) {
        state.histSeeded = true;
        EstadoPlus.seed().then((ok) => { if (ok && state.check === c) renderHealth(); });
    }
    if (!state.estadoEntered) {
        state.estadoEntered = true;
        const v = $("view-estado");
        v.classList.add("enter");
        setTimeout(() => v.classList.remove("enter"), 1200);
    }
    const openAreas = new Set([...document.querySelectorAll("#view-estado details.row[open]")].map((d) => d.dataset.area));
    const areas = groupByArea(c.findings || []);
    const toReview = areas.filter((a) => SEV[a.severity].order >= 2).length;

    $("overall-pill").replaceWith(Object.assign(sevPill(c.overall), { id: "overall-pill" }));
    $("overall-title").textContent = toReview === 0
        ? "Sin puntos a revisar en las comprobaciones realizadas"
        : `${toReview} ${toReview === 1 ? "área a revisar" : "áreas a revisar"}`;
    $("overall-meta").textContent =
        `Datos de ${fmtDate(c.created_at)} (${ago(c.created_at)}) · ` +
        (c.from_cache ? "revisión reutilizada (caché)" : "revisión recién ejecutada");
    $("hero-timeline").replaceChildren(...[EstadoPlus.timeline()].filter(Boolean));

    const heroCls = SEV[c.overall]?.cls || "ok";
    const ringCounts = { OK: 0, INFO: 0, WARNING: 0, CRITICAL: 0 };
    areas.forEach((a) => { ringCounts[a.severity] += 1; });
    $("hero-ring").replaceChildren(...(areas.length ? [EstadoPlus.ring(ringCounts, areas.length)] : []));
    $("status-hero").className = `status-hero hero-${heroCls}`;
    $("hero-icon").replaceChildren(icon({ ok: "check", info: "info", warn: "alert", crit: "octagon" }[heroCls]));

    const counts = { OK: 0, INFO: 0, WARNING: 0, CRITICAL: 0 };
    areas.forEach((a) => { counts[a.severity] += 1; });
    const filter = EstadoPlus.getFilter();
    const TILE_ICON = { CRITICAL: "octagon", WARNING: "alert", INFO: "info", OK: "check" };
    $("counters").replaceChildren(
        ...["CRITICAL", "WARNING", "INFO", "OK"].map((s) =>
            el("button", {
                type: "button",
                class: `counter tile-${SEV[s].cls}${counts[s] ? "" : " tile-zero"}${filter === SEV[s].cls ? " tile-active" : ""}`,
                title: filter === SEV[s].cls ? "Quitar filtro" : `Mostrar solo: ${SEV[s].label}`,
                "aria-pressed": filter === SEV[s].cls ? "true" : "false",
                onclick: () => { EstadoPlus.setFilter(SEV[s].cls); renderHealth(); },
            },
                el("span", { class: "tile-ico" }, icon(TILE_ICON[s])),
                el("div", {}, el("strong", { text: counts[s] }), el("span", { text: SEV[s].label }))))
    );

    const visible = (a) => !filter || SEV[a.severity].cls === filter;
    const attention = areas.filter((a) => SEV[a.severity].order >= 1 && visible(a));
    const fine = areas.filter((a) => SEV[a.severity].order < 1 && visible(a));
    const note = $("filter-note");
    note.hidden = !filter;
    if (filter) {
        note.replaceChildren(`Mostrando solo «${EstadoPlus.LABEL[filter]}» · `,
            el("button", { class: "btn-link-inline", type: "button", text: "ver todo",
                onclick: () => { EstadoPlus.setFilter(filter); renderHealth(); } }));
    }
    const okOpen = ui.okOpen || filter === "ok";
    $("attn-title").hidden = !attention.length;
    $("ok-title").hidden = !fine.length;
    $("ok-title").replaceChildren(el("span", { class: "chev", text: okOpen ? "▾" : "▸" }), "Todo en orden", el("span", { class: "count-badge", text: fine.length }));
    $("attn-title").replaceChildren("Requiere atención", el("span", { class: "count-badge", text: attention.length }));
    $("ok-title").setAttribute("aria-expanded", String(okOpen));
    $("ok-cards").hidden = !okOpen || !fine.length;
    $("area-cards").replaceChildren(...attention.map(renderAreaCard));
    $("ok-cards").replaceChildren(...fine.map(renderAreaCard));
    document.querySelectorAll("#view-estado details.row").forEach((d) => { if (openAreas.has(d.dataset.area)) d.open = true; });

    const detail = $("detail-panel");
    detail.dataset.loadedFor = "";
    if (detail.open) loadDetail();
}

function renderCpuNodes(rows) {
    const R = 34, C = 2 * Math.PI * R;
    return el("div", { class: "gauges" }, rows.map((r) => {
        const v = Math.min(100, Math.max(0, Number(r.pct) || 0));
        const cls = v >= 85 ? "crit" : v >= 60 ? "warn" : "ok";
        const ns = "http://www.w3.org/2000/svg";
        const mk = (tag, attrs) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, val]) => n.setAttribute(k, val)); return n; };
        const svg = mk("svg", { viewBox: "0 0 80 80", class: "gauge-svg" });
        svg.append(
            mk("circle", { cx: 40, cy: 40, r: R, class: "gauge-bg" }),
            mk("circle", { cx: 40, cy: 40, r: R, class: `gauge-fg g-${cls}`, "stroke-dasharray": `${(C * v / 100).toFixed(1)} ${C.toFixed(1)}`, transform: "rotate(-90 40 40)" }));
        return el("div", { class: `gauge${r.nodo === "Media" ? " gauge-avg" : ""}` },
            el("div", { class: "gauge-wrap" }, svg, el("strong", { class: "gauge-val", text: `${v.toFixed(0)}%` })),
            el("span", { class: "gauge-label", text: r.nodo }));
    }));
}

function renderAreaCard({ area, items, severity }) {
    const relevant = items.filter((f) => f.severity !== "OK");
    const shown = relevant.length ? relevant : items;
    const cls = SEV[severity].cls;
    const extra = shown.length > 1 ? ` (+${shown.length - 1})` : "";

    const body = el("div", { class: "row-body" },
        shown.map((f) => el("div", { class: "row-finding" },
            relevant.length > 1 ? sevPill(f.severity) : null,
            el("p", { text: f.message }),
            f.area === "Bloqueos" && f.details ? renderBlockers(f.details) : null,
            f.area === "CPU" && f.details ? renderCpuNodes(f.details) : null,
            f.action ? el("div", { class: "rec" },
                el("span", { class: "rec-label", text: "Sugerencia" }),
                el("p", { text: f.action }),
                (f.urgency || f.owner) ? el("small", { class: "muted",
                    text: [f.urgency && `Urgencia: ${f.urgency}`, f.owner && `Responsable: ${f.owner}`]
                        .filter(Boolean).join(" · ") }) : null,
            ) : null)),
        el("div", { class: "row-actions-bar" },
            SEV[severity].order >= 1 ? el("button", { class: "btn btn-link",
                onclick: () => askAbout(area, shown) }, icon("chat"), "Preguntar al asistente") : null,
            (AREA_LINKS[area] || []).filter((l) => !l.role || can(l.role)).map((l) => l.href
                ? el("a", { class: "btn btn-link", href: l.href, text: l.label })
                : el("button", { class: "btn btn-link", type: "button", text: l.label, onclick: () => switchView(l.view) }))));

    const cpuNodes = items.find((f) => f.area === "CPU" && f.details);
    const brief = cpuNodes ? cpuNodes.message.replace(/^CPU:\s*/, "") : shown[0].message;
    return el("details", { class: `row row-${cls}`, "data-area": area, ontoggle: onRowToggle },
        el("summary", {},
            el("span", { class: `area-icon ico-${cls}` }, icon(AREA_ICON[area] || "dot")),
            el("strong", { class: "row-title", text: area }),
            el("span", { class: "row-brief", text: brief + extra }),
            EstadoPlus.metric(area),
            EstadoPlus.sparkline(area, cls),
            EstadoPlus.trendBadge(area),
            sevPill(severity),
            el("span", { class: "row-chevron", text: "›" })),
        body);
}

// Acordeón: al abrir un área se cierran las demás.
function onRowToggle(e) {
    const row = e.currentTarget;
    if (!row.open) return;
    document.querySelectorAll("#view-estado details.row[open]").forEach((d) => { if (d !== row) d.open = false; });
}

function toggleOk() {
    ui.okOpen = !ui.okOpen;
    if (state.check) renderHealth();
}

function renderBlockers(details) {
    const cols = [
        ["Sesión", (d) => `inst ${d.instancia} · ${d.sid_serial}`],
        ["Quién", (d) => [d.usuario, d.usuario_so && `(${d.usuario_so})`].filter(Boolean).join(" ")],
        ["Desde", (d) => [d.maquina, d.programa, d.modulo].filter(Boolean).join(" · ")],
        ["Estado", (d) => d.estado + (d.inactiva_s != null ? ` ${fmtSeconds(d.inactiva_s)}` : "")],
        ["Bloquea", (d) => `${d.bloquea_a} ses. · ${fmtSeconds(d.espera_max_s)}`],
        ["Objeto", (d) => d.objeto || "—"],
        ["SQL", (d) => d.sql_id ? `${d.sql_id} (${d.tipo_sql})${d.sql_texto ? ": " + d.sql_texto : ""}` : "—"],
    ];
    return el("div", { class: "table-wrap blockers" },
        el("table", { class: "table table-compact" },
            el("thead", {}, el("tr", {}, cols.map(([h]) => el("th", { text: h })))),
            el("tbody", {}, details.map((d) => el("tr", {}, cols.map(([, fn]) => el("td", { text: fn(d) })))))));
}

function fmtSeconds(s) {
    if (s == null) return "";
    if (s < 60) return `${s} s`;
    if (s < 3600) return `${Math.round(s / 60)} min`;
    return `${(s / 3600).toFixed(1)} h`;
}

function askAbout(area, findings) {
    const detail = findings.map((f) => `«${f.message}»` +
        (f.details ? " Sesiones: " + f.details.map((d) => `${d.sid_serial} ${d.usuario} ${d.maquina} ${d.programa}`).join("; ") : "")
    ).join(" ");
    openAssistant();
    const input = $("chat-input");
    input.value = `Sobre el área ${area} de la última revisión: ${detail} ¿Qué significa y qué debería comprobar?`;
    input.focus();
}

// ---- Detalle técnico (DBA) ----
const DETAIL_LABELS = {
    cpu: "CPU", bloqueos: "Bloqueos", limites: "Límites", tablespaces: "Tablespaces",
    sesiones_inactivas: "Sesiones inactivas", errores_ora: "Problemas Oracle (ADR)",
    esperas: "Esperas", operaciones_largas: "Operaciones largas",
};

async function loadDetail() {
    const panel = $("detail-panel");
    if (!state.check || panel.dataset.loadedFor === String(state.check.id)) return;
    panel.dataset.loadedFor = String(state.check.id);
    $("detail-body").replaceChildren(el("p", { class: "muted", text: "Cargando…" }));
    try {
        const { raw } = await api(`/health-check/${state.check.id}/detail`);
        const keys = Object.keys(raw || {});
        const show = (key) => {
            document.querySelectorAll("#detail-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.key === key));
            $("detail-body").replaceChildren(renderData(raw[key]));
        };
        $("detail-tabs").replaceChildren(...keys.map((k) =>
            el("button", { "data-key": k, text: DETAIL_LABELS[k] || k.replace(/_/g, " "), onclick: () => show(k) })));
        if (keys.length) show(keys[0]);
    } catch (err) {
        panel.dataset.loadedFor = "";
        $("detail-body").replaceChildren(el("p", { class: "form-error", text: err.message }));
    }
}

function renderData(data) {
    if (data == null) return el("p", { class: "muted", text: "Sin datos." });
    if (!Array.isArray(data)) {
        if (typeof data === "object") {
            return data.error ? el("p", { class: "form-error", text: `No disponible: ${data.error}` })
                : renderData([data]);
        }
        return el("p", { class: "big-value", text: String(data) });
    }
    if (!data.length) return el("p", { class: "muted", text: "Sin filas (nada que reportar)." });
    const cols = [...new Set(data.flatMap((r) => Object.keys(r)))];
    return el("table", { class: "table table-compact" },
        el("thead", {}, el("tr", {}, cols.map((c) => el("th", { text: c })))),
        el("tbody", {}, data.slice(0, 500).map((r) =>
            el("tr", {}, cols.map((c) => el("td", { text: r[c] == null ? "" : String(r[c]) }))))));
}

// ========== Mejoras de queries ==========
const QUERY_KIND = {
    nueva_sin_seguimiento: { label: "Nueva sin seguimiento", group: "seguimiento", sev: "WARNING" },
    completada_reaparece: { label: "Completada que sigue en el top", group: "seguimiento", sev: "WARNING" },
    completada_empeora: { label: "Empeora tras el cambio", group: "seguimiento", sev: "WARNING" },
    completada_sin_medir: { label: "Completada sin medir", group: "seguimiento", sev: "INFO" },
    estancada: { label: "Estancada", group: "seguimiento", sev: "WARNING" },
    planes_multiples: { label: "Varios planes", group: "tecnica", sev: "INFO" },
    lecturas_por_fila: { label: "Muchas lecturas por fila", group: "tecnica", sev: "INFO" },
    muchas_ejecuciones: { label: "Exceso de ejecuciones", group: "tecnica", sev: "INFO" },
    plsql: { label: "Llamada PL/SQL", group: "tecnica", sev: "INFO" },
    batch_pesado: { label: "Batch pesado", group: "tecnica", sev: "INFO" },
};
const fmtNum = (n, d = 0) => n == null ? "n/d" : Number(n).toLocaleString("es-ES", { maximumFractionDigits: d });
let queriesData = null;
let queriesOverrides = {};
let dragSqlId = null;

// Aplica sobre el tablero del Excel los cambios locales (estado, prioridad, responsable, nota).
function mergedBoard() {
    return (queriesData?.board || []).map((c) => {
        const o = queriesOverrides[c.sql_id];
        if (!o) return c;
        if (!["estado", "prioridad", "persona", "nota"].some((k) => o[k])) return { ...c, comentarios: o.comments || [] };
        return { ...c, comentarios: o.comments || [], estado_excel: c.estado, estado: o.estado || c.estado, prioridad: o.prioridad || c.prioridad,
            persona: o.persona || c.persona, nota_local: o.nota || "", editado: true, override: o };
    });
}
let queriesMode = "tablero";
let listSort = { key: "cpu_h", dir: -1 };

async function loadQueries(silent = false) {
    if (!silent) {
        $("queries-body").replaceChildren(el("p", { class: "muted", text: "Leyendo informes…" }));
        resetLive("queries");
    }
    try {
        const [data, board] = await Promise.all([
            api("/query-improvements"),
            api("/query-board").catch(() => ({ overrides: queriesOverrides })),
        ]);
        const changed = JSON.stringify(data) !== JSON.stringify(queriesData)
            || JSON.stringify(board.overrides) !== JSON.stringify(queriesOverrides);
        queriesData = data;
        queriesOverrides = board.overrides || {};
        if (!silent || changed) renderQueries();
    } catch (err) {
        if (silent) throw err;
        $("queries-body").replaceChildren(el("p", { class: "form-error", text: err.message }));
    }
}

function filteredCards(list) {
    const text = $("queries-search").value.trim().toLowerCase();
    const group = $("queries-filter").value;
    return list
        .map((i) => ({ ...i, hallazgos: (i.hallazgos || []).filter((f) => !group || QUERY_KIND[f.tipo]?.group === group) }))
        .filter((i) => !group || i.hallazgos.length)
        .filter((i) => !text || [i.sql_id, i.esquema, i.persona].some((v) => String(v || "").toLowerCase().includes(text)));
}

function renderQueries() {
    const data = queriesData;
    if (!data) return;
    if (data.error || !data.week) {
        $("queries-counters").replaceChildren();
        $("queries-body").replaceChildren(el("p", { class: "muted",
            text: data.error || "No hay ningún informe semanal en la carpeta configurada." }));
        return;
    }
    const k = data.kpis;
    $("queries-meta").textContent = `Semana ${data.week} · ${data.file} · ${data.weeks_available} semana(s) disponibles`;
    const counter = (value, label) => el("div", { class: "counter" }, el("strong", { text: value }), el("span", { text: label }));
    $("queries-counters").replaceChildren(
        counter(String(k.sql_en_top), `SQL en el top · ${fmtNum(k.cpu_total_top_h, 1)} h CPU`),
        k.seguimiento_configurado ? counter(String(k.sin_seguimiento), "Sin seguimiento") : counter("—", "Seguimiento no configurado"),
        counter(String(k.completadas_que_reaparecen), `Completadas aún en el top · ${k.completadas_fuera_del_top} ya fuera`),
        counter(String(k.estancadas), "Estancadas (varias semanas)"),
    );
    document.querySelectorAll("#queries-modes button").forEach((b) => b.classList.toggle("active", b.dataset.mode === queriesMode));
    const body = queriesMode === "tablero" ? renderBoard(filteredCards(mergedBoard()), data.states || [])
        : queriesMode === "lista" ? renderList(filteredCards(mergedBoard()))
        : renderRecommendations(filteredCards(data.items));
    $("queries-body").replaceChildren(body);
}

function renderRecommendations(items) {
    if (!items.length) return el("p", { class: "muted", text: "Ninguna SQL coincide con el filtro." });
    return el("div", { class: "cards" }, items.map(renderQueryCard));
}

function cardMetric(c) {
    return c.en_top ? `${fmtNum(c.cpu_h, 1)} h CPU esta semana` : c.cpu_media_h != null ? `${fmtNum(c.cpu_media_h, 1)} h/sem (media) · fuera del top` : "fuera del top";
}

const PRIO_CLASS = { "CRÍTICA": "prio-alta", ALTA: "prio-alta", MEDIA: "prio-media", BAJA: "prio-baja" };

async function saveBoard(sqlId, changes, okMsg) {
    const before = queriesOverrides[sqlId];
    try {
        const { override } = await api(`/query-board/${sqlId}`, { method: "PUT", body: changes });
        if (override) queriesOverrides[sqlId] = override; else delete queriesOverrides[sqlId];
        renderQueries();
        if (okMsg) toast(okMsg);
        return true;
    } catch (err) {
        if (before) queriesOverrides[sqlId] = before;
        renderQueries();
        toast(err.message, "error");
        return false;
    }
}

function moveCard(sqlId, stateName) {
    const card = mergedBoard().find((c) => c.sql_id === sqlId);
    if (!card || card.estado === stateName) return;
    const original = card.estado_excel ?? card.estado;
    // Volver a la columna original del Excel elimina el cambio local de estado.
    saveBoard(sqlId, { estado: stateName === original ? "" : stateName }, `${sqlId} → ${stateName}`);
}

function renderBoard(cards, states) {
    const editable = can("dba");
    const cols = states.filter((s) => s !== "Sin seguimiento" || editable || cards.some((c) => c.estado === s));
    return el("div", { class: "board" }, cols.map((stateName) => {
        const list = cards.filter((c) => c.estado === stateName)
            .sort((a, b) => (b.cpu_h ?? b.cpu_media_h ?? 0) - (a.cpu_h ?? a.cpu_media_h ?? 0));
        const cpu = list.reduce((sum, c) => sum + (c.cpu_h ?? 0), 0);
        const col = el("section", { class: "board-col", "data-state": stateName },
            el("header", {}, el("strong", { text: stateName }),
                el("span", { class: "board-col-meta" },
                    cpu ? el("small", { class: "muted", text: `${fmtNum(cpu, 1)} h` }) : null,
                    el("span", { class: "tag", text: String(list.length) }))),
            el("div", { class: "board-drop" },
                list.map(renderBoardCard),
                list.length ? null : el("p", { class: "board-empty", text: editable ? "Arrastra aquí una tarjeta" : "Sin SQL" })));
        if (editable) {
            col.addEventListener("dragover", (e) => { if (dragSqlId) { e.preventDefault(); col.classList.add("drop-over"); } });
            col.addEventListener("dragleave", (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove("drop-over"); });
            col.addEventListener("drop", (e) => {
                e.preventDefault();
                col.classList.remove("drop-over");
                if (dragSqlId) moveCard(dragSqlId, stateName);
                dragSqlId = null;
            });
        }
        return col;
    }));
}

function renderBoardCard(c) {
    const editable = can("dba");
    const prio = PRIO_CLASS[String(c.prioridad || "").toUpperCase()] || "";
    const card = el("div", {
        class: `board-card ${prio} ${c.en_top ? "" : "board-card-out"}${c.editado ? " board-card-edited" : ""}`,
        role: "button", tabindex: "0", draggable: editable ? "true" : null,
        title: editable ? "Arrastra para cambiar de columna · clic para abrir la ficha" : "Abrir ficha",
        onclick: () => openSqlDetail(c),
        onkeydown: (e) => { if (e.key === "Enter") openSqlDetail(c); },
    },
        el("div", { class: "board-card-head" }, el("span", { class: "mono", text: c.sql_id }),
            el("span", { class: "tag", text: c.prioridad || "—" })),
        el("small", { class: "muted", text: [c.esquema, c.persona || "sin asignar"].filter(Boolean).join(" · ") }),
        el("small", { text: `${cardMetric(c)} · ${c.semanas_top} sem.` }),
        c.mejora_pct != null ? el("small", { text: `Mejora ${fmtNum(c.mejora_pct, 1)} %` }) : null,
        c.nota_local ? el("small", { class: "board-note" }, icon("note", "ico ico-xs"), c.nota_local) : null,
        c.hallazgos.length ? el("small", { class: "board-hint" }, icon("bulb", "ico ico-xs"), c.hallazgos.map((f) => QUERY_KIND[f.tipo]?.label || f.tipo).join(", ")) : null,
        c.estado_excel ? el("small", { class: "board-moved" }, icon("arrow", "ico ico-xs"), `en el Excel: ${c.estado_excel}`) : null);
    if (editable) {
        card.addEventListener("dragstart", (e) => {
            dragSqlId = c.sql_id;
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", c.sql_id);
            requestAnimationFrame(() => card.classList.add("dragging"));
        });
        card.addEventListener("dragend", () => {
            dragSqlId = null;
            card.classList.remove("dragging");
            document.querySelectorAll(".board-col.drop-over").forEach((n) => n.classList.remove("drop-over"));
        });
    }
    return card;
}

function renderBoardEditor(c) {
    const states = queriesData?.states || [];
    const prios = [...new Set(["CRÍTICA", "ALTA", "MEDIA", "BAJA", String(c.prioridad || "").toUpperCase()].filter(Boolean))];
    const o = c.override || {};
    const sel = (id, options, value) => el("select", { id }, options.map((v) => el("option", { value: v, text: v, selected: v === value })));
    const field = (label, node) => el("label", { class: "editor-field" }, el("span", { class: "rec-label", text: label }), node);
    const note = el("textarea", { id: "be-nota", rows: 4, maxlength: 4000, placeholder: "Escribe una nota para el equipo…" });
    note.value = o.nota || "";
    return el("form", { class: "board-editor", onsubmit: async (e) => {
        e.preventDefault();
        const original = c.estado_excel ?? c.estado;
        const estado = $("be-estado").value, prioridad = $("be-prio").value;
        const ok = await saveBoard(c.sql_id, {
            estado: estado === original ? "" : estado,
            prioridad: prioridad === String(queriesData.board.find((b) => b.sql_id === c.sql_id)?.prioridad || "").toUpperCase() ? "" : prioridad,
            persona: $("be-persona").value, nota: note.value,
        }, "Cambios guardados");
        if (ok) $("sql-dialog").close();
    } },
        el("h3", { text: "Editar en el tablero" }),
        el("div", { class: "editor-grid" },
            field("Estado", sel("be-estado", states, c.estado)),
            field("Prioridad", sel("be-prio", prios, String(c.prioridad || "").toUpperCase())),
            field("Responsable", el("input", { id: "be-persona", maxlength: 80, value: c.persona || "", placeholder: "sin asignar" }))),
        field("Nota", note),
        el("div", { class: "inline-form" },
            el("button", { class: "btn btn-primary", type: "submit", text: "Guardar" }),
            c.editado ? el("button", { class: "btn", type: "button", text: "Restablecer al Excel", onclick: async () => {
                if (await saveBoard(c.sql_id, { estado: "", prioridad: "", persona: "", nota: "" }, "Restablecida")) $("sql-dialog").close();
            } }) : null,
            o.updated_by ? el("small", { class: "muted", text: `Último cambio: ${o.updated_by} · ${fmtDate(o.updated_at)}` }) : null));
}

const LIST_COLUMNS = [
    ["sql_id", "SQL_ID"], ["estado", "Estado"], ["prioridad", "Prioridad"], ["esquema", "Esquema"], ["persona", "Responsable"],
    ["cpu_h", "CPU semana (h)"], ["cpu_media_h", "CPU media (h/sem)"], ["semanas_top", "Semanas top"], ["en_top", "En top"],
    ["fecha_completado", "Completado"], ["mejora_pct", "Mejora %"], ["hallazgos", "Recomendaciones"],
];

function renderList(cards) {
    const value = (c, key) => key === "hallazgos" ? c.hallazgos.length : c[key];
    const sorted = [...cards].sort((a, b) => {
        const x = value(a, listSort.key), y = value(b, listSort.key);
        if (x == null) return 1;
        if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * listSort.dir;
    });
    const fmt = (c, key) => {
        const v = value(c, key);
        if (key === "en_top") return v ? "Sí" : "No";
        if (["cpu_h", "cpu_media_h", "mejora_pct"].includes(key)) return v == null ? "" : fmtNum(v, 1);
        return v == null ? "" : String(v);
    };
    return el("div", { class: "table-wrap" }, el("table", { class: "table table-compact table-click" },
        el("thead", {}, el("tr", {}, LIST_COLUMNS.map(([key, label]) => el("th", {
            text: label + (listSort.key === key ? (listSort.dir > 0 ? " ▲" : " ▼") : ""),
            onclick: () => { listSort = { key, dir: listSort.key === key ? -listSort.dir : -1 }; renderQueries(); },
        })))),
        el("tbody", {}, sorted.map((c) => el("tr", { onclick: () => openSqlDetail(c) },
            LIST_COLUMNS.map(([key]) => el("td", { class: key === "sql_id" ? "mono" : null, text: fmt(c, key) })))))));
}

function renderQueryCard(i) {
    const worst = i.hallazgos.some((f) => QUERY_KIND[f.tipo]?.sev === "WARNING") ? "WARNING" : "INFO";
    const metrics = [
        i.cpu_h != null && `${fmtNum(i.cpu_h, 1)} h CPU (${fmtNum(i.pct_cpu, 1)} %)`,
        i.cpu_h_semana_anterior != null && `semana anterior ${fmtNum(i.cpu_h_semana_anterior, 1)} h`,
        i.ejecuciones != null && `${fmtNum(i.ejecuciones)} ejec.`,
        i.gets_ejec != null && `${fmtNum(i.gets_ejec)} lecturas/ejec.`,
        i.planes && `${fmtNum(i.planes)} plan(es)`,
        i.semanas_top && `${i.semanas_top} sem. en top`,
    ].filter(Boolean).join(" · ");
    return el("article", { class: `card sev-border-${SEV[worst].cls}` },
        el("header", {},
            el("h3", { class: "mono", text: i.sql_id }),
            el("span", { class: "tag", text: i.prioridad || "—" })),
        el("p", { class: "muted", text: [i.esquema, `Estado: ${i.estado}`, i.persona].filter(Boolean).join(" · ") }),
        metrics ? el("small", { class: "muted", text: metrics }) : null,
        i.sql_text ? el("pre", { class: "sql-snippet", text: i.sql_text }) : null,
        renderFindings(i.hallazgos),
        el("footer", {}, el("button", { class: "btn btn-link", text: "Ver ficha", onclick: () => openSqlDetail(i) }),
            " ", askButton(i.sql_id)));
}

function renderFindings(list, kindLabel = (t) => QUERY_KIND[t]?.label || t.replace(/^analisis_/, "").replaceAll("_", " ")) {
    return el("ul", { class: "findings" }, list.map((f) => el("li", {},
        el("span", { class: `sev-pill sev-${SEV[QUERY_KIND[f.tipo]?.sev || (f.urgencia === "Alta" ? "WARNING" : "INFO")].cls}`, text: kindLabel(f.tipo) }),
        el("p", { text: f.mensaje }),
        f.accion ? el("div", { class: "rec" },
            el("span", { class: "rec-label", text: "Sugerencia" }),
            el("p", { text: f.accion }),
            f.responsable ? el("small", { class: "muted", text: `Responsable: ${f.responsable}` }) : null) : null)));
}

function askButton(sqlId) {
    return el("button", { class: "btn btn-ghost", type: "button", onclick: () => {
        $("sql-dialog").close();
        openAssistant();
        $("chat-input").value = can("dba")
            ? `Analiza la SQL_ID ${sqlId} y explícame qué revisarías primero y por qué.`
            : `Sobre la SQL_ID ${sqlId} del informe semanal: ¿qué me recomiendas revisar primero y por qué?`;
        $("chat-input").focus();
    } }, icon("chat"), "Preguntar al asistente");
}

function simpleTable(columns, rows, fmt = {}) {
    return el("div", { class: "table-wrap" }, el("table", { class: "table table-compact" },
        el("thead", {}, el("tr", {}, columns.map(([, label]) => el("th", { text: label })))),
        el("tbody", {}, rows.map((r) => el("tr", {}, columns.map(([key]) => {
            const v = r[key];
            const iso = typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v);
            return el("td", { text: fmt[key] ? fmt[key](v, r) : v == null ? "" : typeof v === "number" ? fmtNum(v, 2) : iso ? v.replace("T", " ").slice(0, 19) : String(v) });
        }))))));
}

const SQL_KEYWORDS = "SELECT|FROM|WHERE|AND|OR|NOT|IN|IS|NULL|AS|ON|JOIN|INNER|LEFT|RIGHT|FULL|OUTER|CROSS|GROUP|ORDER|BY|HAVING|UNION|ALL|DISTINCT|INSERT|INTO|VALUES|UPDATE|SET|DELETE|MERGE|USING|MATCHED|THEN|WHEN|CASE|ELSE|END|EXISTS|BETWEEN|LIKE|WITH|DESC|ASC|FETCH|FIRST|NEXT|ROWS|ONLY|OVER|PARTITION|BEGIN|DECLARE|CALL|COUNT|SUM|MIN|MAX|AVG|NVL|DECODE|TO_DATE|TO_CHAR|TRUNC|SYSDATE|ROWNUM|FOR|CONNECT|START|PRIOR";
const SQL_TOKEN_RE = new RegExp(`('(?:[^']|'')*')|(:[A-Za-z0-9_]+)|\\b(${SQL_KEYWORDS})\\b|(\\b\\d+(?:\\.\\d+)?\\b)|(--[^\\n]*|/\\*[\\s\\S]*?\\*/)`, "gi");
const SQL_BREAK_RE = /\s+(?=\b(?:FROM|WHERE|AND|OR|GROUP BY|ORDER BY|HAVING|UNION(?: ALL)?|(?:LEFT |RIGHT |FULL |INNER |CROSS )?(?:OUTER )?JOIN|SET|VALUES|WHEN|ELSE|FETCH)\b)/gi;

// Inserta saltos de línea antes de las cláusulas principales (sin tocar literales entre comillas).
function formatSql(text) {
    if (/\n/.test(text.trim())) return text;
    return text.split(/('(?:[^']|'')*')/).map((part, i) => i % 2 ? part : part.replace(SQL_BREAK_RE, (m, off) => off === 0 ? m : "\n")).join("")
        .replace(/\n(AND|OR)\b/gi, "\n  $1");
}

function highlightSql(text) {
    const out = [];
    let last = 0;
    for (const m of text.matchAll(SQL_TOKEN_RE)) {
        if (m.index > last) out.push(text.slice(last, m.index));
        const cls = m[1] ? "tk-str" : m[2] ? "tk-bind" : m[3] ? "tk-kw" : m[4] ? "tk-num" : "tk-cmt";
        out.push(el("span", { class: cls, text: m[0] }));
        last = m.index + m[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
}

async function copyText(text, okMsg = "Copiado al portapapeles") {
    try {
        await navigator.clipboard.writeText(text);
        toast(okMsg);
    } catch {
        toast("No se pudo copiar. Selecciona el texto y usa Ctrl/⌘+C.", "error");
    }
}

function sqlBlock(text) {
    const pretty = formatSql(text);
    const canFormat = pretty !== text;
    let formatted = canFormat, expanded = false;
    const code = el("pre", { class: "sql-code", tabindex: 0, "aria-label": "Texto SQL" });
    const paint = () => code.replaceChildren(...highlightSql(formatted ? pretty : text));
    const fmtBtn = canFormat ? el("button", { class: "chip-btn", type: "button", "aria-pressed": "true", onclick: () => {
        formatted = !formatted; fmtBtn.setAttribute("aria-pressed", String(formatted)); paint();
    } }, icon("code"), "Formatear") : null;
    const expBtn = el("button", { class: "chip-btn", type: "button", "aria-pressed": "false", onclick: () => {
        expanded = !expanded; expBtn.setAttribute("aria-pressed", String(expanded)); wrap.classList.toggle("expanded", expanded);
    } }, icon("expand"), "Expandir");
    const wrap = el("section", { class: "sql-block" },
        el("header", {},
            el("span", { class: "sql-block-title" }, icon("code"), "Texto SQL",
                el("small", { class: "muted", text: `${fmtNum(text.length)} caracteres` })),
            el("div", { class: "sql-block-tools" }, fmtBtn, expBtn,
                el("button", { class: "chip-btn", type: "button", onclick: () => copyText(text, "SQL copiada") }, icon("copy"), "Copiar"))),
        code);
    paint();
    return wrap;
}

function slug(v) {
    return String(v || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function dlgSection(title, ico, ...children) {
    return el("section", { class: "dlg-sec" }, el("h3", { class: "dlg-sec-title" }, icon(ico), title), ...children);
}

function openSqlDetail(card) {
    const c = mergedBoard().find((b) => b.sql_id === card.sql_id) || card;
    const onBoard = queriesData?.board?.some((b) => b.sql_id === c.sql_id);
    $("sql-dialog-title").replaceChildren(
        el("small", { class: "dlg-kicker", text: "Detalle de SQL" }),
        el("div", { class: "dlg-title-row" },
            el("h2", { class: "mono", text: c.sql_id }),
            el("button", { class: "dlg-copy", type: "button", title: "Copiar SQL_ID", "aria-label": "Copiar SQL_ID", onclick: () => copyText(c.sql_id, "SQL_ID copiado") }, icon("copy"))),
        el("div", { class: "dlg-pills" },
            c.estado ? el("span", { class: `dlg-pill st-${slug(c.estado)}` }, el("i", { class: "dlg-dot" }), String(c.estado)) : null,
            c.prioridad ? el("span", { class: `dlg-pill prio-${slug(c.prioridad)}`, text: `Prioridad ${String(c.prioridad).toLowerCase()}` }) : null,
            c.esquema ? el("span", { class: "dlg-pill" }, icon("disk", "ico ico-xs"), String(c.esquema)) : null,
            el("span", { class: "dlg-pill" }, icon("user", "ico ico-xs"), c.persona ? String(c.persona) : "Sin responsable"),
            c.en_top ? el("span", { class: "dlg-pill hot", text: "En el top" }) : null));
    const facts = [
        ["CPU esta semana", c.cpu_h != null ? `${fmtNum(c.cpu_h, 1)} h (${fmtNum(c.pct_cpu, 1)} %)` : ""],
        ["CPU media", c.cpu_media_h != null ? `${fmtNum(c.cpu_media_h, 1)} h/sem` : ""], ["Ejecuciones/sem", c.ejec_media != null ? fmtNum(c.ejec_media) : ""],
        ["Semanas en top", c.semanas_top], ["En el top", c.en_top == null ? "" : c.en_top ? "Sí" : "No"],
        ["Primera semana", c.primera_semana], ["Última semana", c.ultima_semana],
        ["Pendiente de", c.pendiente_de], ["Completado", c.fecha_completado],
        ["Tiempo antes → después", c.tiempo_antes_s != null || c.tiempo_despues_s != null ? `${fmtNum(c.tiempo_antes_s, 2)} s → ${fmtNum(c.tiempo_despues_s, 2)} s` : ""],
        ["Mejora", c.mejora_pct != null ? `${fmtNum(c.mejora_pct, 1)} %` : ""], ["Comprobación", c.comprobacion],
    ].filter(([, v]) => v !== "" && v != null);
    const analysis = el("div", { id: "sql-analysis" });
    const main = [
        facts.length ? el("div", { class: "fact-grid" }, facts.map(([k, v]) => el("div", { class: "fact" }, el("span", { text: k }), el("strong", { text: String(v) })))) : null,
        c.sql_text ? sqlBlock(String(c.sql_text)) : el("p", { class: "muted dlg-empty", text: "El informe no incluye el texto de esta SQL." }),
        c.query_mejora ? el("div", { class: "rec rec-ok" }, el("span", { class: "rec-label", text: "Propuesta de mejora" }), el("p", { class: "pre-line", text: c.query_mejora })) : null,
        c.notas || c.notas_analisis ? el("div", { class: "rec" }, el("span", { class: "rec-label", text: "Notas del seguimiento" }),
            el("p", { class: "pre-line", text: [c.notas, c.notas_analisis].filter(Boolean).join("\n\n") })) : null,
        c.hallazgos?.length ? dlgSection(`Recomendaciones del informe (${c.hallazgos.length})`, "bulb", renderFindings(c.hallazgos)) : null,
    ].filter(Boolean);
    const side = [
        renderAssignMe(c),
        can("dba") && onBoard ? renderBoardEditor(c)
            : c.nota_local ? el("div", { class: "rec" }, el("span", { class: "rec-label", text: "Nota del equipo" }), el("p", { class: "pre-line", text: c.nota_local })) : null,
        renderComments(c),
    ].filter(Boolean);
    $("sql-dialog-body").replaceChildren(
        el("div", { class: "dlg-layout" }, el("div", { class: "dlg-main" }, main), el("aside", { class: "dlg-side" }, side)),
        analysis);
    $("sql-dialog-foot").replaceChildren(...[
        can("dba") ? el("button", { class: "btn btn-primary", type: "button", onclick: async () => {
            await loadSqlAnalysis(c.sql_id, analysis);
        } }, icon("flask"), "Analizar SQL en la BD") : null,
        askButton(c.sql_id),
        el("span", { class: "dlg-foot-hint muted", text: "Esc para cerrar" }),
    ].filter(Boolean));
    $("sql-dialog-body").scrollTop = 0;
    $("sql-dialog").showModal();
}

function renderAssignMe(c) {
    if (!queriesData?.board?.some((b) => b.sql_id === c.sql_id)) return null;
    const me = state.user.username.toLowerCase();
    const persona = (c.persona || "").trim().toLowerCase();
    const mine = persona === me || persona.split(/[^a-z0-9]+/).includes(me);
    if (persona && !mine) return null;
    const btn = el("button", { class: mine ? "btn" : "btn btn-primary", type: "button" }, icon("user"), mine ? "Quitarme la asignación" : "Asignármela");
    btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
            const { override } = await api(`/query-board/${c.sql_id}/assign-me`, { method: "POST" });
            if (override) queriesOverrides[c.sql_id] = override; else delete queriesOverrides[c.sql_id];
            renderQueries();
            toast(mine ? "Asignación quitada" : "Te la has asignado");
            $("sql-dialog").close();
        } catch (err) { toast(err.message, "error"); btn.disabled = false; }
    });
    return el("div", { class: "assign-card" },
        el("div", {}, el("strong", { text: mine ? "Eres el responsable" : "Sin responsable" }),
            el("small", { class: "muted", text: mine ? "Esta SQL está asignada a ti." : "Puedes hacerte cargo de esta SQL." })),
        btn);
}

function renderComments(c) {
    const box = el("section", { class: "cm" });
    const draw = () => {
        const list = queriesOverrides[c.sql_id]?.comments || [];
        const me = state.user?.username;
        const sync = (comments) => {
            const o = queriesOverrides[c.sql_id] || {};
            if (comments.length) queriesOverrides[c.sql_id] = { ...o, comments };
            else if (["estado", "prioridad", "persona", "nota"].some((k) => o[k])) queriesOverrides[c.sql_id] = { ...o, comments: undefined };
            else delete queriesOverrides[c.sql_id];
            renderQueries();
            draw();
        };
        const input = el("textarea", { class: "cm-input", rows: 2, maxlength: 2000, placeholder: "Escribe un comentario para el equipo… (usa @usuario para avisar a alguien)" });
        const send = async () => {
            const text = input.value.trim();
            if (!text) return;
            try {
                const { comment } = await api(`/query-board/${c.sql_id}/comments`, { method: "POST", body: { text } });
                sync([...(queriesOverrides[c.sql_id]?.comments || []), comment]);
            } catch (err) { toast(err.message, "error"); }
        };
        input.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") send(); });
        box.replaceChildren(
            el("h3", {}, icon("chat"), "Comentarios", el("span", { class: "cm-count", text: String(list.length) })),
            list.length ? el("ul", { class: "cm-list" }, list.map((m) => el("li", { class: "cm-item" },
                el("span", { class: "cm-avatar", text: (m.author || "?").slice(0, 1).toUpperCase() }),
                el("div", { class: "cm-body" },
                    el("div", { class: "cm-meta" },
                        el("strong", { text: m.author }),
                        el("span", { class: "cm-role", text: ROLE_LABEL[m.role] || m.role || "" }),
                        el("span", { class: "muted", text: fmtDate(m.at) }),
                        (m.author === me || state.user?.role === "administrador") ? el("button", { class: "cm-del", title: "Borrar comentario", "aria-label": "Borrar comentario", onclick: async () => {
                            if (!await confirmDialog("¿Borrar este comentario?", "El comentario se eliminará para todos.")) return;
                            try {
                                await api(`/query-board/${c.sql_id}/comments/${m.id}`, { method: "DELETE" });
                                sync(list.filter((x) => x.id !== m.id));
                            } catch (err) { toast(err.message, "error"); }
                        } }, icon("x", "ico ico-xs")) : null),
                    el("p", { class: "pre-line", text: m.text }))))) : el("p", { class: "muted", text: "Todavía no hay comentarios." }),
            can("dba") ? el("div", { class: "cm-form" }, input,
                el("div", { class: "cm-actions" }, el("small", { class: "muted", text: `Se firmará como ${me} · Ctrl/⌘+Intro para enviar` }),
                    el("button", { class: "btn btn-primary", type: "button", text: "Comentar", onclick: send }))) : null);
    };
    draw();
    return box;
}

function anKpi(label, value, tone = "") {
    return el("div", { class: `an-kpi ${tone}` }, el("span", { class: "an-kpi-l", text: label }), el("strong", { class: "an-kpi-v", text: String(value) }));
}

function anCard(title, ...children) {
    return el("section", { class: "an-card" }, el("h4", { text: title }), ...children);
}

function anBars(rows) {
    const vals = rows.map((r) => Number(r.CPU_H) || 0);
    const max = Math.max(...vals, 0.0001);
    return el("div", { class: "an-bars" }, rows.map((r, i) => el("div", { class: "an-bar", title: `${String(r.DIA).slice(0, 10)} · ${fmtNum(vals[i], 2)} h CPU · ${fmtNum(r.EJECUCIONES)} ejec.` },
        el("i", { style: `height:${Math.max(4, (vals[i] / max) * 100)}%` }),
        el("span", { text: String(r.DIA).slice(8, 10) }))));
}

async function loadSqlAnalysis(sqlId, box, force = false) {
    box.replaceChildren(el("div", { class: "an-loading" }, el("span", { class: "an-spin" }),
        el("p", { class: "muted", text: "Analizando en Oracle (solo lectura, unos segundos)…" })));
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
        const r = await api(`/sql-analysis/${encodeURIComponent(sqlId)}${force ? "?force=true" : ""}`);
        const s = r.resumen;
        const topIds = new Set((queriesData?.board || []).filter((b) => b.en_top).map((b) => b.sql_id));
        const planText = (r.plan.lineas || []).map((l) =>
            `${String(l.ID).padStart(3)} ${"  ".repeat(l.PROFUNDIDAD || 0)}${l.OPERACION} ${l.OPCIONES || ""} ${l.OBJETO ? `${l.PROPIETARIO}.${l.OBJETO}` : ""}`.trimEnd()
            + (l.COSTE != null ? `  (coste ${l.COSTE}${l.FILAS_ESTIMADAS != null ? `, ${l.FILAS_ESTIMADAS} filas est.` : ""})` : "")).join("\n");
        const main = String(s.plan_principal ?? "");
        const warns = r.hallazgos.filter((f) => f.urgencia === "Alta" || QUERY_KIND[f.tipo]?.sev === "WARNING").length;
        box.replaceChildren(el("div", { class: "an" },
            el("header", { class: "an-head" },
                el("div", {}, el("h3", {}, icon("flask"), "Análisis técnico"), el("small", { class: "muted", text: `Generado ${r.generado.replace("T", " ")} · solo lectura` })),
                el("button", { class: "btn", type: "button", onclick: () => loadSqlAnalysis(sqlId, box, true) }, icon("refresh"), "Repetir análisis")),
            el("div", { class: "an-kpis" },
                anKpi("Cursores en memoria", s.cursores_en_memoria),
                anKpi("Planes AWR (30 d)", s.planes_awr, s.planes_awr > 1 ? "warn" : ""),
                anKpi("Plan principal", s.plan_principal ?? "n/d"),
                anKpi("Baseline", s.baselines.length ? "Sí" : "No", s.baselines.length ? "ok" : ""),
                anKpi("Perfil SQL", s.perfiles.length ? "Sí" : "No", s.perfiles.length ? "ok" : ""),
                anKpi("Hallazgos", r.hallazgos.length, warns ? "warn" : "ok")),
            s.origen_plan ? el("small", { class: "muted", text: `Origen del plan: ${s.origen_plan}` }) : null,
            anCard("Hallazgos", r.hallazgos.length ? renderFindings(r.hallazgos) : el("p", { class: "muted", text: "Las reglas actuales no detectan nada destacable." })),
            el("div", { class: "an-grid" },
                r.tendencia.length ? anCard("Tendencia diaria (14 días) · CPU h", anBars(r.tendencia),
                    el("details", { class: "an-det an-det-flat" }, el("summary", { text: "Ver datos diarios" }), simpleTable([["DIA", "Día"], ["EJECUCIONES", "Ejec."], ["ELAPSED_S_EJEC", "s/ejec."], ["CPU_H", "CPU (h)"], ["PLANES", "Planes"]], r.tendencia,
                        { DIA: (v) => String(v).slice(0, 10), EJECUCIONES: (v) => fmtNum(v), PLANES: (v) => String(v) }))) : null,
                r.planes.length ? anCard("Planes en el AWR (30 días)",
                    simpleTable([["PLAN_HASH_VALUE", "Plan"], ["EJECUCIONES", "Ejec."], ["ELAPSED_S_EJEC", "s/ejec."], ["LECTURAS_EJEC", "Lecturas/ejec."], ["FILAS_EJEC", "Filas/ejec."], ["CPU_H", "CPU (h)"], ["PRIMERA_VEZ", "Desde"], ["ULTIMA_VEZ", "Hasta"]], r.planes,
                        { PLAN_HASH_VALUE: (v) => String(v) === main ? `${v} ★` : String(v), EJECUCIONES: (v) => fmtNum(v), LECTURAS_EJEC: (v) => fmtNum(v) })) : null),
            r.plsql_hijas.length ? anCard("SQL hijas (ASH, últimas horas)",
                simpleTable([["SQL_ID", "SQL_ID"], ["MUESTRAS", "Muestras"], ["SQL_TEXTO", "SQL"]], r.plsql_hijas,
                    { SQL_ID: (v) => `${v}${topIds.has(v) ? " (en el top)" : ""}`, MUESTRAS: (v) => fmtNum(v) })) : null,
            planText ? el("details", { class: "an-det" }, el("summary", { text: `Plan de ejecución ${r.plan.plan_hash_value}` }), el("pre", { class: "sql-snippet plan-text", text: planText })) : null,
            r.tablas.length ? el("details", { class: "an-det" }, el("summary", { text: `Tablas (${r.tablas.length})` }),
                simpleTable([["PROPIETARIO", "Propietario"], ["TABLA", "Tabla"], ["FILAS", "Filas"], ["ULTIMO_ANALISIS", "Último análisis"], ["OBSOLETAS", "Obsoletas"], ["BLOQUEADAS", "Bloqueadas"], ["MODIFICACIONES", "Cambios"]], r.tablas,
                    { FILAS: (v) => fmtNum(v), MODIFICACIONES: (v) => fmtNum(v), ULTIMO_ANALISIS: (v) => String(v ?? "").slice(0, 10) })) : null,
            r.indices.length ? el("details", { class: "an-det" }, el("summary", { text: `Índices (${r.indices.length})` }),
                simpleTable([["TABLA", "Tabla"], ["INDICE", "Índice"], ["COLUMNAS", "Columnas"], ["UNICIDAD", "Único"], ["ESTADO", "Estado"], ["VISIBILIDAD", "Visible"]], r.indices)) : null,
            Object.keys(r.errores).length ? el("p", { class: "form-error", text: `No se pudo consultar: ${Object.keys(r.errores).join(", ")}` }) : null,
            el("p", { class: "note", text: r.note })));
    } catch (err) {
        box.replaceChildren(el("p", { class: "form-error", text: err.message }));
    }
}

// ========== Histórico ==========
async function loadHistory() {
    const tbody = $("history-table").querySelector("tbody");
    tbody.replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "muted", text: "Cargando…" })));
    try {
        const { history } = await api(`/health-history?limit=${$("history-limit").value}`);
        if (!history.length) {
            tbody.replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "muted", text: "Todavía no hay consultas registradas." })));
            $("history-timeline").replaceChildren();
            return;
        }
        tbody.replaceChildren(...history.map((h) => el("tr", {},
            el("td", { text: fmtDate(h.asked_at) }),
            el("td", { text: h.requested_by }),
            el("td", {}, el("span", { class: `tag ${h.from_cache ? "" : "tag-strong"}`,
                text: h.from_cache ? `Caché (#${h.check_id})` : `Nueva (#${h.check_id})` })),
            el("td", {}, sevPill(h.overall)),
            el("td", {}, el("details", {},
                el("summary", { text: firstLine(h.summary) }),
                el("pre", { class: "summary-pre", text: h.summary }))),
        )));

        const checks = new Map();
        [...history].reverse().forEach((h) => checks.set(h.check_id, h));
        $("history-timeline").replaceChildren(...[...checks.values()].map((h) =>
            el("span", { class: `tl-dot sev-bg-${SEV[h.overall].cls}`,
                title: `#${h.check_id} · ${fmtDate(h.check_created_at)} · ${SEV[h.overall].label}` })));
    } catch (err) {
        tbody.replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "form-error", text: err.message })));
    }
}

function firstLine(text) {
    const raw = (text || "").split("\n").find((l) => l.trim() && !l.startsWith("Estado global")) || text || "";
    const line = raw.replace(/^\s*[-•*]\s*/, "").replace(/^\[(OK|INFO|WARNING|CRITICAL)\]\s*/, "");
    return line.length > 110 ? line.slice(0, 107) + "…" : line;
}

// ========== Usuarios ==========
async function loadUsers() {
    const tbody = $("users-table").querySelector("tbody");
    try {
        const { users } = await api("/users");
        tbody.replaceChildren(...users.map(renderUserRow));
    } catch (err) {
        tbody.replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "form-error", text: err.message })));
    }
}

function renderUserRow(u) {
    const self = u.username === state.user.username;
    // Uno mismo no puede quitarse el rol ni desactivarse (evita quedarse fuera por error).
    const selfTip = self ? "No puedes cambiar tu propio rol ni desactivarte" : null;
    const roleSel = el("select", { "aria-label": `Rol de ${u.username}`, disabled: self, title: selfTip,
        onchange: (e) => updateUser(u.username, { role: e.target.value }) },
        Object.keys(ROLE_LEVEL).map((r) => el("option", { value: r, selected: r === u.role, text: ROLE_LABEL[r] })));
    const active = el("input", { type: "checkbox", checked: u.active, disabled: self, title: selfTip,
        "aria-label": `${u.username} activo`, onchange: (e) => updateUser(u.username, { active: e.target.checked }) });
    return el("tr", {},
        el("td", {}, u.username, self ? el("span", { class: "tag tag-strong", style: "margin-left:8px", text: "tú" }) : null),
        el("td", {}, roleSel),
        el("td", {}, active),
        el("td", { text: fmtDate(u.created_at) }),
        el("td", { class: "row-actions" }, el("div", { class: "row-actions-inner" },
            el("button", { class: "btn btn-small", onclick: () => resetPassword(u.username) }, icon("key"), "Contraseña"),
            self ? null : el("button", { class: "btn btn-small btn-danger", onclick: () => deleteUser(u.username) }, icon("trash"), "Eliminar"))));
}

async function updateUser(username, changes) {
    try {
        await api(`/users/${encodeURIComponent(username)}`, { method: "PATCH", body: changes });
        toast("Usuario actualizado");
        if (username === state.user.username) state.user = await api("/auth/me");
    } catch (err) {
        toast(err.message, "error");
    }
    loadUsers();
}

async function resetPassword(username) {
    const res = await uiDialog({
        title: `Cambiar contraseña de ${username}`, message: "Mínimo 10 caracteres.", ok: "Guardar",
        fields: [{ name: "p1", label: "Nueva contraseña", type: "password", minlength: 10 },
                 { name: "p2", label: "Repite la contraseña", type: "password", minlength: 10 }],
    });
    if (!res) return;
    if (res.p1 !== res.p2) return toast("Las contraseñas no coinciden", "error");
    updateUser(username, { password: res.p1 });
}

async function deleteUser(username) {
    if (!await confirmDialog(`¿Eliminar el usuario ${username}?`, "Perderá el acceso a SIMBA de inmediato. Esta acción no se puede deshacer.")) return;
    try {
        await api(`/users/${encodeURIComponent(username)}`, { method: "DELETE" });
        toast("Usuario eliminado");
    } catch (err) {
        toast(err.message, "error");
    }
    loadUsers();
}

async function createUser(e) {
    e.preventDefault();
    try {
        await api("/users", { method: "POST", body: {
            username: $("nu-username").value.trim(), password: $("nu-password").value, role: $("nu-role").value } });
        e.target.reset();
        toast("Usuario creado");
        loadUsers();
    } catch (err) {
        toast(err.message, "error");
    }
}

// ========== Asistente ==========
function openAssistant() {
    document.body.classList.add("assistant-open");
    $("assistant").setAttribute("aria-hidden", "false");
    $("assistant-toggle").setAttribute("aria-expanded", "true");
    setTimeout(() => $("chat-input").focus(), 200);
}

function closeAssistant() {
    document.body.classList.remove("assistant-open");
    $("assistant").setAttribute("aria-hidden", "true");
    $("assistant-toggle").setAttribute("aria-expanded", "false");
}

function chatHeaders() {
    return state.chatSessionId ? { "X-Session-Id": state.chatSessionId } : {};
}

function rememberChat(res) {
    const sid = res.headers.get("X-Session-Id");
    if (sid) { state.chatSessionId = sid; sessionStorage.setItem("chatSessionId", sid); }
    sessionStorage.setItem("chatHistory", JSON.stringify(state.chat.slice(-60)));
}

function renderChat() {
    const box = $("messages");
    if (!state.chat.length) {
        box.replaceChildren(el("div", { class: "msg msg-assistant" }, el("div", { class: "bubble" },
            el("p", { text: "Hola. Puedo explicarte el estado de la base de datos, el porqué de un hallazgo o consultar datos concretos (CPU, sesiones, consultas pesadas…)." }),
            el("p", { class: "muted", text: "El panel de estado no usa IA; úsame solo cuando necesites una explicación o un dato adicional." }))));
        return;
    }
    box.replaceChildren(...state.chat.map((m) => renderMessage(m.role, m.content)));
    box.scrollTop = box.scrollHeight;
}

function renderMessage(role, content) {
    return el("div", { class: `msg msg-${role}` }, el("div", { class: "bubble" }, renderMarkdown(content)));
}

/** Markdown mínimo construido con nodos DOM (negrita, código, listas, párrafos). */
function renderMarkdown(text) {
    const frag = document.createDocumentFragment();
    const inline = (line) => {
        const span = document.createDocumentFragment();
        line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).forEach((part) => {
            if (/^\*\*[^*]+\*\*$/.test(part)) span.append(el("strong", { text: part.slice(2, -2) }));
            else if (/^`[^`]+`$/.test(part)) span.append(el("code", { text: part.slice(1, -1) }));
            else if (part) span.append(part);
        });
        return span;
    };
    let list = null;
    let pre = null;
    for (const line of String(text || "").split("\n")) {
        if (line.trim().startsWith("```")) {
            if (pre) { frag.append(pre); pre = null; } else { pre = el("pre"); }
            continue;
        }
        if (pre) { pre.append(line + "\n"); continue; }
        const item = line.match(/^\s*(?:[-*+]|\d+\.)\s+(.*)$/);
        if (item) {
            if (!list) { list = el("ul"); frag.append(list); }
            list.append(el("li", {}, inline(item[1])));
            continue;
        }
        list = null;
        const heading = line.match(/^#{1,4}\s+(.*)$/);
        if (heading) frag.append(el("h4", {}, inline(heading[1])));
        else if (line.trim()) frag.append(el("p", {}, inline(line)));
    }
    if (pre) frag.append(pre);
    return frag;
}

function setBusy(busy) {
    state.busy = busy;
    $("send-btn").disabled = busy;
    const box = $("messages");
    $("typing")?.remove();
    if (busy) {
        box.append(el("div", { class: "msg msg-assistant", id: "typing" },
            el("div", { class: "bubble typing" }, el("span"), el("span"), el("span"))));
        box.scrollTop = box.scrollHeight;
    }
}

function pushMessage(role, content) {
    state.chat.push({ role, content });
    if (state.chat.length === 1) $("messages").replaceChildren();
    $("messages").append(renderMessage(role, content));
    $("messages").scrollTop = $("messages").scrollHeight;
}

async function sendMessage(text) {
    const message = (text ?? $("chat-input").value).trim();
    if (!message || state.busy) return;
    $("chat-input").value = "";
    pushMessage("user", message);
    setBusy(true);
    try {
        const res = await api("/chat", { method: "POST", body: { message }, headers: chatHeaders(), raw: true });
        const data = await res.json().catch(() => ({}));
        rememberChat(res);
        if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
        pushMessage("assistant", data.success ? data.message : `⚠️ ${data.message}`);
        if (data.is_report && data.report?.filename) downloadReport(data.report.filename);
    } catch (err) {
        if (err.message !== "Sesión caducada") pushMessage("assistant", `⚠️ ${err.message}`);
    } finally {
        setBusy(false);
        sessionStorage.setItem("chatHistory", JSON.stringify(state.chat.slice(-60)));
    }
}

async function clearChat() {
    if (!await confirmDialog("¿Limpiar la conversación?", "Se borrará el historial del asistente en esta sesión.", "Limpiar")) return;
    await api("/clear-history", { method: "POST", headers: chatHeaders(), raw: true }).catch(() => {});
    state.chat = [];
    sessionStorage.removeItem("chatHistory");
    renderChat();
}

function downloadReport(filename) {
    const a = el("a", { href: `${API}/download-report/${encodeURIComponent(filename)}`, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    toast("Informe generado y descargado");
}

// ---- AWR (DBA) ----
async function uploadAwr(files) {
    if (!can("dba") || !files?.length || state.busy) return;
    const file = files[0];
    if (files.length > 1) return toast("Carga un único informe AWR cada vez.", "error");
    if (!/\.html?$/i.test(file.name)) return toast("Solo se admiten informes AWR .html o .htm.", "error");
    if (file.size === 0 || file.size > AWR_MAX_MB * 1024 * 1024) return toast(`El informe debe ocupar entre 1 byte y ${AWR_MAX_MB} MB.`, "error");

    openAssistant();
    pushMessage("user", `📄 Informe AWR cargado: ${file.name}`);
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    try {
        const res = await api("/awr/upload", { method: "POST", body: form, headers: chatHeaders(), raw: true });
        const data = await res.json().catch(() => ({}));
        rememberChat(res);
        if (!res.ok || !data.success) throw new Error(data.detail || data.message || `Error ${res.status}`);
        pushMessage("assistant", data.message);
    } catch (err) {
        pushMessage("assistant", `⚠️ No se pudo analizar el informe AWR: ${err.message}`);
    } finally {
        setBusy(false);
        sessionStorage.setItem("chatHistory", JSON.stringify(state.chat.slice(-60)));
    }
}

// ========== Tema y eventos ==========
function initTheme() {
    const dark = localStorage.getItem("darkMode") === "true";
    document.body.classList.toggle("dark", dark);
    $("theme-btn").querySelector("use").setAttribute("href", dark ? "#i-sun" : "#i-moon");
    $("theme-btn").title = dark ? "Tema claro" : "Tema oscuro";
}

function bindEvents() {
    $("login-form").addEventListener("submit", login);
    $("logout-btn").addEventListener("click", logout);
    $("theme-btn").addEventListener("click", () => {
        localStorage.setItem("darkMode", String(!document.body.classList.contains("dark")));
        initTheme();
    });
    $("tabs").addEventListener("click", (e) => {
        const tab = e.target.closest("[data-view]");
        if (tab) switchView(tab.dataset.view);
    });

    $("refresh-btn").addEventListener("click", () => loadHealth(false));
    $("force-btn").addEventListener("click", () => loadHealth(true));
    $("detail-panel").addEventListener("toggle", (e) => { if (e.target.open) loadDetail(); });

    $("queries-reload").addEventListener("click", loadQueries);
    document.querySelectorAll("#queries-modes button").forEach((b) => b.addEventListener("click", () => { queriesMode = b.dataset.mode; renderQueries(); }));
    $("sql-dialog-close").addEventListener("click", () => $("sql-dialog").close());
    $("queries-filter").addEventListener("change", renderQueries);
    $("queries-search").addEventListener("input", renderQueries);
    $("ok-title").addEventListener("click", toggleOk);
    $("ok-title").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleOk(); } });
    $("history-reload").addEventListener("click", loadHistory);
    $("history-limit").addEventListener("change", loadHistory);
    $("new-user-form").addEventListener("submit", createUser);

    $("assistant-toggle").addEventListener("click", () =>
        document.body.classList.contains("assistant-open") ? closeAssistant() : openAssistant());
    $("assistant-close").addEventListener("click", closeAssistant);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && document.body.classList.contains("assistant-open") && !document.querySelector("dialog[open]")) closeAssistant();
    });
    $("clear-chat-btn").addEventListener("click", clearChat);
    $("composer").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
    $("chat-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendMessage(); }
    });
    $("quick-actions").addEventListener("click", (e) => {
        if (e.target.dataset.query) sendMessage(e.target.dataset.query);
    });

    $("awr-btn").addEventListener("click", () => $("awr-input").click());
    $("awr-input").addEventListener("change", (e) => { uploadAwr(e.target.files); e.target.value = ""; });
    const panel = $("assistant");
    let depth = 0;
    ["dragover", "drop"].forEach((evt) => window.addEventListener(evt, (e) => e.preventDefault()));
    panel.addEventListener("dragenter", () => { if (can("dba")) { depth++; panel.classList.add("dragging"); } });
    panel.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) panel.classList.remove("dragging"); });
    panel.addEventListener("drop", (e) => { depth = 0; panel.classList.remove("dragging"); uploadAwr(e.dataTransfer.files); });
}
