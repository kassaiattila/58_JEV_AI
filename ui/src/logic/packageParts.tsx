// 231 (plan stage C, C3b5a; DECISIONS 231): what a package's rule shows on its page, by the name of its page part. A
// package runs by a named rule (`jav/app/work.py` `PackageRule`), which its scope names; the service sends it with the
// package's view (`rule`: its name, how a person adds to the package, its page parts), so the package's page, its menu
// and its item list ask this registry by the part's name instead of naming a kind of package. Until 231 C3b5a the logic
// packs' registry keyed by the package's kind (`registry.tsx`). A part is process-specific until its screens move into
// their domain's folder (C3e), so the strict principle's test lists it.
import type { ReactNode } from "react";
import type { Workpackage, WorkpackageView } from "../api";
import { t } from "../i18n";
import { lazyPage } from "../components/LazyPage";

const StatementPackagePanel = lazyPage(() => import("../views/StatementPackagePanel").then((m) => m.StatementPackagePanel));

export type PackagePart = {
  /** The start of the summary line of the package's page (null: nothing to add). */
  summary?: (view: WorkpackageView) => string | null;
  /** Shown above the package's result. */
  resultPanel?: (view: WorkpackageView) => ReactNode;
  /** Where the package was created from (the item list's line). */
  createdFrom?: (wp: Workpackage) => string;
  /** The label of the menu's adding, when the rule adds in its own way (`adds: own`). */
  addLabel?: string;
};

export const PACKAGE_PARTS: Record<string, PackagePart> = {
  // 140: a statement package's party, period and statements, and the party's months before and after its run
  statements: {
    createdFrom: () => t("a statement package"),
    summary: (view) => (view.statements
      ? `${t("Bank statements of {{party}}, {{from}} – {{to}}", { party: view.statements.scope.party.name, from: view.statements.scope.period_start, to: view.statements.scope.period_end })} · `
      : null),
    resultPanel: (view) => (view.statements ? <StatementPackagePanel view={view.statements} /> : null),
    addLabel: "Add statements",
  },
};

/** The page part a package's rule shows (undefined: a package of no rule, or one whose rule shows none). */
export function partOf(view: Pick<WorkpackageView, "rule"> | null | undefined): PackagePart | undefined {
  const name = (view?.rule?.parts ?? []).find((p) => Object.prototype.hasOwnProperty.call(PACKAGE_PARTS, p));
  return name ? PACKAGE_PARTS[name] : undefined;
}

/** Whether a person adds to the package in its rule's own way (its page part) rather than as documents. */
export function addsOwnWay(view: Pick<WorkpackageView, "rule"> | null | undefined): boolean {
  return view?.rule?.adds === "own";
}
