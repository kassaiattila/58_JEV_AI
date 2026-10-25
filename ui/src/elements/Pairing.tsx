// 231 (plan stage C, C2d): the pairing capability's special element (`jav/domains/finance/capabilities.py`): the
// reconciliation package's three stages until now, on a pairing case's tabs by the element's `show` setting — the
// invoices the scope takes (invoices), the statements with the scope and the coverage (lines), the decisions on the
// pairs (decide) and the approved statement (result). The workspace is the case's own (its id is its container's).
import { lazy, Suspense } from "react";
import { t, useLocale } from "../i18n";
import { go } from "../route";
import type { ElementProps } from "./registry";

const ReconcileView = lazy(() => import("../views/reconcile/ReconcileStages").then((m) => ({ default: m.ReconcileView })));

type PairingShow = "invoices" | "lines" | "decide" | "result";
const SHOWS: readonly string[] = ["invoices", "lines", "decide", "result"];

export function Pairing({ caseId, element, page, onChanged }: ElementProps) {
  useLocale();
  const show = (SHOWS.includes(String(element.show)) ? element.show : "decide") as PairingShow;
  // the tab whose element of this type shows the decisions
  const pairingTab = page.tabs.find((tab) => tab.elements.some((e) => e.type === element.type && e.show === "decide"))?.id;
  return (
    <Suspense fallback={<p className="muted">{t("Loading…")}</p>}>
      <ReconcileView wpId={caseId} archived={false} show={show} onChanged={onChanged}
        toPairing={pairingTab ? () => go({ view: "cases", caseId, tab: pairingTab }) : undefined} />
    </Suspense>
  );
}
