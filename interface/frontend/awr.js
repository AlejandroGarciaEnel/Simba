// Ventana AWR (solo administrador): snapshots en horario laboral y resumen semanal.
const AwrView = (() => {
    let timer = null;
    const body = () => document.getElementById("awr-body");
    const hhmm = (iso) => (iso || "").slice(11, 16);
    const label = { ok: "Correcto", warn: "Con huecos", crit: "Faltan snapshots", pending: "Pendiente", off: "No laborable" };

    function stat(cls, title, value, extra) {
        return el("div", { class: `awr-stat ${cls || ""}` }, el("small", { text: title }), el("b", { text: value }), extra ? el("div", { class: "muted", text: extra }) : null);
    }

    function heatmap(d) {
        const grid = el("div", { class: "awr-grid" });
        grid.append(el("span"));
        for (let h = 0; h < 24; h++) grid.append(el("span", { class: "hh", text: h % 3 === 0 ? String(h) : "" }));
        grid.append(el("span"));
        for (const day of d.days) {
            grid.append(el("span", { class: "dl", text: `${day.weekday} ${day.date.slice(8)}` }));
            for (let h = 0; h < 24; h++) {
                const n = day.hours[h];
                const inside = day.laborable && h >= d.work_start && h < d.work_end;
                const miss = inside && n === 0 && day.status !== "pending" && day.status !== "off";
                grid.append(el("span", { class: `awr-cell${n ? " has" : ""}${n > 1 ? " many" : ""}${miss ? " miss" : ""}${inside ? "" : " out"}`,
                    title: `${day.date} ${String(h).padStart(2, "0")}:00 · ${n} snapshot(s)` }));
            }
            grid.append(el("span", { class: `awr-day-badge ${day.status}`, text: label[day.status] || day.status, title: day.message }));
        }
        return grid;
    }

    function render(snap, weekly) {
        const root = body();
        root.replaceChildren();
        if (snap) {
            const today = snap.days[snap.days.length - 1];
            const inst = (today.instances || []).map((i) => `inst ${i.instancia}: ${i.count}`).join(" · ");
            const lastTs = Object.values(snap.last_snapshot).sort().pop();
            root.append(el("div", { class: "awr-stats" },
                stat(snap.today, "Hoy en horario laboral", label[snap.today], today.message),
                stat("", "Snapshots hoy", inst || "0", `Horario ${snap.work_start}:00–${snap.work_end}:00`),
                stat("", "Último snapshot", lastTs ? hhmm(lastTs) : "—", lastTs ? fmtDate(lastTs) : ""),
                stat("", "Frecuencia / retención", `${snap.interval_min} min`, snap.retention_days != null ? `Retención ${snap.retention_days.toFixed(0)} días` : "")));
            const card = el("div", { class: "awr-card" }, el("h3", { text: "Últimos 7 días (snapshots por hora)" }), heatmap(snap));
            card.append(el("div", { class: "awr-legend" },
                el("span", {}, el("i", { style: "background:var(--ok)" }), "Snapshot guardado"),
                el("span", {}, el("i", { style: "background:color-mix(in srgb, var(--crit) 55%, transparent)" }), "Hueco en horario laboral"),
                el("span", {}, el("i", { style: "background:var(--surface-2)" }), "Fuera de horario / sin dato")));
            const gaps = snap.days.filter((x) => (x.instances || []).some((i) => i.status !== "ok"));
            if (gaps.length) {
                card.append(el("p", { class: "muted", text: "Días con incidencias: " + gaps.map((x) => `${x.weekday} ${x.date.slice(8)} (mayor hueco ${Math.max(...x.instances.map((i) => i.max_gap_min))} min)`).join(" · ") }));
            }
            root.append(card);
        } else {
            root.append(el("div", { class: "awr-card awr-err", text: "No se pudo leer DBA_HIST_SNAPSHOT." }));
        }
        if (weekly) {
            const st = weekly.state || {};
            const card = el("div", { class: "awr-card" }, el("h3", { text: "Resumen semanal (Excel del viernes)" }));
            card.append(el("p", { class: "muted", text: weekly.enabled
                ? `Se genera automáticamente cada viernes. Próxima ejecución: ${fmtDate(weekly.next_run)}.`
                : "Generación automática desactivada (SIMBA_WEEKLY_ENABLED)." }));
            if (st.run_at) {
                card.append(el("p", { class: st.status === "error" ? "awr-err" : "", text: st.status === "error"
                    ? `Último intento ${fmtDate(st.run_at)} falló: ${st.error}`
                    : `Última ejecución ${fmtDate(st.run_at)} (${st.trigger === "manual" ? "manual" : "automática"}): ${st.status === "exists" ? "ya existía" : `${st.rows} SQL`} · ${st.file}` }));
            }
            const btn = el("button", { class: "btn btn-primary btn-small", text: "Generar ahora (semana en curso)" });
            btn.addEventListener("click", async () => {
                btn.disabled = true;
                try { await api("/awr/weekly/generate", { method: "POST" }); } catch (e) { alert(e.message); }
                load();
            });
            card.append(btn);
            if (weekly.files.length) {
                const tb = el("table", { class: "awr-files" }, el("tr", {}, el("th", { text: "Fichero" }), el("th", { text: "Modificado" }), el("th")));
                for (const f of weekly.files) {
                    const dl = el("button", { class: "btn btn-small", text: "Descargar" });
                    dl.addEventListener("click", async () => {
                        const res = await api(`/awr/weekly/download?name=${encodeURIComponent(f.name)}`, { raw: true });
                        if (!res.ok) { alert("No se pudo descargar."); return; }
                        const url = URL.createObjectURL(await res.blob());
                        const a = el("a", { href: url, download: f.name });
                        document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
                    });
                    tb.append(el("tr", {}, el("td", { text: f.name }), el("td", { text: fmtDate(f.modified) }), el("td", {}, dl)));
                }
                card.append(tb);
            }
            root.append(card);
        }
    }

    async function load() {
        const [snap, weekly] = await Promise.all([api("/awr/snapshots").catch(() => null), api("/awr/weekly").catch(() => null)]);
        render(snap, weekly);
    }

    function open() {
        load();
        clearInterval(timer);
        timer = setInterval(() => { if (!document.hidden) load(); }, 60000);
    }
    function close() { clearInterval(timer); timer = null; }
    document.addEventListener("DOMContentLoaded", () => document.getElementById("awr-refresh")?.addEventListener("click", load));
    return { open, close };
})();
