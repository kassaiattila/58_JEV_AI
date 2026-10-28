// 231 (plan stage B, B4; DECISIONS 231): a process's own settings in Settings. For each process (a process pack): the
// resources its file names (which price list, which template, how its letters are sent) and the rule values its steps'
// capabilities let it set (how many lines a quote holds, the rounding unit), each with the file's value and the one in
// use; and the roles its partners play. A person saves a new value as a draft, tries a rule value on the process's
// earlier decisions (the preview writes nothing), and makes a draft active by the installation's rule of who may; the
// process's own value can be set aside, and the file's counts again. A case keeps the values it started with.
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type ProcessDescription, type ProcessSettings, type ResourceSetting, type RulePreview, type SettingKind } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { ExampleMaterial } from "../../elements/ExampleMaterial";
import { VersionState } from "../../components/VersionState";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { numText, when } from "../../labels";
import { routeHash } from "../../route";

type Open = { kind: SettingKind; key: string } | null;
type Value = string | number;

/** A rule's value or a decision's outcome as a person reads it: numbers in the language's notation, a list joined, the
 *  parts of an outcome (a quote's totals) named. */
function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return v ? t("Igen") : t("Nem");
  if (Array.isArray(v)) return v.length ? v.map(show).join(", ") : t("none");
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${t(k)} ${show(x)}`).join(" · ");
  return numText(v, 4);
}

/** A resource's value as a person reads it: its option's label; a code (an option without a label of its own, or a
 *  value no option names) in the code face. */
function ResourceValue({ r, value }: { r: ResourceSetting; value: Value }) {
  const found = r.options?.find((o) => o.value === value);
  return found && found.label !== found.value ? <>{t(found.label)}</> : <span className="mono">{String(value)}</span>;
}

function policyText(p: ProcessSettings["policy"]) {
  if (p.activation === "owner") return t("Only these people make a value active: {{names}}.", { names: p.owners.join(", ") || "–" });
  if (p.activation === "second_person") return t("A second person makes a value active, not the one who saved it.");
  return t("The person who saves a value may make it active.");
}

/** 231 (stage U, U3a; the owner's decision of 2026-10-28: each process its own menu item and address): the processes
 *  under the Processes item of the Settings menu, each linked to its own page. */
export function ProcessNav({ current }: { current?: string }) {
  useLocale();
  const list = useLoad("processes", api.processes);
  return (
    <>
      {(list.data?.processes ?? []).map((p) => (
        <a key={p.id} className="settings-sub" href={routeHash({ view: "settings", section: "processes", item: p.id })}
          aria-current={p.id === current ? "page" : undefined}>{t(p.title)}</a>
      ))}
    </>
  );
}

const TABS = [["about", "Description"], ["uses", "What it uses"], ["values", "Rule values"], ["partners", "Partner roles"],
  ["examples", "Examples"]] as const;
type Tab = (typeof TABS)[number][0];

export function ProcessSettingsPanel({ pack, tab }: { pack?: string; tab?: string }) {
  useLocale();
  const list = useLoad("processes", api.processes);
  const packs = list.data?.processes ?? [];
  if (list.error) return <p className="notice error" role="alert">{list.error.message}</p>;
  if (!list.data) return <p className="muted">{t("Loading…")}</p>;
  if (!packs.length) return <p className="muted">{t("No process is installed.")}</p>;
  const chosen = packs.find((p) => p.id === pack);
  if (!chosen) {
    return (
      <table className="table compact" aria-label={t("Processes")}>
        <thead><tr><th>{t("Process")}</th><th>{t("What it is for")}</th></tr></thead>
        <tbody>
          {packs.map((p) => (
            <tr key={p.id}>
              <td><a href={routeHash({ view: "settings", section: "processes", item: p.id })}>{t(p.title)}</a></td>
              <td className="muted small">{p.summary ? t(p.summary) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  const current: Tab = TABS.some(([key]) => key === tab) ? (tab as Tab) : "about";
  return <ProcessPage key={chosen.id} pack={chosen.id} tab={current} />;
}

function ProcessPage({ pack, tab }: { pack: string; tab: Tab }) {
  useLocale();
  const loaded = useLoad(`process-settings:${pack}`, () => api.processSettings(pack));
  const [open, setOpen] = useState<Open>(null);
  const page = loaded.data;
  if (loaded.error) return <p className="notice error" role="alert">{loaded.error.message}</p>;
  if (!page) return <p className="muted">{t("Loading…")}</p>;
  const selected = (kind: SettingKind, key: string) => open?.kind === kind && open.key === key;
  const card = open ? <SettingCard key={`${open.kind}:${open.key}`} page={page} open={open} onClose={() => setOpen(null)} onChanged={loaded.reload} /> : null;
  return (
    <div className="process-settings">
      <div className="process-head">
        <h3>{t(page.pack.title)} <span className="muted small tnum">{page.pack.version}</span></h3>
        {page.description.summary ? <p className="muted">{t(page.description.summary)}</p> : null}
      </div>
      <div className="segmented-tabs" role="tablist" aria-label={t("The process's settings")}>
        {TABS.map(([key, label]) => (
          <a key={key} role="tab" className="seg" aria-selected={tab === key}
            href={routeHash({ view: "settings", section: "processes", item: pack, tab: key })}>{t(label)}</a>
        ))}
      </div>

      {tab === "about" ? <ProcessAbout page={page} /> : null}

      {tab === "uses" ? (
        <section aria-label={t("What it uses")}>
          <p className="muted small">{policyText(page.policy)} {t("A case keeps the values it started with; a change reaches the cases started after it.")}</p>
          {page.resources.length ? (
            <table className="table compact process-values" aria-label={t("Resources")}>
              <thead><tr><th>{t("Setting")}</th><th>{t("In use")}</th><th>{t("The file's value")}</th><th /></tr></thead>
              <tbody>
                {page.resources.map((r) => (
                  <tr key={r.key} aria-selected={selected("settings", r.key)}>
                    <td><button type="button" className="link-btn" onClick={() => setOpen({ kind: "settings", key: r.key })}>{t(r.label)}</button></td>
                    <td className="process-in-use"><ResourceValue r={r} value={r.value} /></td>
                    <td className="muted"><ResourceValue r={r} value={r.file_value} /></td>
                    <td><Origin own={r.own} drafts={r.versions.filter((v) => v.state === "draft").length} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted small">{t("The process uses nothing from the shared library.")}</p>}
          {open?.kind === "settings" ? card : null}
        </section>
      ) : null}

      {tab === "values" ? (
        <section aria-label={t("Rule values")}>
          <p className="muted small">{policyText(page.policy)} {t("A case keeps the values it started with; a change reaches the cases started after it.")}</p>
          {page.rules.length ? (
            <table className="table compact process-values" aria-label={t("Rule values")}>
              <thead><tr><th>{t("Rule")}</th><th className="num">{t("In use")}</th><th className="num">{t("The file's value")}</th><th /></tr></thead>
              <tbody>
                {page.rules.map((r) => (
                  <tr key={r.key} aria-selected={selected("rules", r.key)}>
                    <td><button type="button" className="link-btn" onClick={() => setOpen({ kind: "rules", key: r.key })}>{t(r.what)}</button></td>
                    <td className="num tnum process-in-use">{show(r.value)}</td>
                    <td className="num tnum muted">{show(r.file_value)}</td>
                    <td><Origin own={r.own} drafts={r.versions.filter((v) => v.state === "draft").length} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted small">{t("The process's steps let it set no rule value.")}</p>}
          {open?.kind === "rules" ? card : null}
        </section>
      ) : null}

      {tab === "partners" ? (
        <section aria-label={t("Partner roles")}>
          {page.partners.length ? (
            <ul className="plain process-partners">
              {page.partners.map((p) => (
                <li key={p.role}>{t(p.label)} <span className="muted small">{t("from the step {{step}}", { step: t(p.step_title) })}</span></li>
              ))}
            </ul>
          ) : <p className="muted small">{t("The process names no partner.")}</p>}
        </section>
      ) : null}

      {tab === "examples" ? (
        <section aria-label={t("Examples")}>
          {page.description.examples ? <ExampleMaterial pack={pack} needed={false} onChanged={loaded.reload} />
            : <p className="muted small">{t("The process has no example material.")}</p>}
        </section>
      ) : null}
    </div>
  );
}

/** 231 (U3a): what the process is for: how a case of it starts, its steps in order (what each does, who starts it,
 *  what it waits for), its outputs and the golden sets that measure it. */
function ProcessAbout({ page }: { page: ProcessSettings }) {
  useLocale();
  const d = page.description;
  return (
    <section className="rc-stack" aria-label={t("Description")}>
      <div>
        <h4>{t("How a case starts")}</h4>
        <ul className="plain">
          {d.intake.map((i, n) => <li key={n}>{intakeText(i)}</li>)}
        </ul>
      </div>
      <div>
        <h4>{t("Its steps")}</h4>
        <table className="table compact" aria-label={t("Its steps")}>
          <thead><tr><th>{t("Step")}</th><th>{t("What it does")}</th><th>{t("Starts")}</th></tr></thead>
          <tbody>
            {d.steps.map((s) => (
              <tr key={s.id}>
                <td>{t(s.title)}</td>
                <td className="small">{t(s.summary)}</td>
                <td className="small">
                  {s.start === "person" ? t("A person starts it") : t("By itself")}
                  {s.optional ? <> · {t("may be left out")}</> : null}
                  {s.after.length ? <span className="muted"> · {t("after {{steps}}", { steps: s.after.map((x) => t(x)).join(", ") })}</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h4>{t("Its outputs")}</h4>
        {d.outputs.length ? (
          <ul className="plain">{d.outputs.map((o) => <li key={o.id}>{o.what ? t(o.what) : o.id} <span className="muted small">{o.format?.toUpperCase()}</span></li>)}</ul>
        ) : <p className="muted small">{t("The process makes no document of its own.")}</p>}
      </div>
      <div>
        <h4>{t("How it is measured")}</h4>
        {d.goldens.length ? (
          <p className="small">{t("Golden sets:")} {d.goldens.map((g, n) => <span key={g}>{n ? ", " : ""}<span className="mono">{g}</span></span>)}</p>
        ) : <p className="muted small">{t("No golden set measures this process yet.")}</p>}
      </div>
    </section>
  );
}

function intakeText(i: ProcessDescription["intake"][number]): string {
  if (i.on === "manual") return t("A person starts it from New case.");
  if (i.on === "package") return t("A document batch's page offers it.");
  return i.starts === "case" ? t("An email with the intent {{intent}} starts it by itself.", { intent: i.intent ?? "–" })
    : t("An email with the intent {{intent}} offers it.", { intent: i.intent ?? "–" });
}

/** Where the value in use comes from: the process's own value, or the file's; and the drafts waiting. */
function Origin({ own, drafts }: { own: boolean; drafts: number }) {
  return (
    <span className="process-origin small">
      {own ? <span className="status s-done">{t("Own value")}</span> : <span className="muted">{t("From the file")}</span>}
      {drafts ? <span className="status s-trial">{t("{{n}} draft(s)", { n: drafts })}</span> : null}
    </span>
  );
}

/** One resource or rule value: a new value saved as a draft, its preview, its versions made active or set aside. */
function SettingCard({ page, open, onClose, onChanged }: {
  page: ProcessSettings; open: NonNullable<Open>; onClose: () => void; onChanged: () => void;
}) {
  useLocale();
  const resource = open.kind === "settings" ? page.resources.find((r) => r.key === open.key) ?? null : null;
  const rule = open.kind === "rules" ? page.rules.find((r) => r.key === open.key) ?? null : null;
  const setting = resource ?? rule;
  const start = useMemo<Value>(() => (setting ? setting.value : ""), [setting]);
  // what the person typed, over the value in use (null: nothing yet); a saved version starts afresh
  const [draft, setDraft] = useState<Value | null>(null);
  const [note, setNote] = useState("");
  const versions = setting?.versions.length ?? 0;
  useEffect(() => { setDraft(null); setNote(""); }, [versions]);
  const value = draft ?? start;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ value: Value; result: RulePreview } | null>(null);
  if (!setting) return null;
  const changed = draft !== null && String(draft) !== String(start);
  const ruleProblem = rule && rule.kind === "int" && (typeof value !== "number" || !Number.isInteger(value)
    || (rule.least !== null && value < rule.least) || (rule.most !== null && value > rule.most))
    ? t("A whole number from {{least}} to {{most}}.", { least: rule.least ?? "–", most: rule.most ?? "–" }) : null;

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function tryOn(v: Value) {
    setBusy(true);
    setError(null);
    try {
      setPreview({ value: v, result: await api.previewRule(page.pack.id, open.key, v) });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const text = (v: Value) => (resource ? <ResourceValue r={resource} value={v} /> : show(v));

  return (
    <section className="card wide process-card" aria-label={resource ? t(resource.label) : t(rule!.what)}>
      <div className="card-head">
        <h3>{resource ? t(resource.label) : t(rule!.what)}</h3>
        <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
      </div>
      <dl className="process-facts">
        <dt>{t("In use")}</dt><dd className="process-in-use tnum">{text(setting.value)}</dd>
        <dt>{t("The file's value")}</dt><dd className="tnum">{text(setting.file_value)}</dd>
        {rule ? <><dt>{t("Read by the steps")}</dt><dd>{rule.steps.map((s) => t(s)).join(", ")}</dd></> : null}
      </dl>
      <div className="form-row">
        <label className="block">{t("New value")}
          {resource?.options || (rule && rule.kind === "choice") ? (
            <select value={String(value)} onChange={(e) => setDraft(e.target.value)}>
              {(resource?.options ?? rule!.options.map((o) => ({ value: o, label: show(o) }))).map((o) => (
                <option key={o.value} value={o.value}>{o.label !== o.value ? t(o.label) : o.value}</option>
              ))}
            </select>
          ) : rule ? (
            <input type="number" className="tnum" value={String(value)} min={rule.least ?? undefined} max={rule.most ?? undefined} step={1}
              onChange={(e) => setDraft(e.target.value === "" ? "" : Number(e.target.value))} />
          ) : (
            <input value={String(value)} maxLength={200} autoComplete="off" onChange={(e) => setDraft(e.target.value)} />
          )}
        </label>
        <label className="block grow">{t("Note")}
          <input value={note} maxLength={2000} autoComplete="off" placeholder={t("Why it changes…")} onChange={(e) => setNote(e.target.value)} />
        </label>
      </div>
      <div className="button-row">
        <button type="button" className="secondary" disabled={busy || !changed || !!ruleProblem}
          onClick={() => void run(() => api.proposeSetting(page.pack.id, open.kind, open.key, value, note.trim() || null))}>
          {t("Save as a draft")}
        </button>
        {rule ? (
          <button type="button" className="secondary" disabled={busy || !changed || !!ruleProblem} onClick={() => void tryOn(value)}>
            {t("Try it on earlier decisions")}
          </button>
        ) : null}
        <span className="muted small">{ruleProblem ?? t("A draft changes nothing until it is made active.")}</span>
      </div>
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
      {preview ? <PreviewResult preview={preview.result} /> : null}
      {setting.versions.length ? (
        <table className="table compact process-versions" aria-label={t("Versions")}>
          <thead><tr><th className="num">{t("Version")}</th><th>{t("State")}</th><th>{t("Value")}</th><th>{t("Note")}</th><th>{t("Who")}</th><th>{t("When")}</th><th /></tr></thead>
          <tbody>
            {setting.versions.map((v) => (
              <tr key={v.version}>
                <td className="num tnum">{v.version}</td>
                <td><VersionState state={v.state} /></td>
                <td className="tnum">{text(v.value)}</td>
                <td>{v.note ?? "–"}</td>
                <td>{v.state === "active" && v.activated_by ? v.activated_by : v.made_by}</td>
                <td className="tnum">{when(v.state === "active" && v.activated_at ? v.activated_at : v.made_at)}</td>
                <td className="button-row">
                  {v.state === "draft" && rule ? (
                    <button type="button" className="quiet small-btn" disabled={busy} onClick={() => void tryOn(v.value)}>{t("Preview")}</button>
                  ) : null}
                  {v.state === "draft" ? (
                    <button type="button" className="primary small-btn" disabled={busy}
                      onClick={() => void run(() => api.activateSetting(page.pack.id, open.kind, open.key, v.version))}>{t("Make active")}</button>
                  ) : null}
                  {v.state === "active" ? (
                    <ConfirmButton className="secondary small-btn" disabled={busy}
                      onConfirm={() => void run(() => api.retireSetting(page.pack.id, open.kind, open.key))}>{t("Use the file's value")}</ConfirmButton>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

/** What a rule value would have changed in the process's earlier decisions. */
function PreviewResult({ preview }: { preview: RulePreview }) {
  useLocale();
  if (!preview.decisions) {
    return <p className="notice small">{t("No decision of this process has read this rule yet. The value shows on the cases started after it is made active.")}</p>;
  }
  return (
    <div className="process-preview">
      <p className="small">
        {t("With {{value}} instead of {{now}}: {{changed}} of the process's {{n}} earlier decisions would come out differently.",
          { value: show(preview.value), now: show(preview.file_value), changed: preview.changed, n: preview.decisions })}
        {preview.failed ? <> {t("{{n}} could not be tried: {{error}}", { n: preview.failed, error: preview.first_error ?? "" })}</> : null}
      </p>
      {preview.examples.length ? (
        <table className="table compact" aria-label={t("Decisions that would change")}>
          <thead><tr><th>{t("Decision")}</th><th>{t("Case")}</th><th>{t("When")}</th><th>{t("Now")}</th><th>{t("With the new value")}</th></tr></thead>
          <tbody>
            {preview.examples.map((e) => (
              <tr key={`${e.point}:${e.subject}`}>
                <td className="mono">{e.point}</td>
                <td><a href={`#/cases/${encodeURIComponent(e.case_id)}`}>{e.case}</a></td>
                <td className="tnum">{when(e.at)}</td>
                <td className="tnum">{show(e.before)}</td>
                <td className="tnum">{show(e.after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
