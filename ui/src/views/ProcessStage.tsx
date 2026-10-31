// Processing section (057): running (trial, live, rerun) at the top, below it the processing settings (a summary,
// editable when expanded; 080: there is one processing, so nothing to choose, only settings) and the package's runs.
// The run's details (progress, cost, call log) are on the run's page. The run buttons do not start anything: they lead
// to the confirmation page (061 decision, `StartConfirm`).
// 168 (DECISIONS 168, the owner's choice "Run on top"): below the Run card the package's items (`PackageItems`), where
// files and folders are added; while its add form is open, its own last step is the view's one solid button.
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Recipe, type RecipeHelp, type RunPlan, type SupersedableRun, type WorkpackageView } from "../api";
import { BlockerList } from "../components/BlockerList";
import { FormActions } from "../components/FormActions";
import { ConfirmButton } from "../components/ConfirmButton";
import { DataTable } from "../components/DataTable";
import { Icon } from "../components/Icon";
import { Picker } from "../components/Picker";
import { PackageCosts } from "./PackageCosts";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { applyPath, itemBudgetLines, MODE, PARAM_LABEL, paramShort, paramsText, PATH, pathOptions, planLines, providerName, RUN_STATUS, shownParams, shownValue, tmap, usdBudget, when, blockerText } from "../labels";
import { processNotices } from "../logic/processNotices";
import { go, wpHash } from "../route";
import { type AddSource } from "./PackageAdd";
import { PackageItems } from "./PackageItems";
import { paramExplanation, RecipeParamList, recipeDefaults, recipeTitle } from "./RecipeInfo";

const ACTIVE = new Set(["queued", "running"]);

// 155: every run spends from the same budget (a trial calls the same services as a live run), so each start button
// carries the cap; a run that can spend nothing carries no mark
const capOf = (budget: Record<string, string>) => Object.values(budget).reduce((s, v) => s + (Number(v) || 0), 0);
const spendMark = (cap: number) => (cap > 0 ? <span className="spend" aria-hidden="true">≤ {usdBudget(cap)}</span> : null);
const withSpend = (cap: number, title?: string) =>
  [title, cap > 0 ? t("Starts a run that can spend up to {{usd}}", { usd: usdBudget(cap) }) : ""].filter(Boolean).join(" · ") || undefined;

