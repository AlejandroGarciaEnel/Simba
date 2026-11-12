// SIMBA · Histórico de revisiones y gestión de usuarios (política de contraseñas).
// Script clásico: comparte el ámbito global con el resto de js/*.js (ver orden en index.html).

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

// Misma política que interface/backend/auth.py (password_problems); el servidor es quien decide.
const PASSWORD_HINT = "Mínimo 10 caracteres combinando 3 tipos (minúsculas, mayúsculas, números, símbolos), o una frase de 16 o más. Sin el nombre de usuario.";
const COMMON_PASSWORDS = new Set(["password", "password1", "password123", "contrasena", "contraseña", "qwerty", "qwertyuiop", "123456789",
    "1234567890", "12345678910", "abc123456", "iloveyou", "admin1234", "administrador", "bienvenido", "bienvenido1", "oracle123",
    "oracle1234", "simba12345", "changeme", "letmein123", "passw0rd", "p@ssw0rd"]);

function passwordProblems(password = "", username = "") {
    const problems = [];
    if (password.length < 10) problems.push("debe tener al menos 10 caracteres");
    const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9]/].filter((rx) => rx.test(password)).length;
    if (password.length < 16 && classes < 3) problems.push("debe combinar al menos 3 tipos de carácter o tener 16 caracteres o más");
    if (username.length >= 3 && password.toLowerCase().includes(username.toLowerCase())) problems.push("no puede contener el nombre de usuario");
    if (COMMON_PASSWORDS.has(password.toLowerCase()) || new Set(password).size <= 2) problems.push("es demasiado común o predecible");
    return problems;
}

function checkPassword(password, username) {
    const problems = passwordProblems(password, username);
    if (problems.length) toast(`La contraseña ${problems.join("; ")}.`, "error");
    return !problems.length;
}

async function resetPassword(username) {
    const res = await uiDialog({
        title: `Cambiar contraseña de ${username}`, message: PASSWORD_HINT, ok: "Guardar",
        fields: [{ name: "p1", label: "Nueva contraseña", type: "password", minlength: 10 },
                 { name: "p2", label: "Repite la contraseña", type: "password", minlength: 10 }],
    });
    if (!res) return;
    if (res.p1 !== res.p2) return toast("Las contraseñas no coinciden", "error");
    if (!checkPassword(res.p1, username)) return;
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
    if (!checkPassword($("nu-password").value, $("nu-username").value.trim())) return;
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
