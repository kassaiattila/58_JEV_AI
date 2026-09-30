// 063 (decision of 2026-09-29): explanation of the recipes. The work package's Recipe card states, per setting, what
// the chosen value means and what the budget per item is; the Beállítások › Receptek (Settings › Recipes) page gives
// the full description (what it is for, what it needs, steps, result, the person's task, every value of the settings).
// The text comes from `configs/recipe_help.json`.
import { api, type Recipe, type RecipeHelp } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { docTypeLabel, itemBudgetLines, PARAM_LABEL, paramShort } from "../labels";

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

/** The Recipe card's explanatory list: per setting, the chosen value and its meaning, with the budget at the end. */
export function RecipeParamList({ recipe, params, help }: { recipe: Recipe; params: Record<string, string>; help?: RecipeHelp }) {
  useLocale();
  const full = { ...recipeDefaults(recipe), ...params };
  return (
    <dl className="param-help">
      {Object.keys(recipe.params).map((k) => {
        const text = paramExplanation(help, k, full[k]);
        return (
          <div key={k} className="param-row">
            <dt>{PARAM_LABEL[k] ?? k}</dt>
            <dd><strong>{paramShort(k, full[k])}</strong>{text ? <span className="param-note">{text}</span> : null}</dd>
          </div>
        );
      })}
      <div className="param-row">
        <dt>{t("Költségkeret")}</dt>
        <dd>
          {itemBudgetLines(recipe, full).map((line) => <strong key={line} className="budget-line">{line}</strong>)}
          <span className="param-note">{t(BUDGET_NOTE)}</span>
        </dd>
      </div>
    </dl>
  );
}

/** Beállítások › Receptek (Settings › Recipes): the full description of every recipe. */
export function RecipesPanel() {
  useLocale();
  const recipes = useLoad("recipes", api.recipes);
  if (recipes.error) return <p className="notice error">{recipes.error.message}</p>;
  if (!recipes.data) return <p className="muted">{t("Betöltés…")}</p>;
  return (
    <>
      <p className="page-summary">{t("A recept mondja meg, mit csináljon a rendszer egy munkacsomag tételeivel: milyen lépésekben, milyen beállításokkal és legfeljebb mekkora költséggel. A receptet a csomag Feldolgozás szakaszában lehet kiválasztani és módosítani; a módosítás új változatként mentődik, a korábbi futások a saját receptjüket őrzik.")}</p>
      {recipes.data.recipes.map((r) => <RecipeDetails key={r.id} recipe={r} help={recipes.data?.help} />)}
    </>
  );
}

function RecipeDetails({ recipe, help }: { recipe: Recipe; help?: RecipeHelp }) {
  useLocale();
  const defaults = recipeDefaults(recipe);
  const when = help?.recipes[recipe.id]?.when;
  return (
    <section className="card wide recipe-doc" id={`recipe-${recipe.id}`} aria-label={t(recipe.title)}>
      <div className="card-head">
        <h3>{t(recipe.title)}</h3>
        <span className="muted small">{t("{{version}}. változat", { version: recipe.version })}</span>
      </div>
      <p>{t(recipe.description)}</p>
      <dl className="recipe-kv">
        {when ? <><dt>{t("Mikor válaszd")}</dt><dd>{t(when)}</dd></> : null}
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
      {Object.entries(recipe.params).map(([k, spec]) => {
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
