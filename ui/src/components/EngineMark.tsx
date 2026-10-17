// 160-D (plan F-csak-gpt Sz6, L6; decision 160 D3): the AI engine that produced a run's results, shown with them. It is
// a fact about the run, not a state, so it is a neutral mark (a hairline frame, square-cornered as small markers are)
// with no state colour and no accent (docs/guides/DESIGN.md). Nothing is shown when the engine is not known: an older
// service, or an email intent taken from another run.
import type { Engine } from "../api";
import { t, useLocale } from "../i18n";
import { ENGINE } from "../labels";

const NOTE: Record<Engine, string> = {
  jev: "JEV recognised the type and the intent and chose or checked the values; GPT extracted where the type's path needs it.",
  gpt: "GPT recognised the type and the intent and extracted the values; the code checked them against the document, JEV did not.",
};

export function EngineMark({ engine }: { engine?: Engine | null }) {
  useLocale();
  if (!engine) return null;
  return <span className="engine-mark" title={t(NOTE[engine])}>{t("AI engine: {{engine}}", { engine: ENGINE[engine] })}</span>;
}
