// 218 (plan G-process-core P3e; the owner's request and decisions of 2026-10-23): Settings › Rules — how the system
// decides on its own, read only. One row per kind of decision it records (the `rules` dataset, jav/app/rules_view.py):
// its area, what it decides, its rule values, the version of each rule file in use and how many decisions it has made.
// A row stays within four lines (a title of up to two, what it decides in two); a decision's title opens its whole rule below the table: what it decides and what it
// is not for, every value, the rule files with their versions and since when they are in use, and the count. The texts
// are English source strings from `configs/rule_help.json`, translated here; a value's codes come as the interface's
// own labels, an email's next step by its code (named as everywhere). The price lists and the output templates, which a
// person edits, are linked to their own pages. 231 (U4d; the owner's decisions of 2026-10-29): the page is Settings ›
// Defaults: a value on a decision's sheet may be given the installation's own value (`DefaultEditor`).
import { Fragment, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { api, type Defaults, type DsColumn, type DsPage, type DsRow } from "../../api";
import { DataTable } from "../../components/DataTable";
import { useLoad } from "../../hooks";
import { getLocale, t, useLocale } from "../../i18n";
import { moneyText, nextFlowText, numText, when } from "../../labels";
import { DefaultEditor } from "./DefaultEditor";

type Step = { code: string; reads_text: boolean };
export interface RuleValue {
  file: string; key: string; label: string;
  format: "percent" | "points" | "yes_no" | "number" | "names" | "name" | "route" | "routes" | "usd";
  value: unknown;
}
export interface RuleFile { file: string; title: string; version: string | null; dated: string | null; count: number | null; since: string | null }

const NO_SCOPE = {};
const stepText = (s: Step) => nextFlowText(s.code, s.reads_text);

/** A rule value in the chosen language: a probability as a percentage, a gap in percentage points, the codes by their
 *  labels. */
export function valueText(v: RuleValue): string {
  switch (v.format) {
    case "percent": return `${numText(Number(v.value) * 100, 1)}\u00a0%`; // the sign never on a line of its own
    case "points": return t("{{n}} percentage points", { n: numText(Number(v.value) * 100, 1) });
    case "yes_no": return v.value ? t("yes") : t("no");
    case "number": return numText(v.value);
    case "names": return (v.value as string[]).map((n) => t(n)).join(", ");
    case "name": return t(String(v.value));
    case "route": return stepText(v.value as Step);
    case "routes": return (v.value as [string, Step][]).map(([intent, step]) => `${t(intent)} → ${stepText(step)}`).join("; ");
    case "usd": return (v.value as [string, string][]).map(([provider, amount]) => `${provider} ${moneyText(amount)} USD`).join(", ");
    default: return String(v.value ?? "");
  }
}

/** A threshold's label reads on into its value ("… below 60 %"); any other label is followed by a colon. */
const COMPARED = new Set(["percent", "points"]);
const labelText = (v: RuleValue) => (COMPARED.has(v.format) ? t(v.label) : `${t(v.label)}:`);
export const lineText = (v: RuleValue) => `${labelText(v)} ${valueText(v)}`;

const dayText = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(getLocale());

function versionText(f: RuleFile): string {
  if (!f.version) return t("{{n}} files", { n: f.count ?? 0 });
  return f.dated ? t("version {{version}} of {{date}}", { version: f.version, date: dayText(f.dated) })
    : t("version {{version}}", { version: f.version });
}

const sinceText = (f: RuleFile) => (f.since ? t("in use here since {{when}}", { when: when(f.since) })
  : t("no run or decision has used it here yet"));

/** At most `lines` lines in a table cell; the whole text is the tooltip (as the table's own clamp). */
function Clamp({ lines, title, children, className }: { lines: number; title: string; children: ReactNode; className?: string }) {
  return <div className={`dt-clamp${className ? ` ${className}` : ""}`} style={{ WebkitLineClamp: lines }} title={title}>{children}</div>;
}

function ValuesCell({ values }: { values: RuleValue[] }) {
  if (!values.length) return <span className="muted">–</span>;
  return (
    <Clamp lines={4} title={values.map(lineText).join("\n")}>
      {values.map((v, i) => (
        <Fragment key={v.key}>
          <span className="muted">{labelText(v)}</span> {valueText(v)}{i < values.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </Clamp>
  );
}

function FilesCell({ files }: { files: RuleFile[] }) {
  return (
    <Clamp lines={4} title={files.map((f) => `${t(f.title)} (${f.file}): ${versionText(f)}`).join("\n")}>
      {files.map((f, i) => (
        <Fragment key={f.file}>
          {t(f.title)} <span className="muted tnum">{f.version ?? t("{{n}} files", { n: f.count ?? 0 })}</span>
          {i < files.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </Clamp>
  );
}

/** 231 (U4d): a value's default by its id (`<file>.<key>`, the file without its `.json`). */
const defaultId = (v: RuleValue) => `${v.file.replace(/\.json$/, "")}.${v.key}`;

function RuleSheet({ row, area, sheet, onClose, defaults, onDefaults }: {
  row: DsRow; area: string; sheet: RefObject<HTMLElement | null>; onClose: () => void; defaults: Defaults | null; onDefaults: () => void;
}) {
  const values = (row._values ?? []) as RuleValue[];
  const byId = new Map((defaults?.keys ?? []).map((k) => [k.id, k]));
  const files = (row._files ?? []) as RuleFile[];
  const n = Number(row.decisions ?? 0);
  return (
    <section id="rule-sheet" ref={sheet} className="card wide recipe-doc rule-sheet" aria-labelledby="rule-sheet-title">
      <div className="card-head">
        <div>
          <h3 id="rule-sheet-title" tabIndex={-1}>{t(String(row.decision))}</h3>
          {area ? <span className="muted small">{area}</span> : null}
        </div>
        <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
      </div>
      <p className="rule-what">{t(String(row.what))}</p>
      <p className="muted rule-what">{t("Not for: {{text}}", { text: t(String(row.not_for)) })}</p>
      <h4>{t("Rule values")}</h4>
      {values.length ? (
        <dl className="rule-values">
          {values.map((v) => (
            <Fragment key={v.key}>
              <dt>{t(v.label)}</dt>
              <dd>
                {v.format === "routes" ? (
                  <ul className="tight">
                    {(v.value as [string, Step][]).map(([intent, step]) => <li key={intent}>{t(intent)} → {stepText(step)}</li>)}
                  </ul>
                ) : valueText(v)}
                {defaults ? <DefaultEditor v={v} entry={byId.get(defaultId(v))} fixed={defaults.fixed[defaultId(v)]} onChanged={onDefaults} /> : null}
              </dd>
            </Fragment>
          ))}
        </dl>
      ) : <p className="muted">{t("No value of this rule is described yet.")}</p>}
      <h4>{t("Rule files")}</h4>
      <ul className="tight">
        {files.map((f) => (
          <li key={f.file}>
            {t(f.title)} <span className="mono small">{f.file}</span>: <span className="tnum">{versionText(f)}</span> · {sinceText(f)}
          </li>
        ))}
      </ul>
      <h4>{t("Decisions")}</h4>
      <p>
        {n ? t("{{n}} decisions recorded, {{current}} of them with the rules in use now; the last on {{when}}.", {
          n: numText(n, 0), current: numText(Number(row.current ?? 0), 0), when: when(String(row.last_at)),
        }) : t("No decision of this kind has been recorded yet.")}
      </p>
    </section>
  );
}

export function RulesPanel() {
  useLocale();
  const [page, setPage] = useState<DsPage | null>(null);
  const [open, setOpen] = useState<DsRow | null>(null);
  const defaults = useLoad("defaults", api.defaults);  // 231 (U4d): what the installation may set, and its own values
  const sheet = useRef<HTMLElement>(null);
  useEffect(() => { // the opened rule comes into view whole, and its title takes the focus (a screen reader reads it)
    if (!open) return;
    sheet.current?.scrollIntoView?.({ block: "start" });
    sheet.current?.querySelector<HTMLElement>("h3")?.focus({ preventScroll: true });
  }, [open]);
  const areas = page?.columns.find((c) => c.key === "area")?.labels ?? {};
  const rows = page?.rows ?? [];
  const cell = (col: DsColumn, row: DsRow): ReactNode | undefined => {
    if (col.key === "area") { // an area's name heads its group once, in the order shown; a screen reader hears it on each row
      const name = t(col.labels?.[String(row.area)] ?? String(row.area ?? ""));
      const i = rows.findIndex((r) => r._key === row._key);
      return i > 0 && rows[i - 1].area === row.area ? <span className="sr-only">{name}</span> : name;
    }
    if (col.key === "decisions" && !Number(row.decisions)) return <span className="count-zero">0</span>;
    if (col.key === "decision") {
      const what = t(String(row.what));
      return (
        <>
          <button type="button" className="link-btn rule-open" aria-expanded={open?._key === row._key} aria-controls="rule-sheet"
            onClick={() => setOpen(open?._key === row._key ? null : row)}>{t(String(row.decision))}</button>
          <Clamp lines={2} title={what} className="muted">{what}</Clamp>
        </>
      );
    }
    if (col.key === "values") return <ValuesCell values={(row._values ?? []) as RuleValue[]} />;
    if (col.key === "files") return <FilesCell files={(row._files ?? []) as RuleFile[]} />;
    return undefined;
  };
  return (
    <div className="rc-stack">
      <p className="page-summary">
        {t("Each row is one kind of decision the system records: what it decides, the values it decides with, the version of its rule files in use, and how many decisions it has made. Open a decision to set its values' defaults: a draft, tried on the earlier decisions, then made active; the cases that start after use it, and a process's own value still goes over it. A value that costs money stays the file's.")}
      </p>
      <p className="small muted">
        {t("You edit the price lists and the output templates yourself, on their own pages:")}{" "}
        <a href="#/settings/prices">{t("Price lists")}</a> · <a href="#/settings/outputs">{t("Output templates")}</a>
      </p>
      <DataTable dataset="rules" scope={NO_SCOPE} label={t("Rules")} storageId="rules" onPage={setPage} cell={cell}
        emptyText={t("No decision is described yet.")} />
      {open ? (
        <RuleSheet row={open} area={open.area ? t(areas[String(open.area)] ?? String(open.area)) : ""} sheet={sheet}
          onClose={() => setOpen(null)} defaults={defaults.data ?? null} onDefaults={defaults.reload} />
      ) : <p className="muted small">{t("Choose a decision's title to read its whole rule.")}</p>}
    </div>
  );
}
