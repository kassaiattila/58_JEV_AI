// 082 (the owner's request of 2026-10-01): the work package's cost over all its runs, per provider and model, with the
// total. The rows come from the `package_costs` dataset (the call log and the ledger, nothing stored twice); the cost of
// each run is a column of the runs table above it.
import { useState } from "react";
import type { DsPage } from "../api";
import { DataTable } from "../components/DataTable";
import { t, useLocale } from "../i18n";
import { usd } from "../labels";

function totalText(page: DsPage): string {
  const spent = page.rows.reduce((n, r) => n + Number(r.usd ?? 0), 0);
  const reused = page.rows.reduce((n, r) => n + Number(r.reused ?? 0), 0);
  return reused
    ? t("Total: {{usd}}, {{n}} questions answered from earlier answers (free).", { usd: usd(spent), n: reused })
    : t("Total: {{usd}}.", { usd: usd(spent) });
}

export function PackageCosts({ wpId, pollMs }: { wpId: string; pollMs?: number }) {
  useLocale();
  const [total, setTotal] = useState<string | null>(null);
  return (
    <section aria-label={t("Cost of the document batch")} className="wide">
      <h2>{t("Cost of the document batch")}</h2>
      <p className="small"><strong>{total ?? t("Loading…")}</strong></p>
      <p className="muted small">{t("The paid calls of every run, per provider and model; the cost of each run is in the runs table.")}</p>
      <DataTable dataset="package_costs" scope={{ workpackage_id: wpId }} label={t("Cost of the document batch")} storageId="wp-costs" pollMs={pollMs}
        emptyText={t("There have been no paid calls on this batch yet.")} onPage={(page) => setTotal(totalText(page))} />
    </section>
  );
}
