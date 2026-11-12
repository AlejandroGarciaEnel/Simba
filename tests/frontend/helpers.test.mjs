// Tests de los helpers puros del frontal (js/*.js son scripts clásicos): se cargan en un contexto vm
// con un DOM mínimo simulado. Ejecutar con: npm test
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const root = new URL("../../interface/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

function loadFrontend() {
    const ctx = vm.createContext({
        console, URL, Date, Intl, FormData,
        sessionStorage: { getItem: () => null, setItem() {} },
        localStorage: { getItem: () => null, setItem() {} },
        document: { addEventListener() {}, getElementById: () => null },
        window: {},
        navigator: {},
    });
    for (const f of ["present", "core", "queries", "history-users"]) vm.runInContext(read(`frontend/js/${f}.js`), ctx, { filename: `${f}.js` });
    ctx.el = (tag, props = {}) => ({ tag, ...props });  // highlightSql solo necesita la clase y el texto
    // Las const/let de nivel superior no cuelgan del objeto global: se exponen explícitamente.
    Object.assign(ctx, vm.runInContext("({ state, fmtNum, COMMON_PASSWORDS })", ctx));
    return ctx;
}

const fe = loadFrontend();

test("formatSql parte en cláusulas e indenta AND/OR", () => {
    assert.equal(fe.formatSql("SELECT a FROM t WHERE x = 1 AND y = 2 ORDER BY a"),
        "SELECT a\nFROM t\nWHERE x = 1\n  AND y = 2\nORDER BY a");
});

test("formatSql no toca literales ni SQL ya formateado", () => {
    assert.equal(fe.formatSql("SELECT 'a FROM b' FROM t"), "SELECT 'a FROM b'\nFROM t");
    assert.equal(fe.formatSql("SELECT a FROM t WHERE s = 'X' AND b = 1"), "SELECT a\nFROM t\nWHERE s = 'X'\n  AND b = 1");
    const multi = "SELECT a\n  FROM t";
    assert.equal(fe.formatSql(multi), multi);
});

test("highlightSql clasifica tokens y conserva el texto exacto", () => {
    const sql = "SELECT nvl(x,0) FROM t WHERE a = :B1 AND s = 'it''s' -- fin";
    const parts = fe.highlightSql(sql);
    assert.equal(parts.map((p) => typeof p === "string" ? p : p.text).join(""), sql);
    const kinds = Object.fromEntries(parts.filter((p) => typeof p !== "string").map((p) => [p.text, p.class]));
    assert.equal(kinds.SELECT, "tk-kw");
    assert.equal(kinds.nvl, "tk-kw");
    assert.equal(kinds[":B1"], "tk-bind");
    assert.equal(kinds["'it''s'"], "tk-str");
    assert.equal(kinds["0"], "tk-num");
    assert.equal(kinds["-- fin"], "tk-cmt");
});

test("ago y fmtNum", () => {
    const minsAgo = (m) => new Date(Date.now() - m * 60000).toISOString();
    assert.equal(fe.ago(minsAgo(0)), "hace menos de un minuto");
    assert.equal(fe.ago(minsAgo(5)), "hace 5 min");
    assert.equal(fe.ago(minsAgo(180)), "hace 3 h");
    assert.equal(fe.ago(minsAgo(60 * 72)), "hace 3 días");
    assert.equal(fe.ago("no-es-fecha"), "");
    assert.equal(fe.fmtNum(null), "n/d");
    assert.equal(fe.fmtNum(37770), "37.770");
});

test("passwordProblems aplica la misma política que el backend", () => {
    assert.deepEqual([...fe.passwordProblems("Una-clave-2024", "mario")], []);
    assert.deepEqual([...fe.passwordProblems("una frase larga sin mayusculas", "mario")], []);
    assert.equal(fe.passwordProblems("Corta1!").length > 0, true);
    assert.match(fe.passwordProblems("solominusculas", "x").join(), /3 tipos/);
    assert.match(fe.passwordProblems("Mario-2024-clave", "mario").join(), /nombre de usuario/);
    assert.match(fe.passwordProblems("Passw0rd").join() + fe.passwordProblems("P@ssw0rd").join(), /común/);
    assert.match(fe.passwordProblems("aaaaaaaaaaaaaaaaaa").join(), /común o predecible/);
});

test("la lista de contraseñas comunes coincide con interface/backend/auth.py", () => {
    const block = read("backend/auth.py").match(/COMMON_PASSWORDS = frozenset\(\{([\s\S]*?)\}\)/)[1];
    const backend = [...block.matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort();
    assert.deepEqual([...fe.COMMON_PASSWORDS].sort(), backend);
});

test("api() envía X-CSRF-Token solo en peticiones que modifican", async () => {
    const calls = [];
    fe.fetch = async (url, opts) => { calls.push(opts); return { ok: true, status: 200, json: async () => ({}) }; };
    fe.state.user = { username: "u", role: "dba", csrf: "tok" };
    await fe.api("/x");
    await fe.api("/x", { method: "POST", body: { a: 1 } });
    assert.equal(calls[0].headers["X-CSRF-Token"], undefined);
    assert.equal(calls[1].headers["X-CSRF-Token"], "tok");
    assert.equal(calls[1].headers["Content-Type"], "application/json");
});

function loadPresent(on = true) {
    const mem = (init = {}) => { const m = new Map(Object.entries(init)); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)) }; };
    const ctx = vm.createContext({ sessionStorage: mem(), localStorage: mem({ presentMode: String(on) }) });
    vm.runInContext(read("frontend/js/present.js"), ctx, { filename: "present.js" });
    return vm.runInContext("Present", ctx);
}

