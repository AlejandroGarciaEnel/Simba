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
        info: { text: "text-sky-400", ring: "ring-sky-500/30", glow: "shadow-sky-500/10", hex: "#38bdf8", label: "Habitual" },
    };
    // El rojo se reserva para lo anómalo: las inactivas se comparan con su mediana histórica, no con un umbral fijo.
    const median = (a) => { const v = [...a].sort((x, y) => x - y); return v.length ? v[v.length >> 1] : 0; };
    function inactiveStatus(v) {
        const med = median(points.slice(0, -1).map((p) => p.inactive).slice(-96));
        if (v < T.inactive.warn) return { cls: "ok", med, pct: 0, label: "OK" };
        const r = v / (med || 1), pct = Math.round((r - 1) * 100);
        if (r >= 1.5) return { cls: "crit", med, pct, label: "Anómalo" };
        if (r >= 1.15) return { cls: "warn", med, pct, label: "Por encima" };
        return { cls: "info", med, pct, label: "Habitual" };
    }
    const PANEL = "rounded-2xl bg-gradient-to-br from-slate-800/90 to-slate-900/90 ring-1 ring-white/10 shadow-xl backdrop-blur p-4 min-w-0";

    function sparkline(key, tone) {
        const data = points.map((p) => p[key]);
        const w = 200, h = 44;
        const root = svg("svg", { viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none", class: "w-full h-10 mt-2 block" });
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

    function stat(title, icon, value, unit, cls, key, hint, label) {
        const tone = TONE[cls];
        return el("section", { class: `${PANEL.replace("p-4", "p-3")} ring-1 ${tone.ring} shadow-lg ${tone.glow} transition hover:-translate-y-0.5` },
            el("div", { class: "flex items-center justify-between" },
                el("h4", { class: "text-xs font-medium uppercase tracking-wider text-slate-400", text: title }),
                el("span", { class: "text-lg", text: icon })),
            el("div", { class: `mt-1 flex items-baseline gap-1 text-3xl font-semibold tabular-nums ${tone.text}` },
                Number(value).toLocaleString("es-ES"), unit ? el("small", { class: "text-lg font-normal text-slate-500", text: unit }) : null),
            el("div", { class: "mt-1 flex items-center justify-between text-xs text-slate-500" },
                el("span", { text: hint }),
                el("span", { class: `rounded-full px-2 py-0.5 font-medium bg-white/5 ${tone.text}`, text: label || tone.label })),
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
    const geom = { W: 900, H: 250, m: { l: 52, r: 16, t: 14, b: 30 } };

    function timeSeries(id, title, series, thresholds, opts = {}) {
        const sub = opts.sub;
        const { W, H, m } = geom;
        const iw = W - m.l - m.r, ih = H - m.t - m.b;
        const box = el("section", { class: `${PANEL}${opts.span ? " xl:col-span-2" : ""}` },
            el("div", { class: "mb-2 flex flex-wrap items-baseline gap-x-3" },
                el("h4", { class: "text-sm font-semibold text-slate-200", text: title }),
                sub ? el("span", { class: "text-xs text-slate-500", text: sub }) : null));
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
        if (opts.band) {
            // Franjas rojas: periodos con bloqueos activos.
            points.forEach((p, i) => {
                if (!p[opts.band]) return;
                const next = points[i + 1]?.t ?? p.t + 60000;
                plot.append(svg("rect", { x: X(p.t), y: m.t, width: Math.max(2, X(next) - X(p.t)), height: ih, fill: "#fb7185", "fill-opacity": ".10" }));
            });
        }
        series.forEach((s) => {
            const d = points.map((p, i) => {
                const x = X(p.t).toFixed(1), y = Y(p[s.key]).toFixed(1);
                if (!i) return `M${x},${y}`;
                return opts.step ? `H${x} V${y}` : `L${x},${y}`;
            }).join(" ");
            const gid = `ts-${id}-${s.key}`;
            root.querySelector("defs").append(svg("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 },
                svg("stop", { offset: "0%", "stop-color": s.color, "stop-opacity": ".35" }),
                svg("stop", { offset: "100%", "stop-color": s.color, "stop-opacity": "0" })));
            plot.append(svg("path", { d: `${d} L${X(points[points.length - 1].t)},${Y(0)} L${X(points[0].t)},${Y(0)} Z`, fill: `url(#${gid})` }));
            plot.append(svg("path", { d, fill: "none", stroke: s.color, "stroke-width": 2.4, "stroke-linejoin": "round" }));
            if (vis.length <= 60) points.forEach((p) => plot.append(svg("circle", { cx: X(p.t), cy: Y(p[s.key]), r: 3, fill: s.color })));
            else {
                const last = points[points.length - 1];
                plot.append(svg("circle", { cx: X(last.t), cy: Y(last[s.key]), r: 4, fill: s.color, stroke: "#0f172a", "stroke-width": 1.5 }));
            }
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
                ...series.map((s) => el("div", { class: "flex items-center gap-1.5" }, dot(s.color), `${s.label}: ${p[s.key]}${opts.unit || ""}`)));
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
            const ovEl = e.target.closest?.("svg[data-ov]");
            if (ovEl && e.button === 0) { ovPointerDown(e, ovEl); return; }
            const svgEl = e.target.closest?.("svg[data-chart]");
            if (!svgEl || e.button !== 0) return;
            const [t0, t1] = curRange();
            drag = { x: e.clientX, t0, t1, w: svgEl.getBoundingClientRect().width };
        });
        host.addEventListener("dblclick", (e) => { if (e.target.closest?.("svg[data-chart]")) applyRange(null); });
        host.addEventListener("wheel", (e) => {
            const svgEl = e.target.closest?.("svg[data-chart]");
            if (!svgEl || !points.length) return;
            e.preventDefault();
            const r = svgEl.getBoundingClientRect(), { W, m } = geom;
            const frac = Math.min(1, Math.max(0, (((e.clientX - r.left) / r.width) * W - m.l) / (W - m.l - m.r)));
            const [t0, t1] = curRange(), k = e.deltaY < 0 ? 0.8 : 1.25, span = (t1 - t0) * k;
            const c = t0 + frac * (t1 - t0);
            setWindow(c - frac * span, c + (1 - frac) * span);
            scheduleCharts();
        }, { passive: false });
        window.addEventListener("mousemove", (e) => {
            if (ov) { ovPointerMove(e); return; }
            if (!drag) return;
            const dt = -((e.clientX - drag.x) / drag.w) * (geom.W / (geom.W - geom.m.l - geom.m.r)) * (drag.t1 - drag.t0);
            setWindow(drag.t0 + dt, drag.t1 + dt);
            scheduleCharts();
        });
        window.addEventListener("mouseup", () => { drag = null; ov = null; });
    }
    // Minimapa: todo el histórico con la ventana visible; se arrastra, se estiran los bordes o se hace clic para centrar.
    const OV = { W: 900, H: 54 };
    let ov = null;
    function overview() {
        const { W, H } = OV;
        const [a, b] = fullRange(), [t0, t1] = curRange();
        const X = (t) => ((t - a) / (b - a || 1)) * W;
        const max = Math.max(1, ...points.map((p) => p.blocked));
        const Y = (v) => H - 4 - (v / max) * (H - 12);
        const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "block h-14 w-full cursor-pointer select-none", "data-ov": 1 });
        const d = points.map((p, i) => (i ? `H${X(p.t).toFixed(1)} V${Y(p.blocked).toFixed(1)}` : `M${X(p.t).toFixed(1)},${Y(p.blocked).toFixed(1)}`)).join(" ");
        root.append(svg("rect", { x: 0, y: 0, width: W, height: H, rx: 8, class: "ov-bg" }),
            svg("path", { d: `${d} V${H} H${X(points[0].t)} Z`, fill: "#fb7185", "fill-opacity": ".35" }),
            svg("path", { d, fill: "none", stroke: "#fb7185", "stroke-width": 1.5 }));
        const x0 = X(t0), x1 = X(t1);
        root.append(svg("rect", { x: 0, y: 0, width: Math.max(0, x0), height: H, class: "ov-shade" }),
            svg("rect", { x: x1, y: 0, width: Math.max(0, W - x1), height: H, class: "ov-shade" }),
            svg("rect", { x: x0, y: 1, width: Math.max(4, x1 - x0), height: H - 2, fill: "none", stroke: "#818cf8", "stroke-width": 2, rx: 4 }),
            svg("rect", { x: x0 - 3, y: H / 2 - 10, width: 6, height: 20, rx: 3, fill: "#818cf8" }),
            svg("rect", { x: x1 - 3, y: H / 2 - 10, width: 6, height: 20, rx: 3, fill: "#818cf8" }));
        return el("div", { class: "w-full" }, root);
    }
    function ovPointerDown(e, svgEl) {
        const r = svgEl.getBoundingClientRect();
        const [a, b] = fullRange(), [t0, t1] = curRange();
        const span = b - a, x = ((e.clientX - r.left) / r.width) * OV.W, edge = 10;
        const px = (t) => ((t - a) / span) * OV.W;
        let mode = "move";
        if (Math.abs(x - px(t0)) < edge) mode = "l";
        else if (Math.abs(x - px(t1)) < edge) mode = "r";
        else if (x < px(t0) || x > px(t1)) { const c = a + (x / OV.W) * span, h = (t1 - t0) / 2; setWindow(c - h, c + h); renderCharts(); }
        const [n0, n1] = curRange();
        ov = { mode, x: e.clientX, w: r.width, span, t0: n0, t1: n1 };
    }
    function ovPointerMove(e) {
        const dt = ((e.clientX - ov.x) / ov.w) * ov.span;
        if (ov.mode === "move") setWindow(ov.t0 + dt, ov.t1 + dt);
        else if (ov.mode === "l") setWindow(Math.min(ov.t0 + dt, ov.t1 - 5 * 60000), ov.t1);
        else setWindow(ov.t0, Math.max(ov.t1 + dt, ov.t0 + 5 * 60000));
        scheduleCharts();
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
                el("span", { class: "ml-auto text-xs text-slate-400", text: `${label} · rueda = zoom · arrastra para mover · doble clic = todo` })),
            overview(),
            timeSeries("inactive", "Sesiones inactivas > 30 min", [{ key: "inactive", label: "Inactivas", color: "#60a5fa" }],
                [{ v: median(points.map((p) => p.inactive)), cls: "info" }], { sub: "línea discontinua = mediana habitual" }),
            timeSeries("blocked", "Sesiones bloqueadas y bloqueantes", [
                { key: "blocked", label: "Bloqueadas", color: "#fb7185" },
                { key: "blockers", label: "Bloqueantes", color: "#fbbf24" }], null, { step: true, band: "blocked", sub: "franja roja = bloqueo activo" }),
            timeSeries("wait", "Espera máxima de una sesión bloqueada (s)", [{ key: "wait", label: "Espera máx.", color: "#c084fc" }],
                [{ v: T.wait.warn, cls: "warn" }, { v: T.wait.crit, cls: "crit" }], { step: true, band: "blocked", unit: " s", span: true, sub: "aviso 30 s · crítico 300 s" }));
    }

    // El listado completo vive en su propia página (/inactivas), solo para dba/administrador.
    function inactiveLink() {
        const allowed = typeof can === "function" && can("dba");
        return el("section", { class: `${PANEL} flex flex-wrap items-center gap-4` },
            el("div", {},
                el("h4", { class: "text-base font-medium text-slate-200", text: "Listado completo de sesiones inactivas" }),
                el("p", { class: "text-sm text-slate-400", text: "Todas las sesiones inactivas > 30 min de ambos nodos, con filtros, orden y exportación." })),
            allowed
                ? el("a", { href: "/inactivas",
                        class: "ml-auto rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white shadow transition hover:bg-indigo-400", text: "Abrir listado →" })
                : el("span", { class: "ml-auto text-xs text-slate-500", text: "Requiere rol dba" }));
    }
    let blocking = null;
    const openRoots = new Map(); // clave de raíz -> abierta (se conserva entre refrescos)
    const shown = new Map(); // clave de raíz -> víctimas visibles
    let rootsShown = 5;
    const VICTIMS_STEP = 10, ROOTS_STEP = 5;

    function topCounts(list, fn, n = 3) {
        const m = new Map();
        list.forEach((x) => { const k = fn(x); if (k) m.set(k, (m.get(k) || 0) + 1); });
        return [...m].sort((a, b) => b[1] - a[1]).slice(0, n);
    }

    function victimsTable(r, victims, k) {
        const limit = shown.get(k) || VICTIMS_STEP;
        const rows = victims.slice(0, limit);
        const wrap = el("div", { class: "overflow-x-auto px-4 pb-4" });
        const sum = topCounts(victims, (v) => v.evento).concat(topCounts(victims, (v) => v.sql_id && `SQL ${v.sql_id}`));
        if (victims.length > VICTIMS_STEP) {
            wrap.append(el("div", { class: "mb-2 flex flex-wrap gap-1 text-xs text-slate-400" }, el("span", { text: "Resumen:" }),
                sum.map(([t, n]) => el("span", { class: "rounded-full bg-white/10 px-2 py-0.5 text-slate-200", text: `${t} × ${n}` }))));
        }
        wrap.append(el("table", { class: "w-full text-left text-xs" },
            el("thead", {}, el("tr", { class: "uppercase tracking-wider text-slate-500" },
                ["Sesión bloqueada", "Usuario", "Origen", "Espera", "Evento", "Vía", "SQL"].map((h) => el("th", { class: "px-2 py-1 font-medium", text: h })))),
            el("tbody", { class: "divide-y divide-white/5" }, rows.map((v) => el("tr", { class: "text-slate-200" },
                el("td", { class: "whitespace-nowrap px-2 py-1 font-mono", text: `inst ${v.instancia} · ${v.sid},${v.serial}` }),
                el("td", { class: "whitespace-nowrap px-2 py-1", text: v.usuario || "—" }),
                el("td", { class: "max-w-[14rem] truncate whitespace-nowrap px-2 py-1", title: [v.maquina, v.programa].filter(Boolean).join(" · "), text: [v.maquina, v.programa].filter(Boolean).join(" · ") }),
                el("td", { class: `whitespace-nowrap px-2 py-1 ${TONE[level(v.segundos_espera, T.wait)].text}`, text: fmtSeconds(v.segundos_espera) }),
                el("td", { class: "max-w-[12rem] truncate whitespace-nowrap px-2 py-1", title: v.evento || "", text: v.evento || "" }),
                el("td", { class: "whitespace-nowrap px-2 py-1", text: v.sid_bloqueante === r.sid && v.inst_bloqueante === r.instancia ? "directo" : `SID ${v.sid_bloqueante}` }),
                el("td", { class: "max-w-xs truncate px-2 py-1 font-mono", title: v.sql_texto || "", text: v.sql_id ? `${v.sql_id} ${v.sql_texto || ""}` : "—" }))))));
        if (victims.length > limit) {
            wrap.append(el("button", { class: "mt-2 rounded-lg bg-white/10 px-3 py-1 text-xs text-slate-200 hover:bg-white/20",
                text: `Mostrar ${Math.min(VICTIMS_STEP, victims.length - limit)} más (${victims.length - limit} ocultas)`,
                onclick: () => { shown.set(k, limit + VICTIMS_STEP); render(); } }));
        }
        return wrap;
    }

    function chainsPanel() {
        const total = blocking.waiting.length;
        const box = el("section", { class: PANEL }, el("div", { class: "mb-3 flex flex-wrap items-center justify-between gap-2" },
            el("h4", { class: "text-sm font-medium text-slate-200", text: `🔗 Cadenas de bloqueo · ${blocking.roots.length} bloqueante(s), ${total} bloqueada(s)` }),
            el("span", { class: "text-xs text-slate-500", text: `Actualizado ${blocking.taken_at ? blocking.taken_at.slice(11) : ""}` })));
        const key = (i, sid) => `${i}:${sid}`;
        const byRoot = new Map();
        blocking.waiting.forEach((w) => {
            const k = key(w.inst_raiz ?? w.inst_bloqueante, w.sid_raiz ?? w.sid_bloqueante);
            (byRoot.get(k) || byRoot.set(k, []).get(k)).push(w);
        });
        const chip = (t, cls = "bg-white/10 text-slate-200") => el("span", { class: `rounded-full px-2 py-0.5 text-xs ${cls}`, text: t });
        const roots = [...blocking.roots].sort((a, b) => b.sesiones_bloqueadas - a.sesiones_bloqueadas || b.segundos_espera - a.segundos_espera);
        roots.slice(0, rootsShown).forEach((r, idx) => {
            const k = key(r.instancia, r.sid);
            const victims = (byRoot.get(k) || []).sort((a, b) => b.segundos_espera - a.segundos_espera);
            const sev = level(r.segundos_espera, T.wait);
            const isOpen = openRoots.has(k) ? openRoots.get(k) : (idx === 0 && roots.length > 1) || (roots.length === 1 && victims.length <= 20);
            const card = el("details", { class: "mb-3 rounded-xl bg-slate-950/50 ring-1 ring-white/10", open: isOpen },
                el("summary", { class: "flex cursor-pointer flex-wrap items-center gap-2 px-4 py-3" },
                    el("span", { class: `text-lg ${TONE[sev].text}`, text: "🔒" }),
                    el("b", { class: "text-slate-100", text: `${r.usuario || "?"} · inst ${r.instancia} · SID ${r.sid},${r.serial}` }),
                    chip(`bloquea a ${r.sesiones_bloqueadas}`, "bg-rose-500/20 text-rose-300"),
                    chip(`espera máx. ${fmtSeconds(r.segundos_espera)}`, "bg-amber-500/20 text-amber-300"),
                    chip(r.estado === "ACTIVE" ? "ACTIVA" : `inactiva ${fmtSeconds(r.segundos_ultima_llamada)}`),
                    r.objeto ? chip(r.objeto, "bg-indigo-500/20 text-indigo-300") : null),
                el("div", { class: "grid gap-1 px-4 pb-3 text-xs text-slate-400" },
                    el("div", { text: `Origen: ${[r.maquina, r.programa, r.modulo].filter(Boolean).join(" · ") || "—"}` }),
                    r.sql_id ? el("div", { class: "font-mono", text: `SQL ${r.sql_id} (${r.tipo_sql}): ${r.sql_texto || "—"}` }) : null),
                victims.length ? victimsTable(r, victims, k) : null);
            card.addEventListener("toggle", () => openRoots.set(k, card.open));
            box.append(card);
        });
        if (roots.length > rootsShown) {
            box.append(el("button", { class: "rounded-lg bg-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/20",
                text: `Mostrar ${Math.min(ROOTS_STEP, roots.length - rootsShown)} bloqueantes más (${roots.length - rootsShown} ocultos)`,
                onclick: () => { rootsShown += ROOTS_STEP; render(); } }));
        }
        return box;
    }

    function blockersTable() {
        if (blocking?.roots?.length) return chainsPanel();
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
        const ina = inactiveStatus(last.inactive);
        host.replaceChildren(
            el("header", { class: "flex flex-wrap items-center justify-between gap-2" },
                el("h3", { class: "text-lg font-semibold text-slate-100", text: "Sesiones · inactivas y bloqueadas" }),
                el("span", { class: "inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300 ring-1 ring-emerald-500/30" },
                    el("span", { class: "h-2 w-2 animate-pulse rounded-full bg-emerald-400" }),
                    `En vivo · ${fmtTime(last.t)}`)),
            el("div", { class: "grid grid-cols-2 gap-3 lg:grid-cols-4" },
                stat("Inactivas > 30 min", "😴", last.inactive, "", ina.cls, "inactive",
                    ina.cls === "ok" ? `Aviso a partir de ${T.inactive.warn}` : `Habitual ~${ina.med} · ${ina.pct >= 0 ? "+" : ""}${ina.pct}%`, ina.label),
                stat("Bloqueadas", "⛔", last.blocked, "", last.blocked ? "warn" : "ok", "blocked", "Esperando a un bloqueante"),
                stat("Bloqueantes", "🔒", last.blockers, "", last.blockers ? "warn" : "ok", "blockers", "Raíz de los bloqueos"),
                stat("Espera máxima", "⏱️", last.wait, "s", level(last.wait, T.wait), "wait", `Aviso ${T.wait.warn} s · crítico ${T.wait.crit} s`)),
            el("div", { id: "sessions-charts", class: "grid grid-cols-1 gap-4 xl:grid-cols-2" }),
            inactiveLink(),
            blockersTable(),
            el("p", { class: "text-xs text-slate-500", text: `${points.length} muestras · última revisión ${fmtDate(new Date(last.t).toISOString())} · ` +
                "se actualiza sola con cada revisión (caché de Oracle)" }));
        renderCharts();
    }

    async function update(check) {
        if (check) { current = check; addPoint(toPoint(check)); }
        await seed();
        if (typeof can === "function" && can("dba")) {
            try { blocking = await api("/blocking-sessions"); } catch { blocking = null; }
        }
        render();
    }

    bindInteractions(document.getElementById("sessions-dash"));
    return { update, render };
})();
