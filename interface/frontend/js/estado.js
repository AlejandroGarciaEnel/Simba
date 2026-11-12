// SIMBA · Navegación entre vistas y panel de Estado.
// Script clásico: comparte el ámbito global con el resto de js/*.js (ver orden en index.html).

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
