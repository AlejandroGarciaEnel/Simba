// Panel estilo Grafana de sesiones inactivas y bloqueadas (JS vanilla + SVG, sin dependencias).
// Las series se construyen con el histórico de revisiones y se amplían con cada revisión nueva.
const SessionsDash = (() => {
    const T = { inactive: { warn: 20, crit: 50 }, wait: { warn: 30, crit: 300 } };
    const NS = "http://www.w3.org/2000/svg";
    let points = []; // { t: ms, inactive, blocked, blockers, wait }
    let seeded = false;
    let current = null;

    const num = (s, re) => { const m = re.exec(s || ""); return m ? Number(m[1]) : 0; };

    function toPoint(check) {
        const f = check.findings || [];
        const ses = f.find((x) => x.area === "Sesiones");
        const blo = f.find((x) => x.area === "Bloqueos");
        const bm = blo?.message || "";
        return {
            t: new Date(check.created_at || check.check_created_at).getTime(),
            inactive: num(ses?.message, /^(\d+)/),
            blocked: num(bm, /^(\d+) sesi/),
            blockers: num(bm, /por (\d+) sesi/),
            wait: num(bm, /mayor es de (\d+) s/),
        };
    }

    function addPoint(p) {
        if (isNaN(p.t) || points.some((x) => x.t === p.t)) return;
        points.push(p);
        points.sort((a, b) => a.t - b.t);
        points = points.slice(-1000);
    }

    async function seed() {
        if (seeded) return;
        seeded = true;
        try {
            const { history } = await api("/health-history?limit=200");
            history.forEach((h) => addPoint(toPoint(h)));
        } catch { seeded = false; }
    }

    const level = (v, th) => (v >= th.crit ? "crit" : v >= th.warn ? "warn" : "ok");
    const svg = (tag, attrs = {}, ...kids) => {
        const n = document.createElementNS(NS, tag);
        for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
        kids.forEach((k) => n.append(k));
        return n;
    };
    const fmtTime = (t) => new Date(t).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });

    const TONE = {
        ok: { text: "text-emerald-400", ring: "ring-emerald-500/30", glow: "shadow-emerald-500/10", hex: "#34d399", label: "OK" },
        warn: { text: "text-amber-400", ring: "ring-amber-500/40", glow: "shadow-amber-500/20", hex: "#fbbf24", label: "Aviso" },
        crit: { text: "text-rose-400", ring: "ring-rose-500/50", glow: "shadow-rose-500/30", hex: "#fb7185", label: "Crítico" },
    };
    const PANEL = "rounded-2xl bg-gradient-to-br from-slate-800/90 to-slate-900/90 ring-1 ring-white/10 shadow-xl backdrop-blur p-4 min-w-0";

    function sparkline(key, tone) {
        const data = points.map((p) => p[key]);
        const w = 200, h = 44;
        const root = svg("svg", { viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none", class: "w-full h-14 mt-3 block" });
        if (data.length < 2) return root;
        const max = Math.max(...data, 1);
        const xy = data.map((v, i) => [(i / (data.length - 1)) * w, h - 3 - (v / max) * (h - 8)]);
        const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        const id = `sp-${key}`;
        root.append(
            svg("defs", {}, svg("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 },
                svg("stop", { offset: "0%", "stop-color": tone.hex, "stop-opacity": ".45" }),
                svg("stop", { offset: "100%", "stop-color": tone.hex, "stop-opacity": "0" }))),
            svg("path", { d: `${line} L${w},${h} L0,${h} Z`, fill: `url(#${id})` }),
            svg("path", { d: line, fill: "none", stroke: tone.hex, "stroke-width": 2, "vector-effect": "non-scaling-stroke", "stroke-linejoin": "round" }));
        return root;
    }

    function stat(title, icon, value, unit, cls, key, hint) {
        const tone = TONE[cls];
        return el("section", { class: `${PANEL} ring-1 ${tone.ring} shadow-lg ${tone.glow} transition hover:-translate-y-0.5` },
            el("div", { class: "flex items-center justify-between" },
                el("h4", { class: "text-xs font-medium uppercase tracking-wider text-slate-400", text: title }),
                el("span", { class: "text-lg", text: icon })),
            el("div", { class: `mt-2 flex items-baseline gap-1 text-6xl font-semibold tabular-nums ${tone.text}` },
                Number(value).toLocaleString("es-ES"), unit ? el("small", { class: "text-lg font-normal text-slate-500", text: unit }) : null),
            el("div", { class: "mt-1 flex items-center justify-between text-xs text-slate-500" },
                el("span", { text: hint }),
                el("span", { class: `rounded-full px-2 py-0.5 font-medium bg-white/5 ${tone.text}`, text: tone.label })),
            sparkline(key, tone));
    }

    const dot = (color) => el("i", { class: "inline-block h-2.5 w-2.5 rounded-sm", style: `background:${color}` });

    // ---- Ventana temporal compartida por las gráficas (zoom con rueda, arrastrar para desplazar) ----
    const win = { from: null, to: null }; // null = todo el rango
    const fullRange = () => [points[0].t, Math.max(points[points.length - 1].t, points[0].t + 60000)];
    const curRange = () => { const [a, b] = fullRange(); return [win.from ?? a, win.to ?? b]; };
    const setWindow = (from, to) => {
        const [a, b] = fullRange();
        const span = Math.max(to - from, 5 * 60000);
        if (span >= b - a) { win.from = win.to = null; return; }
        from = Math.min(Math.max(from, a), b - span);
        win.from = from; win.to = from + span;
    };
    const RANGES = [["1 h", 3600e3], ["4 h", 4 * 3600e3], ["8 h", 8 * 3600e3], ["Jornada", "day"], ["Todo", null]];
    function applyRange(v) {
        const [, b] = fullRange();
        if (v == null) win.from = win.to = null;
        else if (v === "day") { const d = new Date(b); d.setHours(0, 0, 0, 0); setWindow(d.getTime(), b); }
        else setWindow(b - v, b);
        renderCharts();
    }
    const geom = { W: 900, H: 340, m: { l: 52, r: 16, t: 14, b: 30 } };

    function timeSeries(id, title, series, thresholds) {
        const { W, H, m } = geom;
        const iw = W - m.l - m.r, ih = H - m.t - m.b;
        const box = el("section", { class: PANEL }, el("h4", { class: "mb-2 text-base font-medium text-slate-200", text: title }));
        if (points.length < 2) {
            box.append(el("p", { class: "py-16 text-center text-sm text-slate-500", text: "Recogiendo datos… (hacen falta al menos 2 revisiones)" }));
            return box;
        }
        const [t0, t1] = curRange();
        const vis = points.filter((p) => p.t >= t0 - (t1 - t0) * 0.02 && p.t <= t1 + (t1 - t0) * 0.02);
        const maxV = Math.max(1, ...series.flatMap((s) => vis.map((p) => p[s.key])), ...(thresholds || []).map((x) => x.v));
        const top = Math.max(4, Math.ceil(maxV * 1.1));
        const X = (t) => m.l + ((t - t0) / (t1 - t0 || 1)) * iw;
        const Y = (v) => m.t + ih - (v / top) * ih;
        const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "block h-auto w-full cursor-grab select-none", "data-chart": id });
        const clip = `clip-${id}`;
        root.append(svg("defs", {}, svg("clipPath", { id: clip }, svg("rect", { x: m.l, y: m.t, width: iw, height: ih }))));
        for (let i = 0; i <= 4; i++) {
            const v = (top / 4) * i, y = Y(v);
            root.append(svg("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: "stroke-white/10" }));
            const lab = svg("text", { x: m.l - 8, y: y + 4, class: "fill-slate-500", "font-size": 12, "text-anchor": "end" });
            lab.textContent = Math.round(v);
            root.append(lab);
        }
        for (let i = 0; i <= 6; i++) {
            const t = t0 + ((t1 - t0) / 6) * i;
            const lab = svg("text", { x: X(t), y: H - 8, class: "fill-slate-500", "font-size": 12, "text-anchor": i === 0 ? "start" : i === 6 ? "end" : "middle" });
            lab.textContent = fmtTime(t);
            root.append(lab);
        }
        const plot = svg("g", { "clip-path": `url(#${clip})` });
        (thresholds || []).forEach((th) => plot.append(
            svg("line", { x1: m.l, x2: W - m.r, y1: Y(th.v), y2: Y(th.v), stroke: TONE[th.cls].hex, "stroke-dasharray": "6 5", "stroke-width": 1 })));
        series.forEach((s) => {
            const d = points.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p[s.key]).toFixed(1)}`).join(" ");
            const gid = `ts-${id}-${s.key}`;
            root.querySelector("defs").append(svg("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 },
                svg("stop", { offset: "0%", "stop-color": s.color, "stop-opacity": ".35" }),
                svg("stop", { offset: "100%", "stop-color": s.color, "stop-opacity": "0" })));
            plot.append(svg("path", { d: `${d} L${X(points[points.length - 1].t)},${Y(0)} L${X(points[0].t)},${Y(0)} Z`, fill: `url(#${gid})` }));
            plot.append(svg("path", { d, fill: "none", stroke: s.color, "stroke-width": 2.4, "stroke-linejoin": "round" }));
            points.forEach((p) => plot.append(svg("circle", { cx: X(p.t), cy: Y(p[s.key]), r: 3, fill: s.color })));
        });
        root.append(plot);
        const cursor = svg("line", { y1: m.t, y2: m.t + ih, class: "stroke-white/40", visibility: "hidden" });
        root.append(cursor);
        const tip = el("div", { class: "pointer-events-none absolute top-2 z-10 min-w-44 rounded-lg bg-slate-950/95 px-3 py-2 text-xs text-slate-200 shadow-xl ring-1 ring-white/10", hidden: true });
        root.addEventListener("mousemove", (e) => {
            if (drag) return;
            const r = root.getBoundingClientRect();
            const x = ((e.clientX - r.left) / r.width) * W;
            const p = vis.length ? vis.reduce((a, b) => (Math.abs(X(b.t) - x) < Math.abs(X(a.t) - x) ? b : a)) : null;
            if (!p) return;
            cursor.setAttribute("x1", X(p.t)); cursor.setAttribute("x2", X(p.t));
            cursor.setAttribute("visibility", "visible");
            tip.hidden = false;
            tip.style.left = `${Math.max(0, Math.min(e.clientX - r.left + 14, r.width - 190))}px`;
            tip.replaceChildren(el("b", { class: "mb-1 block text-slate-100", text: new Date(p.t).toLocaleString("es-ES") }),
                ...series.map((s) => el("div", { class: "flex items-center gap-1.5" }, dot(s.color), `${s.label}: ${p[s.key]}`)));
        });
        root.addEventListener("mouseleave", () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; });
        box.append(el("div", { class: "relative" }, root, tip),
            el("div", { class: "mt-2 flex gap-4 text-xs text-slate-400" }, series.map((s) => el("span", { class: "flex items-center gap-1.5" }, dot(s.color), s.label))));
        return box;
    }

    // Arrastrar = desplazar, doble clic = ver todo.
    let drag = null;
    function bindInteractions(host) {
        host.addEventListener("mousedown", (e) => {
            const svgEl = e.target.closest?.("svg[data-chart]");
            if (!svgEl || e.button !== 0) return;
            const [t0, t1] = curRange();
            drag = { x: e.clientX, t0, t1, w: svgEl.getBoundingClientRect().width };
        });
        host.addEventListener("dblclick", (e) => { if (e.target.closest?.("svg[data-chart]")) applyRange(null); });
        window.addEventListener("mousemove", (e) => {
            if (!drag) return;
            const dt = -((e.clientX - drag.x) / drag.w) * (geom.W / (geom.W - geom.m.l - geom.m.r)) * (drag.t1 - drag.t0);
            setWindow(drag.t0 + dt, drag.t1 + dt);
            scheduleCharts();
        });
        window.addEventListener("mouseup", () => { drag = null; });
    }
    let raf = 0;
    const scheduleCharts = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(renderCharts); };

    function renderCharts() {
        const box = document.getElementById("sessions-charts");
        if (!box || !points.length) return;
        const [t0, t1] = curRange();
        const label = win.from == null ? "Todo el histórico" : `${new Date(t0).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" })} → ${fmtTime(t1)}`;
        box.replaceChildren(
            el("div", { class: "flex flex-wrap items-center gap-2" },
                ...RANGES.map(([txt, v]) => el("button", {
                    class: "rounded-lg bg-white/5 px-3 py-1.5 text-xs font-medium text-slate-200 ring-1 ring-white/10 transition hover:bg-indigo-500/30",
                    text: txt, onclick: () => applyRange(v) })),
                el("span", { class: "ml-auto text-xs text-slate-400", text: `${label} · arrastra para mover · doble clic = todo` })),
            timeSeries("inactive", "Sesiones inactivas > 30 min", [{ key: "inactive", label: "Inactivas", color: "#60a5fa" }],
                [{ v: T.inactive.warn, cls: "warn" }]),
            timeSeries("blocked", "Sesiones bloqueadas y bloqueantes", [
                { key: "blocked", label: "Bloqueadas", color: "#fb7185" },
                { key: "blockers", label: "Bloqueantes", color: "#fbbf24" }]));
    }

    // El listado completo vive en su propia página (/inactivas), solo para dba/administrador.
    function inactiveLink() {
        const allowed = typeof can === "function" && can("dba");
        return el("section", { class: `${PANEL} flex flex-wrap items-center gap-4` },
            el("div", {},
                el("h4", { class: "text-base font-medium text-slate-200", text: "Listado completo de sesiones inactivas" }),
                el("p", { class: "text-sm text-slate-400", text: "Todas las sesiones inactivas > 30 min de ambos nodos, con filtros, orden y exportación." })),
            allowed
                ? el("a", { href: "/inactivas", target: "_blank", rel: "noopener",
                        class: "ml-auto rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white shadow transition hover:bg-indigo-400", text: "Abrir listado ↗" })
                : el("span", { class: "ml-auto text-xs text-slate-500", text: "Requiere rol dba" }));
    }
    function blockersTable() {
        const blo = (current?.findings || []).find((f) => f.area === "Bloqueos");
        const rows = blo?.details || [];
        const box = el("section", { class: PANEL }, el("h4", { class: "mb-3 text-sm font-medium text-slate-200", text: "Sesiones bloqueantes (última revisión)" }));
        if (!rows.length) {
            box.append(el("p", { class: "rounded-xl bg-emerald-500/10 py-8 text-center text-sm text-emerald-300", text: "✔ No hay sesiones bloqueadas" }));
            return box;
        }
        const cols = [
            ["Sesión", (d) => `inst ${d.instancia} · ${d.sid_serial}`],
            ["Usuario", (d) => d.usuario],
            ["Origen", (d) => [d.maquina, d.programa].filter(Boolean).join(" · ")],
            ["Estado", (d) => d.estado + (d.inactiva_s != null ? ` ${fmtSeconds(d.inactiva_s)}` : "")],
            ["Bloquea a", (d) => d.bloquea_a],
            ["Espera máx.", (d) => fmtSeconds(d.espera_max_s)],
            ["Objeto", (d) => d.objeto || "—"],
        ];
        box.append(el("div", { class: "overflow-x-auto" }, el("table", { class: "w-full text-left text-sm" },
            el("thead", {}, el("tr", { class: "text-xs uppercase tracking-wider text-slate-500" }, cols.map(([h]) => el("th", { class: "px-3 py-2 font-medium", text: h })))),
            el("tbody", { class: "divide-y divide-white/5" }, rows.map((d) =>
                el("tr", { class: `transition hover:bg-white/5 ${TONE[level(d.espera_max_s, T.wait)].text}` },
                    cols.map(([, fn]) => el("td", { class: "px-3 py-2 text-slate-200", text: fn(d) }))))))));
        return box;
    }

    function render() {
        const host = document.getElementById("sessions-dash");
        if (!host || !points.length) return;
        const last = points[points.length - 1];
        host.replaceChildren(
            el("header", { class: "flex flex-wrap items-center justify-between gap-2" },
                el("h3", { class: "text-lg font-semibold text-slate-100", text: "Sesiones · inactivas y bloqueadas" }),
                el("span", { class: "inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300 ring-1 ring-emerald-500/30" },
                    el("span", { class: "h-2 w-2 animate-pulse rounded-full bg-emerald-400" }),
                    `En vivo · ${fmtTime(last.t)}`)),
            el("div", { class: "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" },
                stat("Inactivas > 30 min", "😴", last.inactive, "", level(last.inactive, T.inactive), "inactive", `Aviso a partir de ${T.inactive.warn}`),
                stat("Bloqueadas", "⛔", last.blocked, "", last.blocked ? "warn" : "ok", "blocked", "Esperando a un bloqueante"),
                stat("Bloqueantes", "🔒", last.blockers, "", last.blockers ? "warn" : "ok", "blockers", "Raíz de los bloqueos"),
                stat("Espera máxima", "⏱️", last.wait, "s", level(last.wait, T.wait), "wait", `Aviso ${T.wait.warn} s · crítico ${T.wait.crit} s`)),
            el("div", { id: "sessions-charts", class: "grid grid-cols-1 gap-4" }),
            inactiveLink(),
            blockersTable(),
            el("p", { class: "text-xs text-slate-500", text: `${points.length} muestras · última revisión ${fmtDate(new Date(last.t).toISOString())} · ` +
                "se actualiza sola con cada revisión (caché de Oracle)" }));
        renderCharts();
    }

    async function update(check) {
        if (check) { current = check; addPoint(toPoint(check)); }
        await seed();
        render();
    }

    bindInteractions(document.getElementById("sessions-dash"));
    return { update, render };
})();
