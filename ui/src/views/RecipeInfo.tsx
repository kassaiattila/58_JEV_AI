// 063 (decision of 2026-09-29): explanation of the processing. The work package's settings card states, per setting,
// what the chosen value means and what the budget per item is; the Beállítások › Feldolgozás (Settings › Processing)
// page gives the full description: how each item kind is processed, the steps, the paths compared with the measured
// numbers (080), every value of the settings and the result. The text comes from `configs/recipe_help.json`.
import { api, type Recipe, type RecipeHelp } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { docTypeLabel, itemBudgetLines, jevOffNote, orderedParams, PARAM_LABEL, paramApplies, paramInEffect, paramShort } from "../labels";

const BUDGET_NOTE = "felső határ: ennyit foglal le a rendszer a futás indításakor; a tényleges költség általában kisebb, és a futás oldalán követhető";

/** The recipe's default settings (the parameters' default values). */
export const recipeDefaults = (r: Recipe): Record<string, string> =>
  Object.fromEntries(Object.entries(r.params).map(([k, spec]) => [k, spec.default ?? ""]));

/** The explanation of a setting's chosen value; if the value has none (e.g. document type), the setting's own. */
export function paramExplanation(help: RecipeHelp | undefined, k: string, v: string): string | null {
  const p = help?.params[k];
  const text = p?.options[v] ?? p?.help;
  return text ? t(text) : null;
}

/** The settings card's explanatory list: per setting, the chosen value and its meaning, with the budget at the end.
 *  `kinds` (080): the package's item kinds — a setting or budget line that cannot act on any of them is left out. */
export function RecipeParamList({ recipe, params, help, kinds }: { recipe: Recipe; params: Record<string, string>; help?: RecipeHelp; kinds?: string[] }) {
  useLocale();
  const full = { ...recipeDefaults(recipe), ...params };
  return (
    <dl className="param-help">
      {/* 089: the use of JEV first; without it the path and the JEV answers do not count, one sentence instead */}
      {orderedParams(Object.keys(recipe.params)).filter((k) => paramApplies(k, kinds) && paramInEffect(k, full)).map((k) => {
        const text = paramExplanation(help, k, full[k]);
        const note = k === "jev" ? jevOffNote(full) : null;
        return (
          <div key={k} className="param-row">
            <dt>{PARAM_LABEL[k] ?? k}</dt>
            <dd><strong>{paramShort(k, full[k])}</strong>{text ? <span className="param-note">{text}</span> : null}
              {note ? <span className="param-note">{note}</span> : null}</dd>
          </div>
        );
      })}
      <div className="param-row">
        <dt>{t("Költségkeret")}</dt>
        <dd>
          {itemBudgetLines(recipe, full, kinds).map((line) => <strong key={line} className="budget-line">{line}</strong>)}
          <span className="param-note">{t(BUDGET_NOTE)}</span>
        </dd>
      </div>
    </dl>
  );
}

/** Beállítások › Feldolgozás (Settings › Processing, 080): how the system processes a package, the paths compared and
 *  the settings — for the processing the UI offers (one since 080). */
export function RecipesPanel() {
  useLocale();
  const recipes = useLoad("recipes", api.recipes);
  if (recipes.error) return <p className="notice error">{recipes.error.message}</p>;
  if (!recipes.data) return <p className="muted">{t("Betöltés…")}</p>;
  const help = recipes.data.help;
  return (
    <>
      <p className="page-summary">{help?.intro ? t(help.intro) : null} {t("A beállításokat a csomag Feldolgozás szakaszában lehet módosítani; a módosítás új változatként mentődik, a korábbi futások a saját beállításaikat őrzik.")}</p>
      {help?.paths ? <PathCompare paths={help.paths} /> : null}
      {recipes.data.recipes.map((r) => <RecipeDetails key={r.id} recipe={r} help={help} />)}
    </>
  );
}

/** 080: the S and G paths side by side — what they do, what they read, which services, typical cost, the measured
 *  agreement with the golden set, which document types, when each is better. */
