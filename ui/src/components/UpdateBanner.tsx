// 091 (the version banner, the owner's decision of 2026-10-02: "yes, with a banner"): a browser tab left open
// for a long time keeps the interface it loaded, even after the service was restarted with new code (090: the owner's
// screenshot showed the pre-089 layout). The tab remembers the service's state at page load and checks it every minute
// and whenever the tab is shown again; if a newer version runs, a banner at the top asks for a reload. Unsaved
// corrections survive the reload: they are kept in the tab's own storage (066, audit point 20).
import { useEffect, useState } from "react";
import { api, type Health } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";

export const VERSION_POLL_MS = 60000;

/** Whether `now` is a newer service than `first`, the one the page was loaded from. A different commit or UI build
 *  means new code. A restart (a different start time) counts only when a commit is unknown or had uncommitted changes,
 *  because then the same commit does not prove the same code. */
export function newerVersion(first: Health, now: Health): boolean {
  if (first.ui_build && now.ui_build && first.ui_build !== now.ui_build) return true;
  if (first.commit && now.commit && first.commit !== now.commit) return true;
  const unproven = !first.commit || !now.commit || first.dirty !== false || now.dirty !== false;
  return unproven && first.started_at !== now.started_at;
}

export function UpdateBanner({ pollMs = VERSION_POLL_MS }: { pollMs?: number }) {
  useLocale();
  const h = useLoad("version-check", api.health, pollMs);
  const [first, setFirst] = useState<Health | null>(null);
  const { data, reload } = h;

  useEffect(() => {
    if (data && !first) setFirst(data);
  }, [data, first]);

  useEffect(() => {
    // a tab coming back to the foreground checks at once instead of waiting for the next minute
    const onShow = () => { if (!document.hidden) reload(); };
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
  }, [reload]);

  if (!data || !first || !newerVersion(first, data)) return null;
  return (
    <div className="update-banner" role="status">
      <span>{t("Újabb változat fut. Töltsd újra az oldalt az új felülethez; a mentetlen javításaid megmaradnak.")}</span>
      <button type="button" className="primary" onClick={() => window.location.reload()}>{t("Újratöltés")}</button>
    </div>
  );
}
