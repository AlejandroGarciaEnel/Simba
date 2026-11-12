// SIMBA · Asistente IA en panel lateral.
// Script clásico: comparte el ámbito global con el resto de js/*.js (ver orden en index.html).

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