function PathCompare({ paths }: { paths: NonNullable<RecipeHelp["paths"]> }) {
  useLocale();
  return (
    <section className="card wide recipe-doc" aria-label={t("Az utak összevetése")}>
      <h3>{t("Az utak összevetése")}</h3>
      <p>{t(paths.intro)}</p>
      <div className="table-scroll">
        <table className="path-compare">
          <thead><tr><th scope="col"><span className="sr-only">{t("Szempont")}</span></th><th scope="col">{t(paths.columns.S)}</th><th scope="col">{t(paths.columns.G)}</th></tr></thead>
          <tbody>
            {paths.rows.map((row) => (
              <tr key={row.label}><th scope="row">{t(row.label)}</th><td>{t(row.S)}</td><td>{t(row.G)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">{t(paths.measured)}</p>
    </section>
  );
}

function RecipeDetails({ recipe, help }: { recipe: Recipe; help?: RecipeHelp }) {
  useLocale();
  const defaults = recipeDefaults(recipe);
  const kinds = help?.kinds ?? {};
  return (
    <section className="card wide recipe-doc" id={`recipe-${recipe.id}`} aria-label={t(recipe.title)}>
      <div className="card-head">
        <h3>{t("Hogyan dolgozik a rendszer")}</h3>
        <span className="muted small">{t("{{version}}. változat", { version: recipe.version })}</span>
      </div>
      <p>{t(recipe.description)}</p>
      <dl className="recipe-kv">
        {kinds.document ? <><dt>{t("PDF-irat")}</dt><dd>{t(kinds.document)}</dd></> : null}
        {kinds.email ? <><dt>{t("Levél")}</dt><dd>{t(kinds.email)}</dd></> : null}
        <dt>{t("Mi kell hozzá")}</dt>
        <dd><ul className="tight">{recipe.requirements.map((x) => <li key={x}>{t(x)}</li>)}</ul></dd>
        <dt>{t("Lépések")}</dt>
        <dd><ol className="tight">{recipe.steps.map((x) => <li key={x}>{t(x)}</li>)}</ol></dd>
        <dt>{t("Eredmény")}</dt><dd>{t(recipe.result)}</dd>
        <dt>{t("Az ember teendője")}</dt><dd>{t(recipe.manual_action)}</dd>
        <dt>{t("Költségkeret alapbeállítással")}</dt>
        <dd>
          {itemBudgetLines(recipe, defaults).map((line) => <div key={line}>{line}</div>)}
          <span className="muted small">{t(BUDGET_NOTE)}</span>
        </dd>
      </dl>
      <h4>{t("Beállítások")}</h4>
      {orderedParams(Object.keys(recipe.params)).map((k) => {
        const spec = recipe.params[k];
        const options = spec.allowed ?? [];
        // the budget per option is only shown where the setting also affects the cost (e.g. path, task proposal)
        const costs = options.map((o) => itemBudgetLines(recipe, { ...defaults, [k]: o }).join("; "));
        const costVaries = new Set(costs).size > 1;
        const p = help?.params[k];
        return (
          <div key={k} className="param-doc">
            <p><strong>{PARAM_LABEL[k] ?? k}</strong>{p?.help ? <> — {t(p.help)}</> : null}</p>
            {k === "doc_type" ? (
              <details>
                <summary>{t("{{n}} választható irattípus; alapbeállítás: {{name}}", { n: options.length, name: docTypeLabel(spec.default ?? "") })}</summary>
                <ul className="tight columns">{options.map((o) => <li key={o}>{docTypeLabel(o)}</li>)}</ul>
              </details>
            ) : (
              <ul className="option-list">
                {options.map((o, i) => (
                  <li key={o}>
                    <strong>{paramShort(k, o)}</strong>
                    {o === spec.default ? <span className="status s-ok">{t("alapbeállítás")}</span> : null}
                    {p?.options[o] ? <span className="option-text">{t(p.options[o])}</span> : null}
                    {jevOffNote({ [k]: o }) ? <span className="option-text">{jevOffNote({ [k]: o })}</span> : null}
                    {costVaries ? <span className="muted small option-text">{t("Költségkeret: {{cost}}", { cost: costs[i] })}</span> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </section>
  );
}
