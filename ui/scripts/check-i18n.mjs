// Fordítás-teljesség ellenőrzése (057, a régi V4 `ui/scripts/check-i18n.mjs` mintájára, egyszerűsítve).
// Kötelező angol fordítás:
//  - a felület minden `t("…")` hívásának szöveg-literálja (TypeScript-elemzéssel, nem regexszel);
//  - a szolgáltatás felől jövő feliratok: az adatkészletek oszlopnevei (`jav/datasets.py` `_col(...)`), a felsorolt
//    feliratok (`configs/datasets.json` labels) és a mező- / oszlopnevek (`configs/field_labels.json`).
// Hibát ad: hiányzó kulcs, üres fordítás, eltérő helyőrző ({{név}}), ugyanaz a kulcs két fájlban eltérően.
// Futtatás: `npm run i18n:check`; `--self-test`: a hibaágak ellenőrzése.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const UI = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = path.resolve(UI, "..");

export function validate(required, dictionaries) {
  const errors = [];
  const merged = {};
  const holes = (s) => (s.match(/\{\{\w+\}\}/g) ?? []).sort().join("|");
  for (const [file, dict] of dictionaries) {
    for (const [k, v] of Object.entries(dict)) {
      if (typeof v !== "string" || !v.trim()) errors.push(`${file}: üres fordítás: ${k}`);
      else if (holes(k) !== holes(v)) errors.push(`${file}: eltérő helyőrző: ${k}`);
      if (k in merged && merged[k] !== v) errors.push(`${file}: eltérő fordítás: ${k}`);
      merged[k] = v;
    }
  }
  for (const k of required) if (!(k in merged)) errors.push(`hiányzó angol fordítás: ${k}`);
  return errors;
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
  }
  return out;
}

export function uiKeys(files) {
  const keys = new Set();
  for (const f of files) {
    const src = ts.createSourceFile(f, fs.readFileSync(f, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const visit = (n) => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "t" && n.arguments.length) {
        const a = n.arguments[0];
        if (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a)) keys.add(a.text);
        // t(feltétel ? "a" : "b"): mindkét ág kötelező
        if (ts.isConditionalExpression(a)) for (const b of [a.whenTrue, a.whenFalse]) if (ts.isStringLiteral(b)) keys.add(b.text);
      }
      // tmap({...}): a címkeszótár minden szöveg-értéke kötelező (olvasáskor fordít)
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "tmap" && n.arguments.length
          && ts.isObjectLiteralExpression(n.arguments[0])) {
        for (const pr of n.arguments[0].properties) if (ts.isPropertyAssignment(pr) && ts.isStringLiteral(pr.initializer)) keys.add(pr.initializer.text);
      }
      ts.forEachChild(n, visit);
    };
    visit(src);
  }
  return keys;
}

export function serverKeys() {
  const keys = new Set();
  const py = fs.readFileSync(path.join(ROOT, "jav", "datasets.py"), "utf8");
  for (const m of py.matchAll(/_col\(\s*(?:f?"[^"]*"|[a-z_]+)\s*,\s*"([^"]+)"/g)) keys.add(m[1]);
  const ds = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "datasets.json"), "utf8"));
  for (const group of Object.values(ds.labels)) for (const v of Object.values(group)) keys.add(v);
  const fl = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "field_labels.json"), "utf8"));
  for (const section of ["fields", "columns", "doc_types"]) for (const v of Object.values(fl[section] ?? {})) keys.add(v);
  // 058: a levél-szándékok neve (a teendő-szövegben és a levél nézetében) a felületen fordítva jelenik meg
  const it = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "intents.json"), "utf8"));
  for (const i of it.intents ?? []) if (i.display_name) keys.add(i.display_name);
  // 058 K5.3: a feladat-akciók neve
  const et = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "email_tasks.json"), "utf8"));
  for (const v of Object.values(et.actions ?? {})) keys.add(v);
  // a receptek termékszövege (cím, leírás, lépések) a felületen fordítva jelenik meg
  const rc = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "recipes.json"), "utf8"));
  for (const r of Array.isArray(rc.recipes) ? rc.recipes : Object.values(rc.recipes ?? {})) {
    // 063: a Receptek oldal a feltételeket, az eredményt és az ember teendőjét is mutatja
    for (const v of [r.title, r.description, ...(r.steps ?? []), ...(r.requirements ?? []), r.result, r.manual_action]) if (v) keys.add(v);
  }
  // 063: a receptek magyarázata (mikor való, a beállítások és értékeik jelentése)
  const rh = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "recipe_help.json"), "utf8"));
  for (const r of Object.values(rh.recipes ?? {})) if (r.when) keys.add(r.when);
  for (const p of Object.values(rh.params ?? {})) {
    if (p.help) keys.add(p.help);
    for (const v of Object.values(p.options ?? {})) keys.add(v);
  }
  return keys;
}

