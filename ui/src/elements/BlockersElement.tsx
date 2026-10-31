// 231 (stage D, D-f9): what holds a case (blockers), on its Overview: each step that stopped, must run again, waits
// for a person's start or decision, or waits for something else, in the pack's order, with the tab where it is
// resolved as the row's one link. Nothing holding it is one quiet line; a closed case says so. U-A8: a stopped step
// says why in a person's words where it gives them, its note otherwise. 263 (plan E, E2, H6): a step that runs a
// sub-case is an item of the case's track of its own, so its row leads there; the tab the list itself is on is named,
// not linked.
import type { BlockersData } from "../api";
import { t, useLocale } from "../i18n";
import { saidText } from "../labels";
import { routeHash } from "../route";
import { blockerKind, blockersStatus } from "./caseStatus";
import type { ElementProps } from "./registry";

const loading = <p className="muted">{t("Loading…")}</p>;

export function BlockersView(p: ElementProps) {
  useLocale();
  const d = p.element.data as BlockersData | null;
  if (!d) return loading;
  const state = blockersStatus(d);
  const tabLabel = (id: string | null) => (id ? p.page.tabs.find((x) => x.id === id)?.label ?? null : null);
  const here = p.page.tabs.find((x) => x.elements.includes(p.element))?.id ?? null;
  const ownItem = (step: string) => p.page.tabs.some((x) => x.elements.some((e) => e.type === "sub_case" && e.step === step));
  return (
    <section className="card" aria-label={t("What holds the case")}>
      <div className="card-head">
        <h2>{t("What holds the case")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {d.status !== "open" ? (
        <p className="muted">{t("The case is closed: nothing holds it.")}</p>
      ) : !d.items.length ? (
        <p className="muted">{t("Nothing holds the case: its steps work by themselves.")}</p>
      ) : (
        <table className="table compact blockers">
          <thead><tr><th>{t("Step")}</th><th>{t("What holds it")}</th><th>{t("Where")}</th></tr></thead>
          <tbody>
            {d.items.map((b) => {
              const kind = blockerKind(b.kind);
              const title = p.page.steps[b.step]?.title;
              const item = ownItem(b.step) ? b.step : b.tab;
              const label = item === b.step && item !== b.tab ? title ?? b.step : tabLabel(b.tab);
              return (
                <tr key={b.step}>
                  <td>{title ? t(title) : b.step}</td>
                  <td><span className={`status ${kind.mark}`}>{kind.text}</span>
                    {b.reasons?.length ? <span className="muted small"> — {b.reasons.map(saidText).join("; ")}</span>
                      : b.note ? <span className="muted small"> — {b.note}</span> : null}</td>
                  <td>{label && item && item !== here ? <a href={routeHash({ view: "cases", caseId: p.caseId, tab: item })}>{t(label)}</a>
                    : label ? <span className="muted">{t(label)}</span> : <span className="muted">–</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
