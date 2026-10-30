// 263 (plan E, E1; the owner's decision of 2026-10-30: a thing opens on its own page, and the way back finds the list as
// it was): a thing's page steps to the previous and the next thing of the list it was opened from, in the order the list
// showed them (its search, filters, grouping and order; `DataTable` `persist` keeps it). Opened from elsewhere (a sent
// link), there is no list to step in, and nothing is shown.
import { useHash } from "../hooks";
import { t, useLocale } from "../i18n";
import { rowOrder } from "./DataTable";

const pathOf = (hash: string) => hash.split("?", 1)[0];

export function ItemSteps({ list }: { list: string }) {
  useLocale();
  const hash = useHash();
  const order = rowOrder(list);
  const here = order.findIndex((h) => pathOf(h) === pathOf(hash));
  if (here < 0 || order.length < 2) return null;
  const prev = order[here - 1];
  const next = order[here + 1];
  return (
    <span className="item-steps" role="group" aria-label={t("Step in the list")}>
      {prev ? <a className="button secondary small-btn" href={prev}>{t("← Previous")}</a>
        : <span className="button secondary small-btn" aria-disabled="true">{t("← Previous")}</span>}
      {next ? <a className="button secondary small-btn" href={next}>{t("Next →")}</a>
        : <span className="button secondary small-btn" aria-disabled="true">{t("Next →")}</span>}
    </span>
  );
}
