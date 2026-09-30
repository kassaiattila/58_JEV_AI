// Feldolgozás szakasz (057): futtatás (próba, éles, újrafuttatás) felül, alatta a recept (összefoglaló, kinyitva
// szerkeszthető) és a csomag futásai. A futás részletei (haladás, költség, hívásnapló) a futás oldalán. A futtató
// gombok nem indítanak: a megerősítő oldalra visznek (061 döntés, `StartConfirm`).
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Recipe, type WorkpackageView } from "../api";
import { DataTable } from "../components/DataTable";
import { Icon } from "../components/Icon";
import { Picker } from "../components/Picker";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { docTypeLabel, itemBudgetLines, MODE, PARAM_LABEL, providerName, RUN_STATUS, tmap, usdBudget, when, blockerText } from "../labels";
import { go } from "../route";
import { paramExplanation, RecipeParamList, recipeDefaults } from "./RecipeInfo";

const ACTIVE = new Set(["queued", "running"]);

export function ProcessStage({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const { workpackage: wp, readiness, last_run: last } = view;
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const active = last ? ACTIVE.has(last.status) : false;
  // 058: egyetlen kiemelt gomb — az, amelyiket a csomag következő lépése kér (a lista és a fejléc is ezt mutatja)
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
    // a recept mostani változatára: a meglévő beállítások maradnak, az új paraméter az alapértéket kapja
    const a = wp.assignment;
    const r = recipes.data?.recipes.find((x) => x.id === a?.recipe_id);
    if (!a || !r) return;
    setBusy(true);
    setMsg(null);
    try {
      const params: Record<string, string> = {};
      for (const [k, spec] of Object.entries(r.params)) params[k] = a.params[k] ?? spec.default ?? "";
      // a megjegyzés adat (a hozzárendelés naplójában), nem felirat
      await api.saveWorkflow(wp.id, { recipe_id: r.id, params, expected_revision: a.revision, note: "frissítés a recept mostani változatára" }); // i18n-ignore
      setMsg({ error: false, text: t("A hozzárendelés a recept mostani változatára frissült.") });
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  // 061: a gomb a megerősítő oldalra visz; az indítás ott történik
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
        ) : <p className="muted">{t("Ezen a csomagon még nem futott recept.")}</p>}
        {view.attachments_missing ? (
          // 058 K5.2: a 058 előtti levélcsomagban a PDF-csatolmányok még nem tételek; felvéve a levél-recept kinyeri az adatukat
          <p className="notice">{t("A levelek {{n}} PDF-csatolmánya még nincs a csomagban. Felvéve a következő futás a csatolmányok adatait is kinyeri.", { n: view.attachments_missing })}
            {" "}<button type="button" className="secondary small-btn" disabled={busy || active} onClick={() => void addAttachments()}><Icon name="plus" />{t("Csatolmányok felvétele")}</button></p>
        ) : null}
        {!readiness.ready ? (
          <ul className="plain">{readiness.blockers.map((b, i) => <li key={i} className="blocker">{blockerText(b)}</li>)}</ul>
        ) : null}
        {readiness.warnings.length ? (
          <ul className="plain">{readiness.warnings.map((w, i) => (
            <li key={i} className="warning">{blockerText(w)}
              {w.code === "recipe_changed" ? <> <button type="button" className="secondary small-btn" disabled={busy || active || !recipes.data}
                onClick={() => void refreshAssignment()}><Icon name="rerun" />{t("Frissítés a recept mostani változatára")}</button></> : null}
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
          <dt>{t("Újrafuttatás")}</dt><dd>{t("a legutóbbi futás megismétlése ugyanazzal a bemenettel, új futásként (például hiba, leállítás vagy a recept frissítése után)")}</dd>
        </dl>
        <p className="muted small">
          {t("Költségkeret: {{budget}}.", { budget: Object.entries(readiness.budget)
            .map(([p, v]) => t("{{provider}} legfeljebb {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ") || t("nincs") })}
        </p>
        {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
      </section>

      <RecipeCard view={view} onChanged={onChanged} />

      <section aria-label={t("Futások")} className="wide">
        <h2>{t("A csomag futásai")}</h2>
        <DataTable dataset="runs" scope={{ workpackage_id: wp.id }} label={t("A csomag futásai")} storageId="wp-runs" defaultHidden={["workpackage_name"]} pollMs={active ? 4000 : undefined}
          emptyText={t("Még nem futott.")} initial={{ limit: 50 }} />
      </section>
    </div>
  );
}

const PARAM_VALUE: Record<string, string> = tmap({
  "arm:auto": "automatikus: az irattípus ajánlott útja (közmű-számla: G, mert tételt is ad; magyar számla: S)",
  "arm:S": "S: a kód jelöltet talál, a JEV választ",
  "arm:G": "G: GPT-kivonat, JEV-ellenőrzés",
  "jev_cache:reuse": "Korábbi válasz újrahasználható",
  "jev_cache:live": "Mindig élő hívás",
  "tasks:off": "Nincs feladatjavaslat",
  "tasks:propose": "Feladatjavaslat a levelekből (GPT; archiválandó levélen nem; elfogadni csak ember tud)",
  "azure_ocr:on": "Gyenge helyi felismerésnél Azure-felismerés (fizetős, a recept Azure-keretén belül)",
  "azure_ocr:off": "Csak helyi felismerés",
});
/** Paraméter-érték felirata; irattípusnál a típus neve. */
export const paramValue = (k: string, v: string) => PARAM_VALUE[`${k}:${v}`] ?? (k === "doc_type" ? docTypeLabel(v) : v);

function RecipeCard({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const wp = view.workpackage;
  const current = wp.assignment;
  const recipes = useLoad("recipes", api.recipes);
  const [open, setOpen] = useState(!current);
  const [recipeId, setRecipeId] = useState(current?.recipe_id ?? "");
  const [params, setParams] = useState<Record<string, string>>(current?.params ?? {});
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const recipe: Recipe | undefined = recipes.data?.recipes.find((r) => r.id === recipeId);
  const currentRecipe = recipes.data?.recipes.find((r) => r.id === current?.recipe_id);
  const whenText = (r: Recipe) => { const w = recipes.data?.help?.recipes[r.id]?.when; return w ? t(w) : null; };

  useEffect(() => {
    if (!recipeId && recipes.data?.recipes.length) setRecipeId(recipes.data.recipes[0].id);
  }, [recipes.data, recipeId]);

  const options = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const [k, spec] of Object.entries(recipe?.params ?? {})) out[k] = spec.allowed ?? (spec.default ? [spec.default] : []);
    return out;
  }, [recipe]);

  async function save() {
    if (!recipe) return;
    setBusy(true);
    setMsg(null);
    try {
      const full: Record<string, string> = {};
      for (const [k, spec] of Object.entries(recipe.params)) full[k] = params[k] ?? spec.default ?? "";
      await api.saveWorkflow(wp.id, { recipe_id: recipe.id, params: full, expected_revision: current?.revision ?? 0, note: note || undefined });
      setMsg({ error: false, text: t("Recept elmentve.") });
      setNote("");
      setOpen(false);
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.status === 409 ? t("Közben más módosította a receptet. Frissítettük; a beállításaid megmaradtak, mentsd újra.") : err.message });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide" aria-label={t("Recept")}>
      <div className="card-head">
        <h2>{t("Recept")}</h2>
        {current ? <button type="button" className="secondary" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? <><Icon name="close" />{t("Bezárás")}</> : <><Icon name="edit" />{t("Módosítás")}</>}</button> : null}
      </div>
      {current ? (
        <>
          <p>
            <strong>{currentRecipe ? t(currentRecipe.title) : current.recipe_id}</strong>
            {/* 065: a recept változata (mint a megerősítő oldalon); a hozzárendelés belső sorszáma nem „változat” */}
            <span className="muted small"> ({t("{{version}}. változat", { version: current.recipe_version })}) — {t("hozzárendelte: {{actor}}, {{when}}", { actor: current.actor, when: when(current.created_at) })}</span>
          </p>
          {/* 063: beállításonként a jelentés és a tételenkénti költségkeret, alatta a recept teljes leírása */}
          {currentRecipe && !open ? (
            <>
              {whenText(currentRecipe) ? <p className="muted">{whenText(currentRecipe)}</p> : null}
              <RecipeParamList recipe={currentRecipe} params={current.params} help={recipes.data?.help} />
              <p className="small"><a href={`#/settings/recipes`}>{t("A receptek teljes leírása a Beállításokban")} ›</a></p>
            </>
          ) : null}
        </>
      ) : <p className="muted">{t("Még nincs recept: válaszd ki, mit csináljon a rendszer a csomag irataival.")}</p>}
      {open ? (
        <div className="recipe-form">
          {recipes.error ? <p className="notice error">{recipes.error.message}</p> : null}
          <Picker label={t("Recept")} value={recipeId || null} className="block-picker"
            options={(recipes.data?.recipes ?? []).map((r) => ({ value: r.id, label: t("{{title}} ({{version}}. változat)", { title: t(r.title), version: r.version }) }))}
            onChange={(v) => { setRecipeId(v); setParams({}); }} />
          {recipe ? (
            <>
              <p className="muted small">{t(recipe.description)}</p>
              {whenText(recipe) ? <p className="small"><strong>{t("Mikor válaszd")}:</strong> {whenText(recipe)}</p> : null}
              <ol className="steps">{recipe.steps.map((s) => <li key={s}>{t(s)}</li>)}</ol>
              {Object.entries(options).map(([k, opts]) => {
                const value = params[k] ?? recipe.params[k].default ?? "";
                const explain = paramExplanation(recipes.data?.help, k, value);
                return (
                  <div key={k} className="param-field">
                    <Picker label={PARAM_LABEL[k] ?? k} className="block-picker" value={value}
                      options={opts.map((o) => ({ value: o, label: paramValue(k, o) }))}
                      onChange={(v) => setParams((p) => ({ ...p, [k]: v }))} />
                    {explain ? <p className="param-note">{explain}</p> : null}
                  </div>
                );
              })}
              <p className="small"><strong>{t("Költségkeret")}:</strong> {itemBudgetLines(recipe, { ...recipeDefaults(recipe), ...params }).join("; ")}</p>
              <label className="block">{t("Megjegyzés")} <span className="muted">{t("(elhagyható)")}</span>
                <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
              </label>
              <button type="button" className="primary" disabled={busy} onClick={() => void save()}>
                {current ? t("Recept mentése") : t("Recept hozzárendelése")}
              </button>
            </>
          ) : null}
        </div>
      ) : null}
      {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
    </section>
  );
}
