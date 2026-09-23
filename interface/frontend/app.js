/**
 * Script principal de la aplicación frontend.
 * Maneja chat, dark mode, descarga de informes y comunicación con API.
 */

const API_BASE = "/api";
let chatHistory = [];
let isDarkMode = localStorage.getItem("darkMode") === "true";
let isLoading = false;

// ========== Inicialización ==========
document.addEventListener("DOMContentLoaded", () => {
    initializeTheme();
    initializeEventListeners();
    restoreChatHistory();
    checkHealth();
    
    // Verificar salud cada 30 segundos
    setInterval(checkHealth, 30000);
});

// ========== Tema Oscuro ==========
function initializeTheme() {
    if (isDarkMode) {
        document.body.classList.add("dark-theme");
        updateThemeIcon();
    }
}

function toggleTheme() {
    isDarkMode = !isDarkMode;
    document.body.classList.toggle("dark-theme");
    localStorage.setItem("darkMode", isDarkMode);
    updateThemeIcon();
}

function updateThemeIcon() {
    const btn = document.getElementById("theme-btn");
    btn.querySelector(".theme-icon").textContent = isDarkMode ? "☀️" : "🌙";
}

// ========== Event Listeners ==========
function initializeEventListeners() {
    const sendBtn = document.getElementById("send-btn");
    const userInput = document.getElementById("user-input");
    const themeBtn = document.getElementById("theme-btn");
    const clearHistoryBtn = document.getElementById("clear-history-btn");
    const retryBtn = document.getElementById("retry-btn");

    // Enviar mensaje
    sendBtn.addEventListener("click", sendMessage);
    
    // Enter + Ctrl para enviar
    userInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-expand textarea
    userInput.addEventListener("input", () => {
        userInput.style.height = "auto";
        userInput.style.height = Math.min(userInput.scrollHeight, 120) + "px";
    });

    // Tema
    themeBtn.addEventListener("click", toggleTheme);

    // Limpiar historial
    clearHistoryBtn.addEventListener("click", clearChatHistory);

    // Reintentar conexión
    retryBtn.addEventListener("click", retryConnection);

    // Quick actions
    document.querySelectorAll(".quick-action-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.getElementById("user-input").value = btn.dataset.query;
            sendMessage();
        });
    });
}

// ========== Enviar Mensaje ==========
async function sendMessage() {
    const userInput = document.getElementById("user-input");
    const message = userInput.value.trim();

    if (!message || isLoading) return;

    // Agregar mensaje del usuario al historial y UI
    addMessageToUI("user", message);
    chatHistory.push({ role: "user", content: message });

    userInput.value = "";
    userInput.style.height = "auto";

    isLoading = true;
    showLoadingIndicator();

    try {
        const response = await fetch(`${API_BASE}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                history: chatHistory.slice(0, -1),
            }),
        });

        if (!response.ok) {
            throw new Error(`Error ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (data.success) {
            // Agregar respuesta del asistente
            addMessageToUI("assistant", data.message);
            chatHistory.push({ role: "assistant", content: data.message });

            // Verificar si es solicitud de informe
            if (data.is_report && data.report && data.report.success) {
                downloadReport(data.report.filename);
                showNotification("✅ Informe generado y descargado automáticamente");
            }

            hideErrorBanner();
        } else {
            // Error en respuesta
            if (data.is_bd_error) {
                showErrorBanner(data.message, true);
            } else {
                showErrorBanner(data.message, false);
            }
            addMessageToUI("assistant", `⚠️ Error: ${data.message}`);
        }
    } catch (error) {
        console.error("Error:", error);
        showErrorBanner(`Error de conexión: ${error.message}`, false);
        addMessageToUI("assistant", `❌ No se pudo procesar tu pregunta. Intenta de nuevo.`);
    } finally {
        isLoading = false;
        hideLoadingIndicator();
        saveChatHistory();
    }
}

// ========== UI - Mensajes ==========
function addMessageToUI(role, content) {
    const messagesContainer = document.getElementById("chat-messages");

    // Si es el primer mensaje real (quitar mensaje inicial)
    if (
        messagesContainer.children.length === 1 &&
        messagesContainer.children[0].classList.contains("initial-message")
    ) {
        messagesContainer.children[0].remove();
    }

    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${role}-message`;

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";
    contentDiv.innerHTML = parseMarkdown(content);

    messageDiv.appendChild(contentDiv);
    messagesContainer.appendChild(messageDiv);

    // Scroll al final
    setTimeout(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }, 50);
}

function showLoadingIndicator() {
    const messagesContainer = document.getElementById("chat-messages");
    const loadingDiv = document.createElement("div");
    loadingDiv.className = "message assistant-message";
    loadingDiv.id = "loading-message";

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";
    contentDiv.innerHTML = `
        <div class="loading-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;

    loadingDiv.appendChild(contentDiv);
    messagesContainer.appendChild(loadingDiv);

    setTimeout(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }, 50);
}

