// 231 (plan stage C, C3d; DECISIONS 231): how a person gives a source a domain adds to the shared ones (a folder,
// files, a package), by the source kind's name: in the general form of a case that downloads it (`ProcessCreate`) and in
// a workflow's step of the new work wizard (`NewWork`). The shared code asks this registry instead of naming the kind; an
// entry is process-specific until its screens move into their domain's folder (C3e), so the strict principle's test
// lists it.
import type { ReactNode } from "react";
import type { CaseSource } from "../api";
import { MailboxRequestFields, MailboxStepFields, type MailboxStepDraft } from "../views/Mailbox";

export type SourceChooser = {
  /** A case's source: told whenever it changes (null while it is not complete). */
  Case: (p: { onChange: (source: CaseSource | null) => void }) => ReactNode;
  /** A workflow step's source in the wizard's draft (`hasPeriod`: the workflow has one to take). */
  Step: (p: { draft: MailboxStepDraft; hasPeriod: boolean; onChange: (patch: Partial<MailboxStepDraft>) => void }) => ReactNode;
};

export const SOURCE_CHOOSERS: Record<string, SourceChooser> = {
  // 048 T2 / 231 C3d: a mailbox download (its addresses, folders and period)
  mailbox: {
    Case: ({ onChange }) => <MailboxRequestFields onChange={(req) => onChange(req ? { kind: "mailbox", request: req } : null)} />,
    Step: (p) => <MailboxStepFields {...p} />,
  },
};

/** The chooser of a source kind a domain adds (undefined: a shared one, or none). */
export function chooserOf(kind: string | undefined): SourceChooser | undefined {
  return kind && Object.prototype.hasOwnProperty.call(SOURCE_CHOOSERS, kind) ? SOURCE_CHOOSERS[kind] : undefined;
}
