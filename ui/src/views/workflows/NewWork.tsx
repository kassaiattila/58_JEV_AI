// 146 (backlog F-package-kind-chooser; DECISIONS 146): the new work wizard. The owner chose a step-by-step wizard over
// templates described as data (`configs/workflows.json`), for many kinds of work and for chains of steps:
//   1 What is the work for? (a group)  2 Which work? (a template: a single kind, or a workflow of several steps)
//   3 Details: a single kind's own form (as before), or a workflow's party, period and each step's source and budget
//   4 Overview (a workflow): the chain, the sources and the budgets, then it is made and its first steps start.
// A paid step starts by itself only within the budget given here; the estimate is the processing's item budget times
// the items found.
// 147 (DECISIONS 147): a workflow repeated for the next period opens at its details, filled in from the earlier one's
// draft (the period moved on, a documents step only with the documents no live run has processed); a person checks it
// and approves the budgets again.
import { Fragment, useMemo, useState } from "react";
import {
  api, ApiError, type Engine, type MailboxRequest, type WorkflowBudget, type WorkflowDraft, type WorkflowEstimate, type WorkflowSource,
  type WorkflowTemplate, type WorkflowTemplates, type WorkKind, type WorkSourceKind,
} from "../../api";
import { BrowseButton } from "../../components/BrowseButton";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { go } from "../../route";
import { splitAccounts, toggleAccount } from "../Mailbox";
import { PartyChoice } from "../../components/PartyChoice";
import { hasOwnForm, SingleForm } from "../../logic/steps";
import { ENGINE } from "../../labels";
import { budgetText, centsUp, mergeProposal, PROVIDER } from "./labels";

const SOURCE_LABEL: Record<WorkSourceKind, string> = {
  folder: "A folder", files: "Given files", mailbox: "A mailbox", package: "An existing work package",
  none: "Nothing: made from the earlier steps",
};

/** The first and the last day of the last closed month. */
export function lastClosedMonth(today = new Date()): [string, string] {
  const first = new Date(Date.UTC(today.getFullYear(), today.getMonth() - 1, 1));
  const last = new Date(Date.UTC(today.getFullYear(), today.getMonth(), 0));
  return [first.toISOString().slice(0, 10), last.toISOString().slice(0, 10)];
}