function hideLoadingIndicator() {
    const loading = document.getElementById("loading-message");
    if (loading) loading.remove();
}

// ========== Markdown Parser Ligero ==========
function parseMarkdown(text) {
    let html = escapeHtml(text);

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // Italic
    html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");

    // Code inline
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Code block
    html = html.replace(
        /```(\w+)?\n([\s\S]*?)```/g,
        "<pre><code>$2</code></pre>"
    );

    // Listas no ordenadas
    html = html.replace(/^\s*[-*+]\s+(.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*?<\/li>)/s, "<ul>$1</ul>");

    // Listas ordenadas
    html = html.replace(/^\s*\d+\.\s+(.+)$/gm, "<li>$1</li>");

    // Line breaks
    html = html.replace(/\n\n/g, "</p><p>");
    html = html.replace(/\n/g, "<br>");

    // Párrafos
    if (!html.startsWith("<")) {
        html = "<p>" + html + "</p>";
    }

    return html;
}

function escapeHtml(text) {
    const map = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    };
    return text.replace(/[&<>"']/g, (m) => map[m]);
}

// ========== Errores y Notificaciones ==========
function showErrorBanner(message, canRetry = false) {
    const banner = document.getElementById("error-banner");
    const errorText = document.getElementById("error-text");
    const retryBtn = document.getElementById("retry-btn");

    errorText.textContent = message;
    retryBtn.style.display = canRetry ? "block" : "none";

    banner.style.display = "flex";
}

function hideErrorBanner() {
    document.getElementById("error-banner").style.display = "none";
}

function showNotification(message) {
    // Crear notificación temporal
    const notification = document.createElement("div");
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: var(--color-success);
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 10000;
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = "slideOut 0.3s ease";
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// ========== Health Check ==========
async function checkHealth() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        if (response.ok) {
            const data = await response.json();
            updateConnectionStatus(data.db_connected);
            return true;
        } else {
            updateConnectionStatus(false);
            return false;
        }
    } catch (error) {
        console.error("Health check error:", error);
        updateConnectionStatus(false);
        return false;
    }
}

function updateConnectionStatus(connected) {
    const dot = document.getElementById("status-dot");
    const text = document.getElementById("status-text");

    if (connected) {
        dot.className = "status-dot connected";
        text.textContent = "Base de datos conectada";
    } else {
        dot.className = "status-dot error";
        text.textContent = "Base de datos desconectada";
    }
}

// ========== Reintentar Conexión ==========
async function retryConnection() {
    isLoading = true;
    document.getElementById("retry-btn").disabled = true;

    try {
        const response = await fetch(`${API_BASE}/reset-connection`, {
            method: "POST",
        });

        const data = await response.json();

        if (data.success) {
            hideErrorBanner();
            addMessageToUI("assistant", "✅ " + data.message);
            updateConnectionStatus(data.db_connected);
        } else {
            showErrorBanner(data.message, true);
            addMessageToUI("assistant", "❌ " + data.message);
        }
    } catch (error) {
        showErrorBanner(`Error: ${error.message}`, true);
    } finally {
        isLoading = false;
        document.getElementById("retry-btn").disabled = false;
    }
}

// ========== Historial de Chat ==========
function saveChatHistory() {
    localStorage.setItem("chatHistory", JSON.stringify(chatHistory));
}

function restoreChatHistory() {
    const saved = localStorage.getItem("chatHistory");
    if (saved) {
        try {
            chatHistory = JSON.parse(saved);
            // Renderizar historial
            chatHistory.forEach((msg) => {
                addMessageToUI(msg.role, msg.content);
            });
        } catch (e) {
            console.error("Error restaurando historial:", e);
            chatHistory = [];
        }
    }
}

function clearChatHistory() {
    if (!confirm("¿Estás seguro de que deseas limpiar el historial?")) {
        return;
    }

    chatHistory = [];
    localStorage.removeItem("chatHistory");

    const messagesContainer = document.getElementById("chat-messages");
    messagesContainer.innerHTML = `
        <div class="message assistant-message initial-message">
            <div class="message-content">
                <p>Hola 👋 Soy tu asistente de monitorización de bases de datos Oracle.</p>
                <p>Puedo ayudarte a:</p>
                <ul>
                    <li>Ver el uso actual de CPU</li>
                    <li>Identificar queries pesadas</li>
                    <li>Detectar sesiones bloqueadas</li>
                    <li>Encontrar sesiones inactivas</li>
                    <li>Generar informes completos en HTML</li>
                </ul>
                <p>¿Qué deseas saber? Usa los botones de la izquierda o escribe tu pregunta.</p>
            </div>
        </div>
    `;

    hideErrorBanner();
}

// ========== Descargar Informe ==========
function downloadReport(filename) {
    const link = document.createElement("a");
    link.href = `${API_BASE}/download-report/${filename}`;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}