export function ProcessStage({ view, adding = false, onChanged }: { view: WorkpackageView; adding?: boolean; onChanged: () => void }) {
  useLocale();
  const { workpackage: wp, readiness, last_run: last } = view;
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const active = last ? ACTIVE.has(last.status) : false;
  // 160-C S3: the run the next step is about (a later trial or a run over the pending items does not hide an open
  // live run): its rerun, and the mode of the pending items' run when they are next
  const target = view.current_run ?? last;
  // 058: a single highlighted button — the one the package's next step asks for (the list and the header show it too)
  const primary = view.next.code === "pending" ? `pending-${target?.mode ?? "apply"}`
    : ({ start: "shadow", go_live: "apply", rerun: "rerun" }[view.next.code as string] ?? null);
  const btn = (which: string) => (primary === which && !adding ? "primary" : "secondary");
  const [source, setSource] = useState<AddSource>("files"); // 168: the add form's source (the address holds whether it is open)
  const recipes = useLoad("recipes", api.recipes);

  // 261: a domain's notice runs its action as the section's own buttons (058 K5.2: until 261, adding an email package's
  // attachments here)
  async function runNotice(action: () => Promise<unknown>) {
    setBusy(true);
    setMsg(null);
    try {
      await action();
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  async function refreshAssignment() {
    // to the processing's current version (080: a retired or internal recipe moves onto the active processing): the
    // existing settings stay, a new setting gets its default value, a given document type is dropped
    const a = wp.assignment;
    const r = recipes.data?.recipes.find((x) => x.id === a?.recipe_id) ?? recipes.data?.recipes[0];
    if (!a || !r) return;
    setBusy(true);
    setMsg(null);
    try {
      const params: Record<string, string> = {};
      for (const [k, spec] of Object.entries(r.params)) params[k] = a.params[k] ?? spec.default ?? "";
      // the note is data (in the assignment's log), not a label
      await api.saveWorkflow(wp.id, { recipe_id: r.id, params, expected_revision: a.revision, note: "frissítés a feldolgozás mostani változatára" }); // i18n-ignore
      setMsg({ error: false, text: t("The settings now use the current version of the processing.") });
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  async function supersede(runId: string) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.supersede(runId);
      setMsg({ error: false, text: t("Run superseded: {{n}} open to-dos closed.", { n: r.reasons_closed }) });
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  // 061: the button leads to the confirmation page; the start happens there
  const start = (mode: "shadow" | "apply", rerun = false, pending = false) =>
    go({ view: "workpackages", wpId: wp.id, stage: "process", start: { mode, rerun, ...(pending ? { pending } : {}) } });
  const cap = capOf(readiness.budget);
  const spend = spendMark(cap);
  // 160-C S3: per mode, the run over only the pending items, with its own cap
  const supplements = (["apply", "shadow"] as const).flatMap((m) => {
    const s = readiness.supplement?.[m];
    return s ? [{ mode: m, ...s }] : [];
  });
  // 168: the same buttons on the Run card and beside the item list's pending line (there never the solid one)
  const pendingButtons = (cls: (mode: string) => string, where = "run") => supplements.map((s) => (
    <button key={s.mode} type="button" className={cls(s.mode)} data-run={where === "run" ? `pending-${s.mode}` : undefined}
      title={withSpend(capOf(s.budget))} disabled={!s.ready || busy || active} onClick={() => start(s.mode, false, true)}>
      <Icon name={s.mode === "apply" ? "play" : "trial"} />
      {s.mode === "apply" ? t("Live run, pending items only ({{n}})", { n: s.items }) : t("Trial run, pending items only ({{n}})", { n: s.items })}…
      {spendMark(capOf(s.budget))}
    </button>
  ));

  return (
    <div className="stage-grid">
      <section className="card wide" aria-label={t("Run")}>
        {/* 263 (F1): the card's own buttons - the runs - in its head, on the right */}
        <div className="card-head">
          <h2>{t("Run")}</h2>
          <div className="button-row end run-buttons">
            {pendingButtons((m) => btn(`pending-${m}`))}
            <button type="button" className={btn("shadow")} data-run="shadow" title={withSpend(cap)} disabled={!readiness.ready || busy || active}
              onClick={() => start("shadow")}><Icon name="trial" />{t("Trial run")}…{spend}</button>
            {/* the live run is the consequential one: only its result can be released */}
            <button type="button" className={btn("apply")} data-run="apply" title={withSpend(cap)}
              disabled={!readiness.ready || busy || active} onClick={() => start("apply")}><Icon name="play" />{t("Live run")}…{spend}</button>
            <button type="button" className={btn("rerun")} data-run="rerun" disabled={!target || !readiness.ready || busy || active}
              title={withSpend(cap, target ? t("Again as a new {{mode}} run, on the package's documents as they are now", { mode: MODE[target.mode].toLowerCase() }) : t("No run to repeat yet"))}
              onClick={() => target && start(target.mode, true)}><Icon name="rerun" />{t("Rerun")}…{spend}</button>
          </div>
        </div>
        {last ? (
          <div className="run-summary">
            <span className={`status s-${last.status}`}>{RUN_STATUS[last.status] ?? last.status}</span>
            <span>{t("{{mode}} run · {{when}} · {{done}}/{{total}} items", { mode: MODE[last.mode], when: when(last.created_at), done: last.items_done, total: last.items })}</span>
            {last.open_reasons ? <a href={wpHash(wp.id, "review")}>{t("To-dos: {{n}}", { n: last.open_reasons })}</a> : null}
            <a className="small" href={`#/runs/${last.run_id}`}>{t("Details of the latest run")}</a>
            {active ? (
              <div className="bar wide-bar" role="meter" aria-label={t("Progress")} aria-valuemin={0} aria-valuemax={last.items} aria-valuenow={last.items_done}>
                <span style={{ width: `${(100 * last.items_done) / Math.max(1, last.items)}%` }} />
              </div>
            ) : null}
          </div>
        ) : <p className="muted">{t("No processing has run on this batch yet.")}</p>}
        {processNotices().map((Notice, i) => <Notice key={i} view={view} disabled={busy || active} run={runNotice} />)}
        {!readiness.ready ? (
          <BlockerList items={readiness.blockers.map((b, i) => ({ key: String(i), content: blockerText(b) }))} />
        ) : null}
        {readiness.warnings.length ? (
          <BlockerList items={readiness.warnings.map((w, i) => ({ key: String(i), warning: true, content: <>{blockerText(w)}
            {w.code === "recipe_changed" || w.code === "recipe_retired" ? <> <button type="button" className="secondary small-btn" disabled={busy || active || !recipes.data}
              onClick={() => void refreshAssignment()}><Icon name="rerun" />{t("Switch to the current processing")}</button></> : null}</> }))} />
        ) : null}
        <OlderRunsOffer runs={view.supersedable ?? []} busy={busy || active} onSupersede={(id) => void supersede(id)} />
        <dl className="run-help small">
          <dt>{t("Trial run")}</dt><dd>{t("the result can be viewed and downloaded but not released")}</dd>
          <dt>{t("Live run")}</dt><dd>{t("a person approves the result in the Result stage, with no open to-dos")}</dd>
          {/* 160-C S2: a rerun takes the package as it is now, not the earlier run's input */}
          <dt>{t("Rerun")}</dt><dd>{t("the last run again as a new run, on all the package's documents as they are now (the added ones too, the removed ones not), for example after an error, a stop or a change of settings")}</dd>
          {supplements.length ? <>
            <dt>{t("Pending items only")}</dt>
            <dd>{t("a new run over only the items no run of that kind has finished yet (added since, or failed); the earlier runs and their approval stay as they are, and its result is reviewed and approved on its own")}</dd>
          </> : null}
        </dl>
        {readiness.plan ? <RunPlanList plan={readiness.plan} budget={readiness.budget} /> : (
          <p className="muted small">
            {t("Budget: {{budget}}.", { budget: Object.entries(readiness.budget)
              .map(([p, v]) => t("{{provider}} up to {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ") || t("none") })}
          </p>
        )}
        {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
      </section>

      {/* 168: the address holds whether the add form is open, so the package's actions menu can open it */}
      <PackageItems view={view} adding={adding ? source : null} onChanged={onChanged}
        onAddingChange={(s) => { if (s) setSource(s); go({ view: "workpackages", wpId: wp.id, stage: "process", ...(s ? { add: true } : {}) }); }}
        pendingAction={supplements.length ? <div className="button-row">{pendingButtons(() => "secondary", "items")}</div> : undefined} />

      <SettingsCard view={view} onChanged={onChanged} />

      <section aria-label={t("Runs")} className="wide">
        <h2>{t("Runs of the document batch")}</h2>
        <DataTable dataset="runs" scope={{ workpackage_id: wp.id }} label={t("Runs of the document batch")} storageId="wp-runs" defaultHidden={["workpackage_name"]} pollMs={active ? 4000 : undefined}
          emptyText={t("Not run yet.")} initial={{ limit: 50 }} />
      </section>

      <PackageCosts wpId={wp.id} pollMs={active ? 4000 : undefined} />
    </div>
  );
}

const PARAM_VALUE: Record<string, string> = tmap({
  "jev_cache:reuse": "Previous answer may be reused",
  "jev_cache:live": "Always a live call",
  "tasks:off": "No task proposals",
  "tasks:propose": "Task proposals from the emails (GPT; not for emails to be archived; only a person can accept them)",
  "azure_ocr:on": "Azure recognition when the local recognition is weak (paid, within the run's Azure budget)",
  "azure_ocr:off": "Local recognition only",
  // 120 (the owner's decision of 2026-10-06; codepoints for the language guard)
  "unknown_documents:facts": "A PDF whose type has no fitting type pack: general, source-bound facts (GPT + JEV; a scan through local text recognition, with a to-do); the recognised type and its uncertainty are kept",
  "unknown_documents:review": "Processing of such a PDF stops with a to-do (earlier behaviour)",
  // 190: a quote request written in the email itself
  "email_text:extract": "A quote request written in the email itself is extracted from its text (GPT + JEV, about 0.006 USD per such email, at most 0.03 USD reserved per email)",
  "email_text:off": "The email's own text is not extracted; its attachments still are",
  "jev:on": "On: JEV recognises the type and the email's intent, and chooses or checks during extraction",
  "jev:off": "Off: GPT only (OpenAI) — type recognition, extraction and email intent by GPT, checked by the code",
  // 090: the processing path (the documents' path and the use of JEV as one choice)
  "path:auto": "Automatic (recommended) — JEV and GPT, the document type's recommended path for each document",
  "path:gpt": "GPT only, without JEV — type recognition, data extraction and email intent with GPT, checked in code (OpenAI)",
  "path:jev": "With JEV (recommended) — JEV recognises the email's intent",
});
/** Label of a setting's value in the editor and on the confirmation page; the path by what it does (080, the owner's
 *  decision of 2026-10-01), a document type by its name. */
export const paramValue = (k: string, v: string) => PARAM_VALUE[`${k}:${v}`] ?? paramShort(k, v);

/** 080 (the pre-start overview of F-külső-kapcsolók): which services a run may call, with the budget maximum and what
 *  it is for. */
/** 152 (the owner's request of 2026-10-12): the package's older live runs a later live run repeated on the same
 *  documents, each with a link to its page and a "Supersede" button (the run's page offers the same, 151). Human work
 *  left on a run stays with it and is named before the click. */
/** 153: the human work left on an older run, naming only the parts that are not zero ("0 closed to-dos" read oddly). */
function humanWorkLeft(r: number, c: number): string {
  if (r && c) return t("{{r}} closed to-dos and {{c}} hand-corrected documents stay with it and are not carried over", { r, c });
  return r ? t("{{r}} closed to-dos stay with it and are not carried over", { r })
    : t("{{c}} hand-corrected documents stay with it and are not carried over", { c });
}

/** 200 (decision of 2026-10-22): older trial runs with open to-dos too; the wording names the runs' kinds only when a
 *  trial is among them, so a list of live runs reads as before. */
export function OlderRunsOffer({ runs, busy, onSupersede }: { runs: SupersedableRun[]; busy: boolean; onSupersede: (runId: string) => void }) {
  useLocale();
  if (!runs.length) return null;
  const open = runs.reduce((n, r) => n + r.open_reasons, 0);
  const trials = runs.some((r) => r.mode === "shadow");
  return (
    <div className="notice" role="region" aria-label={trials ? t("Older runs") : t("Older live runs")}>
      <p>{trials
        ? t("{{n}} older run(s) were repeated by a later run on the same documents. Superseding stops them and closes their {{m}} open to-dos; a superseded live run cannot be approved afterwards.",
          { n: runs.length, m: open })
        : t("{{n}} older live run(s) were repeated by a later live run on the same documents. Superseding stops them and closes their {{m}} open to-dos; they cannot be approved afterwards.",
          { n: runs.length, m: open })}</p>
      <ul className="plain">
        {runs.map((r) => (
          <li key={r.run_id}>
            <a href={`#/runs/${encodeURIComponent(r.run_id)}`}>{r.mode === "shadow" ? t("Trial run, {{when}}", { when: when(r.created_at) })
              : t("Live run, {{when}}", { when: when(r.created_at) })}</a>
            {" · "}{t("{{n}} open to-dos", { n: r.open_reasons })}
            {r.resolved_reasons + r.corrected_items > 0 ? <span className="error-text">{" · "}{humanWorkLeft(r.resolved_reasons, r.corrected_items)}</span> : null}{" "}
            <ConfirmButton className="secondary small-btn" disabled={busy} onConfirm={() => onSupersede(r.run_id)}>{t("Supersede")}</ConfirmButton>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RunPlanList({ plan, budget }: { plan: RunPlan; budget: Record<string, string> }) {
  useLocale();
  return (
    <div className="run-plan">
      <h3>{t("What happens when the run starts")}</h3>
      <ul className="plain small">{planLines(plan, budget).map((line) => <li key={line}>{line}</li>)}</ul>
      <p className="muted small">{t("The budget is an upper limit: the system reserves this much when the run starts; the actual cost is usually lower and can be followed on the run's page.")}</p>
    </div>
  );
}

/** The settings of the package's processing (080: one processing — the system recognises each document's type — so
 *  there is nothing to choose, only settings). Without saved settings the default ones apply; starting a run saves
 *  them. A package still on an older recipe shows that recipe's title and can be moved onto the current processing. */
function SettingsCard({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const wp = view.workpackage;
  const current = wp.assignment;
  const recipes = useLoad("recipes", api.recipes);
  const catalogue = useMemo(() => recipes.data?.recipes ?? [], [recipes.data]);
  const help: RecipeHelp | undefined = recipes.data?.help;
  const currentRecipe = catalogue.find((r) => r.id === current?.recipe_id);
  const [open, setOpen] = useState(false);
  const [recipeId, setRecipeId] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const recipe: Recipe | undefined = catalogue.find((r) => r.id === recipeId) ?? currentRecipe ?? catalogue[0];
  // 080: only the settings that act on the package's items (no task proposal on a package without emails)
  const kinds = useMemo(() => [...new Set(wp.items.map((i) => i.kind))], [wp.items]);

  useEffect(() => {
    // the editor starts from the saved settings; an older recipe's settings carry over where the processing has them
    if (!open || !recipe) return;
    setParams(Object.fromEntries(Object.entries(recipe.params).map(([k, spec]) => [k, current?.params[k] ?? spec.default ?? ""])));
  }, [open, recipe, current?.revision]); // eslint-disable-line react-hooks/exhaustive-deps -- a poll must not reset the edits

  const options = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const [k, spec] of Object.entries(recipe?.params ?? {})) out[k] = spec.allowed ?? (spec.default ? [spec.default] : []);
    return out;
  }, [recipe]);
  const full: Record<string, string> = recipe ? { ...recipeDefaults(recipe), ...params } : {};

  async function save() {
    if (!recipe) return;
    setBusy(true);
    setMsg(null);
    try {
      const full: Record<string, string> = {};
      for (const [k, spec] of Object.entries(recipe.params)) full[k] = params[k] ?? spec.default ?? "";
      await api.saveWorkflow(wp.id, { recipe_id: recipe.id, params: full, expected_revision: current?.revision ?? 0, note: note || undefined });
      setMsg({ error: false, text: t("Settings saved.") });
      setNote("");
      setOpen(false);
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.status === 409 ? t("Someone else changed the settings meanwhile. We refreshed them; your choices are kept, save again.") : err.message });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide" aria-label={t("Processing settings")}>
      <div className="card-head">
        <h2>{t("Processing settings")}</h2>
        {/* 263 (F1): the form's exit is its foot's "Cancel" */}
        {open ? null : (
          <button type="button" className="secondary" aria-expanded={open} disabled={!catalogue.length}
            onClick={() => { setRecipeId(currentRecipe?.id ?? catalogue[0]?.id ?? ""); setOpen(true); }}>
            <Icon name="edit" />{t("Modify")}
          </button>
        )}
      </div>
      {recipes.error ? <p className="notice error">{recipes.error.message}</p> : null}
      {!open ? (
        current && currentRecipe ? (
          <>
            <p><strong>{recipeTitle(currentRecipe, help)}</strong></p>
            <p className="muted small">{t("saved by {{actor}}, {{when}}", { actor: current.actor, when: when(current.created_at) })}</p>
            {/* 063: each setting's meaning and the per-item cost budget */}
            <RecipeParamList recipe={currentRecipe} params={current.params} help={help} kinds={kinds} />
          </>
        ) : current ? (
          <>
            <p><strong>{t(recipes.data?.titles?.[current.recipe_id] ?? current.recipe_id)}</strong>
              <span className="muted small"> — {t("saved by {{actor}}, {{when}}", { actor: current.actor, when: when(current.created_at) })}</span></p>
            <p className="muted">{paramsText(current.params)}</p>
            <p className="notice">{t("This batch keeps the settings of an earlier version of the processing. With the Change button you can move it onto the current processing; its settings are kept, and a document type given in advance is dropped, because the system recognises it.")}</p>
          </>
        ) : catalogue[0] ? (
          <>
            <p><strong>{recipeTitle(catalogue[0], help)}</strong></p>
            <p className="muted">{t("Default settings: if you do not change them, they are saved to the batch when a run starts.")}</p>
            <RecipeParamList recipe={catalogue[0]} params={{}} help={help} kinds={kinds} />
          </>
        ) : null
      ) : recipe ? (
        <div className="recipe-form">
          {help?.recipes[recipe.id]?.when ? <p className="notice small">{t(help.recipes[recipe.id].when)}</p> : null}
          {catalogue.length > 1 ? (
            <Picker label={t("Processing")} value={recipe.id} className="block-picker"
              options={catalogue.map((r) => ({ value: r.id, label: recipeTitle(r, help) }))}
              onChange={(v) => setRecipeId(v)} />
          ) : null}
          {/* 090: the processing path first (the documents' path and the use of JEV as one choice), then the settings
              that count; without JEV the JEV answers are not shown */}
          {shownParams(Object.keys(options), full, kinds).map((k) => {
            const value = shownValue(k, full, kinds);
            const choices = k === PATH ? pathOptions(options.arm ?? [], kinds) : options[k];
            const explain = paramExplanation(help, k, value, recipe);
            return (
              <div key={k} className="param-field">
                <Picker label={PARAM_LABEL[k] ?? k} className="block-picker" value={value}
                  options={choices.map((o) => ({ value: o, label: paramValue(k, o) }))}
                  onChange={(v) => setParams((p) => (k === PATH ? applyPath({ ...full, ...p }, v) : { ...p, [k]: v }))} />
                {explain ? <p className="param-note">{explain}</p> : null}
              </div>
            );
          })}
          <p className="small"><strong>{t("Cost budget")}:</strong> {itemBudgetLines(recipe, full, kinds).join("; ")}</p>
          <label className="block">{t("Note")} <span className="muted">{t("(may be omitted)")}</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
          </label>
          <FormActions onCancel={() => setOpen(false)} busy={busy}>
            <button type="button" className="primary" disabled={busy} onClick={() => void save()}>{t("Save settings")}</button>
          </FormActions>
        </div>
      ) : null}
      <p className="small"><a href={`#/settings/recipes`}>{t("How the system works and what the settings mean")} ›</a></p>
      {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
    </section>
  );
}
