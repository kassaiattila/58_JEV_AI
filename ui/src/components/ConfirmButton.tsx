// 066 Á36 (döntés 2026-09-29): a visszavonhatatlan műveletek (kiadás, leállítás) rövid megerősítést kérnek: az első
// kattintás után a gomb „Biztosan? Kattints újra” feliratra vált, és csak a második kattintás hajt végre, néhány
// másodpercen belül. Felugró ablak nincs; a billentyűzettel ugyanígy működik.
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
