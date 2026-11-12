// SIMBA · Mejoras de queries: tablero, modal de detalle SQL y análisis en la BD.
// Script clásico: comparte el ámbito global con el resto de js/*.js (ver orden en index.html).

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
    document.querySelectorAll("#queries-modes button").forEach((b) => { b.classList.toggle("active", b.dataset.mode === queriesMode); b.setAttribute("aria-pressed", String(b.dataset.mode === queriesMode)); });
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
    return text.split(/('(?:[^']|'')*')/).map((part, i) => i % 2 ? part : part.replace(SQL_BREAK_RE, (m, off) => i === 0 && off === 0 ? m : "\n")).join("")
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
