// Output templates (179, plan 170 L4, DECISIONS 178): a person's own Excel templates of the three downloads that can have
// one - a package's result, its utility cost, a reconciliation statement. A template is an Excel workbook with markers in
// its cells; the system writes the data into them and keeps the workbook's look. Here a template is uploaded (the
// service reads the file the system's file picker chose, and checks it: a refused file names every problem with its
// cell), each version previewed with made-up data, made active or retired; the markers are listed to copy. A package
// chooses its template next to each download (`components/TemplateChoice.tsx`); without a choice the built-in template
// makes the file, as before. 196: the quote's template is a Word document with the same markers.
import { useMemo, useState } from "react";
import {
  api, ApiError, type OutputMarkerGroup, type OutputName, type OutputTemplate, type OutputTemplateCheck,
  type OutputTemplateIssue, type OutputTemplateVersion,
} from "../../api";
import { UsedBy, useUsedBy } from "../../components/UsedBy";
import { BlockerList } from "../../components/BlockerList";
import { BrowseButton } from "../../components/BrowseButton";
import { ConfirmButton } from "../../components/ConfirmButton";
import { FormActions } from "../../components/FormActions";
import { DataTable } from "../../components/DataTable";
import { ItemSteps } from "../../components/ItemSteps";
import { PageActions } from "../../components/PageActions";
import { Icon } from "../../components/Icon";
import { Picker } from "../../components/Picker";
import { VersionState } from "../../components/VersionState";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { go, settingsHash } from "../../route";
import { settingsChanged, useSettingsCrumb, useSettingsTitle } from "./settingsTree";

const LIST = "settings_output_templates";
const NEW = "new";
const UPLOAD = "upload";
const MARKERS = "markers";
import { when } from "../../labels";

/** The outputs in the order the settings page shows them; the labels name the downloads as the Result section does. */
export const OUTPUTS: { key: OutputName; label: string; hint: string; format: "xlsx" | "docx" }[] = [
  { key: "package_result", label: "Package result", hint: "The full Excel package of a package's result, and the workbook a release stores", format: "xlsx" },
  { key: "utility_cost", label: "Utility cost", hint: "The utility cost by month of a package with utility bills, and the workbook its release stores", format: "xlsx" },
  { key: "reconcile_statement", label: "Reconciliation statement", hint: "A reconciliation package's statement: the draft's download and the file its approval stores", format: "xlsx" },
  { key: "quote", label: "Quote", hint: "A quote's Word document: the draft's download and the file its approval stores", format: "docx" },
];
export const outputLabel = (o: OutputName) => t(OUTPUTS.find((x) => x.key === o)?.label ?? o);


/** A check's problem or warning in words; the cell (`Sheet!B4`) and the detail are shown beside it. */
export function issueText(code: string): string {
  const text: Record<string, string> = {
    too_large: t("The file is too large."),
    not_xlsx: t("The file is not an Excel workbook (.xlsx)."),
    not_docx: t("The file is not a Word document (.docx)."),
    unsafe_content: t("The file holds active content (a macro or an embedded object); such a file is not accepted."),
    unreadable: t("The file cannot be read."),
    external_link: t("The file links to another file."),
    field: t("A field that computes or imports, such as = or INCLUDETEXT. A template holds no calculation: a total is a marker. Page numbers, dates and links may stay."),
    months_in_word: t("The months spread across columns, which only an Excel template can do."),
    nested_rows: t("A repeated table row stands inside another repeated row."),
    attached_template: t("The document names the template it was made from, a file on a computer; the name is removed when the document is filled."),
    data_connection: t("The workbook has a data connection."),
    unknown_marker: t("A marker this output does not have."),
    row_mixes_tables: t("One row holds the columns of two tables; a table's columns stand in a row of their own."),
    formula: t("A formula. A template holds no formula: a total or a count is a marker, the system computes it."),
    table_in_two_rows: t("A table's columns stand in two rows; they belong in one row, which is repeated."),
    merged_row: t("A merged cell in a table's row; the repeated row cannot keep it."),
    value_in_row: t("A single value in a table's row; it would be repeated with every row."),
    months_not_last: t("The months' marker must stand alone in its cell, with nothing to its right in its row."),
    no_marker: t("The workbook has no marker."),
    conditional_formatting: t("Conditional formatting: kept, but it does not spread to the repeated rows."),
    data_validation: t("Data validation: kept, but it does not spread to the repeated rows."),
  };
  return text[code] ?? code;
}

