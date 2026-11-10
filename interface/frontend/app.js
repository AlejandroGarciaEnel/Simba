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
const AREA_ICON = {
    CPU: "🧠", Bloqueos: "🔒", Conexiones: "🔌", Espacio: "💾", Sesiones: "👥",
    Errores: "⚠️", Esperas: "⏳", "Operaciones largas": "🐢",
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

function can(role) {
    return state.user && ROLE_LEVEL[state.user.role] >= ROLE_LEVEL[role];
}

function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "medium" });
}

function ago(iso) {
    const mins = Math.round((Date.now() - new Date(iso)) / 60000);
    if (isNaN(mins)) return "";
    if (mins < 1) return "hace menos de un minuto";
    if (mins < 60) return `hace ${mins} min`;
    const h = Math.round(mins / 60);
    return h < 48 ? `hace ${h} h` : `hace ${Math.round(h / 24)} días`;
}

function toast(message, kind = "ok") {
    const t = el("div", { class: `toast toast-${kind}`, text: message });
    $("toasts").append(t);
    setTimeout(() => t.remove(), 4000);
}

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

let connTimer = null;
async function pollConnection() {
    clearInterval(connTimer);
    const update = async () => {
        if (!state.user) return;
        try {
            const h = await api("/health");
            const ok = h.db_connected && h.llm_ready;
            $("conn-dot").className = `dot ${ok ? "dot-ok" : h.db_connected ? "dot-warn" : "dot-crit"}`;
            $("conn-text").textContent = ok ? "BD y asistente conectados"
                : h.db_connected ? "BD conectada · asistente no disponible" : "BD no conectada";
        } catch {
            $("conn-dot").className = "dot dot-crit";
            $("conn-text").textContent = "Servidor no disponible";
        }
    };
    await update();
    connTimer = setInterval(update, 60000);
}

// ========== Navegación ==========
function switchView(view) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
    document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== `view-${view}`; });
    if (view === "historico") loadHistory();
    if (view === "usuarios") loadUsers();
}