export function NewWork({ onPackage, onWorkflow, initialTemplate, initialGroup, repeatOf }: {
  onPackage: (wpId: string) => void; onWorkflow: (wfId: string) => void; initialTemplate?: string; initialGroup?: string;
  /** 147: the workflow to repeat for the next period */
  repeatOf?: string;
}) {
  useLocale();
  const conf = useLoad("workflow-templates", api.workflowTemplates);
  const repeat = useLoad(repeatOf ? `workflow-repeat:${repeatOf}` : null, () => api.workflowRepeat(repeatOf!));
  const [stage, setStage] = useState(initialTemplate || repeatOf ? 3 : 1);
  const [group, setGroup] = useState(initialGroup ?? "documents");
  const [chosen, setTemplateId] = useState<string | null>(initialTemplate ?? null);
  const templateId = repeatOf ? repeat.data?.template ?? null : chosen;
  const tpl = conf.data?.templates.find((x) => x.id === templateId) ?? null;
  // 181: a one-step template opens its kind's own form (the kinds come from the service); before the templates have
  // loaded, a template whose id is a kind with a form of its own opens that form at once, as before
  const single = tpl ? (tpl.steps.length === 1 ? tpl.steps[0].kind : null)
    : templateId && !repeatOf && hasOwnForm(templateId) ? templateId : null;
  const isWorkflow = Boolean(tpl && tpl.steps.length > 1);
  const labels = isWorkflow ? ["What is it for?", "Which work?", "Details", "Overview"] : ["What is it for?", "Which work?", "Details"];

  const inGroup = (g: string) => conf.data?.templates.filter((x) => x.group === g) ?? [];
  function pickGroup(g: string) {
    setGroup(g);
    const first = inGroup(g)[0];
    setTemplateId(first ? first.id : null);
  }

  return (
    <section className="card create wizard" aria-label={t("New work")}>
      <ol className="wizard-steps">
        {labels.map((l, i) => (
          <li key={l} aria-current={stage === i + 1 ? "step" : undefined} className={stage > i + 1 ? "done" : undefined}>
            <span className="wizard-n">{i + 1}</span> {t(l)}
          </li>
        ))}
      </ol>
      {conf.error && stage < 3 ? <p className="notice error" role="alert">{conf.error.message}</p> : null}
      {stage >= 3 && !single && !conf.data && !conf.error && !repeatOf ? <p className="muted">{t("Loading…")}</p> : null}
      {repeat.error ? <p className="notice error" role="alert">{repeat.error.message}</p> : null}
      {repeatOf && !repeat.data && !repeat.error ? <p className="muted">{t("Loading…")}</p> : null}
      {stage === 1 ? (
        conf.data ? (
          <>
            {conf.data.intro ? <p className="muted small">{t(conf.data.intro)}</p> : null}
            <fieldset className="wizard-choices">
              <legend>{t("What is the work for?")}</legend>
              {conf.data.groups.map((g) => (
                <label key={g.id} className="wizard-choice">
                  <input type="radio" name="wz-group" checked={group === g.id} onChange={() => pickGroup(g.id)} aria-label={t(g.title)} />
                  <span><strong>{t(g.title)}</strong><span className="muted small">{t(g.description)}</span></span>
                </label>
              ))}
            </fieldset>
            <div className="button-row">
              <button type="button" className="primary" onClick={() => { if (!templateId || tpl?.group !== group) pickGroup(group); setStage(2); }}>{t("Next →")}</button>
            </div>
          </>
        ) : <p className="muted">{t("Loading…")}</p>
      ) : null}
      {stage === 2 && conf.data ? (
        <>
          <fieldset className="wizard-choices">
            <legend>{t("Which work?")}</legend>
            {inGroup(group).map((x) => <TemplateChoice key={x.id} tpl={x} conf={conf.data!} checked={templateId === x.id} onPick={() => setTemplateId(x.id)} />)}
          </fieldset>
          <div className="button-row">
            <button type="button" className="secondary" onClick={() => setStage(1)}>{t("← Back")}</button>
            <button type="button" className="primary" disabled={!templateId} onClick={() => setStage(3)}>{t("Next →")}</button>
          </div>
        </>
      ) : null}
      {stage >= 3 && single ? (
        <>
          <SingleForm kind={single} onDone={onPackage} />
          {!initialTemplate ? <div className="button-row"><button type="button" className="secondary" onClick={() => setStage(2)}>{t("← Back")}</button></div> : null}
        </>
      ) : null}
      {stage >= 3 && isWorkflow && tpl && conf.data ? (
        <WorkflowSetup tpl={tpl} conf={conf.data} overview={stage === 4} initial={repeat.data ?? undefined}
          onBack={repeatOf && stage === 3 ? () => go({ view: "workflows", wfId: repeatOf }) : () => setStage(stage - 1)}
          onNext={() => setStage(4)} onCreated={onWorkflow} />
      ) : null}
    </section>
  );
}

function TemplateChoice({ tpl, conf, checked, onPick }: { tpl: WorkflowTemplate; conf: WorkflowTemplates; checked: boolean; onPick: () => void }) {
  useLocale();
  const chain = tpl.steps.length > 1;
  return (
    <label className="wizard-choice">
      <input type="radio" name="wz-template" checked={checked} onChange={onPick} aria-label={t(tpl.title)} />
      <span>
        <strong>{t(tpl.title)}</strong>
        <span className="muted small">{t(tpl.description)}</span>
        {chain ? (
          <span className="wz-chain small" aria-label={t("Steps")}>
            {tpl.steps.map((s, i) => (
              <Fragment key={s.id}>
                {i ? <span aria-hidden="true"> → </span> : null}
                <span className="chip">{t(s.title ?? conf.kinds[s.kind].title)}</span>
              </Fragment>
            ))}
          </span>
        ) : <span className="small">{t(conf.kinds[tpl.steps[0].kind].cost)}</span>}
      </span>
    </label>
  );
}