function Issues({ items, warning }: { items: OutputTemplateIssue[]; warning?: boolean }) {
  useLocale();
  return (
    <BlockerList parts items={items.map((p, i) => ({ key: `${p.code}:${p.where}:${i}`, warning, content: <>
        {p.where ? <span className="mono">{p.where}</span> : null}
        <span>{issueText(p.code)}</span>
        <IssueDetail issue={p} />
      </> }))} />
  );
}

// the check's reason for a marker it does not know (`jav/app/outputs/markers.py`), in words: `{{x}}: <reason>`
const MARKER_REASONS: [RegExp, (m: string[]) => string][] = [
  [/^not a marker name$/, () => t("it is not written as a marker")],
  [/^no value (\w+)$/, (m) => t("the output has no value {{name}}", { name: m[1] })],
  [/^no table (\w+)$/, (m) => t("the output has no table {{name}}", { name: m[1] })],
  [/^table (\w+) has no column (\w+)$/, (m) => t("table {{table}} has no column {{column}}", { table: m[1], column: m[2] })],
  [/^table (\w+) has no months$/, (m) => t("table {{table}} has no months", { table: m[1] })],
  [/^column (\S+) is not a number$/, (m) => t("column {{column}} is not a number, so it has no total", { column: m[1] })],
  [/^no :(\w+) for (a value|the months|a column)$/, (m) => t("“:{{op}}” cannot be used here", { op: m[1] })],
];

/** The detail beside a problem: the size of a file too large, the marker and the reason of an unknown one, the tables
 *  or markers a row mixes; a library's own message (an unreadable or unsafe file) is not shown, the text says it. */
function IssueDetail({ issue }: { issue: OutputTemplateIssue }) {
  useLocale();
  if (!issue.detail || issue.code === "unsafe_content" || issue.code === "unreadable") return null;
  if (issue.code === "too_large") return <span className="muted tnum">{sizeText(Number(issue.detail))}</span>;
  if (issue.code === "unknown_marker") {
    const at = issue.detail.indexOf("}}: ");
    const marker = at < 0 ? issue.detail : issue.detail.slice(0, at + 2);
    const reason = at < 0 ? "" : issue.detail.slice(at + 4);
    const known = MARKER_REASONS.map(([re, say]) => [reason.match(re), say] as const).find(([m]) => m);
    return (
      <>
        <span className="mono">{marker}</span>
        {reason ? <span className="muted">{known ? known[1]([...known[0]!]) : reason}</span> : null}
      </>
    );
  }
  return <span className="mono muted">{issue.detail}</span>;
}

const sizeText = (bytes: number | null | undefined) =>
  bytes === null || bytes === undefined || Number.isNaN(bytes) ? "" : bytes < 1024 ? t("{{n}} B", { n: bytes })
    : bytes < 1024 * 1024 ? t("{{n}} kB", { n: Math.round(bytes / 1024) }) : t("{{n}} MB", { n: (bytes / 1024 / 1024).toFixed(1) });

/** 263 (plan E, E1; the owner's decisions of 2026-10-30): the templates are the one list; a template is a page of its
 *  own, an upload (a new template or a new version) a page of its own, and the markers to copy a page of their own. */
export function OutputTemplatesPanel({ item, tab }: { item?: string; tab?: string }) {
  useLocale();
  const data = useLoad("output-templates", api.outputTemplates);
  const templates = data.data?.templates ?? [];
  const tpl = item && item !== NEW && item !== MARKERS ? templates.find((x) => x.template === item) : undefined;
  const changed = () => { data.reload(); settingsChanged(); };
  useSettingsTitle(item === NEW ? t("Upload a template") : item === MARKERS ? t("The markers") : tpl ? (tab === UPLOAD ? t("New version") : tpl.name) : null);
  // 264 (F5): a new version's page has its template among the crumbs
  useSettingsCrumb(tpl && tab === UPLOAD ? { label: tpl.name, href: settingsHash("outputs", tpl.template) } : null);
  if (data.error) return <p className="notice error" role="alert">{data.error.message}</p>;
  if (!data.data) return <p className="muted">{t("Loading…")}</p>;
  if (item === MARKERS) return <MarkersCard groups={data.data.outputs} />;
  if (item === NEW || (tpl && tab === UPLOAD)) {
    return <UploadCard key={tpl?.template ?? NEW} again={tpl ?? null} onStart={() => undefined}
      onCancel={() => go({ view: "settings", section: "outputs", ...(tpl ? { item: tpl.template } : {}) })}
      onDone={() => { changed(); go({ view: "settings", section: "outputs", ...(tpl ? { item: tpl.template } : {}) }); }} />;
  }
  if (item && !tpl) return <p className="notice warn">{t("It is not among the templates (any more).")}</p>;
  if (tpl) {
    return (
      <>
        <PageActions>
          <ItemSteps list={LIST} />
          <a className="button secondary" href={settingsHash("outputs", tpl.template, UPLOAD)}>{t("New version")}</a>
        </PageActions>
        <OutputTemplates output={tpl.output} templates={[tpl]} onChanged={changed} />
      </>
    );
  }
  return (
    <section className="stage-stack" aria-label={t("Output templates")}>
      <PageActions><a className="button primary" href={settingsHash("outputs", NEW)}>{t("Upload a template")}</a></PageActions>
      <p className="muted small">
        {t("An own template is an Excel workbook or, for a quote, a Word document with markers, such as {{package}} or {{invoices.amount}}: the system writes the data into them and keeps the file's look. Without one, a download is made with the built-in template, as before. A package chooses its template next to each download.")}
      </p>
      <DataTable dataset={LIST} label={t("Output templates")} storageId={LIST} persist={LIST}
        toolbar={<a className="small" href={settingsHash("outputs", MARKERS)}>{t("The markers")} →</a>}
        emptyText={t("No own template: the built-in template makes every download.")} />
    </section>
  );
}

