// Processing section (057): running (trial, live, rerun) at the top, below it the processing settings (a summary,
// editable when expanded; 080: there is one processing, so nothing to choose, only settings) and the package's runs.
// The run's details (progress, cost, call log) are on the run's page. The run buttons do not start anything: they lead
// to the confirmation page (061 decision, `StartConfirm`).
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Recipe, type RecipeHelp, type RunPlan, type WorkpackageView } from "../api";
import { DataTable } from "../components/DataTable";
import { Icon } from "../components/Icon";
import { Picker } from "../components/Picker";
import { PackageCosts } from "./PackageCosts";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { applyPath, itemBudgetLines, MODE, PARAM_LABEL, paramShort, paramsText, PATH, pathOptions, planLines, providerName, RUN_STATUS, shownParams, shownValue, tmap, usdBudget, when, blockerText } from "../labels";
import { go } from "../route";
import { paramExplanation, RecipeParamList, recipeDefaults, recipeTitle } from "./RecipeInfo";

const ACTIVE = new Set(["queued", "running"]);

export function ProcessStage({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const { workpackage: wp, readiness, last_run: last } = view;
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const active = last ? ACTIVE.has(last.status) : false;
  // 058: a single highlighted button — the one the package's next step asks for (the list and the header show it too)
  const primary = { start: "shadow", go_live: "apply", rerun: "rerun" }[view.next.code as string] ?? null;
  const btn = (which: string) => (primary === which ? "primary" : "secondary");
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

  // 061: the button leads to the confirmation page; the start happens there
  const start = (mode: "shadow" | "apply", rerun = false) => go({ view: "workpackages", wpId: wp.id, stage: "process", start: { mode, rerun } });

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
        <div className="button-row">
          <button type="button" className={btn("shadow")} disabled={!readiness.ready || busy || active} onClick={() => start("shadow")}><Icon name="trial" />{t("Próbafutás")}…</button>
          <button type="button" className={btn("apply")}
            disabled={!readiness.ready || busy || active} onClick={() => start("apply")}><Icon name="play" />{t("Éles futás")}…</button>
          <button type="button" className={btn("rerun")} disabled={!last || !readiness.ready || busy || active}
            title={last ? t("A legutóbbi ({{mode}}) futás megismétlése ugyanezzel a bemenettel", { mode: MODE[last.mode].toLowerCase() }) : t("Még nincs megismételhető futás")}
            onClick={() => last && start(last.mode, true)}><Icon name="rerun" />{t("Újrafuttatás")}…</button>
        </div>
        <dl className="run-help small">
          <dt>{t("Próbafutás")}</dt><dd>{t("az eredmény megtekinthető és letölthető, de nem adható ki")}</dd>
          <dt>{t("Éles futás")}</dt><dd>{t("az eredményt ember hagyja jóvá az Eredmény szakaszban, nyitott teendő nélkül")}</dd>
          <dt>{t("Újrafuttatás")}</dt><dd>{t("a legutóbbi futás megismétlése ugyanazzal a bemenettel, új futásként (például hiba, leállítás vagy a beállítások módosítása után)")}</dd>
        </dl>
        {readiness.plan ? <RunPlanList plan={readiness.plan} budget={readiness.budget} /> : (
          <p className="muted small">
            {t("Költségkeret: {{budget}}.", { budget: Object.entries(readiness.budget)
              .map(([p, v]) => t("{{provider}} legfeljebb {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ") || t("nincs") })}
          </p>
        )}
        {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
      </section>

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
