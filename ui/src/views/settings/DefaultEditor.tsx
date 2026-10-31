// 231 (stage U, U4d; the owner's decisions of 2026-10-29): a rule value's default, under the value on the rule's sheet
// (Settings › Defaults). A value the installation may set shows whether its own value or the file's counts, a form
// fitting its kind (a percentage, a whole number, an amount, yes or no, one of a list, a set, a map of routes, an
// ordered list of codes), the
// value's try on the earlier decisions, and its versions: a draft is made active by the process values' rule, and
// "Back to the file's value" sets the own value aside. A value that stays the file's says why. A case keeps the values
// of its start; a process's own value still goes over a default.
import { useState } from "react";
import { api, ApiError, type DefaultKey, type DefaultPreview, type DefaultValue, type FixedWhy } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { FormActions } from "../../components/FormActions";
import { VersionState } from "../../components/VersionState";
import { t, useLocale } from "../../i18n";
import { docTypeLabel, nextFlowText, numText, when } from "../../labels";
import type { RuleValue } from "./RulesPanel";

const FIXED_TEXT: Record<FixedWhy, string> = {
  cost: "Stays the file's value: it changes a paid request or a budget.",
  structure: "Stays the file's value: it is the catalogue's structure.",
  format: "Stays the file's value: it is a property of a number's format.",
};

/** A percentage or a gap in percentage points is edited as a percentage. */
const asPercent = (entry: DefaultKey, v: RuleValue) => entry.kind === "number" && (v.format === "percent" || v.format === "points");
const codeText = (code: string) => (docTypeLabel(code) !== code ? docTypeLabel(code) : t(code));
const optionText = (v: RuleValue, code: string) => (v.format === "route" || v.format === "routes" ? nextFlowText(code) : codeText(code));

/** A default's value in words, as the rule's sheet shows the file's. */
export function defaultText(entry: DefaultKey, v: RuleValue, value: DefaultValue): string {
  if (asPercent(entry, v)) {
    const n = numText(Number(value) * 100, 1);
    return v.format === "points" ? t("{{n}} percentage points", { n }) : `${n} %`;
  }
  if (entry.kind === "bool") return value ? t("yes") : t("no");
  if (entry.kind === "int" || entry.kind === "amount") return numText(value as number | string);
  if (entry.kind === "set" || entry.kind === "list") return (value as string[]).map(codeText).join(", ") || "–";
  if (entry.kind === "map") return Object.entries(value as Record<string, string>).map(([k, code]) => `${t(k)} → ${optionText(v, code)}`).join("; ");
  if (entry.kind === "choice") return v.format === "number" ? numText(String(value)) : optionText(v, String(value));
  return String(value);
}

type Draft = string | boolean | string[] | Record<string, string>;
const NL = String.fromCharCode(10);  // a list's codes, one a line

function draftOf(entry: DefaultKey, v: RuleValue): Draft {
  const value = entry.value ?? entry.file_value;
  if (asPercent(entry, v)) return numText(Number(value) * 100, 2);
  if (entry.kind === "int" || entry.kind === "number") return String(value);
  if (entry.kind === "set") return [...(value as string[])];
  if (entry.kind === "list") return (value as string[]).join(NL);
  if (entry.kind === "map") return { ...(value as Record<string, string>) };
  return value as Draft;
}

/** The value the form holds, as the service takes it (null: not a number). */
function valueOf(entry: DefaultKey, v: RuleValue, draft: Draft): DefaultValue | null {
  if (entry.kind === "int" || entry.kind === "number") {
    const n = Number(String(draft).replace(",", ".").replace(/\s/g, ""));
    if (!String(draft).trim() || !Number.isFinite(n)) return null;
    if (asPercent(entry, v)) return Math.round(n * 100) / 10000;
    return entry.kind === "int" ? Math.trunc(n) : n;
  }
  if (entry.kind === "amount") return String(draft).replace(",", ".").replace(/\s/g, "");
  if (entry.kind === "set") return entry.options.filter((o) => (draft as string[]).includes(o));
  if (entry.kind === "list") return String(draft).split(NL).map((line) => line.trim()).filter(Boolean);
  return draft as DefaultValue;
}