function UploadCard({ again, onDone, onCancel, onStart }: {
  again: OutputTemplate | null; onDone: (text: string) => void; onCancel: () => void; onStart: () => void;
}) {
  useLocale();
  // a new version keeps the template's output; its name can change (the template takes the newest name)
  const [output, setOutput] = useState<OutputName>(again?.output ?? "package_result");
  const [name, setName] = useState(again?.name ?? "");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<OutputTemplateCheck | null>(null);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const ready = !!name.trim() && !!path.trim() && !busy;
  const word = OUTPUTS.find((o) => o.key === output)?.format === "docx";

  async function upload() {
    setBusy(true);
    setRefused(null);
    setMsg(null);
    onStart();
    try {
      const v = await api.uploadOutputTemplate({ output, name: name.trim(), path: path.trim(), ...(again ? { template: again.template } : {}) });
      setName("");
      setPath("");
      onDone(t("Uploaded: {{name}}, version {{n}}, as a draft. Download its preview to check it, then make it active.", { name: v.name, n: v.version }));
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "template_refused" && err.check && "output" in err.check) setRefused(err.check);
      else setMsg({ error: true, text: err.code === "forbidden_path" ? t("The chosen place is not among the allowed places.") : err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide template-upload" aria-label={again ? t("New version of {{name}}", { name: again.name }) : t("Upload a template")}>
      <div className="card-head">
        <h3>{again ? t("New version of {{name}}", { name: again.name }) : t("Upload a template")}</h3>
      </div>
      <div className="form-row">
        <Picker label={t("Output")} value={output} disabled={!!again} className="template-output"
          options={OUTPUTS.map((o) => ({ value: o.key, label: t(o.label) }))} onChange={(v) => setOutput(v as OutputName)} />
        <label className="block grow">{t("Name")}
          <input value={name} maxLength={120} autoComplete="off" placeholder={t("for example: Monthly report for the board…")} onChange={(e) => setName(e.target.value)} />
        </label>
      </div>
      <div className="form-row">
        <label className="block grow">{word ? t("The document's full path (.docx)") : t("The workbook's full path (.xlsx)")}
          <input value={path} maxLength={2000} spellCheck={false} autoComplete="off" onChange={(e) => setPath(e.target.value)} />
        </label>
        <BrowseButton kind="files" initial={path} onPick={([p]) => setPath(p)} />
      </div>
      {/* 263 (F1): "Cancel" and the upload at the foot, on the right (as the price lists') */}
      <FormActions onCancel={onCancel} busy={busy} note={t("The file is checked before it is stored; a stored version never changes.")}>
        <button type="button" className="primary" disabled={!ready} onClick={() => void upload()}>
          {busy ? t("Checking…") : t("Upload and check")}
        </button>
      </FormActions>
      {refused ? (
        <div role="alert" className="template-refused">
          <p className="error-text">{t("The template was not stored: the check found {{n}} problem(s).", { n: refused.problems.length })}</p>
          <Issues items={refused.problems} />
          {refused.warnings.length ? <Issues items={refused.warnings} warning /> : null}
        </div>
      ) : null}
      {msg ? <p role="status" className={msg.error ? "notice error" : "small ok"}>{msg.text}</p> : null}
    </section>
  );
}

/** One output's templates: every version as a row, newest first, with its state, its check's warnings and actions. */
function OutputTemplates({ output, templates, onChanged }: { output: OutputName; templates: OutputTemplate[]; onChanged: () => void }) {
  useLocale();
  const used = useUsedBy("output_template");
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const spec = OUTPUTS.find((o) => o.key === output)!;

  async function act(fn: () => Promise<OutputTemplateVersion>, done: (v: OutputTemplateVersion) => string) {
    setBusy(true);
    setMsg(null);
    try {
      const v = await fn();
      setMsg({ error: false, text: done(v) });
      onChanged();
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sheet template-output-block">
      <p className="muted small">{t(spec.label)} — {t(spec.hint)}</p>
      {templates.length === 0 ? (
        <p className="muted small">{t("No own template: the built-in template makes this download.")}</p>
      ) : (
        <table className="table compact template-table">
          {/* the same columns in every output's table, so the three read as one list */}
          <colgroup>
            <col className="c-name" /><col className="c-version" /><col className="c-state" /><col className="c-uploaded" />
            <col className="c-check" /><col className="c-files" /><col className="c-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>{t("Template")}</th><th className="num">{t("Version")}</th><th>{t("State")}</th><th>{t("Uploaded")}</th>
              <th>{t("The check")}</th><th>{t("Files")}</th><th><span className="sr-only">{t("Actions")}</span></th>
            </tr>
          </thead>
          <tbody>
            {templates.flatMap((tpl) => tpl.versions.map((v, i) => (
              <tr key={`${tpl.template}:${v.version}`} className={i === 0 ? "template-first" : ""}>
                {i === 0 ? (
                  <td rowSpan={tpl.versions.length} className="template-name">
                    <div><strong>{tpl.name}</strong></div>
                    <UsedBy used={used} ident={tpl.template} />
                  </td>
                ) : null}
                <td className="num tnum">{t("version {{n}}", { n: v.version })}</td>
                <td><VersionState state={v.state} /></td>
                <td className="template-uploaded"><span>{v.uploaded_by}</span><span className="muted tnum">{when(v.uploaded_at)}</span></td>
                <td>
                  {v.check.warnings.length ? (
                    <details className="template-warnings">
                      <summary><span className="status s-warn">{t("{{n}} warning(s)", { n: v.check.warnings.length })}</span></summary>
                      <Issues items={v.check.warnings} warning />
                    </details>
                  ) : <span className="muted small">{t("no problem")}</span>}
                </td>
                <td>
                  <span className="release-files">
                    <a href={api.outputTemplatePreviewUrl(v.template, v.version, spec.format)} download>{t("Preview (made-up data)")}</a>
                    <a href={api.outputTemplateFileUrl(v.template, v.version)} download title={v.file_name}>{t("The uploaded file")}</a>
                  </span>
                </td>
                <td className="template-actions">
                  {v.state === "active" ? (
                    <ConfirmButton className="quiet small-btn" disabled={busy} danger
                      onConfirm={() => void act(() => api.retireOutputTemplate(v.template),
                        () => t("Retired: {{name}}. The packages that chose it are made with the built-in template.", { name: tpl.name }))}>
                      {t("Retire")}
                    </ConfirmButton>
                  ) : (
                    <button type="button" className="secondary small-btn" disabled={busy}
                      onClick={() => void act(() => api.activateOutputTemplate(v.template, v.version),
                        (r) => t("Active: {{name}}, version {{n}}. A package can choose it next to its download.", { name: r.name, n: r.version }))}>
                      {t("Make active")}
                    </button>
                  )}
                </td>
              </tr>
            )))}
          </tbody>
        </table>
      )}
      {msg ? <p role="status" className={msg.error ? "notice error" : "small ok"}>{msg.text}</p> : null}
    </div>
  );
}

// the kinds of a marker's value, in words
const kindText = (k: string) => ({
  text: t("text"), date: t("date"), money: t("amount"), number: t("number"), count: t("count"), probability: t("probability"),
  flag: t("yes or empty"), json: t("structured text"),
} as Record<string, string>)[k] ?? k;

// the tables of the outputs, by their contract keys (`configs/outputs.json`)
const tableTitle = (key: string) => ({
  native_facts: t("Native facts"), native_readings: t("Native readings"), emails: t("Emails"), tasks: t("Tasks"),
  documents: t("Documents"), datapoints: t("Data points"), line_items: t("Line items"), utility_cost: t("Utility cost"),
  utility_sources: t("Utility cost sources"), invoices: t("Invoices"), lines: t("Statement lines"),
} as Record<string, string>)[key] ?? key;

const groupKey = (g: OutputMarkerGroup) => (g.table === null ? "values" : g.part ? `${g.table}:${g.part}` : g.table);
const groupTitle = (g: OutputMarkerGroup) =>
  g.table === null ? t("Values (each written once)") : g.part ? `${tableTitle(g.table)}: ${g.label ?? g.part}` : tableTitle(g.table);
const ALL = "*";

/** The markers of an output to copy, searchable, in groups: the values, then each table with its row count and months. */
function MarkersCard({ groups }: { groups: Record<OutputName, { markers: OutputMarkerGroup[] }> }) {
  useLocale();
  const [output, setOutput] = useState<OutputName>("package_result");
  const [table, setTable] = useState(ALL);
  const [q, setQ] = useState("");
  const all = groups[output]?.markers ?? [];
  const needle = q.trim().toLowerCase();
  const shown = useMemo(() => all.filter((g) => table === ALL || groupKey(g) === table).map((g) => ({
    ...g, rows: g.rows.filter((r) => !needle || `${r.marker} ${r.label} ${t(r.label)}`.toLowerCase().includes(needle)),
  })).filter((g) => g.rows.length || (!needle && (g.count || g.months))), [all, table, needle]);
  return (
    <section className="card wide" aria-label={t("Markers")}>
      <h3>{t("Markers")}</h3>
      <details className="marker-help">
        <summary>{t("How markers work")}</summary>
        <ul className="plain small">
          <li><span className="mono">{"{{package}}"}</span> {t("one value, written where the marker stands; a marker can stand inside a text")}</li>
          <li><span className="mono">{"{{invoices.amount}}"}</span> {t("a table's column: the row holding it is repeated for every row of the table, with that row's look")}</li>
          <li><span className="mono">{"{{invoices.amount:sum}}"}</span> · <span className="mono">{"{{invoices:count}}"}</span> {t("a column's total and a table's row count, written once, computed by the system")}</li>
          <li><span className="mono">{"{{invoice_hu.gross_total}}"}</span> {t("a table per document type is named by the type, its columns are the type's fields")}</li>
          <li><span className="mono">{"{{utility_cost.months}}"}</span> · <span className="mono">{"{{utility_cost.months:names}}"}</span> {t("one column per month, spreading to the right: its amounts in a table's row, its names in a header row")}</li>
        </ul>
      </details>
      <div className="form-row marker-filters">
        <Picker label={t("Output")} value={output} className="template-output"
          options={OUTPUTS.map((o) => ({ value: o.key, label: t(o.label) }))} onChange={(v) => { setOutput(v as OutputName); setTable(ALL); }} />
        <Picker label={t("Table")} value={table} className="template-output"
          options={[{ value: ALL, label: t("Every table") }, ...all.map((g) => ({ value: groupKey(g), label: groupTitle(g) }))]} onChange={setTable} />
        <label className="block grow">{t("Search")}
          <input type="search" value={q} spellCheck={false} autoComplete="off" placeholder={t("a marker or its label…")} onChange={(e) => setQ(e.target.value)} />
        </label>
      </div>
      <div className="marker-scroll">
        <table className="table compact marker-table">
          <thead>
            <tr><th>{t("Marker")}</th><th>{t("Label in the built-in template")}</th><th>{t("Kind")}</th><th>{t("Total")}</th></tr>
          </thead>
          {shown.map((g) => (
            <tbody key={groupKey(g)}>
              <tr className="marker-group">
                <th colSpan={4} scope="rowgroup">
                  <span>{groupTitle(g)}</span>
                  {g.count ? <span className="marker-extra">{t("row count")} <Copyable text={g.count} /></span> : null}
                  {g.months ? <span className="marker-extra">{t("months")} <Copyable text={g.months.row} /> <Copyable text={g.months.names} /></span> : null}
                </th>
              </tr>
              {g.rows.map((r) => (
                <tr key={r.marker}>
                  <td><Copyable text={r.marker} /></td>
                  <td>{t(r.label)}</td>
                  <td className="muted">{kindText(r.kind)}</td>
                  <td>{r.sum ? <Copyable text={r.sum} /> : null}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
        {shown.length === 0 ? <p className="muted small">{t("No marker matches.")}</p> : null}
      </div>
    </section>
  );
}

/** A marker in the code face with a button that copies it. */
function Copyable({ text }: { text: string }) {
  useLocale();
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false); // no clipboard (an insecure page): the marker can still be selected and copied by hand
    }
  }
  return (
    <span className="copyable">
      <code className="mono">{text}</code>
      <button type="button" className="quiet copy-btn" aria-label={t("Copy {{marker}}", { marker: text })} title={t("Copy the marker")} onClick={() => void copy()}>
        <Icon name={copied ? "check" : "copy"} />
      </button>
      {copied ? <span className="sr-only" role="status">{t("Copied")}</span> : null}
    </span>
  );
}
