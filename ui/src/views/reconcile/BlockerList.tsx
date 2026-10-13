// 153 (review): the approval's blockers grouped by reason. A package of a few hundred documents from unapproved runs
// listed each one, about 8,500 pixels of the Preparation stage; now each reason is one line with its count, and its
// documents open below it.
import type { ReconcileBlocker } from "../../api";
import { useLocale } from "../../i18n";
import { blockerGroups, blockerGroupText, blockerText } from "./labels";

export function BlockerList({ blockers }: { blockers: ReconcileBlocker[] }) {
  useLocale();
  return (
    <ul className="plain">
      {blockerGroups(blockers).map((g) => g.items.length === 1 ? (
        <li key={g.code} className="blocker small">{blockerText(g.items[0])}</li>
      ) : (
        <li key={g.code} className="blocker small">
          <details>
            <summary>{blockerGroupText(g.code, g.items.length)}</summary>
            <ul className="plain">
              {g.items.map((b) => <li key={`${b.code}:${b.doc_id}`}>{blockerText(b)}</li>)}
            </ul>
          </details>
        </li>
      ))}
    </ul>
  );
}
