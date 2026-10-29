// 231 (plan stage C, C3d; DECISIONS 231): how a person gives a source a domain adds to the shared ones (a folder,
// files, a package), by the source kind's name: in the general form of a case that downloads it (`ProcessCreate`) and in
// a workflow's step of the new work wizard (`NewWork`). The shared code asks this registry instead of naming the kind.
// 231 (C3e): the domain registers its chooser when the interface loads (`ui/src/domains/`), as it registers its source
// kind with the service (`jav/app/workflow_steps.py` `SourceKind`); the shared code names none.
import type { ReactNode } from "react";
import type { CaseSource, WorkflowSource, WorkflowStep, Workpackage, WorkpackageView } from "../api";

/** The new work wizard's part of a source kind: the step's own draft (from a repeated workflow's stored source, or a
 *  new one), its fields, and the stored source it makes (null while it is not complete). */
export type StepChooser<D> = {
  draft: (stored: WorkflowSource | null, hasPeriod: boolean) => D;
  Fields: (p: { draft: D; hasPeriod: boolean; onChange: (patch: Partial<D>) => void }) => ReactNode;
  source: (draft: D, period: [string, string]) => WorkflowSource | null;
};

export type SourceChooser<D = unknown> = {
  /** The wizard's choice of the source (an English source text, translated when shown). */
  label: string;
  /** A case's source: told whenever it changes (null while it is not complete); 261: `initial`, the source it starts
   *  from (a next period's form, filled in from the previous case). */
  Case: (p: { onChange: (source: CaseSource | null) => void; initial?: CaseSource | null }) => ReactNode;
  /** A workflow step's source in the wizard. */
  step: StepChooser<D>;
  /** A workflow step's stored source in a few words (the workflow's page). */
  words: (source: WorkflowStep["source"]) => string;
  /** 231 (U3): a case's source in a few words, for the case's name when a person gives none (the mailbox, the period). */
  name?: (source: CaseSource) => string;
  /** 261: where a package of this source kind came from (the item list's line), from its view when the list has it. */
  createdFrom?: (wp: Workpackage, view?: WorkpackageView | null) => string;
};

const CHOOSERS = new Map<string, SourceChooser>();

/** Registers a domain's source kind's chooser (a domain's `index.tsx`); a second registration replaces the first. */
export function registerSourceChooser<D>(kind: string, chooser: SourceChooser<D>): void {
  CHOOSERS.set(kind, chooser as SourceChooser);
}

/** The chooser of a source kind a domain adds (undefined: a shared one, or none). */
export function chooserOf(kind: string | undefined): SourceChooser | undefined {
  return kind ? CHOOSERS.get(kind) : undefined;
}
