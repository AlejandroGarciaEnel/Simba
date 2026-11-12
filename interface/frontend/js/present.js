// SIMBA · Modo presentación: sustituye en el navegador los datos reales (personas, usuarios, esquemas,
// máquinas, tablespaces, objetos, texto SQL y notas) por seudónimos estables. No toca el backend.
// Script clásico: se carga antes que core.js en index.html y antes que inactivas.js en inactivas.html.

const Present = (() => {
    const FLAG = "presentMode";
    const STORE = "presentMap";
    const GLOBALS = [["PRAGU4E", "DEMO_DB"]];
    const KEEP_SCHEMAS = new Set(["SYS", "SYSTEM", "PUBLIC", "DBSNMP", "XDB", "OUTLN", "AUDSYS", "SYSMAN", "ORACLE", "ROOT"]);
    const FORMATS = {
        person: (n) => `Persona ${letters(n)}`,
        user: (n) => `demo${pad(n)}`,
        schema: (n) => `ESQUEMA_${pad(n)}`,
        osuser: (n) => `usr_so_${pad(n)}`,
        host: (n) => `equipo-${pad(n)}`,
        ts: (n) => `TS_DATOS_${pad(n)}`,
        object: (n) => `OBJETO_${pad(n)}`,
        ident: (n) => `OBJ_${pad(n)}`,
    };
    // "ident" son identificadores sacados del texto SQL: no se buscan en textos libres (ID, NAME… romperían frases).
    const TEXT_KINDS = ["person", "user", "schema", "osuser", "host", "ts", "object"];
    const KEY_KIND = {
        persona: "person", responsable: "person",
        username: "user", author: "user", requested_by: "user", actor: "user", assigned_by: "user",
        esquema: "schema", usuario: "schema", USUARIO: "schema", OWNER: "schema", USERNAME: "schema", PARSING_SCHEMA_NAME: "schema", SCHEMA: "schema",
        usuario_so: "osuser", OSUSER: "osuser",
        maquina: "host", MAQUINA: "host", MACHINE: "host", TERMINAL: "host", terminal: "host",
        TABLESPACE_NAME: "ts", tablespace: "ts",
        objeto: "object", OBJETO: "object", OBJECT_NAME: "object", PROPIETARIO: "schema", TABLA: "object",
        sql_text: "sql", sql_texto: "sql", SQL_TEXT: "sql", sql_fulltext: "sql",
        notas: "note", notas_analisis: "note", nota: "note", nota_local: "note",
    };
    const RAW_KEYS = new Set(["csrf", "sql_id", "id", "role", "severity", "overall", "status", "estado", "prioridad"]);
    const SQL_WORDS = new Set(("SELECT FROM WHERE AND OR NOT IN IS NULL AS ON JOIN INNER LEFT RIGHT FULL OUTER CROSS GROUP ORDER BY HAVING " +
        "UNION ALL DISTINCT INSERT INTO VALUES UPDATE SET DELETE MERGE USING MATCHED THEN WHEN CASE ELSE END EXISTS BETWEEN LIKE WITH DESC " +
        "ASC FETCH FIRST NEXT ROWS ROW ONLY OVER PARTITION BEGIN DECLARE CALL COUNT SUM MIN MAX AVG NVL NVL2 DECODE TO_DATE TO_CHAR " +
        "TO_NUMBER TO_TIMESTAMP TRUNC ROUND SYSDATE SYSTIMESTAMP ROWNUM ROWID LEVEL FOR CONNECT START PRIOR DUAL IF LOOP WHILE EXIT RETURN " +
        "RETURNING BULK COLLECT FORALL COMMIT ROLLBACK EXECUTE IMMEDIATE CURSOR OPEN CLOSE EXCEPTION OTHERS RAISE NUMBER VARCHAR2 VARCHAR " +
        "CHAR DATE TIMESTAMP INTEGER BOOLEAN TRUE FALSE TABLE INDEX VIEW CREATE ALTER DROP TRUNCATE GRANT LOCK MODE NOWAIT WAIT SKIP LOCKED " +
        "OF ANY SOME UPPER LOWER SUBSTR INSTR LENGTH REPLACE TRIM LTRIM RTRIM COALESCE CAST EXTRACT INTERVAL DAY MONTH YEAR HOUR MINUTE " +
        "SECOND ADD_MONTHS LAST_DAY MONTHS_BETWEEN ROW_NUMBER RANK DENSE_RANK LAG LEAD LISTAGG WITHIN XMLAGG REGEXP_LIKE REGEXP_SUBSTR " +
        "REGEXP_REPLACE ABS MOD GREATEST LEAST PIPELINED NOCOPY OUT DEFAULT CONSTANT TYPE ROWTYPE RECORD PRAGMA AUTONOMOUS_TRANSACTION " +
        "MINUS INTERSECT NULLS LAST PERCENT ESCAPE SAMPLE SEED HINT FORCE PARALLEL NOPARALLEL APPEND FULL INDEX_RS_ASC USE_NL USE_HASH LEADING").split(" "));
    const SQL_TOKEN = /('(?:[^']|'')*')|("[^"]*")|(--[^\n]*|\/\*[\s\S]*?\*\/)|(:\w+)|([A-Za-z_][\w$#]*)/g;
    // Identificadores Oracle en mayúsculas con guion bajo (TSL_GCWEB…) que aparecen solo en textos libres.
    const ORA_NAME = /(?<![\w$#.])[A-Z][A-Z0-9$#]*_[A-Z0-9_$#]+(?![\w$#])/g;
    const ORA_KEEP = /^(DBA|CDB|ALL|USER|SYS|GV|V)_|^(SQL_ID|SQL_TEXT|PLAN_HASH_VALUE|LIMIT_VALUE|RESOURCE_NAME|TABLESPACE_NAME)$|_(TIME|GETS|READS|WRITES|VALUE|NAME|ID|PCT|MB|GB)$/;
    // Frases del backend que citan usuarios u objetos sin campo propio (health/checker.py, sql_analysis.py).
    const CONTEXT = [
        [/(\bde )([A-Z][A-Z0-9_$#]{2,})(?= al \d)/g, "schema"],
        [/(\busuario )([A-Z][A-Z0-9_$#]{2,})\b/g, "schema"],
        [/(\bmáquina )([\w.\\-]*[\d\\.-][\w.\\-]*\w)/g, "host"],
    ];
    const DOTTED = /(?<![\w$#.])([A-Z][A-Z0-9_$#]{1,29})\.([A-Z][A-Z0-9_$#]{1,29})(?![\w$#])/g;
    const PERSON_RE = /^[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]+)+$/;

    const pad = (n) => String(n).padStart(2, "0");
    const letters = (n) => { let s = ""; for (n -= 1; n >= 0; n = Math.floor(n / 26) - 1) s = String.fromCharCode(65 + (n % 26)) + s; return s; };
    const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const store = (name) => { try { return globalThis[name] || null; } catch { return null; } };

    let map = load();
    let textRe = null, reverseRe = null, grown = false;

    function load() {
        try {
            const saved = JSON.parse(store("sessionStorage")?.getItem(STORE) || "null");
            if (saved && saved.real && saved.fake) return saved;
        } catch { /* mapa corrupto: se empieza de cero */ }
        return { real: {}, fake: {}, count: {} };
    }
    function save() { try { store("sessionStorage")?.setItem(STORE, JSON.stringify(map)); } catch { /* sin almacenamiento */ } }

    function register(kind, real) {
        const key = `${kind}:${kind === "ident" ? real.toUpperCase() : real}`;
        if (map.real[key]) return map.real[key];
        map.count[kind] = (map.count[kind] || 0) + 1;
        const fake = FORMATS[kind](map.count[kind]);
        map.real[key] = fake;
        if (kind !== "ident") { map.fake[fake] = real; grown = true; }
        textRe = reverseRe = null;
        save();
        return fake;
    }
    const lookup = (kind, real) => map.real[`${kind}:${kind === "ident" ? real.toUpperCase() : real}`];

    function registerValue(kind, value) {
        const v = String(value).trim();
        if (!v || v === "-" || v.length > 200) return;
        if (kind === "person") { if (PERSON_RE.test(v)) register("person", v); return; }
        if (kind === "schema") { if (!KEEP_SCHEMAS.has(v.toUpperCase())) register("schema", v); return; }
        if (kind === "osuser" && v.toLowerCase() === "oracle") return;
        if (kind === "object") {
            const parts = v.split(".");
            if (parts.length === 2 && KEEP_SCHEMAS.has(parts[0].toUpperCase())) return;
            if (parts.length === 2) { registerValue("schema", parts[0]); register("object", parts[1]); } else register("object", v);
            return;
        }
        if (kind === "user" || kind === "osuser" || kind === "host" || kind === "ts") register(kind, v);
    }

    function boundaryRe(tokens) {
        if (!tokens.length) return null;
        const alt = tokens.sort((a, b) => b.length - a.length).map(esc).join("|");
        return new RegExp(`(?<![\\w$#.\\\\-])(?:${alt})(?![\\w$#\\\\-])`, "g");
    }

    function maskText(s) {
        if (typeof s !== "string" || !s) return s;
        for (const [real, fake] of GLOBALS) s = s.replace(new RegExp(esc(real), "gi"), fake);
        if (textRe === null) {
            const tokens = Object.keys(map.real).filter((k) => TEXT_KINDS.includes(k.slice(0, k.indexOf(":"))) && k.length - k.indexOf(":") > 3)
                .map((k) => k.slice(k.indexOf(":") + 1));
            textRe = boundaryRe(tokens) || false;
        }
        if (textRe) s = s.replace(textRe, (m) => TEXT_KINDS.map((k) => lookup(k, m)).find(Boolean) || m);
        for (const [re, k] of CONTEXT) s = s.replace(re, (all, pre, name) => pre + (map.fake[name] || KEEP_SCHEMAS.has(name) ? name : register(k, name)));
        s = s.replace(DOTTED, (all, a, b) => map.fake[a] || KEEP_SCHEMAS.has(a) || ORA_KEEP.test(b) ? all
            : `${lookup("schema", a) || register("schema", a)}.${map.fake[b] ? b : lookup("object", b) || register("object", b)}`);
        const kind = /tablespace/i.test(s) ? "ts" : "object";
        return s.replace(ORA_NAME, (m) => map.fake[m] || ORA_KEEP.test(m) ? m : register(kind, m));
    }

    function unmaskText(s) {
        if (typeof s !== "string" || !s) return s;
        for (const [real, fake] of GLOBALS) s = s.split(fake).join(real);
        if (reverseRe === null) reverseRe = boundaryRe(Object.keys(map.fake)) || false;
        return reverseRe ? s.replace(reverseRe, (m) => map.fake[m] ?? m) : s;
    }

    function maskSql(sql) {
        return String(sql).replace(SQL_TOKEN, (m, lit, quoted, comment, bind, word) => {
            if (lit) return "'***'";
            if (comment) return comment.startsWith("--") ? "-- …" : "/* … */";
            if (bind) return m;
            const name = quoted ? quoted.slice(1, -1) : word;
            if (!quoted && SQL_WORDS.has(word.toUpperCase())) return m;
            if (KEEP_SCHEMAS.has(name.toUpperCase())) return m;
            const fake = lookup("schema", name) || lookup("schema", name.toUpperCase()) || lookup("object", name) || lookup("object", name.toUpperCase()) || register("ident", name);
            const out = !quoted && word === word.toLowerCase() ? fake.toLowerCase() : fake;
            return quoted ? `"${out}"` : out;
        });
    }

    // Conserva marcas de fecha y palabras de estado ("[14/10] …", "PENDIENTE") y oculta el texto libre.
    function maskNote(note) {
        return String(note).split("\n").map((line) => {
            const t = line.trim();
            if (!t || /^[-\sA-ZÁÉÍÓÚÑ.:]*$/.test(t)) return line;
            const prefix = (t.match(/^(\[[^\]]{1,24}\]\s*)+/) || [""])[0];
            return `${prefix}Comentario de seguimiento (oculto en modo presentación)`;
        }).join("\n");
    }

    function collect(node, key) {
        if (Array.isArray(node)) { node.forEach((x) => collect(x, key)); return; }
        if (node && typeof node === "object") { for (const [k, v] of Object.entries(node)) collect(v, k); return; }
        const kind = KEY_KIND[key];
        if (typeof node === "string" && kind && kind !== "sql" && kind !== "note") registerValue(kind, node);
    }

    function transform(node, key) {
        if (Array.isArray(node)) return node.map((x) => transform(x, key));
        if (node && typeof node === "object") {
            const out = {};
            for (const [k, v] of Object.entries(node)) out[k] = transform(v, k);
            return out;
        }
        if (typeof node !== "string" || RAW_KEYS.has(key)) return node;
        const kind = KEY_KIND[key];
        if (kind === "sql") return maskSql(node);
        if (kind === "note") return maskNote(node);
        if (kind) {
            const v = node.trim();
            if (kind === "object") {
                const [a, b] = v.split(".");
                if (b !== undefined) return `${lookup("schema", a) || a}.${lookup("object", b) || b}`;
            }
            const fake = lookup(kind, v);
            if (fake) return fake;
        }
        return maskText(node);
    }

    // Un valor descubierto ahora puede estar ya pintado en otra vista (p. ej. un esquema citado en el resumen).
    function scrub(root) {
        if (!root?.ownerDocument) return;
        const walker = root.ownerDocument.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
            const t = maskText(n.nodeValue);
            if (t !== n.nodeValue) n.nodeValue = t;
        }
        root.querySelectorAll("[title]").forEach((e) => { const t = maskText(e.title); if (t !== e.title) e.title = t; });
    }

    function mask(data) {
        if (!isOn()) return data;
        grown = false;
        collect(data, "");
        const out = transform(data, "");
        if (grown && globalThis.document?.body) setTimeout(() => scrub(globalThis.document.body), 0);
        return out;
    }

    function unmask(data) {
        if (!isOn()) return data;
        if (typeof data === "string") return unmaskText(data);
        return JSON.parse(unmaskText(JSON.stringify(data)));
    }

    // Las rutas llevan seudónimos codificados (p. ej. nombres de fichero): se descodifican para revertirlos.
    function unmaskPath(path) {
        if (!isOn()) return path;
        return path.replace(/[^/?&=]+/g, (seg) => {
            let dec;
            try { dec = decodeURIComponent(seg); } catch { return seg; }
            const back = unmaskText(dec);
            return back === dec ? seg : encodeURIComponent(back);
        });
    }

    function isOn() {
        try { return store("localStorage")?.getItem(FLAG) === "true"; } catch { return false; }
    }
    function setOn(on) {
        try { store("localStorage")?.setItem(FLAG, String(!!on)); } catch { /* sin almacenamiento */ }
    }

    // Las notas se muestran ocultas y no se pueden revertir: guardarlas sobrescribiría la real.
    const canWrite = (body) => !isOn() || !(body && typeof body === "object" && body.nota);

    return { isOn, setOn, mask, scrub, unmask, unmaskPath, maskText, maskSql, maskNote, canWrite };
})();
