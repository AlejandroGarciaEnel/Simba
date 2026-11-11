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
        points = points.slice(-200);
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

    function sparkline(key, cls) {
        const data = points.map((p) => p[key]);
        const w = 200, h = 40;
        if (data.length < 2) return svg("svg", { viewBox: `0 0 ${w} ${h}`, class: "gf-spark" });
        const max = Math.max(...data, 1);
        const xy = data.map((v, i) => [(i / (data.length - 1)) * w, h - 3 - (v / max) * (h - 8)]);
        const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        return svg("svg", { viewBox: `0 0 ${w} ${h}`, class: `gf-spark gf-${cls}`, preserveAspectRatio: "none" },
            svg("path", { d: `${line} L${w},${h} L0,${h} Z`, class: "gf-area" }),
            svg("path", { d: line, class: "gf-line" }));
    }

    function stat(title, value, unit, cls, key, hint) {
        return el("section", { class: "gf-panel gf-stat" },
            el("h4", { class: "gf-title", text: title }),
            el("div", { class: `gf-value gf-${cls}` }, String(value), el("small", { text: unit })),
            el("p", { class: "gf-hint", text: hint }),
            sparkline(key, cls));
    }

    // Serie temporal con rejilla, umbrales y tooltip al pasar el ratón.
    function timeSeries(title, series, thresholds) {
        const W = 640, H = 240, m = { l: 40, r: 12, t: 12, b: 26 };
        const iw = W - m.l - m.r, ih = H - m.t - m.b;
        const box = el("section", { class: "gf-panel gf-chart" }, el("h4", { class: "gf-title", text: title }));
        if (points.length < 2) {
            box.append(el("p", { class: "gf-empty", text: "Recogiendo datos… (hacen falta al menos 2 revisiones)" }));
            return box;
        }
        const t0 = points[0].t, t1 = points[points.length - 1].t || t0 + 1;
        const maxV = Math.max(1, ...series.flatMap((s) => points.map((p) => p[s.key])), ...(thresholds || []).map((x) => x.v));
        const top = Math.max(4, Math.ceil(maxV * 1.1));
        const X = (t) => m.l + ((t - t0) / (t1 - t0 || 1)) * iw;
        const Y = (v) => m.t + ih - (v / top) * ih;
        const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "gf-svg" });
        for (let i = 0; i <= 4; i++) {
            const v = (top / 4) * i, y = Y(v);
            root.append(svg("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: "gf-grid" }));
            const lab = svg("text", { x: m.l - 6, y: y + 3, class: "gf-axis", "text-anchor": "end" });
            lab.textContent = Math.round(v);
            root.append(lab);
        }
        for (let i = 0; i <= 4; i++) {
            const t = t0 + ((t1 - t0) / 4) * i;
            const lab = svg("text", { x: X(t), y: H - 8, class: "gf-axis", "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle" });
            lab.textContent = fmtTime(t);
            root.append(lab);
        }
        (thresholds || []).forEach((th) => root.append(
            svg("line", { x1: m.l, x2: W - m.r, y1: Y(th.v), y2: Y(th.v), class: `gf-thr gf-${th.cls}` })));
        series.forEach((s) => {
            const d = points.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p[s.key]).toFixed(1)}`).join(" ");
            root.append(svg("path", { d: `${d} L${X(t1)},${Y(0)} L${X(t0)},${Y(0)} Z`, class: "gf-fill", style: `fill:${s.color}` }));
            root.append(svg("path", { d, class: "gf-series", style: `stroke:${s.color}` }));
        });
        const cursor = svg("line", { y1: m.t, y2: m.t + ih, class: "gf-cursor", visibility: "hidden" });
        root.append(cursor);
        const tip = el("div", { class: "gf-tip", hidden: true });
        root.addEventListener("mousemove", (e) => {
            const r = root.getBoundingClientRect();
            const x = ((e.clientX - r.left) / r.width) * W;
            const p = points.reduce((a, b) => (Math.abs(X(b.t) - x) < Math.abs(X(a.t) - x) ? b : a));
            cursor.setAttribute("x1", X(p.t)); cursor.setAttribute("x2", X(p.t));
            cursor.setAttribute("visibility", "visible");
            tip.hidden = false;
            tip.style.left = `${Math.min(e.clientX - r.left + 12, r.width - 170)}px`;
            tip.replaceChildren(el("b", { text: new Date(p.t).toLocaleString("es-ES") }),
                ...series.map((s) => el("div", {}, el("i", { style: `background:${s.color}` }), `${s.label}: ${p[s.key]}`)));
        });
        root.addEventListener("mouseleave", () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; });
        box.append(el("div", { class: "gf-plot" }, root, tip),
            el("div", { class: "gf-legend" }, series.map((s) => el("span", {}, el("i", { style: `background:${s.color}` }), s.label))));
        return box;
    }

    function blockersTable() {
        const blo = (current?.findings || []).find((f) => f.area === "Bloqueos");
        const rows = blo?.details || [];
        const box = el("section", { class: "gf-panel gf-wide" }, el("h4", { class: "gf-title", text: "Sesiones bloqueantes (última revisión)" }));
        if (!rows.length) {
            box.append(el("p", { class: "gf-empty", text: "✔ No hay sesiones bloqueadas" }));
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
        box.append(el("div", { class: "table-wrap" }, el("table", { class: "table table-compact" },
            el("thead", {}, el("tr", {}, cols.map(([h]) => el("th", { text: h })))),
            el("tbody", {}, rows.map((d) => el("tr", {}, cols.map(([, fn]) => el("td", { text: fn(d) }))))))));
        return box;
    }

    function render() {
        const host = document.getElementById("sessions-dash");
        if (!host || !points.length) return;
        const last = points[points.length - 1];
        host.replaceChildren(
            el("div", { class: "gf-row" },
                stat("Sesiones inactivas > 30 min", last.inactive, "", level(last.inactive, T.inactive), "inactive", `Umbral: ${T.inactive.warn} aviso`),
                stat("Sesiones bloqueadas", last.blocked, "", last.blocked ? "warn" : "ok", "blocked", "Esperando a un bloqueante"),
                stat("Sesiones bloqueantes", last.blockers, "", last.blockers ? "warn" : "ok", "blockers", "Raíz de los bloqueos"),
                stat("Espera máxima", last.wait, "s", level(last.wait, T.wait), "wait", `Aviso ${T.wait.warn} s · crítico ${T.wait.crit} s`)),
            el("div", { class: "gf-row gf-row-2" },
                timeSeries("Sesiones inactivas > 30 min", [{ key: "inactive", label: "Inactivas", color: "#5794f2" }],
                    [{ v: T.inactive.warn, cls: "warn" }]),
                timeSeries("Sesiones bloqueadas y bloqueantes", [
                    { key: "blocked", label: "Bloqueadas", color: "#f2495c" },
                    { key: "blockers", label: "Bloqueantes", color: "#ff9830" }])),
            blockersTable(),
            el("p", { class: "gf-foot", text: `${points.length} muestras · última revisión ${fmtDate(new Date(last.t).toISOString())} · ` +
                "se actualiza sola con cada revisión (caché de Oracle)" }));
    }

    async function update(check) {
        if (check) { current = check; addPoint(toPoint(check)); }
        await seed();
        render();
    }

    return { update, render };
})();