// --- a workflow's details and overview ----------------------------------------------------------------------------------

interface StepDraft {
  source: WorkSourceKind; folder: string; recursive: boolean; onlyNew: boolean; files: string; packageId: string;
  packageName: string; accounts: string; folders: string; usePeriod: boolean; days: number; maxItems: number;
  budget: WorkflowBudget; estimate: WorkflowEstimate | null; estimating: boolean; error: string | null;
  /** 167 (review 160 U-9): the services whose budget the person typed here (a new estimate leaves them) */
  typed: Record<string, boolean>;
  /** 160-D: the step's own AI engine; null: the application's when the step starts */
  engine: Engine | null;
}

function draftFor(kind: WorkKind, conf: WorkflowTemplates): StepDraft {
  return {
    source: conf.kinds[kind].sources[0], folder: "", recursive: false, onlyNew: false, files: "", packageId: "", packageName: "",
    accounts: "", folders: "Inbox", usePeriod: true, days: 31, maxItems: 0, budget: {}, estimate: null, estimating: false, error: null,
    engine: null, typed: {},
  };
}

/** 147: a step of a repeated workflow, from the draft's source (none: the person gives it), budget and (160-D) engine. */
function draftFrom(kind: WorkKind, conf: WorkflowTemplates, src: WorkflowSource | null, budget: WorkflowBudget,
  engine: Engine | null = null): StepDraft {
  const d = { ...draftFor(kind, conf), budget: { ...budget }, engine };
  if (!src) return d;
  switch (src.kind) {
    case "folder": return { ...d, source: "folder", folder: src.folder ?? "", recursive: Boolean(src.recursive), onlyNew: Boolean(src.only_new) };
    case "files": return { ...d, source: "files", files: (src.paths ?? []).join("\n"), onlyNew: Boolean(src.only_new) };
    case "package": return { ...d, source: "package", packageId: src.workpackage_id ?? "" };
    case "mailbox": {
      const r = src.request;
      if (!r) return d;
      return { ...d, source: "mailbox", accounts: r.accounts.join(", "), folders: (r.folders ?? ["Inbox"]).join(", "),
        usePeriod: !r.since_days, days: r.since_days ?? 31, maxItems: r.max_items ?? 0 };
    }
    default: return { ...d, source: "none" };
  }
}

/** The overview's words after a step's source: the folder, the package's name (146 F-wizard-overview-package-name),
 * and whether only the new documents are taken. */
function sourceDetail(d: StepDraft, src: WorkflowSource | null): string {
  const what = src?.folder ? `: ${src.folder}` : d.source === "package" && d.packageName ? `: ${d.packageName}` : "";
  return src?.only_new ? `${what} · ${t("only the documents no live run has processed yet")}` : what;
}

function lines(text: string): string[] {
  return text.split(/\r?\n/).map((s) => s.trim().replace(/^"|"$/g, "")).filter(Boolean);
}

function sourceOf(d: StepDraft, period: [string, string]): WorkflowSource | null {
  switch (d.source) {
    case "folder": return d.folder.trim() ? { kind: "folder", folder: d.folder.trim(), recursive: d.recursive, ...(d.onlyNew ? { only_new: true } : {}) } : null;
    case "files": return lines(d.files).length ? { kind: "files", paths: lines(d.files), ...(d.onlyNew ? { only_new: true } : {}) } : null;
    case "package": return d.packageId ? { kind: "package", workpackage_id: d.packageId } : null;
    case "mailbox": {
      const accounts = splitAccounts(d.accounts);
      if (!accounts.length) return null;
      const request: MailboxRequest = {
        accounts, folders: d.folders.split(",").map((f) => f.trim()).filter(Boolean), max_items: d.maxItems,
        ...(d.usePeriod ? { received_from: period[0], received_to: period[1] } : { since_days: d.days }),
      };
      return { kind: "mailbox", request };
    }
    default: return { kind: "none" };
  }
}

