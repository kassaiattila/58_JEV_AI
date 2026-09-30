// Egy munkacsomag (057): fejléc a következő lépés gombjával, alatta a munka szakaszai — Feldolgozás · Ellenőrzés ·
// Eredmény —, mindegyik a saját állapotával (a régi V4 szakasz-füleinek mintájára). Cím nélkül a csomag a következő
// lépés szakaszánál nyílik meg; a lépést a szolgáltatás számolja egy helyen (a lista oszlopa is ezt mutatja).
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, USERS_EVENT, type WorkpackageView } from "../api";
import { PageHeader } from "../components/PageHeader";
import { Picker } from "../components/Picker";
import { useEvent, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { itemCountText, MODE, RUN_STATUS, stepLabel, tmap, when } from "../labels";
import { go, type Route, type Stage } from "../route";
import { DocumentsPanel } from "./DocumentsPanel";
import { ProcessStage } from "./ProcessStage";
import { ResultStage } from "./ResultStage";
import { ReviewWorkspace } from "./ReviewWorkspace";
import { StartConfirm } from "./StartConfirm";
import { WorkpackageActions } from "./WorkpackageActions";

const STAGE_LABEL = tmap({ process: "Feldolgozás", review: "Ellenőrzés", result: "Eredmény" }) as Record<Stage, string>;
const ACTIVE = new Set(["queued", "running"]);

export function stageStatus(view: WorkpackageView): Record<Stage, string> {
  const last = view.last_run;
  const recipe = view.workpackage.assignment;
  return {
    process: last ? `${MODE[last.mode]} · ${(RUN_STATUS[last.status] ?? last.status).toLowerCase()} · ${last.items_done}/${last.items}`
      : recipe ? (view.readiness.ready ? t("indítható") : t("nem indítható")) : t("nincs recept"),
    review: last ? (last.open_reasons ? t("{{n}} teendő", { n: last.open_reasons }) : t("nincs teendő")) : itemCountText(view.workpackage.items),
    result: !last ? t("még nincs") : last.mode === "shadow" ? t("próba-eredmény") : last.approval ? t("kiadva") : t("jóváhagyásra vár"),
  };
}

/** A következő lépés felirata a választott nyelven (a közös `stepLabel` a szolgáltatás kódjából és paramétereiből). */
export function nextStepText(view: WorkpackageView): string {
  return stepLabel(view.next.code, view.next.params, view.next.label);
}

/** 061: a csomag felelőse a névlistából (a „Saját csomagjaim” szűrő ez alapján). */
function OwnerPicker({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const users = useLoad("users", api.users);
  useEvent(USERS_EVENT, users.reload);
  const [error, setError] = useState<string | null>(null);
  const owner = view.workpackage.owner ?? "";
  const list = users.data?.users ?? [];
  const options = [{ value: "", label: t("nincs felelős") }, ...list.map((u) => ({ value: u, label: u }))];
  if (owner && !list.includes(owner)) options.push({ value: owner, label: owner });
  async function change(v: string) {
    setError(null);
    try {
      await api.setOwner(view.workpackage.id, v || null);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }
  return (
    <div className="owner-picker">
      <Picker label={t("Felelős")} value={owner} options={options} compact onChange={(v) => void change(v)}
        emptyText={t("Még nincs név a listában (Beállítások › Felhasználók).")} />
      {error ? <span className="small error-text" role="alert">{error}</span> : null}
    </div>
  );
}

export function WorkpackageDetail({ route, wpId }: { route: Extract<Route, { view: "workpackages" }>; wpId: string }) {
  useLocale();
  const [poll, setPoll] = useState(false);
  const wp = useLoad(`wp:${wpId}`, () => api.workpackage(wpId), poll ? 4000 : undefined);
  const lastStatus = wp.data?.last_run?.status;
  useEffect(() => setPoll(lastStatus ? ACTIVE.has(lastStatus) : false), [lastStatus]); // csak futás közben frissül magától
  const recipes = useLoad("recipes", api.recipes);

  if (wp.error?.status === 404 || wp.error?.status === 422) {
    // A címben kért csomag nincs meg: ezt mondjuk ki, nem nyitunk meg helyette másikat.
    return (
      <PageHeader crumbs={[{ label: t("Munkacsomagok"), href: "#/workpackages" }]} title={t("A munkacsomag nem található")}
        summary={<><span className="mono">{wpId}</span>: {t("nincs ilyen azonosítójú munkacsomag (vagy törölték). Válassz a listából.")}</>} />
    );
  }
  if (wp.error) return <p className="notice error" role="alert">{wp.error.message}</p>;
  if (!wp.data) return <p className="muted">{t("Betöltés…")}</p>;
  const view = wp.data;
  const { workpackage, next, last_run: last } = view;
  const stage: Stage = route.stage ?? next.stage;
  const status = stageStatus(view);

  const summary: ReactNode = (
    <>
      {itemCountText(workpackage.items)}
      {workpackage.assignment ? ` · ${(() => { const r = recipes.data?.recipes.find((x) => x.id === workpackage.assignment!.recipe_id); return r ? t(r.title) : workpackage.assignment!.recipe_id; })()}` : ""}
      {last ? ` · ${t("utolsó futás: {{mode}}, {{when}}", { mode: MODE[last.mode].toLowerCase(), when: when(last.created_at) })}` : ` · ${t("még nem futott")}`}
    </>
  );
  // a következő lépés gombja; ha éppen annak a szakasznak az oldalán vagyunk, nem kell
  const nextButton = next.stage !== stage || route.stage === undefined ? (
    <button type="button" className="primary" onClick={() => go({ view: "workpackages", wpId, stage: next.stage })}>{nextStepText(view)} →</button>
  ) : <span className="next-hint">{t("Következő lépés: {{step}}", { step: nextStepText(view) })}</span>;

  return (
    <>
      <PageHeader crumbs={[{ label: t("Munkacsomagok"), href: "#/workpackages" }]} title={workpackage.name} summary={summary}
        actions={<><OwnerPicker view={view} onChanged={wp.reload} />{nextButton}<WorkpackageActions view={view} onChanged={wp.reload} /></>} />
      {workpackage.status === "archived" ? (
        <p className="notice">{t("Ez a csomag el van rejtve a listából; a futásai és az eredményei megmaradtak. Visszahozni a „Csomag kezelése” gombbal lehet.")}</p>
      ) : null}
      <div className="stage-tabs" role="tablist" aria-label={t("A csomag szakaszai")}>
        {(Object.keys(STAGE_LABEL) as Stage[]).map((s, i) => (
          <a key={s} role="tab" aria-selected={stage === s} className={`stage-tab ${next.stage === s ? "is-next" : ""}`} href={`#/workpackages/${wpId}/${s}`}>
            <span className="stage-no" aria-hidden="true">{i + 1}</span>
            <span className="stage-text"><strong>{STAGE_LABEL[s]}</strong><span className="small">{status[s]}</span></span>
          </a>
        ))}
      </div>
      <div role="tabpanel" aria-label={STAGE_LABEL[stage]}>
        {stage === "process" && route.start ? <StartConfirm view={view} mode={route.start.mode} rerun={route.start.rerun} onChanged={wp.reload} /> : null}
        {stage === "process" && !route.start ? <ProcessStage view={view} onChanged={wp.reload} /> : null}
        {stage === "review" ? (
          view.runs ? (
            <>
              <ReviewWorkspace wp={workpackage} itemId={route.itemId} />
              <details className="details mt">
                <summary>{t("Iratok kezelése: megnyitás, letöltés, eltávolítás")}</summary>
                <DocumentsPanel wp={workpackage} onChanged={wp.reload} />
              </details>
            </>
          ) : (
            <>
              <p className="notice">{t("A csomagon még nem futott recept, ezért nincs mit ellenőrizni. Az iratok itt megnyithatók és letölthetők; a feldolgozást a")}{" "}
                <a href={`#/workpackages/${wpId}/process`}>{STAGE_LABEL.process}</a> {t("szakaszban indíthatod.")}</p>
              <DocumentsPanel wp={workpackage} onChanged={wp.reload} />
            </>
          )
        ) : null}
        {stage === "result" ? <ResultStage view={view} table={route.table} runId={route.runId} onChanged={wp.reload} /> : null}
      </div>
    </>
  );
}