export function DefaultEditor({ v, entry, fixed, onChanged }: {
  v: RuleValue; entry: DefaultKey | undefined; fixed: FixedWhy | undefined; onChanged: () => void;
}) {
  useLocale();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  if (!entry) return fixed ? <p className="muted small default-line">{t(FIXED_TEXT[fixed])}</p> : null;

  async function act(fn: () => Promise<unknown>, done: string): Promise<boolean> {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ error: false, text: done });
      onChanged();
      return true;
    } catch (e) {
      setMsg({ error: true, text: e instanceof ApiError ? e.message : String(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="default-editor">
      <p className="small default-line">
        {entry.active
          ? <>{t("The installation's own value: version {{n}}", { n: entry.active })} <span className="muted">· {t("the file's: {{value}}", { value: defaultText(entry, v, entry.file_value) })}</span></>
          : <span className="muted">{t("The file's value counts.")}</span>}
        {!editing ? <> <button type="button" className="secondary small-btn" disabled={busy} onClick={() => { setMsg(null); setEditing(true); }}>{t("Set a default")}</button></> : null}
      </p>
      {editing ? (
        <DefaultForm v={v} entry={entry} busy={busy} onCancel={() => setEditing(false)}
          onSave={async (value, note) => {
            if (await act(() => api.proposeDefault(entry.id, value, note), t("Saved as a draft. Make it active to use it."))) setEditing(false);
          }} />
      ) : null}
      {entry.versions.length ? (
        <div className="default-versions-wrap">
        <table className="table compact default-versions" aria-label={t("Versions")}>
          <thead><tr><th className="num">{t("Version")}</th><th>{t("Value")}</th><th>{t("State")}</th><th>{t("Made by")}</th><th><span className="sr-only">{t("Actions")}</span></th></tr></thead>
          <tbody>
            {entry.versions.map((x) => (
              <tr key={x.version}>
                <td className="num tnum">{t("version {{n}}", { n: x.version })}</td>
                <td>{defaultText(entry, v, x.value)}</td>
                <td><VersionState state={x.state} /></td>
                <td>
                  <span>{x.made_by}</span> <span className="muted tnum">{when(x.made_at)}</span>
                  {x.note ? <span className="muted small default-note">{x.note}</span> : null}
                </td>
                <td className="button-row">
                  {x.state === "draft" || x.state === "superseded" ? (
                    <button type="button" className="secondary small-btn" disabled={busy}
                      onClick={() => void act(() => api.activateDefault(entry.id, x.version), t("Version {{n}} is active: the cases that start from now on use it.", { n: x.version }))}>
                      {t("Make version {{n}} active", { n: x.version })}
                    </button>
                  ) : null}
                  {x.state === "active" ? (
                    <ConfirmButton className="secondary small-btn" disabled={busy}
                      onConfirm={() => void act(() => api.retireDefault(entry.id), t("The file's value counts again for the cases that start from now on."))}>
                      {t("Back to the file's value")}
                    </ConfirmButton>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      ) : null}
      {msg ? <p role="status" className={msg.error ? "notice error" : "small ok"}>{msg.text}</p> : null}
    </div>
  );
}

function DefaultForm({ v, entry, busy, onCancel, onSave }: {
  v: RuleValue; entry: DefaultKey; busy: boolean; onCancel: () => void; onSave: (value: DefaultValue, note: string | null) => void;
}) {
  useLocale();
  const [draft, setDraft] = useState<Draft>(() => draftOf(entry, v));
  const [note, setNote] = useState("");
  const [tried, setTried] = useState<DefaultPreview | null>(null);
  const [tryError, setTryError] = useState<string | null>(null);
  const value = valueOf(entry, v, draft);
  const label = t(entry.what);
  async function tryIt() {
    if (value === null) return;
    setTryError(null);
    try {
      setTried(await api.previewDefault(entry.id, value));
    } catch (e) {
      setTried(null);
      setTryError(e instanceof ApiError ? e.message : String(e));
    }
  }
  const change = (d: Draft) => { setDraft(d); setTried(null); };
  return (
    <form className="default-form" aria-label={t("Set a default")} onSubmit={(e) => { e.preventDefault(); if (value !== null) onSave(value, note.trim() || null); }}>
      {entry.kind === "bool" ? (
        <label className="block">{label}
          <select value={draft ? "yes" : "no"} onChange={(e) => change(e.target.value === "yes")}>
            <option value="yes">{t("yes")}</option><option value="no">{t("no")}</option>
          </select>
        </label>
      ) : entry.kind === "choice" ? (
        <label className="block">{label}
          <select value={String(draft)} onChange={(e) => change(e.target.value)}>
            {entry.options.map((o) => <option key={o} value={o}>{optionText(v, o)}</option>)}
          </select>
        </label>
      ) : entry.kind === "set" ? (
        <fieldset className="default-set">
          <legend>{label}</legend>
          {entry.options.map((o) => (
            <label key={o} className="check">
              <input type="checkbox" checked={(draft as string[]).includes(o)}
                onChange={(e) => change(e.target.checked ? [...(draft as string[]), o] : (draft as string[]).filter((x) => x !== o))} /> {codeText(o)}
            </label>
          ))}
        </fieldset>
      ) : entry.kind === "list" ? (
        <label className="block">{label}
          <textarea value={String(draft)} rows={Math.max(3, String(draft).split(NL).length + 1)} onChange={(e) => change(e.target.value)} />
          <span className="muted small">{t("One code a line, in their order.")}</span>
        </label>
      ) : entry.kind === "map" ? (
        <fieldset className="default-map">
          <legend>{label}</legend>
          {Object.keys(entry.file_value as Record<string, string>).map((k) => (
            <label key={k} className="block">{t(k)}
              <select value={(draft as Record<string, string>)[k]} onChange={(e) => change({ ...(draft as Record<string, string>), [k]: e.target.value })}>
                {entry.options.map((o) => <option key={o} value={o}>{optionText(v, o)}</option>)}
              </select>
            </label>
          ))}
        </fieldset>
      ) : (
        <label className="block">{label}
          <span className="default-number">
            <input value={String(draft)} inputMode="decimal" autoComplete="off" className="tnum" onChange={(e) => change(e.target.value)} />
            {asPercent(entry, v) ? <span className="muted">{v.format === "points" ? t("percentage points") : "%"}</span> : null}
          </span>
          {entry.least !== null || entry.most !== null ? (
            <span className="muted small">{asPercent(entry, v)
              ? t("Between {{least}} and {{most}}.", { least: numText((entry.least ?? 0) * 100, 0), most: numText((entry.most ?? 1) * 100, 0) })
              : entry.most !== null ? t("Between {{least}} and {{most}}.", { least: numText(entry.least ?? 0, 0), most: numText(entry.most, 0) })
                : t("At least {{least}}.", { least: numText(entry.least ?? 0, 0) })}</span>
          ) : null}
        </label>
      )}
      <label className="block">{t("Note")}
        <input value={note} maxLength={2000} autoComplete="off" onChange={(e) => setNote(e.target.value)} />
      </label>
      <FormActions onCancel={onCancel} busy={busy}
        start={<button type="button" className="secondary" disabled={busy || value === null} onClick={() => void tryIt()}>{t("Try it on earlier decisions")}</button>}>
        <button type="submit" className="primary" disabled={busy || value === null}>{t("Save as a draft")}</button>
      </FormActions>
      {tryError ? <p className="notice error" role="alert">{tryError}</p> : null}
      {tried ? (
        <div className="default-tried" role="status">
          <p className="small">
            {tried.decisions
              ? t("{{n}} earlier decisions read it: {{changed}} would come out differently, {{failed}} could not be run again.", {
                n: numText(tried.decisions, 0), changed: numText(tried.changed, 0), failed: numText(tried.failed, 0) })
              : t("No earlier decision read it yet.")}
            {tried.covered ? <> {t("{{n}} more were decided by a process's own value, which a default does not reach.", { n: numText(tried.covered, 0) })}</> : null}
          </p>
          {tried.examples.length ? (
            <ul className="tight small">
              {tried.examples.map((x, i) => (
                <li key={i}><span className="mono">{x.subject}</span>{x.case ? ` · ${x.case}` : ""}: {String(x.before)} → {String(x.after)}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