// ========== Estado ==========
async function loadHealth(force) {
    const buttons = [$("refresh-btn"), $("force-btn")];
    buttons.forEach((b) => { b.disabled = true; });
    $("overall-title").textContent = force ? "Ejecutando revisión en Oracle…" : "Cargando revisión…";
    try {
        state.check = await api(`/health-check${force ? "?force=true" : ""}`, { method: "POST" });
        renderHealth();
        if (force) toast("Revisión nueva completada");
    } catch (err) {
        $("overall-title").textContent = "No se pudo obtener la revisión";
        $("overall-meta").textContent = err.message;
    } finally {
        buttons.forEach((b) => { b.disabled = false; });
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

function renderHealth() {
    const c = state.check;
    const areas = groupByArea(c.findings || []);
    const toReview = areas.filter((a) => SEV[a.severity].order >= 2).length;

    $("overall-pill").replaceWith(Object.assign(sevPill(c.overall), { id: "overall-pill" }));
    $("overall-title").textContent = toReview === 0
        ? "Sin puntos a revisar en las comprobaciones realizadas"
        : `${toReview} ${toReview === 1 ? "área a revisar" : "áreas a revisar"}`;
    $("overall-meta").textContent =
        `Datos de ${fmtDate(c.created_at)} (${ago(c.created_at)}) · ` +
        (c.from_cache ? "revisión reutilizada (caché)" : "revisión recién ejecutada");

    const counts = { OK: 0, INFO: 0, WARNING: 0, CRITICAL: 0 };
    areas.forEach((a) => { counts[a.severity] += 1; });
    $("counters").replaceChildren(
        ...["CRITICAL", "WARNING", "INFO", "OK"].map((s) =>
            el("div", { class: `counter sev-border-${SEV[s].cls}` },
                el("strong", { text: counts[s] }), el("span", { text: SEV[s].label })))
    );

    $("area-cards").replaceChildren(...areas.map(renderAreaCard));

    const detail = $("detail-panel");
    detail.dataset.loadedFor = "";
    if (detail.open) loadDetail();
}

function renderAreaCard({ area, items, severity }) {
    const relevant = items.filter((f) => f.severity !== "OK");
    const shown = relevant.length ? relevant : items;
    const list = el("ul", { class: "findings" },
        shown.map((f) => el("li", {},
            relevant.length > 1 ? sevPill(f.severity) : null,
            el("p", { text: f.message }),
            f.action ? el("div", { class: "rec" },
                el("span", { class: "rec-label", text: "Sugerencia" }),
                el("p", { text: f.action }),
                (f.urgency || f.owner) ? el("small", { class: "muted",
                    text: [f.urgency && `Urgencia: ${f.urgency}`, f.owner && `Responsable: ${f.owner}`]
                        .filter(Boolean).join(" · ") }) : null,
            ) : null,
        )));

    const ask = el("button", {
        class: "btn btn-link",
        text: "💬 Preguntar al asistente",
        onclick: () => askAbout(area, shown),
    });

    return el("article", { class: `card sev-border-${SEV[severity].cls}` },
        el("header", {},
            el("h3", {}, el("span", { class: "area-icon", text: AREA_ICON[area] || "•" }), area),
            sevPill(severity)),
        list,
        SEV[severity].order >= 1 ? el("footer", {}, ask) : null);
}

function askAbout(area, findings) {
    const detail = findings.map((f) => `«${f.message}»`).join(" ");
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
    const line = (text || "").split("\n").find((l) => l.trim() && !l.startsWith("Estado global")) || text || "";
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
    const roleSel = el("select", { onchange: (e) => updateUser(u.username, { role: e.target.value }) },
        Object.keys(ROLE_LEVEL).map((r) => el("option", { value: r, selected: r === u.role, text: ROLE_LABEL[r] })));
    const active = el("input", { type: "checkbox", checked: u.active,
        onchange: (e) => updateUser(u.username, { active: e.target.checked }) });
    return el("tr", {},
        el("td", {}, u.username, self ? el("span", { class: "muted", text: " (tú)" }) : null),
        el("td", {}, roleSel),
        el("td", {}, active),
        el("td", { text: fmtDate(u.created_at) }),
        el("td", { class: "row-actions" },
            el("button", { class: "btn btn-small", text: "Cambiar contraseña", onclick: () => resetPassword(u.username) }),
            self ? null : el("button", { class: "btn btn-small btn-danger", text: "Eliminar", onclick: () => deleteUser(u.username) })));
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
    const password = prompt(`Nueva contraseña para ${username} (mínimo 10 caracteres):`);
    if (password) updateUser(username, { password });
}

async function deleteUser(username) {
    if (!confirm(`¿Eliminar el usuario ${username}?`)) return;
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
}

function closeAssistant() {
    document.body.classList.remove("assistant-open");
    $("assistant").setAttribute("aria-hidden", "true");
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
    if (!confirm("¿Limpiar la conversación con el asistente?")) return;
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
    $("theme-btn").textContent = dark ? "☀️" : "🌙";
}

function bindEvents() {
    $("login-form").addEventListener("submit", login);
    $("logout-btn").addEventListener("click", logout);
    $("theme-btn").addEventListener("click", () => {
        localStorage.setItem("darkMode", String(!document.body.classList.contains("dark")));
        initTheme();
    });
    $("tabs").addEventListener("click", (e) => {
        if (e.target.dataset.view) switchView(e.target.dataset.view);
    });

    $("refresh-btn").addEventListener("click", () => loadHealth(false));
    $("force-btn").addEventListener("click", () => loadHealth(true));
    $("detail-panel").addEventListener("toggle", (e) => { if (e.target.open) loadDetail(); });

    $("history-reload").addEventListener("click", loadHistory);
    $("history-limit").addEventListener("change", loadHistory);
    $("new-user-form").addEventListener("submit", createUser);

    $("assistant-toggle").addEventListener("click", () =>
        document.body.classList.contains("assistant-open") ? closeAssistant() : openAssistant());
    $("assistant-close").addEventListener("click", closeAssistant);
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
