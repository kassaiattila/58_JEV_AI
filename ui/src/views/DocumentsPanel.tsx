// A csomag iratai (057): nem önálló fül, hanem az Ellenőrzés része (döntés 2026-09-28). Iratonként megnyitás és
// letöltés, eltávolítás a csomagból; a futás előtt ez az Ellenőrzés egyetlen tartalma.
import { useState } from "react";
import { api, ApiError, type Workpackage } from "../api";
import { DataTable } from "../components/DataTable";
import { t, useLocale } from "../i18n";

export function DocumentsPanel({ wp, onChanged }: { wp: Workpackage; onChanged: () => void }) {
  useLocale();
  const [error, setError] = useState<string | null>(null);
  async function remove(itemId: string) {
    setError(null);
    try {
      await api.removeItem(wp.id, itemId, wp.revision);
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 409 ? t("A csomag közben változott. Frissítettük a listát, nézd át és próbáld újra.") : err.message);
      onChanged();
    }
  }
  return (
    <section aria-label={t("A csomag iratai")} className="stage-stack">
      <p className="muted small">{t("Forrás: {{source}} · a csomag {{rev}}. változata", {
        source: wp.source_kind === "folder" || wp.source_kind === "mailbox" ? wp.source_ref : t("kézi válogatás"), rev: wp.revision })}</p>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {/* a csomag változata a kulcsban: eltávolítás után a lista újratöltődik */}
      <DataTable key={`${wp.id}:${wp.revision}`} dataset="workpackage_items" scope={{ workpackage_id: wp.id }} label={t("A csomag iratai")}
        emptyText={t("A csomag üres.")} storageId="workpackage_items" maxHeight="60vh"
        actions={(row) => (
          <>
            <a className="small" href={api.sourceUrl(wp.id, String(row.item_id))} target="_blank" rel="noreferrer">{t("Megnyitás")}</a>
            <a className="small" href={api.sourceUrl(wp.id, String(row.item_id))} download>{t("Letöltés")}</a>
            <button type="button" className="quiet small-btn" onClick={() => void remove(String(row.item_id))}>{t("Eltávolítás")}</button>
          </>
        )} />
    </section>
  );
}
