// 231 (plan stage C, C3b5a; DECISIONS 231): what a package's rule shows on its page, by the name of its page part. A
// package runs by a named rule (`jav/app/work.py` `PackageRule`), which its scope names; the service sends it with the
// package's view (`rule`: its name, how a person adds to the package, its page parts), so the package's page, its menu
// and its item list ask this registry by the part's name instead of naming a kind of package. Until 231 C3b5a the logic
// packs' registry keyed by the package's kind. 231 (C3e): the domain whose rule it is registers the part when the
// interface loads (`registerPackagePart`, from `ui/src/domains/<domain>/index.tsx`).
import type { ComponentType, ReactNode } from "react";
import type { Workpackage, WorkpackageView } from "../api";
import type { AddSource } from "../views/PackageAdd";

export type PackagePart = {
  /** The start of the summary line of the package's page (null: nothing to add). */
  summary?: (view: WorkpackageView) => string | null;
  /** Shown above the package's result. */
  resultPanel?: (view: WorkpackageView) => ReactNode;
  /** Where the package was created from (the item list's line). */
  createdFrom?: (wp: Workpackage) => string;
  /** The label of the menu's adding, when the rule adds in its own way (`adds: own`). */
  addLabel?: string;
  /** 231 (C3e): the form of adding in the rule's own way (`adds: own`). */
  Add?: ComponentType<{ wp: Workpackage; source?: AddSource; onDone: () => void; onCancel: () => void }>;
  /** 231 (C3e): the package's scope is the rule's (`PackageRule.own_scope`): a person can neither give nor take it. */
  ownScope?: boolean;
};

const PARTS = new Map<string, PackagePart>();

/** Registers a domain's rule's page part by its name (a second registration replaces the first). */
export function registerPackagePart(name: string, part: PackagePart): void {
  PARTS.set(name, part);
}

/** The page part a package's rule shows (undefined: a package of no rule, or one whose rule shows none). */
export function partOf(view: Pick<WorkpackageView, "rule"> | null | undefined): PackagePart | undefined {
  const name = (view?.rule?.parts ?? []).find((p) => PARTS.has(p));
  return name ? PARTS.get(name) : undefined;
}

/** Whether a person adds to the package in its rule's own way (its page part) rather than as documents. */
export function addsOwnWay(view: Pick<WorkpackageView, "rule"> | null | undefined): boolean {
  return view?.rule?.adds === "own";
}
