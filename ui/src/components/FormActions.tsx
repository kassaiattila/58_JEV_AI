// 263 (plan E, F1; the page rules of 2026-10-30): a form's or a card's buttons at its foot, on the right - "Cancel" and
// then the main button, the last; what removes or retires stands apart at the left end; a short note before the
// buttons says what holds the main one back. Every form and card builds its foot with it, so the order and the place
// are the same everywhere.
import type { ReactNode } from "react";
import { t, useLocale } from "../i18n";

export function FormActions({ children, onCancel, cancelLabel, start, note, busy }: {
  /** the main button (and any quieter one before it) */
  children?: ReactNode;
  onCancel?: () => void;
  cancelLabel?: string;
  /** what removes or retires: at the left end */
  start?: ReactNode;
  note?: ReactNode;
  busy?: boolean;
}) {
  useLocale();
  return (
    <div className="form-actions">
      {start ? <div className="form-actions-start">{start}</div> : null}
      {note ? <span className="form-actions-note small muted">{note}</span> : null}
      {onCancel ? <button type="button" className="secondary" disabled={busy} onClick={onCancel}>{cancelLabel ?? t("Cancel")}</button> : null}
      {children}
    </div>
  );
}
