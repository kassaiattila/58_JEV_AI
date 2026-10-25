// 181 (plan 170 L5): the workflow step kinds' own forms on the interface, the counterpart of the local service's
// registry (`jav/app/workflow_steps.py`). What a kind takes and needs (its packages, whether it is paid, its scope) comes
// from the service with the templates; only the form a single kind opens with is the interface's own. 231 (C3b5a): the
// documents' and the bank statements' one-step templates are their process packs' (the general form), so their own
// forms went.
import type { ReactNode } from "react";
import { ProcessCreate } from "../elements/ProcessStart";
import { Mailbox } from "../views/Mailbox";
import { QuoteCreate } from "../views/quotes/Quote";

type Form = (onDone: (wpId: string) => void) => ReactNode;

const FORMS: Record<string, Form> = {
  emails: () => <Mailbox variant="pull" />,
  quote: (onDone) => <QuoteCreate onDone={onDone} />,  // 191
};

/** Whether the kind has a form of its own here. A one-step template's id is its kind's (checked by
 * `tests/test_workflow_steps_181.py`), so the wizard opens such a template's form before the templates have loaded. */
export function hasOwnForm(kind: string): boolean {
  return Object.prototype.hasOwnProperty.call(FORMS, kind);
}

/** The form a one-step template of this kind opens with (231 C3b5a: none for a kind without one); 231 (C1c): a
 *  process pack's case (`kind: process`) opens the general form of the pack its step names. */
export function SingleForm({ kind, pack, onDone }: { kind: string; pack?: string; onDone: (wpId: string) => void }) {
  if (kind === "process" && pack) return <ProcessCreate pack={pack} onDone={onDone} />;
  return <>{hasOwnForm(kind) ? FORMS[kind](onDone) : null}</>;
}