test("modo presentación seudonimiza campos y también los textos libres", () => {
    const P = loadPresent();
    const out = P.mask({
        board: [{ sql_id: "5j63dku49x6hf", persona: "Francisco Martin", esquema: "GCWEB", estado: "En curso",
            mensaje: "5 semanas en el top (responsable: Francisco Martin).", notas: "PENDIENTE\n[04/09] Hablar con Simone" }],
        sessions: [{ usuario: "ENET", maquina: "ENELINT\\eevzekespp-31", programa: "oracle@ENELINT\\eevzekespp-31 (PPA7)", TABLESPACE_NAME: "GEMAS_DATA" }],
        detail: [{ objeto: "ENET.T_CHANGESET" }, { objeto: "SYS.I_OBJ5" }],
        file: "PRAGU4E_Informe_Semana.xlsx", csrf: "ENET",
    });
    const [card] = out.board, [ses] = out.sessions;
    assert.equal(card.sql_id, "5j63dku49x6hf");
    assert.equal(card.persona, "Persona A");
    assert.equal(card.esquema, "ESQUEMA_01");
    assert.equal(card.mensaje, "5 semanas en el top (responsable: Persona A).");
    assert.equal(card.notas, "PENDIENTE\n[04/09] Comentario de seguimiento (oculto en modo presentación)");
    assert.equal(ses.usuario, "ESQUEMA_02");
    assert.equal(ses.maquina, "equipo-01");
    assert.equal(ses.programa, "oracle@equipo-01 (PPA7)");
    assert.equal(ses.TABLESPACE_NAME, "TS_DATOS_01");
    assert.equal(out.detail[0].objeto, "ESQUEMA_02.OBJETO_01");
    assert.equal(out.detail[1].objeto, "SYS.I_OBJ5");
    assert.equal(out.file, "DEMO_DB_Informe_Semana.xlsx");
    assert.equal(out.csrf, "ENET");
    assert.equal(P.maskText("12 tablespace(s) por encima del 85%: TSL_GCWEB (88.7%), GEMAS_DATA (89.6%). Ver DBA_HIST_SQLSTAT y SQL_ID."),
        "12 tablespace(s) por encima del 85%: TS_DATOS_02 (88.7%), TS_DATOS_01 (89.6%). Ver DBA_HIST_SQLSTAT y SQL_ID.");
    assert.equal(P.maskText("la mayor: Index Fast Full Scan de LAVORIMT al 34.5%; usuario ATLANTE, máquina srv-app01.local. Lectura completa de: GIS.T_CUPS. Hay SYS.OBJ$"),
        "la mayor: Index Fast Full Scan de ESQUEMA_03 al 34.5%; usuario ESQUEMA_04, máquina equipo-02. Lectura completa de: ESQUEMA_05.OBJETO_02. Hay SYS.OBJ$");
});

test("modo presentación oculta identificadores y literales del SQL", () => {
    const P = loadPresent();
    P.mask({ esquema: "ENET" });
    assert.equal(P.maskSql("SELECT a.id FROM enet.t_cups a WHERE a.cups = 'ES0031' AND x = :1 -- nota"),
        "SELECT obj_01.obj_02 FROM esquema_01.obj_03 obj_01 WHERE obj_01.obj_04 = '***' AND obj_05 = :1 -- …");
});

test("modo presentación revierte seudónimos en rutas y cuerpos, y bloquea escrituras", () => {
    const P = loadPresent();
    P.mask({ username: "mario", esquema: "GCWEB" });
    assert.equal(P.unmaskPath(`/awr/weekly/download?name=${encodeURIComponent("DEMO_DB_Informe.xlsx")}`), "/awr/weekly/download?name=PRAGU4E_Informe.xlsx");
    assert.equal(P.unmask({ question: "¿Qué hace ESQUEMA_01 y demo01?" }).question, "¿Qué hace GCWEB y mario?");
    assert.equal(P.canWrite({ estado: "En curso", nota: "" }), true);
    assert.equal(P.canWrite({ nota: "Comentario de seguimiento (oculto en modo presentación)" }), false);
    const off = loadPresent(false);
    assert.equal(off.mask({ esquema: "GCWEB" }).esquema, "GCWEB");
    assert.equal(off.canWrite({ nota: "x" }), true);
});
