// 176 (plan 170 L3): the logic packs on the interface - the kinds of work package that do a piece of work of their
// own (a reconciliation, a statement package) - in one place, the counterpart of the local service's registry
// (`jav/logic_packs.py`). The package's page, its menu and its item list ask this registry instead of naming the
// kind; a package of a plain processing kind (a folder, a mailbox, chosen files) has no entry.
import type { ReactNode } from "react";
import type { Workpackage, WorkpackageView } from "../api";
import { t } from "../i18n";
import { tmap } from "../labels";
import type { Stage } from "../route";
import { quoteStatus, QuoteStages, quoteSummary } from "../views/quotes/Quote";
import { ReconcileStages } from "../views/reconcile/ReconcileStages";
import { routingStatus, routingSummary, RoutingStages } from "../views/routing/Routing";
import { StatementPackagePanel } from "../views/StatementPackagePanel";

export type LogicUi = {
  /** A package without runs shows its own stages instead of Processing, Review and Result. */
  stages?: {
    labels: Record<Stage, string>;
    /** each stage's status line, from the package's own part of the view (null: the view has none) */
    status: (view: WorkpackageView) => Record<Stage, string> | null;
    summary: (view: WorkpackageView) => ReactNode;
    body: (view: WorkpackageView, stage: Stage, onChanged: () => void) => ReactNode;
  };
  /** The start of the summary line of a package with runs (null: nothing to add). */
  summary?: (view: WorkpackageView) => string | null;
  /** Shown above the result of a package with runs. */
  resultPanel?: (view: WorkpackageView) => ReactNode;
  /** How a person adds to the package: nothing, or statements through its own survey; without it, documents. */
  adds?: "nothing" | "statements";
  /** Where the package was created from (the item list's line). */
  createdFrom?: (wp: Workpackage) => string;
};

// 132: a reconciliation package's stages (it has no files and no runs: a scope, the pairing, the result)
const RECONCILE_STAGE_LABEL = tmap({ process: "Preparation", review: "Pairing", result: "Result" }) as Record<Stage, string>;

export const LOGIC: Record<string, LogicUi> = {
  reconcile: {
    adds: "nothing", // 167: a reconciliation package has no documents
    stages: {
      labels: RECONCILE_STAGE_LABEL,
      status: (view) => {
        if (!view.reconcile) return null;
        const { scope, counts, approval } = view.reconcile;
        return {
          process: t("{{n}} accounts, {{from}} – {{to}}", { n: scope.accounts.length, from: scope.period_start, to: scope.period_end }),
          review: counts.open_lines ? t("{{n}} open lines", { n: counts.open_lines }) : t("no open line"),
          // 145: the approved version, if any
          result: approval?.active ? t("approved: version {{n}}", { n: approval.active.version }) : t("not approved yet"),
        };
      },
      summary: (view) => (view.reconcile
        ? t("Reconciliation of {{n}} accounts or cards, {{from}} – {{to}}", { n: view.reconcile.scope.accounts.length, from: view.reconcile.scope.period_start, to: view.reconcile.scope.period_end })
        : null),
      body: (view, stage, onChanged) => <ReconcileStages view={view} stage={stage} onChanged={onChanged} />,
    },
  },
  // 181: an email routing package routes its email packages' attachments; it has no documents and no runs of its own
  email_routing: {
    adds: "nothing",
    createdFrom: () => t("an email routing package"),
    stages: {
      labels: tmap({ process: "Email packages", review: "Routing", result: "Routed" }) as Record<Stage, string>,
      status: routingStatus,
      summary: routingSummary,
      body: (view, stage, onChanged) => <RoutingStages view={view} stage={stage} onChanged={onChanged} />,
    },
  },
  // 191 (plan F-quote-package B3): a quote package reads its request in the package it came from; no files, no runs
  quote: {
    adds: "nothing",
    createdFrom: () => t("a quote request"),
    stages: {
      labels: tmap({ process: "Request", review: "Quote", result: "Approval" }) as Record<Stage, string>,
      status: quoteStatus,
      summary: quoteSummary,
      body: (view, stage, onChanged) => <QuoteStages view={view} stage={stage} onChanged={onChanged} />,
    },
  },
  statements: {
    adds: "statements",
    createdFrom: () => t("a statement package"),
    summary: (view) => (view.statements
      ? `${t("Bank statements of {{party}}, {{from}} – {{to}}", { party: view.statements.scope.party.name, from: view.statements.scope.period_start, to: view.statements.scope.period_end })} · `
      : null),
    // 140: a statement package's statements and its party's months, before and after its run
    resultPanel: (view) => (view.statements ? <StatementPackagePanel view={view.statements} /> : null),
  },
};

/** The logic pack a work package of this kind runs; undefined for a plain processing kind. */
export function logicOf(kind: string | undefined): LogicUi | undefined {
  return kind && Object.prototype.hasOwnProperty.call(LOGIC, kind) ? LOGIC[kind] : undefined;
}
