/**
 * SIMBA · Web de monitorización con roles.
 * Panel de estado (sin IA), histórico, gestión de usuarios y asistente opcional en panel lateral.
 * Todo el contenido que llega del servidor se pinta con textContent (sin innerHTML con datos).
 *
 * El frontal se reparte en scripts clásicos (js/*.js) que comparten el ámbito global; el orden de
 * carga en index.html importa: core → live → estado → queries → history-users → assistant → main.
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
    if (method !== "GET" && state.user?.csrf) opts.headers["X-CSRF-Token"] = state.user.csrf;
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
    closeLiveEvents();
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
