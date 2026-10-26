// 181 (plan 170 L5): the workflow step kinds' own forms on the interface, the counterpart of the local service's
// registry (`jav/app/workflow_steps.py`). 231 (C3b5a, C3c, C3d): every one-step template is a process pack's case (the
// documents', the bank statements', the IT quote's, the mailbox download's), opened with the pack's general form, so
// the kinds' own forms went.
import { ProcessCreate } from "../elements/ProcessStart";

/** The form a one-step template opens with: the general form of the pack its step names (231 C1c); nothing for a
 *  template that names none. */
export function SingleForm({ kind, pack, onDone }: { kind: string; pack?: string; onDone: (wpId: string) => void }) {
  return kind === "process" && pack ? <ProcessCreate pack={pack} onDone={onDone} /> : null;
}
