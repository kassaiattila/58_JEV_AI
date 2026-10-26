// 231 (plan stage C, C2d): the pairing element's tab lines and the case's summary, from its data (the scope, the counts
// and the approval); the texts are the reconciliation package's stage lines.
import type { WorkpackageView } from "../api";
import { t } from "../i18n";
import type { ElementProps } from "./registry";

type PairingData = NonNullable<WorkpackageView["reconcile"]>;

const pairingOf = (p: ElementProps) => p.element.data as PairingData | null;

export function pairingLine(p: ElementProps): string | null {
  const d = pairingOf(p);
  if (!d) return null;
  const { scope, counts, approval } = d;
  if (p.element.show === "invoices") return t("{{n}} invoices", { n: counts.own_invoices ?? 0 });
  if (p.element.show === "lines") return t("{{n}} bank accounts", { n: scope.accounts.length });  // the period is in the case's summary
  if (p.element.show === "result") return approval?.active ? t("approved: version {{n}}", { n: approval.active.version }) : t("not approved yet");
  return counts.open_lines ? t("{{n}} open lines", { n: counts.open_lines }) : t("no open line");
}

export function pairingSummary(p: ElementProps): string | null {
  const d = pairingOf(p);
  return d ? t("Reconciliation of {{n}} accounts or cards, {{from}} – {{to}}", {
    n: d.scope.accounts.length, from: d.scope.period_start, to: d.scope.period_end }) : null;
}
