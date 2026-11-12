// SIMBA · Tema y enlace de eventos de la interfaz.
// Script clásico: comparte el ámbito global con el resto de js/*.js (ver orden en index.html).

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
