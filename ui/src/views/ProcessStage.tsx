// Processing section (057): running (trial, live, rerun) at the top, below it the processing settings (a summary,
// editable when expanded; 080: there is one processing, so nothing to choose, only settings) and the package's runs.
// The run's details (progress, cost, call log) are on the run's page. The run buttons do not start anything: they lead
// to the confirmation page (061 decision, `StartConfirm`).
// 168 (DECISIONS 168, the owner's choice "Run on top"): below the Run card the package's items (`PackageItems`), where
// files and folders are added; while its add form is open, its own last step is the view's one solid button.
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Recipe, type RecipeHelp, type RunPlan, type SupersedableRun, type WorkpackageView } from "../api";
import { ConfirmButton } from "../components/ConfirmButton";
import { DataTable } from "../components/DataTable";
import { Icon } from "../components/Icon";
import { Picker } from "../components/Picker";
import { PackageCosts } from "./PackageCosts";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { applyPath, itemBudgetLines, MODE, PARAM_LABEL, paramShort, paramsText, PATH, pathOptions, planLines, providerName, RUN_STATUS, shownParams, shownValue, tmap, usdBudget, when, blockerText } from "../labels";
import { go } from "../route";
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

  async function addAttachments() {
    setBusy(true);
    setMsg(null);
    try {
      await api.addAttachments(wp.id, wp.revision);
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
      setMsg({ error: false, text: t("A beállítások a feldolgozás mostani változatára frissültek.") });
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
      <section className="card wide" aria-label={t("Futtatás")}>
        <div className="card-head">
          <h2>{t("Futtatás")}</h2>
          {last ? <a className="small" href={`#/runs/${last.run_id}`}>{t("A legutóbbi futás részletei")}</a> : null}
        </div>
        {last ? (
          <div className="run-summary">
            <span className={`status s-${last.status}`}>{RUN_STATUS[last.status] ?? last.status}</span>
            <span>{t("{{mode}} futás · {{when}} · {{done}}/{{total}} tétel", { mode: MODE[last.mode], when: when(last.created_at), done: last.items_done, total: last.items })}</span>
            {last.open_reasons ? <a href={`#/workpackages/${wp.id}/review`}>{t("{{n}} teendő", { n: last.open_reasons })}</a> : null}
            {active ? (
              <div className="bar wide-bar" role="meter" aria-label={t("Haladás")} aria-valuemin={0} aria-valuemax={last.items} aria-valuenow={last.items_done}>
                <span style={{ width: `${(100 * last.items_done) / Math.max(1, last.items)}%` }} />
              </div>
            ) : null}
          </div>
        ) : <p className="muted">{t("Ezen a csomagon még nem futott feldolgozás.")}</p>}
        {view.attachments_missing ? (
          // 058 K5.2: in an email package from before 058 the PDF attachments are not items yet; once added, the email
          // recipe extracts their data
          <p className="notice">{t("A levelek {{n}} PDF-csatolmánya még nincs a csomagban. Felvéve a következő futás a csatolmányok adatait is kinyeri.", { n: view.attachments_missing })}
            {" "}<button type="button" className="secondary small-btn" disabled={busy || active} onClick={() => void addAttachments()}><Icon name="plus" />{t("Csatolmányok felvétele")}</button></p>
        ) : null}
        {!readiness.ready ? (
          <ul className="plain">{readiness.blockers.map((b, i) => <li key={i} className="blocker">{blockerText(b)}</li>)}</ul>
        ) : null}
        {readiness.warnings.length ? (
          <ul className="plain">{readiness.warnings.map((w, i) => (
            <li key={i} className="warning">{blockerText(w)}
              {w.code === "recipe_changed" || w.code === "recipe_retired" ? <> <button type="button" className="secondary small-btn" disabled={busy || active || !recipes.data}
                onClick={() => void refreshAssignment()}><Icon name="rerun" />{t("Átállítás a mostani feldolgozásra")}</button></> : null}
            </li>))}
          </ul>
        ) : null}
        <OlderRunsOffer runs={view.supersedable ?? []} busy={busy || active} onSupersede={(id) => void supersede(id)} />
        <div className="button-row">
          {pendingButtons((m) => btn(`pending-${m}`))}
          <button type="button" className={btn("shadow")} data-run="shadow" title={withSpend(cap)} disabled={!readiness.ready || busy || active}
            onClick={() => start("shadow")}><Icon name="trial" />{t("Próbafutás")}…{spend}</button>
          {/* the live run is the consequential one: only its result can be released */}
          <button type="button" className={btn("apply")} data-run="apply" title={withSpend(cap)}
            disabled={!readiness.ready || busy || active} onClick={() => start("apply")}><Icon name="play" />{t("Éles futás")}…{spend}</button>
          <button type="button" className={btn("rerun")} data-run="rerun" disabled={!target || !readiness.ready || busy || active}
            title={withSpend(cap, target ? t("Again as a new {{mode}} run, on the package's documents as they are now", { mode: MODE[target.mode].toLowerCase() }) : t("Még nincs megismételhető futás"))}
            onClick={() => target && start(target.mode, true)}><Icon name="rerun" />{t("Újrafuttatás")}…{spend}</button>
        </div>
        <dl className="run-help small">
          <dt>{t("Próbafutás")}</dt><dd>{t("az eredmény megtekinthető és letölthető, de nem adható ki")}</dd>
          <dt>{t("Éles futás")}</dt><dd>{t("az eredményt ember hagyja jóvá az Eredmény szakaszban, nyitott teendő nélkül")}</dd>
          {/* 160-C S2: a rerun takes the package as it is now, not the earlier run's input */}
          <dt>{t("Újrafuttatás")}</dt><dd>{t("the last run again as a new run, on all the package's documents as they are now (the added ones too, the removed ones not), for example after an error, a stop or a change of settings")}</dd>
          {supplements.length ? <>
            <dt>{t("Pending items only")}</dt>
            <dd>{t("a new run over only the items no run of that kind has finished yet (added since, or failed); the earlier runs and their approval stay as they are, and its result is reviewed and approved on its own")}</dd>
          </> : null}
        </dl>
        {readiness.plan ? <RunPlanList plan={readiness.plan} budget={readiness.budget} /> : (
          <p className="muted small">
            {t("Költségkeret: {{budget}}.", { budget: Object.entries(readiness.budget)
              .map(([p, v]) => t("{{provider}} legfeljebb {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ") || t("nincs") })}
          </p>
        )}
        {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
      </section>

      {/* 168: the address holds whether the add form is open, so the package's actions menu can open it */}
      <PackageItems view={view} adding={adding ? source : null} onChanged={onChanged}
        onAddingChange={(s) => { if (s) setSource(s); go({ view: "workpackages", wpId: wp.id, stage: "process", ...(s ? { add: true } : {}) }); }}
        pendingAction={supplements.length ? <div className="button-row">{pendingButtons(() => "secondary", "items")}</div> : undefined} />

      <SettingsCard view={view} onChanged={onChanged} />

      <section aria-label={t("Futások")} className="wide">
        <h2>{t("A csomag futásai")}</h2>
        <DataTable dataset="runs" scope={{ workpackage_id: wp.id }} label={t("A csomag futásai")} storageId="wp-runs" defaultHidden={["workpackage_name"]} pollMs={active ? 4000 : undefined}
          emptyText={t("Még nem futott.")} initial={{ limit: 50 }} />
      </section>

      <PackageCosts wpId={wp.id} pollMs={active ? 4000 : undefined} />
    </div>
  );
}

const PARAM_VALUE: Record<string, string> = tmap({
  "jev_cache:reuse": "Korábbi válasz újrahasználható",
  "jev_cache:live": "Mindig élő hívás",
  "tasks:off": "Nincs feladatjavaslat",
  "tasks:propose": "Feladatjavaslat a levelekből (GPT; archiválandó levélen nem; elfogadni csak ember tud)",
  "azure_ocr:on": "Gyenge helyi felismerésnél Azure-felismerés (fizetős, a futás Azure-keretén belül)",
  "azure_ocr:off": "Csak helyi felismerés",
  // 120 (the owner's decision of 2026-10-06; codepoints for the language guard)
  "unknown_documents:facts": "PDF, amelynek t\u00edpus\u00e1hoz nincs illeszked\u0151 t\u00edpusle\u00edr\u00e1s: \u00e1ltal\u00e1nos, forr\u00e1shoz k\u00f6t\u00f6tt adatjavaslatok (GPT + JEV; a szkennelt iratot helyi sz\u00f6vegfelismer\u00e9ssel, teend\u0151vel); a felismert t\u00edpus \u00e9s bizonytalans\u00e1ga megmarad",
  "unknown_documents:review": "Az ilyen PDF feldolgoz\u00e1sa meg\u00e1ll, \u00e9s teend\u0151t kap (kor\u00e1bbi viselked\u00e9s)",
  "jev:on": "Bekapcsolva: a JEV ismeri fel a típust és a levél szándékát, és választ vagy ellenőriz az adatkinyerésnél",
  "jev:off": "Kikapcsolva: csak GPT (OpenAI) — típusfelismerés, adatkinyerés és levélszándék GPT-vel, kódos ellenőrzéssel",
  // 090: the processing path (the documents' path and the use of JEV as one choice)
  "path:auto": "Automatikus (ajánlott) — JEV és GPT, iratonként az irattípus ajánlott útja",
  "path:gpt": "Csak GPT, JEV nélkül — típusfelismerés, adatkinyerés és levélszándék GPT-vel, kódos ellenőrzéssel (OpenAI)",
  "path:jev": "JEV-vel (ajánlott) — a JEV ismeri fel a levél szándékát",
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

export function OlderRunsOffer({ runs, busy, onSupersede }: { runs: SupersedableRun[]; busy: boolean; onSupersede: (runId: string) => void }) {
  useLocale();
  if (!runs.length) return null;
  const open = runs.reduce((n, r) => n + r.open_reasons, 0);
  return (
    <div className="notice" role="region" aria-label={t("Older live runs")}>
      <p>{t("{{n}} older live run(s) were repeated by a later live run on the same documents. Superseding stops them and closes their {{m}} open to-dos; they cannot be approved afterwards.",
        { n: runs.length, m: open })}</p>
      <ul className="plain">
        {runs.map((r) => (
          <li key={r.run_id}>
            <a href={`#/runs/${encodeURIComponent(r.run_id)}`}>{t("Live run, {{when}}", { when: when(r.created_at) })}</a>
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
      <h3>{t("Mi történik indításkor")}</h3>
      <ul className="plain small">{planLines(plan, budget).map((line) => <li key={line}>{line}</li>)}</ul>
      <p className="muted small">{t("A keret felső határ: ennyit foglal le a rendszer az indításkor; a tényleges költség általában kisebb, és a futás oldalán követhető.")}</p>
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
      setMsg({ error: false, text: t("Beállítások elmentve.") });
      setNote("");
      setOpen(false);
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.status === 409 ? t("Közben más módosította a beállításokat. Frissítettük; a választásaid megmaradtak, mentsd újra.") : err.message });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide" aria-label={t("Feldolgozási beállítások")}>
      <div className="card-head">
        <h2>{t("Feldolgozási beállítások")}</h2>
        <button type="button" className="secondary" aria-expanded={open} disabled={!catalogue.length}
          onClick={() => { setRecipeId(currentRecipe?.id ?? catalogue[0]?.id ?? ""); setOpen((o) => !o); }}>
          {open ? <><Icon name="close" />{t("Bezárás")}</> : <><Icon name="edit" />{t("Módosítás")}</>}
        </button>
      </div>
      {recipes.error ? <p className="notice error">{recipes.error.message}</p> : null}
      {!open ? (
        current && currentRecipe ? (
          <>
            <p><strong>{recipeTitle(currentRecipe, help)}</strong></p>
            <p className="muted small">{t("mentette: {{actor}}, {{when}}", { actor: current.actor, when: when(current.created_at) })}</p>
            {/* 063: each setting's meaning and the per-item cost budget */}
            <RecipeParamList recipe={currentRecipe} params={current.params} help={help} kinds={kinds} />
          </>
        ) : current ? (
          <>
            <p><strong>{t(recipes.data?.titles?.[current.recipe_id] ?? current.recipe_id)}</strong>
              <span className="muted small"> — {t("mentette: {{actor}}, {{when}}", { actor: current.actor, when: when(current.created_at) })}</span></p>
            <p className="muted">{paramsText(current.params)}</p>
            <p className="notice">{t("Ez a csomag egy korábbi feldolgozási változat beállításait őrzi. A Módosítás gombbal a mostani feldolgozásra állíthatod; a beállításai megmaradnak, az előre megadott irattípus elmarad, mert a rendszer felismeri.")}</p>
          </>
        ) : catalogue[0] ? (
          <>
            <p><strong>{recipeTitle(catalogue[0], help)}</strong></p>
            <p className="muted">{t("Alapbeállítás: ha nem módosítod, a futás indításakor ez mentődik a csomaghoz.")}</p>
            <RecipeParamList recipe={catalogue[0]} params={{}} help={help} kinds={kinds} />
          </>
        ) : null
      ) : recipe ? (
        <div className="recipe-form">
          {help?.recipes[recipe.id]?.when ? <p className="notice small">{t(help.recipes[recipe.id].when)}</p> : null}
          {catalogue.length > 1 ? (
            <Picker label={t("Feldolgozás")} value={recipe.id} className="block-picker"
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
          <p className="small"><strong>{t("Költségkeret")}:</strong> {itemBudgetLines(recipe, full, kinds).join("; ")}</p>
          <label className="block">{t("Megjegyzés")} <span className="muted">{t("(elhagyható)")}</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
          </label>
          <button type="button" className="primary" disabled={busy} onClick={() => void save()}>{t("Beállítások mentése")}</button>
        </div>
      ) : null}
      <p className="small"><a href={`#/settings/recipes`}>{t("Hogyan dolgozik a rendszer, és mit jelentenek a beállítások")} ›</a></p>
      {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
    </section>
  );
}
