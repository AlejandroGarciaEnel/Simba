// SIMBA · Actualización en vivo: SSE (/api/events), polling de respaldo, campana de avisos y conexión.
// Script clásico: comparte el ámbito global con el resto de js/*.js (ver orden en index.html).

// ========== Actualización en vivo ==========
// Un único temporizador de 5 s ejecuta las tareas vencidas. Se pausa con la pestaña oculta,
// reintenta con backoff si falla y la revisión de salud usa la caché del servidor (sin force).
const LIVE = {
    conn: { every: 15000, run: () => refreshConnection(), views: null },
    health: { every: 60000, run: () => loadHealth(false, true), views: ["estado", "sesiones"] },
    notifs: { every: 30000, run: () => loadNotifications(), views: null },
    queries: { every: 300000, run: () => loadQueries(true), views: ["queries"] },
};
const live = { timer: null, view: "estado", last: {}, fails: {}, busy: {}, connOk: null, updatedAt: null, es: null, sse: false };
// Mientras el flujo SSE está abierto, conexión y avisos llegan por /api/events y no se sondean.
const SSE_TASKS = new Set(["conn", "notifs"]);

function openLiveEvents() {
    closeLiveEvents();
    if (!window.EventSource) return;
    const es = new EventSource(API + "/events");
    live.es = es;
    es.onopen = () => { live.sse = true; };
    es.onerror = () => { live.sse = false; };
    es.addEventListener("status", (e) => applyHealth(JSON.parse(e.data)));
    es.addEventListener("notifications", (e) => applyNotifications(JSON.parse(e.data)));
    es.addEventListener("logout", () => { closeLiveEvents(); showLogin(); });
}

function closeLiveEvents() {
    live.es?.close();
    live.es = null;
    live.sse = false;
}

function pollConnection() {
    clearInterval(live.timer);
    openLiveEvents();
    live.last = { health: Date.now(), queries: Date.now() }; live.fails = {};
    liveTick();
    live.timer = setInterval(liveTick, 5000);
}

async function liveTick() {
    if (!state.user || document.hidden) return;
    const now = Date.now();
    for (const [name, t] of Object.entries(LIVE)) {
        if (live.busy[name] || (t.views && !t.views.includes(live.view))) continue;
        if (live.sse && SSE_TASKS.has(name)) continue;
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
    await applyNotifications(await api("/notifications"));
}

async function applyNotifications(data) {
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
        applyHealth(await api("/health"));
    } catch (err) {
        $("conn-dot").className = "dot dot-crit";
        live.connText = "Servidor no disponible · reintentando";
        renderLiveStamp();
        throw err;
    }
}

function applyHealth(h) {
    const ok = h.db_connected && h.llm_ready;
    $("conn-dot").className = `dot ${ok ? "dot-ok" : h.db_connected ? "dot-warn" : "dot-crit"}`;
    live.connText = ok ? "BD y asistente conectados"
        : h.db_connected ? "BD conectada · asistente no disponible" : "BD no conectada";
    live.updatedAt = Date.now();
    renderLiveStamp();
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
