// 081 (the owner's trial of 2026-10-01): a „Tallózás…” (Browse…) button next to a path field. It asks the local service
// to open the operating system's own folder or file picker on this machine, and the chosen path fills the field; the
// path can still be typed. While the dialog is open the button says so, with a hint to look on the taskbar in case the
// dialog opened behind the browser.
import { useState } from "react";
import { api, type ApiError } from "../api";
import { t, useLocale } from "../i18n";

export function BrowseButton({ kind, initial, onPick }: {
  kind: "folder" | "files"; initial?: string; onPick: (paths: string[]) => void;
}) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function browse() {
    setBusy(true);
    setError(null);
    const from = initial?.trim() || undefined;
    try {
      if (kind === "folder") {
        const res = await api.pickFolder(t("Mappa kiválasztása"), from);
        if (res.path) onPick([res.path]);
      } else {
        const res = await api.pickFiles(t("Fájlok kiválasztása"), from);
        if (res.paths.length) onPick(res.paths);
      }
    } catch (e) {
      const err = e as ApiError;
      setError(err.code === "picker_busy" ? t("Már nyitva van egy választó ablak; előbb azt zárd be.")
        : err.code === "picker_unavailable" ? t("A választó ablak itt nem nyitható meg; írd be az útvonalat.")
        : err.code === "forbidden_path" ? t("A választott hely nincs az engedélyezett helyek között.")
        : err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="browse">
      <button type="button" onClick={() => void browse()} disabled={busy} aria-busy={busy}>
        {busy ? t("A választó ablak nyitva…") : t("Tallózás…")}
      </button>
      {busy ? <span className="muted">{t("Ha nem látod, nézd meg a tálcán.")}</span> : null}
      {error ? <span className="notice error" role="alert">{error}</span> : null}
    </span>
  );
}
