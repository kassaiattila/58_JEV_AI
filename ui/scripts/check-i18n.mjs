// Translation completeness check (057, modelled on the legacy V4 `ui/scripts/check-i18n.mjs`, simplified).
// An English translation is required for:
//  - the string literal of every `t("…")` call in the interface (by TypeScript parsing, not by regex);
//  - the labels coming from the service: the dataset column names (`jav/app/datasets.py` `_col(...)`), the enumerated
//    labels (`configs/datasets.json` labels) and the field / column names (`configs/field_labels.json`).
// Errors: a missing key, an empty translation, a differing placeholder ({{name}}), the same key translated differently
// in two files.
// Run: `npm run i18n:check`; `--self-test`: checks the error branches.
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
      if (typeof v !== "string" || !v.trim()) errors.push(`${file}: empty translation: ${k}`);
      else if (holes(k) !== holes(v)) errors.push(`${file}: different placeholders: ${k}`);
      if (k in merged && merged[k] !== v) errors.push(`${file}: different translation: ${k}`);
      merged[k] = v;
    }
  }
  for (const k of required) if (!(k in merged)) errors.push(`missing English translation: ${k}`);
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
        // t(condition ? "a" : "b"): both branches are required
        if (ts.isConditionalExpression(a)) for (const b of [a.whenTrue, a.whenFalse]) if (ts.isStringLiteral(b)) keys.add(b.text);
      }
      // tmap({...}): every string value of the label map is required (it translates on read)
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
  const py = fs.readFileSync(path.join(ROOT, "jav", "app", "datasets.py"), "utf8");
  for (const m of py.matchAll(/_col\(\s*(?:f?"[^"]*"|[a-z_]+)\s*,\s*"([^"]+)"/g)) keys.add(m[1]);
  // 167 (review 160 U-15): the export's fixed columns are (key, label, kind) triples (`_DOC_KEYS`, `_DP_KEYS`, `_LI_KEYS`)
  for (const m of py.matchAll(/\(\s*"[a-z_]+"\s*,\s*"([^"]+)"\s*,\s*"(?:text|id|enum|number|date|datetime|money|bool)"\s*\)/g)) keys.add(m[1]);
  const ds = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "datasets.json"), "utf8"));
  for (const group of Object.values(ds.labels)) for (const v of Object.values(group)) keys.add(v);
  const fl = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "field_labels.json"), "utf8"));
  // 231 (U1): the names of the fields' enumerated values (`values`)
  for (const section of ["fields", "columns", "doc_types", "values"]) for (const v of Object.values(fl[section] ?? {})) keys.add(v);
  // 197: a type's own names of shared fields (`by_type`)
  for (const own of Object.values(fl.by_type ?? {})) for (const v of Object.values(own)) keys.add(v);
  // 058: the names of the email intents (in the to-do text and in the email view) appear translated in the interface
  const it = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "intents.json"), "utf8"));
  for (const i of it.intents ?? []) if (i.display_name) keys.add(i.display_name);
  // 058 K5.3: the names of the task actions
  const et = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "email_tasks.json"), "utf8"));
  for (const v of Object.values(et.actions ?? {})) keys.add(v);
  // the recipes' product text (title, description, steps) appears translated in the interface
  const rc = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "recipes.json"), "utf8"));
  for (const r of Array.isArray(rc.recipes) ? rc.recipes : Object.values(rc.recipes ?? {})) {
    // 063: the Recipes page also shows the requirements, the result and what the person has to do
    for (const v of [r.title, r.description, ...(r.steps ?? []), ...(r.requirements ?? []), r.result, r.manual_action]) if (v) keys.add(v);
  }
  // 063: the recipe explanations (when a recipe fits, what the settings and their values mean)
  const rh = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "recipe_help.json"), "utf8"));
  for (const r of Object.values(rh.recipes ?? {})) {
    for (const text of [r.when, r.title]) if (text) keys.add(text);
    for (const input of r.inputs ?? []) {
      keys.add(input.label);
      keys.add(input.description);
    }
    for (const p of Object.values(r.params ?? {})) {
      if (p.help) keys.add(p.help);
      for (const text of Object.values(p.options ?? {})) keys.add(text);
    }
  }
  // 080: the general introduction, the item kinds and the comparison of the paths (Settings › Processing)
  if (rh.intro) keys.add(rh.intro);
  for (const v of Object.values(rh.kinds ?? {})) keys.add(v);
  const paths = rh.paths ?? {};
  for (const v of [paths.intro, paths.measured, ...Object.values(paths.columns ?? {})]) if (v) keys.add(v);
  for (const row of paths.rows ?? []) for (const v of [row.label, row.S, row.G]) if (v) keys.add(v);
  for (const p of Object.values(rh.params ?? {})) {
    if (p.help) keys.add(p.help);
    for (const v of Object.values(p.options ?? {})) keys.add(v);
  }
  // 146: the bank files the system reads (Settings › Processing, the statement package's form)
  const bf = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "bank_files.json"), "utf8"));
  for (const v of [bf.intro, ...Object.values(bf.read_by ?? {}), ...Object.values(bf.checks ?? {}), ...(bf.not_read ?? [])]) if (v) keys.add(v);
  for (const f of bf.files ?? []) for (const v of [f.bank, f.statement, ...(f.formats ?? []), ...(f.notes ?? [])]) if (v) keys.add(v);
  // 218 (P3e): the rules' plain description (Settings › Rules): the areas, the rule files, each decision's texts and
  // the labels of its values
  const rules = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "rule_help.json"), "utf8"));
  for (const v of [...Object.values(rules.areas ?? {}), ...Object.values(rules.files ?? {})]) keys.add(v);
  for (const p of Object.values(rules.points ?? {})) {
    for (const v of [p.title, p.what, p.not_for]) if (v) keys.add(v);
    for (const value of p.values ?? []) {
      keys.add(value.label);
      for (const v of Object.values(value.labels ?? {})) keys.add(v);
    }
  }
  // 146: the new work wizard's groups, kinds and templates (configs/workflows.json)
  const wf = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", "workflows.json"), "utf8"));
  if (wf.intro) keys.add(wf.intro);
  for (const g of wf.groups ?? []) for (const v of [g.title, g.description]) if (v) keys.add(v);
  for (const k of Object.values(wf.kinds ?? {})) for (const v of [k.title, k.description, k.cost]) if (v) keys.add(v);
  for (const tp of wf.templates ?? []) {
    for (const v of [tp.title, tp.description]) if (v) keys.add(v);
    for (const s of tp.steps ?? []) if (s.title) keys.add(s.title);
  }
  // 231 (A6): the process packs' title, tab labels and step titles (configs/processes/*.json), shown on a case's page
  const packs = path.join(ROOT, "configs", "processes");
  for (const f of fs.existsSync(packs) ? fs.readdirSync(packs).filter((n) => n.endsWith(".json")) : []) {
    const pack = JSON.parse(fs.readFileSync(path.join(packs, f), "utf8"));
    if (pack.title) keys.add(pack.title);
    for (const tab of pack.screens?.tabs ?? []) if (tab.label) keys.add(tab.label);
    for (const s of pack.steps ?? []) if (s.title) keys.add(s.title);
    if (pack.summary) keys.add(pack.summary);  // 231 (U0): what the process is for, on the new case page
    if (pack.examples?.note) keys.add(pack.examples.note);  // 231 (U1e): how its example material is tried
  }
  // 231 (U0): the titles of a process's packets of example documents (configs/examples_*.json)
  for (const f of fs.readdirSync(path.join(ROOT, "configs")).filter((n) => /^examples_.*\.json$/.test(n))) {
    for (const packet of JSON.parse(fs.readFileSync(path.join(ROOT, "configs", f), "utf8")).packets ?? []) if (packet.title) keys.add(packet.title);
  }
  // 231 (U-A7): the fact catalogues' titles and labels (configs/facts_*.json), shown on a case's data check and rules
  for (const f of fs.readdirSync(path.join(ROOT, "configs")).filter((n) => /^facts_.*\.json$/.test(n))) {
    const cat = JSON.parse(fs.readFileSync(path.join(ROOT, "configs", f), "utf8"));
    for (const d of [...Object.values(cat.facts ?? {}), ...Object.values(cat.outcomes ?? {})]) if (d.title) keys.add(d.title);
    for (const v of Object.values(cat.labels ?? {})) keys.add(v);
  }
  return keys;
}

