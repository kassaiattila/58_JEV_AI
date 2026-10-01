import { useState } from "react";
import { api, ApiError, type ProviderCost, type RunCostView, type RunView } from "../api";
import { DataTable } from "../components/DataTable";
import { nameCell, NameModeSwitch } from "../components/NameCell";
import { PageHeader } from "../components/PageHeader";
import { ACTIVE_RUN, useLoad, useRunView } from "../hooks";
import { getLocale, t, useLocale } from "../i18n";
import { MODE, paramsText, providerName, reasonText, tmap, usd, when } from "../labels";
import { useNameMode } from "../names";
import { RunStatus } from "./Workpackages";
import { Icon } from "../components/Icon";
import { ConfirmButton } from "../components/ConfirmButton";

const ACTIVE = new Set(["queued", "running"]);

/** All runs (part of Beállítások › Rendszer (Settings › System), 057): monitoring; closing the tab does not stop
 *  them. */
export function RunList() {
  useLocale();
  return <DataTable dataset="runs" label={t("Futások")} pollMs={5000} emptyText={t("Még nem volt futás.")} storageId="all-runs" />;
}

export function RunDetail({ runId }: { runId: string }) {
  useLocale();
  const names = useNameMode();
  const view = useRunView(runId); // refreshes automatically only while the run is in progress
  const wp = useLoad(view.data ? `wp:${view.data.run.workpackage_id}` : null, () => api.workpackage(view.data!.run.workpackage_id));
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (view.error?.status === 404 || view.error?.status === 422) {
    return (
      <PageHeader crumbs={[{ label: t("Munkacsomagok"), href: "#/workpackages" }]} title={t("A futás nem található")}
        summary={<><span className="mono">{runId}</span>: {t("nincs ilyen azonosítójú futás.")}</>} />
    );
  }
  if (view.error) return <p className="notice error" role="alert">{view.error.message}</p>;
  if (!view.data) return <p className="muted">{t("Betöltés…")}</p>;
  const { run, budget } = view.data;

  const own = view.data.open_reasons;
  const ownTotal = Object.values(own).reduce((n, r) => n + r.length, 0);
  // 083: a to-do left by a budget stop opens the budget part by itself
  const budgetBlocked = Object.values(own).some((rs) => rs.some((r) => /BudgetExceeded|budget_exceeded/.test(r.reason)));
  const wpBase = `#/workpackages/${encodeURIComponent(run.workpackage_id)}`;

  async function cancel() {
    setBusy(true);
    setMsg(null);
    try {
      await api.cancel(runId);
      setMsg({ error: false, text: t("Leállítás kérve: a sorban álló tételek azonnal, a futó a következő lépés után áll le.") });
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
      view.reload();
    }
  }

  return (
    <>
      <PageHeader
        crumbs={[{ label: t("Munkacsomagok"), href: "#/workpackages" }, { label: wp.data?.workpackage.name ?? run.workpackage_id, href: wpBase },
          { label: t("Feldolgozás"), href: `${wpBase}/process` }]}
        title={t("{{mode}} futás, {{when}}", { mode: MODE[run.mode], when: when(run.created_at) })} badge={<RunStatus status={run.status} />}
        summary={<>{run.recipe?.title ? t(run.recipe.title) : run.recipe_id} · {paramsText(run.params)} · {t("indította: {{actor}}", { actor: run.actor })}
          {run.finished_at ? ` · ${t("befejeződött: {{when}}", { when: when(run.finished_at) })}` : ""}</>}
        actions={<div className="button-row">
          {ACTIVE.has(run.status) ? <ConfirmButton className="secondary" disabled={busy} onConfirm={() => void cancel()}><Icon name="stop" />{t("Leállítás")}</ConfirmButton> : null}
          <a className="secondary dl-btn" href={`${wpBase}/result?run=${encodeURIComponent(run.run_id)}`}>{run.mode === "apply" && !run.approval ? t("Eredmény és jóváhagyás") : t("Eredmény")}</a>
        </div>} />
      {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
      {run.approval ? <p className="notice ok-box">{t("Kiadva: jóváhagyta {{who}}, {{when}}.", { who: run.approved_by, when: when(run.approved_at) })}</p> : null}
      {ownTotal ? <p className="notice">{t("{{n}} nyitott teendő.", { n: ownTotal })} <a href={`${wpBase}/review`}>{t("Ellenőrzés")}</a></p> : null}

      <div className="run-grid">
        <section aria-label={t("Tételek")}>
          <h2>{t("Tételek")}</h2>
          <DataTable dataset="run_items" scope={{ run_id: runId, names }} label={t("A futás tételei")} pollMs={view.data && ACTIVE_RUN.has(view.data.run.status) ? 3000 : undefined}
            toolbar={<NameModeSwitch />}
            cell={(col, row) => {
              if (col.key !== "open_reasons") return nameCell(col, row);
              const reasons = own[String(row.item_id)] ?? [];
              return reasons.length ? (
                <a href={`${wpBase}/review/${String(row.item_id)}`} title={reasons.map((x) => reasonText(x.reason)).join("\n")}>
                  {t("{{n}} teendő", { n: reasons.length })}
                </a>
              ) : <span className="muted">–</span>;
            }} />
        </section>
        <aside aria-label={t("Költség és munkasor")}>
          <RunCost costs={view.data.costs} budget={budget} budgetBlocked={budgetBlocked} />
          <h3 className="mt">{t("Munkasor")}</h3>
          <dl className="kv">{Object.entries(run.jobs).map(([k, v]) => [<dt key={`${k}t`}>{JOB[k] ?? k}</dt>, <dd key={`${k}d`}>{v}</dd>])}</dl>
        </aside>
      </div>
      <Journal runId={runId} />
    </>
  );
}

const JOB: Record<string, string> = tmap({ queued: "sorban", claimed: "fut", done: "kész", dead: "hibás (feladva)", cancelled: "leállítva" });

/** 083: the providers in the order of the cost list (JEV, OpenAI, Azure DI), not in the budget row's order. */
const PROVIDER_ORDER = ["jev", "openai", "azure_di"];
function byProvider<T>(entries: [string, T][]): [string, T][] {
  const rank = (p: string) => (PROVIDER_ORDER.includes(p) ? PROVIDER_ORDER.indexOf(p) : PROVIDER_ORDER.length);
  return [...entries].sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
}

export function BudgetBars({ budget }: { budget: RunView["budget"] }) {
  useLocale();
  const entries = byProvider(Object.entries(budget.providers));
  if (!entries.length) return <p className="muted small">{t("Nincs keret rögzítve.")}</p>;
  return (
    <>
      {entries.map(([p, v]) => {
        const pct = Math.min(100, (Number(v.committed_usd) / Math.max(Number(v.limit_usd), 1e-9)) * 100);
        return (
          <div key={p} className="budget">
            <div className="budget-label"><span>{providerName(p)}</span><span className="mono">{usd(v.committed_usd)} / {usd(v.limit_usd)}</span></div>
            <div className="bar" role="meter" aria-label={t("{{provider}} keret felhasználva", { provider: providerName(p) })} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
              <span style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
      <p className="muted small">{t("A lekötött összeg a lefutott hívások költsége, plusz a még le nem zárt hívások legrosszabb becslése.")}</p>
    </>
  );
}

const EXPECTED: Record<string, string> = tmap({ yes: "várható", maybe: "lehetséges", no: "nem várt" });

/** 083: the run's cost on its page. The owner found the total hard to read while the budget bars came first, so the
 *  total comes first, then each provider's actual calls and cost, then the plan against the actual cost; the budget
 *  bars sit in a closed part that opens by itself when a budget is nearly used up or stopped something. */
export function RunCost({ costs, budget, budgetBlocked }: { costs: RunCostView | undefined; budget: RunView["budget"]; budgetBlocked: boolean }) {
  useLocale();
  const k = budgetSummary(budget, budgetBlocked);
  return (
    <section aria-label={t("Költség")}>
      <h2>{t("Költség")}</h2>
      {costs ? <>
        <div className="cost-total"><span>{t("A futás költsége")}</span><strong className="mono">{usd(costs.total.usd)}</strong></div>
        {costs.providers.length ? (
          <dl className="kv cost-kv">
            {costs.providers.map((p) => [
              <dt key={`${p.provider}t`}>{providerName(p.provider)}</dt>,
              <dd key={`${p.provider}d`}>
                {providerCostLines(p).map((line) => <div key={line} className="small">{line}</div>)}
                {p.models.length ? <div className="muted small mono">{p.models.join(", ")}</div> : null}
              </dd>,
            ])}
          </dl>
        ) : <p className="muted small">{t("Nem volt fizetős hívás.")}</p>}
        {costs.total.reused ? <p className="muted small">{t("{{n}} kérdés korábbi válaszból (ingyenes)", { n: costs.total.reused })}</p> : null}
        <PlanVsActual costs={costs} />
      </> : null}
      {k ? (
        <details className="details budget-box" open={k.open}>
          <summary>{k.text}</summary>
          <BudgetBars budget={budget} />
        </details>
      ) : null}
    </section>
  );
}

/** 083: the closed budget part's title (each provider's share used) and whether it opens by itself: at 80% use of any
 *  budget, or when the budget stopped something in the run. Null when the run has no budget. */
export function budgetSummary(budget: RunView["budget"], blocked: boolean): { text: string; open: boolean } | null {
  const entries = byProvider(Object.entries(budget.providers));
  if (!entries.length) return null;
  const share = (v: { limit_usd: string; committed_usd: string }) => Number(v.committed_usd) / Math.max(Number(v.limit_usd), 1e-9);
  const pct = new Intl.NumberFormat(getLocale(), { style: "percent", maximumFractionDigits: 0 });
  const list = entries.map(([p, v]) => `${providerName(p)} ${pct.format(share(v))}`).join(", ");
  // the small tolerance: 0.32 / 0.40 is 0.7999… in floating point, and exactly 80% must open the part
  return { text: t("Keret ({{list}})", { list }), open: blocked || entries.some(([, v]) => share(v) >= 0.8 - 1e-9) };
}

/** 082, 083: the actual lines of one provider under the run's total: the paid calls and their cost, and the reserved
 *  amount of the calls without a known cost apart (it is not a cost). */
export function providerCostLines(p: ProviderCost): string[] {
  const out: string[] = [];
  if (p.calls) {
    out.push(p.failed
      ? t("{{n}} fizetős hívás (ebből {{failed}} sikertelen) · {{usd}}", { n: p.calls, failed: p.failed, usd: usd(p.usd) })
      : t("{{n}} fizetős hívás · {{usd}}", { n: p.calls, usd: usd(p.usd) }));
  } else out.push(t("Nem volt fizetős hívás."));
  if (Number(p.held_usd) > 0) out.push(t("Lefoglalt, ismeretlen kimenetelű: {{usd}} (nem költség, a keret ennyivel számol)", { usd: usd(p.held_usd) }));
  return out;
}

/** 083: what the pre-start overview expected of a provider, against the actual cost. */
export function planLine(p: ProviderCost): string {
  return p.expected
    ? t("Terv: {{expected}} · tényleges: {{usd}}", { expected: EXPECTED[p.expected], usd: usd(p.usd) })
    : t("Terv nélkül · tényleges: {{usd}}", { usd: usd(p.usd) });
}

/** 082, 083: per provider, what the pre-start overview expected against the actual cost, and a warning when a provider
 *  was called that the overview did not count on. */
export function PlanVsActual({ costs }: { costs: RunCostView }) {
  useLocale();
  return (
    <section aria-label={t("Tervezett és tényleges")}>
      <h3 className="mt">{t("Tervezett és tényleges")}</h3>
      {costs.plan_saved ? (
        <dl className="kv cost-kv">
          {costs.providers.map((p) => [
            <dt key={`${p.provider}t`}>{providerName(p.provider)}</dt>,
            <dd key={`${p.provider}d`}>
              <div className="small">{planLine(p)}</div>
              {p.unexpected ? <p className="notice error small" role="alert">{t("Az indítás előtti áttekintés nem számolt ezzel a szolgáltatóval, mégis volt hívás.")}</p> : null}
            </dd>,
          ])}
        </dl>
      ) : <p className="muted small">{t("Ennél a futásnál az indítás előtti áttekintés még nem mentődött; csak a tényleges költés látszik.")}</p>}
    </section>
  );
}

function Journal({ runId }: { runId: string }) {
  useLocale();
  const [open, setOpen] = useState(false);
  return (
    <details className="details mt" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>{t("Hívásnapló (nyers modellhívások)")}</summary>
      {open ? (
        <DataTable dataset="calls" scope={{ run_id: runId }} label={t("Hívásnapló")} maxHeight="50vh"
          emptyText={t("Nem volt fizetős hívás (például minden válasz a gyorsítótárból jött).")} />
      ) : null}
    </details>
  );
}
