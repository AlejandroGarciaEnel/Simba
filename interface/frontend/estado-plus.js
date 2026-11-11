// Extras de la pestaña Estado: tendencias entre revisiones, mini-gráficas por área,
// línea de tiempo del estado global y filtro por severidad. Solo lee el histórico ya existente.
const EstadoPlus = (() => {
    const NS = "http://www.w3.org/2000/svg";
    const MAX_POINTS = 30;
    let hist = []; // { id, t, overall, areas: { [area]: { order, value, msg } } }
    let seeded = false;
    let filter = null; // null | "crit" | "warn" | "info" | "ok"

    const ORDER = { OK: 0, INFO: 1, WARNING: 2, CRITICAL: 3 };
    const CLS = { OK: "ok", INFO: "info", WARNING: "warn", CRITICAL: "crit" };
    const LABEL = { crit: "Prioritario", warn: "A revisar", info: "Informativo", ok: "Correcto" };
    const UNIT = { CPU: "%", Conexiones: "%" };
    const TOLERANCE = { CPU: 3, Conexiones: 3 };

    const pick = (s, re) => { const m = re.exec(s || ""); return m ? Number(m[1]) : null; };
    const METRIC = {
        CPU: (m) => pick(m, /media (\d+(?:\.\d+)?)%/),
        Bloqueos: (m) => pick(m, /^(\d+) sesi/) ?? 0,
        Conexiones: (m) => pick(m, /\((\d+)%\)/),
        Espacio: (m) => pick(m, /^(\d+) tablespace/) ?? 0,
        Sesiones: (m) => pick(m, /^(\d+)/),
        Errores: (m) => new Set(String(m || "").match(/ORA[- ]?\d+/g) || []).size,
        Esperas: (m) => pick(m, /con (\d+) sesi/),
        "Operaciones largas": (m) => pick(m, /^(\d+) operaci/) ?? 0,
    };

    function summarize(check) {
        const areas = {};
        for (const f of check.findings || []) {
            const order = ORDER[f.severity] ?? 0;
            const cur = areas[f.area];
            if (!cur || order > cur.order) {
                const fn = METRIC[f.area];
                areas[f.area] = { order, value: fn ? fn(f.message) : null, msg: f.message };
            }
        }
        return {
            id: check.id ?? check.check_id,
            t: new Date(check.created_at || check.check_created_at).getTime(),
            overall: check.overall,
            areas,
        };
    }

    function add(check) {
        const p = summarize(check);
        if (isNaN(p.t) || hist.some((x) => x.id === p.id || x.t === p.t)) return;
        hist.push(p);
        hist.sort((a, b) => a.t - b.t);
        hist = hist.slice(-200);
    }

    async function seed() {
        if (seeded) return;
        seeded = true;
        try {
            const { history } = await api("/health-history?limit=120");
            history.forEach(add);
            return true;
        } catch { seeded = false; }
    }

    const svg = (tag, attrs = {}) => {
        const n = document.createElementNS(NS, tag);
        for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
        return n;
    };

    function series(area) {
        return hist.slice(-MAX_POINTS).map((h) => h.areas[area]?.value).filter((v) => v != null);
    }

    function sparkline(area, cls) {
        const data = series(area);
        const w = 84, h = 26, pad = 3;
        const root = svg("svg", { viewBox: `0 0 ${w} ${h}`, class: `spark spark-${cls}`, "aria-hidden": "true" });
        if (data.length < 2) {
            root.append(svg("line", { x1: pad, y1: h / 2, x2: w - pad, y2: h / 2, class: "spark-line spark-flat" }));
            return root;
        }
        const lo = Math.min(...data), hi = Math.max(...data), span = hi - lo || 1;
        const xy = data.map((v, i) => [
            pad + (i * (w - 2 * pad)) / (data.length - 1),
            h - pad - ((v - lo) / span) * (h - 2 * pad),
        ]);
        const pts = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        root.append(
            svg("polygon", { points: `${pad},${h - pad} ${pts} ${w - pad},${h - pad}`, class: "spark-fill" }),
            svg("polyline", { points: pts, class: "spark-line" }),
            svg("circle", { cx: xy.at(-1)[0], cy: xy.at(-1)[1], r: 2.4, class: "spark-dot" }));
        return root;
    }

    // Compara la última revisión con la anterior (severidad primero, después la métrica).
    function trend(area) {
        if (hist.length < 2) return null;
        const cur = hist.at(-1).areas[area];
        const prev = hist.at(-2).areas[area];
        if (!cur) return null;
        if (!prev) return cur.order >= 1 ? { kind: "new", text: "nuevo" } : null;
        if (cur.order > prev.order) return prev.order === 0 ? { kind: "new", text: "nuevo" } : { kind: "up", text: "empeora" };
        if (cur.order < prev.order) return { kind: "down", text: "mejora" };
        if (cur.value != null && prev.value != null) {
            const d = cur.value - prev.value;
            if (Math.abs(d) > (TOLERANCE[area] ?? 0)) {
                const unit = UNIT[area] || "";
                const txt = `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(unit ? 0 : 0)}${unit}`;
                return { kind: d > 0 ? "up" : "down", text: txt };
            }
        }
        return { kind: "flat", text: "estable" };
    }

    function trendBadge(area) {
        const t = trend(area);
        if (!t) return null;
        const arrow = { up: "▲", down: "▼", new: "●", flat: "=" }[t.kind];
        return el("span", { class: `trend trend-${t.kind}`, title: "Respecto a la revisión anterior", text: `${arrow} ${t.text}` });
    }

    // Una cápsula por revisión reciente, coloreada con el estado global de ese momento.
    function timeline() {
        const last = hist.slice(-MAX_POINTS);
        if (!last.length) return null;
        const bars = last.map((h) => el("span", {
            class: `tl-bar tl-${CLS[h.overall] || "ok"}`,
            title: `${new Date(h.t).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" })} · ${LABEL[CLS[h.overall]] || h.overall}`,
        }));
        return el("div", { class: "timeline", "aria-label": "Estado global de las últimas revisiones" },
            el("span", { class: "tl-cap", text: `Últimas ${last.length} revisiones` }),
            el("div", { class: "tl-bars" }, bars));
    }

    const getFilter = () => filter;
    const setFilter = (f) => { filter = filter === f ? null : f; return filter; };

    return { seed, add, sparkline, trendBadge, timeline, getFilter, setFilter, LABEL };
})();