/** Kiegészítő átnézés (--audit): minden ékezetes (magyarnak látszó) szöveg-literál és JSX-szöveg, amelyhez nincs angol
 *  fordítás — így a konstansban álló és csak futáskor fordított feliratok hiánya is kiderül. Kivétel: import-útvonal,
 *  a `// i18n-ignore` megjegyzésű sor (pl. keresési minta, magyar formátumpélda). */
export function audit(files, known) {
  const hu = /[áéíóöőúüűÁÉÍÓÖŐÚÜŰ]/;
  const out = [];
  for (const f of files) {
    const text = fs.readFileSync(f, "utf8");
    const lines = text.split("\n");
    const src = ts.createSourceFile(f, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const report = (n, value) => {
      const v = value.trim();
      if (!v || !hu.test(v) || known.has(v)) return;
      const line = src.getLineAndCharacterOfPosition(n.getStart()).line;
      if (/i18n-ignore/.test(lines[line] ?? "")) return;
      out.push(`${path.relative(UI, f)}:${line + 1}: ${v.slice(0, 90)}`);
    };
    const visit = (n) => {
      if (ts.isImportDeclaration(n)) return;
      if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) report(n, n.text);
      else if (ts.isJsxText(n)) report(n, n.text);
      else if (ts.isTemplateExpression(n)) report(n, n.head.text + n.templateSpans.map((x) => "{{…}}" + x.literal.text).join(""));
      ts.forEachChild(n, visit);
    };
    visit(src);
  }
  return out;
}

function dictionaries() {
  const dir = path.join(UI, "src", "i18n");
  return fs.readdirSync(dir).filter((f) => /^en-.*\.json$/.test(f)).sort()
    .map((f) => [f, JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"))]);
}

const direct = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (!direct) {
  // modulként betöltve (pl. kulcslistához): nem fut ellenőrzés
} else if (process.argv.includes("--self-test")) {
  assert.deepEqual(validate(["Szia {{név}}"], [["ok", { "Szia {{név}}": "Hi {{név}}" }]]), []);
  assert.ok(validate(["Szia"], [["hiány", {}]]).some((e) => e.includes("hiányzó")));
  assert.ok(validate(["Szia"], [["üres", { Szia: "" }]]).some((e) => e.includes("üres")));
  assert.ok(validate(["Szia {{a}}"], [["rossz", { "Szia {{a}}": "Hi {{b}}" }]]).some((e) => e.includes("helyőrző")));
  assert.ok(validate(["Szia"], [["egy", { Szia: "Hi" }], ["kettő", { Szia: "Hey" }]]).some((e) => e.includes("eltérő fordítás")));
  console.log("check-i18n önteszt: rendben");
} else if (process.argv.includes("--audit")) {
  const known = new Set(dictionaries().flatMap(([, d]) => Object.keys(d)));
  const files = walk(path.join(UI, "src")).filter((f) => !f.includes(`${path.sep}i18n${path.sep}`));
  const found = audit(files, known);
  if (found.length) {
    console.error(found.join("\n"));
    console.error(`\n${found.length} fordítatlan magyar szöveg (vagy jelöld // i18n-ignore megjegyzéssel, ha nem felirat).`);
    process.exit(1);
  }
  console.log("check-i18n --audit: nincs fordítatlan magyar szöveg.");
} else {
  const required = new Set([...uiKeys(walk(path.join(UI, "src"))), ...serverKeys()]);
  const errors = validate([...required].sort(), dictionaries());
  if (errors.length) {
    console.error(errors.join("\n"));
    console.error(`\n${errors.length} hiba (${required.size} kötelező felirat).`);
    process.exit(1);
  }
  console.log(`check-i18n: rendben, ${required.size} felirat mind lefordítva.`);
}
