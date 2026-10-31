// 066 Á36 (decision of 2026-09-29): irreversible actions (release, stop, delete) ask for a short confirmation. 263 (plan
// E, F1; the owner's decision of 2026-10-31: a confirmation card everywhere): the button opens a small card under it
// that says what is about to happen (`question`), with "Cancel" and the action itself on the right; Esc or a click
// outside closes it, and focus goes to the action. It replaced the click-twice label („Biztosan? Kattints újra”).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { t, useLocale } from "../i18n";
import { FormActions } from "./FormActions";
import { Popover } from "./Popover";

// 073: also used for the other one-click deletions (mail schedule, package item, user). `ariaLabel` names an
// icon-like button. `danger`: the action removes something, so its button in the card is the danger one; otherwise the
// card's action is the solid main button.
export function ConfirmButton({ onConfirm, children, className, disabled, ariaLabel, question, confirmLabel, danger }: {
  onConfirm: () => void; children: ReactNode; className?: string; disabled?: boolean; ariaLabel?: string;
  /** what is about to happen, in a sentence or two (default: "Are you sure?") */
  question?: ReactNode;
  /** the action's label in the card (default: the button's own) */
  confirmLabel?: ReactNode;
  danger?: boolean;
}) {
  useLocale();
  const anchor = useRef<HTMLButtonElement>(null);
  const action = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => action.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);
  return (
    <>
      <button ref={anchor} type="button" className={className} disabled={disabled} aria-label={ariaLabel}
        aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {children}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t("Confirmation")} align="right" className="confirm-card">
        <p className="confirm-question">{question ?? t("Are you sure?")}</p>
        <FormActions onCancel={() => { setOpen(false); anchor.current?.focus(); }}>
          <button ref={action} type="button" className={danger ? "danger" : "primary"}
            onClick={() => { setOpen(false); onConfirm(); }}>{confirmLabel ?? children}</button>
        </FormActions>
      </Popover>
    </>
  );
}
