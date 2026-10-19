// 181 (plan 170 L5): the workflow step kinds' own forms on the interface, the counterpart of the local service's
// registry (`jav/workflow_steps.py`). What a kind takes and needs (its packages, whether it is paid, its scope) comes
// from the service with the templates; only the form a single kind opens with is the interface's own. A kind without
// an entry opens the documents form.
import type { ReactNode } from "react";
import { DocumentsCreate } from "../views/DocumentsCreate";
import { Mailbox } from "../views/Mailbox";
import { ReconcileCreate } from "../views/reconcile/ReconcileCreate";
import { RoutingCreate } from "../views/routing/Routing";
import { StatementPackageCreate } from "../views/StatementPackageCreate";

type Form = (onDone: (wpId: string) => void) => ReactNode;

const FORMS: Record<string, Form> = {
  documents: (onDone) => <DocumentsCreate onDone={onDone} />,
  emails: () => <Mailbox variant="pull" />,
  statements: (onDone) => <StatementPackageCreate onDone={onDone} />,
  reconcile: (onDone) => <ReconcileCreate onDone={onDone} />,
  routing: (onDone) => <RoutingCreate onDone={onDone} />,  // 181
};

/** Whether the kind has a form of its own here. A one-step template's id is its kind's (checked by
 * `tests/test_workflow_steps_181.py`), so the wizard opens such a template's form before the templates have loaded. */
export function hasOwnForm(kind: string): boolean {
  return Object.prototype.hasOwnProperty.call(FORMS, kind);
}

/** The form a one-step template of this kind opens with (the documents form for a kind without one). */
export function SingleForm({ kind, onDone }: { kind: string; onDone: (wpId: string) => void }) {
  return <>{(hasOwnForm(kind) ? FORMS[kind] : FORMS.documents)(onDone)}</>;
}
