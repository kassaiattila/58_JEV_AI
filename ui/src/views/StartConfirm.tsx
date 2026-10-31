// Confirmation of starting a run (061 decision: the trial run, live run and rerun buttons do not start anything, but
// lead to this page). It summarises what will start: mode, work package, the processing settings, number of items,
// and (080, the pre-start overview) which services may be called, with the budget maximum and what for. A run can
// only be started from here; Mégse (Cancel) goes back. 160-C S3: the run over only the pending items shows their count,
// budget and plan, and starts with their input.
import { useState } from "react";
import { api, ApiError, type WorkpackageView } from "../api";
import { BlockerList } from "../components/BlockerList";
import { FormActions } from "../components/FormActions";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { blockerText, MODE, PARAM_LABEL, providerName, shownParams, shownValue, usdBudget, when } from "../labels";
import { go } from "../route";
import { paramValue, RunPlanList } from "./ProcessStage";

const ACTIVE = new Set(["queued", "running"]);

export function StartConfirm({ view, mode, rerun, pending = false, onChanged }: {
  view: WorkpackageView; mode: "shadow" | "apply"; rerun: boolean; pending?: boolean; onChanged: () => void;
}) {
  useLocale();
  const { workpackage: wp, last_run: last } = view;
  // 066 Á12: the budget, the item count and the input fingerprint come from a fresh request; the work package view is
  // loaded once, and after a restart of the local service or a change in between it would show a stale budget. Until
  // then, starting is disabled.
  const fresh = useLoad(`readiness:${wp.id}`, () => api.readiness(wp.id));
  const readiness = fresh.data ?? view.readiness;
  // 160-C S3: the pending items' own count, blockers, budget, plan and input (gone once they were processed meanwhile)
  const supplement = pending ? readiness.supplement?.[mode] : undefined;
  const offer = pending ? supplement : readiness;
  const recipes = useLoad("recipes", api.recipes);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const assignment = wp.assignment;
  // 080: without saved settings the default processing's defaults apply (and are saved at start)
  const recipe = recipes.data?.recipes.find((r) => r.id === assignment?.recipe_id) ?? (assignment ? undefined : recipes.data?.recipes[0]);
  // 089: a setting missing from an older assignment runs with the processing's default (as on the service), so it is
  // shown with that value
  const defaults: Record<string, string> = Object.fromEntries(Object.entries(recipe?.params ?? {}).map(([k, spec]) => [k, spec.default ?? ""]));
  const settings: Record<string, string> = { ...defaults, ...assignment?.params };
  const kinds = [...new Set(wp.items.map((i) => i.kind))];
  // rerun: the mode of the run the package's next step is about (160-C S3), on the package's items as they are now
  const target = view.current_run ?? last;
  const effectiveMode = rerun && target ? target.mode : mode;
  const items = supplement ? supplement.items : readiness.counts.items;
  const active = last ? ACTIVE.has(last.status) : false;
  const budget = Object.entries(offer?.budget ?? {});
  const paid = budget.some(([, v]) => Number(v) > 0);
  const blocked = !fresh.data || !offer?.ready || active || (rerun && !target);
  const back = () => go({ view: "workpackages", wpId: wp.id, stage: "process" });

  const title = pending
    ? effectiveMode === "apply" ? t("Confirm the live run on the pending items") : t("Confirm the trial run on the pending items")
    : rerun
    ? t("Confirm rerun ({{mode}})", { mode: MODE[effectiveMode].toLowerCase() })
    : effectiveMode === "apply" ? t("Confirm starting a live run") : t("Confirm starting a trial run");
  const meaning = effectiveMode === "apply"
    ? t("A person approves the result in the Result stage, with no open issues.")
    : t("The result can be viewed and downloaded, but not released.");

  async function confirm() {
    setBusy(true);
    setMsg(null);
    try {
      await api.start(wp.id, supplement
        ? { mode: effectiveMode, scope: "pending", expected_revision: readiness.assignment_revision, input_hash: supplement.input_hash }
        : { mode: effectiveMode, expected_revision: readiness.assignment_revision, input_hash: readiness.input_hash,
          ...(rerun && target ? { rerun_of: target.run_id } : {}) });
      // 263 (F2; the owner's decision of 2026-10-31): the person stays where the work is - the batch's Processing
      // stage shows the run's progress, under its case
      onChanged();
      go({ view: "workpackages", wpId: wp.id, stage: "process" });
    } catch (e) {
      const err = e as ApiError;
      setMsg(err.status === 409 && err.code === "revision_conflict"
        ? t("The batch or its settings changed meanwhile. We refreshed it; review it and start again.") : err.message);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide start-confirm" aria-label={title}>
      <h2>{title}</h2>
      <p>{meaning}{pending
        ? ` ${t("Only the items no run of this kind has finished yet (added since, or failed). The earlier runs and their approval stay as they are; this run's result is reviewed and approved on its own.")}`
        : rerun && target ? ` ${t("The run of {{when}} again as a new run, on all the package's documents as they are now (the added ones too, the removed ones not).", { when: when(target.created_at) })}` : ""}</p>
      <dl className="confirm-list">
        <dt>{t("Document batch")}</dt><dd>{wp.name}</dd>
        <dt>{t("Item list")}</dt><dd>{t("{{n}} items", { n: items })}</dd>
        <dt>{t("Processing settings")}</dt>
        <dd>
          {!recipe && assignment ? <>{t(recipes.data?.titles?.[assignment.recipe_id] ?? assignment.recipe_id)}: </> : null}
          {readiness.assignment_default ? <span className="muted small">{t("default settings, saved to the batch when the run starts")}</span> : null}
          {/* 263 (F4): a run no AI works on (its maximum cost is none) names no AI settings */}
          {paid ? (
            <ul className="plain small">
              {/* 090: the processing path first (the documents' path and the use of JEV as one choice), then the settings
                  that count */}
              {shownParams(Object.keys(settings), settings, kinds).map((k) => <li key={k}>{PARAM_LABEL[k] ?? k}: {paramValue(k, shownValue(k, settings, kinds))}</li>)}
            </ul>
          ) : <p className="small muted">{t("No AI works on these items: code reads them.")}</p>}
        </dd>
        <dt>{t("Maximum cost")}</dt>
        <dd>
          {budget.length
            ? budget.map(([p, v]) => t("{{provider}} up to {{amount}}", { provider: providerName(p), amount: usdBudget(v) })).join(", ")
            : t("none")}
          <span className="muted small"> — {paid
            ? t("involves paid calls; the actual cost is usually lower and can be followed on the run page")
            : t("involves no paid calls")}</span>
        </dd>
      </dl>
      {offer?.plan ? <RunPlanList plan={offer.plan} budget={offer.budget} /> : null}
      {offer && !offer.ready ? (
        <BlockerList items={offer.blockers.map((b, i) => ({ key: String(i), content: blockerText(b) }))} />
      ) : null}
      {offer?.warnings.length ? (
        <BlockerList items={offer.warnings.map((w, i) => ({ key: String(i), warning: true, content: blockerText(w) }))} />
      ) : null}
      {pending && fresh.data && !supplement ? <p className="notice">{t("No item is pending any more: there is nothing to start on its own.")}</p> : null}
      {active ? <p className="notice">{t("A run is in progress on this batch; a new one can start only after it.")}</p> : null}
      {!fresh.data ? (
        <p className="muted small" role="status">
          {fresh.error ? t("The current cost limit could not be loaded: {{message}}", { message: fresh.error.message }) : t("Refreshing the cost limit…")}
        </p>
      ) : null}
      {/* 263 (F1): the confirmation card's foot - "Cancel", then the start, on the right */}
      <FormActions onCancel={back} busy={busy}>
        <button type="button" className="primary" disabled={blocked || busy} onClick={() => void confirm()}>
          {busy ? t("Launching…") : pending ? t("Start on the pending items") : rerun ? t("Start rerun")
            : effectiveMode === "apply" ? t("Start live run") : t("Start trial run")}
        </button>
      </FormActions>
      {msg ? <p role="alert" className="notice error">{msg}</p> : null}
    </section>
  );
}
