// Listado completo de sesiones inactivas (solo lectura; la API aplica rol dba y caché de 60 s).
(() => {
    const PAGE = 100;
    const REFRESH_MS = 60000;
    const COLS = [["usuario", "Usuario"], ["usuario_so", "Usuario SO"], ["maquina", "Máquina"], ["programa", "Programa"],
        ["modulo", "Módulo"], ["instancia", "Nodo"], ["sid", "SID"], ["inactiva_s", "Inactiva"], ["conexion", "Conectada desde"]];
    const $ = (id) => document.getElementById(id);
    const st = { rows: [], q: "", inst: "", min: 0, sort: "inactiva_s", dir: -1, page: 0, taken: "" };

    const el = (tag, attrs = {}, ...kids) => {
        const n = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs)) {
            if (k === "text") n.textContent = v;
            else if (k.startsWith("on")) n[k] = v;
            else n.setAttribute(k, v);
        }
        n.append(...kids.flat().filter(Boolean));
        return n;
    };
    const fmtDur = (s) => {
        s = Number(s) || 0;
        const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
        return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
    };

    async function load(silent) {
        try {
            const res = await fetch("/api/inactive-sessions", { credentials: "same-origin" });
            if (res.status === 401) { location.href = "/"; return; }
            if (res.status === 403) throw new Error("Este listado requiere rol dba o administrador.");
            if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Error ${res.status}`);
            const data = await res.json();
            st.rows = data.sessions;
            st.taken = data.taken_at || "";
            $("msg").textContent = "";
            $("live").classList.replace("hidden", "inline-flex");
            fillInstances();
            render();
        } catch (err) {
            // en refrescos silenciosos se conservan los datos anteriores
            $("msg").textContent = silent && st.rows.length ? `Sin conexión con el servidor, se reintentará… (${err.message})` : err.message;
            $("live").classList.replace("inline-flex", "hidden");
            if (!st.rows.length) $("meta").textContent = "No disponible";
        }
    }

    function fillInstances() {
        const sel = $("inst");
        const cur = sel.value;
        const insts = [...new Set(st.rows.map((r) => r.instancia))].sort();
        sel.replaceChildren(el("option", { value: "", text: "Todos los nodos" }),
            ...insts.map((i) => el("option", { value: i, text: `Nodo ${i}` })));
        sel.value = cur;
    }

    const filtered = () => {
        const q = st.q.toLowerCase();
        return st.rows
            .filter((r) => (!st.inst || String(r.instancia) === st.inst) && r.inactiva_s >= st.min
                && (!q || [r.usuario, r.usuario_so, r.maquina, r.programa, r.modulo].some((v) => String(v || "").toLowerCase().includes(q))))
            .sort((a, b) => (a[st.sort] > b[st.sort] ? 1 : a[st.sort] < b[st.sort] ? -1 : 0) * st.dir);
    };

    function stat(title, value, sub) {
        return el("div", { class: "rounded-2xl bg-gradient-to-br from-slate-800/90 to-slate-900/90 p-4 ring-1 ring-white/10" },
            el("p", { class: "text-xs uppercase tracking-wide text-slate-400", text: title }),
            el("p", { class: "mt-1 text-4xl font-semibold text-white", text: value }),
            el("p", { class: "mt-1 truncate text-xs text-slate-500", text: sub }));
    }

    function render() {
        const rows = filtered();
        const all = st.rows;
        const byUser = {};
        all.forEach((r) => { const u = r.usuario || "—"; byUser[u] = (byUser[u] || 0) + 1; });
        const top = Object.entries(byUser).sort((a, b) => b[1] - a[1]);
        const oldest = all.reduce((m, r) => Math.max(m, r.inactiva_s || 0), 0);
        const over1d = all.filter((r) => r.inactiva_s >= 86400).length;

        $("meta").textContent = `Actualizado ${st.taken.replace("T", " ")} · se refresca solo cada minuto`;
        $("stats").replaceChildren(
            stat("Total inactivas", all.length.toLocaleString("es-ES"), "todos los nodos"),
            stat("Más antigua", fmtDur(oldest), "tiempo sin actividad"),
            stat("> 1 día", over1d.toLocaleString("es-ES"), "candidatas a revisar"),
            stat("Usuario con más", top[0] ? String(top[0][1]) : "0", top[0] ? top[0][0] : ""));

        $("chips").replaceChildren(...top.slice(0, 10).map(([u, n]) => el("button", {
            class: `rounded-full px-3 py-1 text-xs ring-1 transition ${st.q === u ? "bg-indigo-500 text-white ring-indigo-400" : "bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10"}`,
            text: `${u} · ${n}`,
            onclick: () => { st.q = st.q === u ? "" : u; $("q").value = st.q; st.page = 0; render(); },
        })));

        $("thead").replaceChildren(el("tr", {}, COLS.map(([k, h]) => el("th", {
            class: "cursor-pointer select-none whitespace-nowrap px-3 py-2 hover:text-white",
            text: h + (st.sort === k ? (st.dir < 0 ? " ▼" : " ▲") : ""),
            onclick: () => { st.dir = st.sort === k ? -st.dir : -1; st.sort = k; render(); },
        }))));

        const pages = Math.max(1, Math.ceil(rows.length / PAGE));
        st.page = Math.min(st.page, pages - 1);
        const slice = rows.slice(st.page * PAGE, (st.page + 1) * PAGE);
        $("tbody").replaceChildren(...slice.map((r) => el("tr", { class: "hover:bg-white/5" }, COLS.map(([k]) => {
            const v = k === "inactiva_s" ? fmtDur(r[k]) : (r[k] ?? "—");
            const hot = k === "inactiva_s" && r[k] >= 86400;
            return el("td", { class: `whitespace-nowrap px-3 py-1.5 ${hot ? "font-medium text-amber-300" : ""}`, text: v });
        }))));
        $("count").textContent = `${rows.length.toLocaleString("es-ES")} de ${all.length.toLocaleString("es-ES")} sesiones`;
        $("page").textContent = `Página ${st.page + 1} de ${pages}`;
        $("prev").disabled = st.page === 0;
        $("next").disabled = st.page >= pages - 1;
    }

    function exportCsv() {
        const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
        const body = [COLS.map(([, h]) => h).join(";"), ...filtered().map((r) => COLS.map(([k]) => esc(r[k])).join(";"))].join("\n");
        const a = el("a", { href: URL.createObjectURL(new Blob(["\ufeff" + body], { type: "text/csv" })), download: "sesiones_inactivas.csv" });
        a.click();
    }

    $("q").oninput = (e) => { st.q = e.target.value; st.page = 0; render(); };
    $("inst").onchange = (e) => { st.inst = e.target.value; st.page = 0; render(); };
    $("min").onchange = (e) => { st.min = Number(e.target.value); st.page = 0; render(); };
    $("prev").onclick = () => { st.page -= 1; render(); };
    $("next").onclick = () => { st.page += 1; render(); };
    $("reload").onclick = () => load(false);
    $("csv").onclick = exportCsv;

    load(false);
    setInterval(() => { if (!document.hidden) load(true); }, REFRESH_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) load(true); });
})();