function WorkflowSetup({ tpl, conf, overview, initial, onBack, onNext, onCreated }: {
  tpl: WorkflowTemplate; conf: WorkflowTemplates; overview: boolean; initial?: WorkflowDraft; onBack: () => void;
  onNext: () => void; onCreated: (wfId: string) => void;
}) {
  useLocale();
  const parties = useLoad("parties", api.parties);
  const [partyId, setPartyId] = useState<string | null>(initial?.party_id ?? null);
  const party = parties.data?.parties.find((p) => p.id === partyId) ?? null;
  const [[start, end], setPeriod] = useState<[string, string]>(() => (initial ? [initial.period_start, initial.period_end] : lastClosedMonth()));
  const [name, setName] = useState(initial?.name ?? "");
  const [auto, setAuto] = useState(initial?.auto ?? true);
  const [drafts, setDrafts] = useState<Record<string, StepDraft>>(() =>
    Object.fromEntries(tpl.steps.map((s) => [s.id, initial?.steps[s.id]
      ? draftFrom(s.kind, conf, initial.steps[s.id].source, initial.steps[s.id].budget, initial.steps[s.id].engine ?? null)
      : draftFor(s.kind, conf)])));
  const appEngine = useLoad("engine", api.engine).data?.engine ?? null;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const periodOk = Boolean(start) && Boolean(end) && start <= end;
  const stepTitle = (id: string) => {
    const s = tpl.steps.find((x) => x.id === id)!;
    return t(s.title ?? conf.kinds[s.kind].title);
  };
  const title = name.trim() || (party ? `${party.name} · ${t(tpl.title)} · ${start} – ${end}` : "");
  const sources = Object.fromEntries(tpl.steps.map((s) => [s.id, sourceOf(drafts[s.id], [start, end])]));
  const missing = tpl.steps.filter((s) => !sources[s.id]).map((s) => stepTitle(s.id));
  const ready = party !== null && periodOk && !missing.length;
  const set = (id: string, patch: Partial<StepDraft>) => setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  // 160-D: only a paid step with its own source has an engine (a brought package keeps its settings)
  const ownEngine = (kind: WorkKind, d: StepDraft) => conf.kinds[kind].own_engine && !["package", "none"].includes(d.source);
  const engineText = (d: StepDraft) => (d.engine ? ENGINE[d.engine]
    : t("as the application ({{engine}})", { engine: appEngine ? ENGINE[appEngine] : "…" }));

  async function estimate(id: string, kind: WorkKind) {
    const source = sources[id];
    if (!source) return;
    set(id, { estimating: true, error: null });
    try {
      const engine = drafts[id].engine;
      const est = await api.workflowEstimate({ kind, source, party_id: party?.id, period_start: start, period_end: end, engine });
      // the budget proposed: the estimate rounded up to the cent (a person can change it)
      const proposed = Object.fromEntries(Object.entries(est.usd).map(([p, v]) => [p, centsUp(v)]));
      // 153 (review D3): merged into the draft as it is now, so a cap typed while the estimate ran stays (it was
      // overwritten by the proposal); an answer for a source changed meanwhile is dropped
      const asked = JSON.stringify([source, engine]);
      setDrafts((prev) => {
        if (JSON.stringify([sourceOf(prev[id], [start, end]), prev[id].engine]) !== asked) return { ...prev, [id]: { ...prev[id], estimating: false } };
        return { ...prev, [id]: { ...prev[id], estimate: est, estimating: false, budget: mergeProposal(prev[id].budget, proposed, prev[id].typed) } };
      });
    } catch (e) {
      set(id, { estimating: false, error: e instanceof ApiError ? e.message : String(e) });
    }
  }

  async function create() {
    if (!party) return;
    setBusy(true);
    setError(null);
    try {
      const view = await api.createWorkflow({
        template: tpl.id, party_id: party.id, period_start: start, period_end: end, name: title, auto,
        ...(initial ? { previous: initial.previous } : {}),
        names: Object.fromEntries(tpl.steps.map((s) => [s.id, `${title} · ${stepTitle(s.id)}`])),
        steps: Object.fromEntries(tpl.steps.map((s) => [s.id, {
          source: sources[s.id]!,
          budget: Object.fromEntries(Object.entries(drafts[s.id].budget).filter(([, v]) => v && Number(v) > 0)),
          ...(ownEngine(s.kind, drafts[s.id]) && drafts[s.id].engine ? { engine: drafts[s.id].engine } : {}),
        }])),
      });
      onCreated(view.workflow.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (overview) {
    return (
      <div className="rc-stack" aria-label={t("Overview")}>
        <h3>{title}</h3>
        <p className="small">{t("{{party}}, {{from}} – {{to}}", { party: party?.name ?? "?", from: start, to: end })}</p>
        <ol className="wz-overview">
          {tpl.steps.map((s) => (
            <li key={s.id}>
              <strong>{stepTitle(s.id)}</strong>
              {s.after?.length ? <span className="muted small"> · {t("starts once these are approved: {{steps}}", { steps: s.after.map(stepTitle).join(", ") })}</span> : null}
              <div className="small">{t(SOURCE_LABEL[drafts[s.id].source])}{sourceDetail(drafts[s.id], sources[s.id])}</div>
              {ownEngine(s.kind, drafts[s.id]) ? (
                <>
                  <div className="small">{t("AI engine: {{engine}}", { engine: engineText(drafts[s.id]) })}</div>
                  <div className="small">{t("Budget for an automatic start: {{budget}}", { budget: budgetText(drafts[s.id].budget) })}</div>
                </>
              ) : null}
            </li>
          ))}
        </ol>
        <p className="small">{auto
          ? t("Each step starts by itself as a live run once the steps it waits for are approved; a paid step only when its run's estimate fits its budget, otherwise it waits for you. You clear the to-dos and approve each step.")
          : t("The automatic chain is off: you start each step on the workflow's page.")}</p>
        {error ? <p className="notice error" role="alert">{error}</p> : null}
        <div className="button-row">
          <button type="button" className="secondary" onClick={onBack}>{t("← Back")}</button>
          <button type="button" className="primary" disabled={busy} onClick={() => void create()}>{busy ? t("Creating…") : t("Create the workflow")}</button>
        </div>
      </div>
    );
  }

  return (
    <div className="rc-stack" aria-label={t("Details")}>
      {parties.error ? <p className="notice error" role="alert">{parties.error.message}</p> : null}
      {initial ? <p className="notice small">{t("This repeats an earlier workflow for the next period. Check the period, the sources and the budgets: you approve them again here.")}</p> : null}
      {parties.data ? <PartyChoice overview={parties.data} value={partyId} onPick={(p) => setPartyId(p.id)} anyParty /> : <p className="muted">{t("Loading…")}</p>}
      <div className="rc-period">
        <label className="block">{t("Period from")}<input type="date" value={start} onChange={(e) => setPeriod([e.target.value, end])} required /></label>
        <label className="block">{t("to")}<input type="date" value={end} onChange={(e) => setPeriod([start, e.target.value])} required /></label>
      </div>
      {!periodOk && start && end ? <p className="small warn-text">{t("The period ends before it starts.")}</p> : null}
      <label className="block">{t("Name")} <span className="muted">{t("(optional: the party, the work and the period)")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} placeholder={title} />
      </label>
      <label className="check"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> {t("Start the steps by themselves")}</label>
      {tpl.steps.map((s, i) => (
        <StepEditor key={s.id} n={i + 1} title={stepTitle(s.id)} kind={s.kind} conf={conf} draft={drafts[s.id]} appEngine={appEngine}
          after={(s.after ?? []).map(stepTitle)} onChange={(patch) => set(s.id, patch)}
          onEstimate={() => void estimate(s.id, s.kind)} canEstimate={Boolean(sources[s.id]) && (!conf.kinds[s.kind].needs.includes("party") || Boolean(party))} />
      ))}
      {missing.length ? <p className="small muted">{t("Still to give: {{steps}}", { steps: missing.join(", ") })}</p> : null}
      <div className="button-row">
        <button type="button" className="secondary" onClick={onBack}>{t("← Back")}</button>
        <button type="button" className="primary" disabled={!ready} onClick={onNext}>{t("Next →")}</button>
      </div>
    </div>
  );
}

function StepEditor({ n, title, kind, conf, draft, appEngine, after, onChange, onEstimate, canEstimate }: {
  n: number; title: string; kind: WorkKind; conf: WorkflowTemplates; draft: StepDraft; appEngine: Engine | null; after: string[];
  onChange: (patch: Partial<StepDraft>) => void; onEstimate: () => void; canEstimate: boolean;
}) {
  useLocale();
  const sources = conf.kinds[kind].sources;
  const paid = conf.kinds[kind].paid && !["package", "none"].includes(draft.source);
  const touched = (patch: Partial<StepDraft>) => onChange({ ...patch, estimate: null });
  return (
    <fieldset className="wz-step">
      <legend><span className="wizard-n">{n}</span> {title}</legend>
      <p className="muted small">{t(conf.kinds[kind].description)} {t(conf.kinds[kind].cost)}
        {after.length ? ` ${t("Starts once these are approved: {{steps}}.", { steps: after.join(", ") })}` : ""}</p>
      {sources.length > 1 ? (
        <div className="segmented" role="radiogroup" aria-label={t("Source of {{step}}", { step: title })}>
          {sources.map((src) => (
            <label key={src}><input type="radio" name={`wz-src-${n}`} checked={draft.source === src} onChange={() => touched({ source: src })} /> {t(SOURCE_LABEL[src])}</label>
          ))}
        </div>
      ) : null}
      {draft.source === "folder" ? (
        <>
          <div className="path-row">
            <label className="block grow">{t("Folder of {{step}}", { step: title })}
              <input value={draft.folder} onChange={(e) => touched({ folder: e.target.value })} />
            </label>
            <BrowseButton kind="folder" initial={draft.folder} onPick={([p]) => touched({ folder: p })} />
          </div>
          {conf.kinds[kind].subfolders ? <label className="check"><input type="checkbox" checked={draft.recursive} onChange={(e) => touched({ recursive: e.target.checked })} /> {t("Include subfolders")}</label> : null}
        </>
      ) : null}
      {conf.kinds[kind].only_new && (draft.source === "folder" || draft.source === "files") ? (
        <label className="check"><input type="checkbox" checked={draft.onlyNew} onChange={(e) => touched({ onlyNew: e.target.checked })} /> {t("Only the documents no live run has processed yet")}</label>
      ) : null}
      {draft.source === "files" ? (
        <div className="path-row">
          <label className="block grow">{t("The files' full paths, one per line")}
            <textarea value={draft.files} rows={3} onChange={(e) => touched({ files: e.target.value })} />
          </label>
          <BrowseButton kind="files" initial={lines(draft.files).at(-1)} onPick={(picked) => touched({ files: [...lines(draft.files), ...picked].join("\n") })} />
        </div>
      ) : null}
      {draft.source === "mailbox" ? <MailboxSource draft={draft} onChange={touched} /> : null}
      {draft.source === "package" ? <PackageSource kinds={conf.kinds[kind].package_kinds} value={draft.packageId} onChange={(id, name) => touched({ packageId: id, packageName: name })} /> : null}
      {paid ? (
        <div className="wz-engine">
          <span className="small">{t("AI engine")}</span>
          {/* 160-D: a choice changes the run's budget, so it clears the estimate like a source change */}
          <div className="segmented" role="radiogroup" aria-label={t("AI engine of {{step}}", { step: title })}>
            {([null, "jev", "gpt"] as const).map((e) => (
              <label key={e ?? "app"}><input type="radio" name={`wz-engine-${n}`} checked={draft.engine === e} onChange={() => touched({ engine: e })} />{" "}
                {e ? ENGINE[e] : t("As the application ({{engine}})", { engine: appEngine ? ENGINE[appEngine] : "…" })}</label>
            ))}
          </div>
        </div>
      ) : null}
      {paid ? (
        <div className="wz-budget">
          <span className="small">{t("Budget for an automatic start (USD)")}</span>
          {(["jev", "openai", "azure_di"] as const).map((p) => (
            <label key={p} className="inline small">{PROVIDER[p]}
              <input type="number" min={0} max={1000} step={0.01} value={draft.budget[p] ?? ""} aria-label={t("{{provider}} budget of {{step}}", { provider: PROVIDER[p], step: title })}
                onChange={(e) => onChange({ budget: { ...draft.budget, [p]: e.target.value }, typed: { ...draft.typed, [p]: true } })} />
            </label>
          ))}
          <button type="button" className="secondary small-btn" disabled={!canEstimate || draft.estimating} onClick={onEstimate}>
            {draft.estimating ? t("Estimating…") : t("Estimate")}
          </button>
          {draft.estimate ? (
            <span className="small">
              {draft.estimate.items === null ? t("The number of items is known only after the download.")
                : t("{{n}} item(s), at most {{cost}}", { n: draft.estimate.items, cost: budgetText(draft.estimate.usd) })}
              {draft.estimate.left_out ? ` · ${t("{{n}} already processed by a live run, left out", { n: draft.estimate.left_out })}` : ""}
              {draft.estimate.note ? ` · ${t(draft.estimate.note)}` : ""}
            </span>
          ) : null}
          {draft.error ? <span className="small warn-text">{draft.error}</span> : null}
        </div>
      ) : null}
    </fieldset>
  );
}

function MailboxSource({ draft, onChange }: { draft: StepDraft; onChange: (patch: Partial<StepDraft>) => void }) {
  useLocale();
  const known = useLoad("mailbox", api.mailbox);
  return (
    <div className="rc-stack">
      <label className="block">{t("Mailbox address")} <span className="muted">{t("(several, comma-separated)")}</span>
        <input value={draft.accounts} onChange={(e) => onChange({ accounts: e.target.value })} placeholder="nev@ceg.hu" />
      </label>
      {known.data?.accounts?.length ? (
        <div className="chip-row" role="group" aria-label={t("Previously used mailboxes")}>
          {known.data.accounts.map((a) => (
            <button key={a} type="button" className="chip" aria-pressed={splitAccounts(draft.accounts).includes(a)}
              onClick={() => onChange({ accounts: toggleAccount(draft.accounts, a) })}>{a}</button>
          ))}
        </div>
      ) : null}
      <div className="form-row">
        <label className="block">{t("Folder")} <span className="muted">{t("(comma-separated)")}</span>
          <input value={draft.folders} onChange={(e) => onChange({ folders: e.target.value })} />
        </label>
        <label className="block">{t("At most this many emails")} <span className="muted">{t("(0 = no limit)")}</span>
          <input type="number" min={0} max={10000} value={draft.maxItems} onChange={(e) => onChange({ maxItems: Number(e.target.value) })} />
        </label>
      </div>
      <label className="check"><input type="checkbox" checked={draft.usePeriod} onChange={(e) => onChange({ usePeriod: e.target.checked })} /> {t("The emails received in the workflow's period")}</label>
      {!draft.usePeriod ? (
        <label className="block">{t("Number of days")}
          <input type="number" min={1} max={3650} value={draft.days} onChange={(e) => onChange({ days: Number(e.target.value) })} />
        </label>
      ) : null}
    </div>
  );
}

function PackageSource({ kinds, value, onChange }: { kinds: string[]; value: string; onChange: (id: string, name: string) => void }) {
  useLocale();
  const list = useLoad("workpackages-brief", api.workpackagesBrief);  // 154: the name and the kind are enough
  const options = useMemo(() => (list.data?.workpackages ?? []).filter((w) => kinds.includes(w.source_kind)), [list.data, kinds]);
  if (list.error) return <p className="notice error" role="alert">{list.error.message}</p>;
  return (
    <label className="block">{t("Work package")}
      <select value={value} onChange={(e) => onChange(e.target.value, options.find((w) => w.id === e.target.value)?.name ?? "")}>
        <option value="">{t("Choose…")}</option>
        {options.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
    </label>
  );
}