/** Supplementary review (--audit): every accented (Hungarian-looking) string literal and JSX text that has no English
 *  translation — so missing translations also come to light for labels that sit in a constant and are only translated
 *  at run time. Exceptions: an import path, a line with the `// i18n-ignore` comment (e.g. a search pattern, a Hungarian
 *  format example). */
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
  // loaded as a module (e.g. for the key list): no check runs
} else if (process.argv.includes("--self-test")) {
  assert.deepEqual(validate(["Szia {{név}}"], [["ok", { "Szia {{név}}": "Hi {{név}}" }]]), []);
  assert.ok(validate(["Szia"], [["hiány", {}]]).some((e) => e.includes("missing")));
  assert.ok(validate(["Szia"], [["üres", { Szia: "" }]]).some((e) => e.includes("empty")));
  assert.ok(validate(["Szia {{a}}"], [["rossz", { "Szia {{a}}": "Hi {{b}}" }]]).some((e) => e.includes("placeholders")));
  assert.ok(validate(["Szia"], [["egy", { Szia: "Hi" }], ["kettő", { Szia: "Hey" }]]).some((e) => e.includes("different translation")));
  console.log("check-i18n self-test: passed");
} else if (process.argv.includes("--audit")) {
  const known = new Set(dictionaries().flatMap(([, d]) => Object.keys(d)));
  const files = walk(path.join(UI, "src")).filter((f) => !f.includes(`${path.sep}i18n${path.sep}`));
  const found = audit(files, known);
  if (found.length) {
    console.error(found.join("\n"));
    console.error(`\n${found.length} untranslated Hungarian text(s) (or mark one with an // i18n-ignore comment if it is not a label).`);
    process.exit(1);
  }
  console.log("check-i18n --audit: no untranslated Hungarian text.");
} else {
  const required = new Set([...uiKeys(walk(path.join(UI, "src"))), ...serverKeys()]);
  const errors = validate([...required].sort(), dictionaries());
  if (errors.length) {
    console.error(errors.join("\n"));
    console.error(`\n${errors.length} error(s) (${required.size} required label(s)).`);
    process.exit(1);
  }
  console.log(`check-i18n: passed, all ${required.size} label(s) translated.`);
}
