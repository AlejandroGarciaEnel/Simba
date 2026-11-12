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
    for (const f of ["core", "queries", "history-users"]) vm.runInContext(read(`frontend/js/${f}.js`), ctx, { filename: `${f}.js` });
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
