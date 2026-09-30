// 066 Á36 (decision of 2026-09-29): irreversible actions (release, stop) ask for a short confirmation: after the first
// click the button's label changes to „Biztosan? Kattints újra” (Are you sure? Click again), and only a second click
// within a few seconds carries it out. There is no pop-up window; it works the same way with the keyboard.
import { useEffect, useState, type ReactNode } from "react";
import { t } from "../i18n";

export const CONFIRM_WINDOW_MS = 5000;

// 073: also used for the other one-click deletions (mail schedule, package item, user). `ariaLabel` names an
// icon-like button; while armed it is dropped so screen readers announce the confirmation text instead.
export function ConfirmButton({ onConfirm, children, className, disabled, ariaLabel }: {
  onConfirm: () => void; children: ReactNode; className?: string; disabled?: boolean; ariaLabel?: string;
}) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), CONFIRM_WINDOW_MS);
    return () => window.clearTimeout(timer);
  }, [armed]);
  return (
    <button type="button" className={className} disabled={disabled} aria-live="polite" aria-label={armed ? undefined : ariaLabel}
      onClick={() => {
        if (!armed) { setArmed(true); return; }
        setArmed(false);
        onConfirm();
      }}>
      {armed ? t("Biztosan? Kattints újra") : children}
    </button>
  );
}
