// 231 (stage U, U0; the owner's decisions of 2026-10-27): a new case of any process, from the case list. The processes a
// person may start by hand, each with what it is for, in the left column; one whose case cannot start yet (a product or
// a tariff with no active version) says what it needs. The chosen process's part stands beside the list, so its next
// step shows without scrolling: its example material where it has some, then its own start form (the shared one,
// `elements/ProcessStart.tsx`), which asks what a case of it needs and starts it. U1e: once the material changes, the
// form is made anew, so its choices (an own party the material made) are read again.
import { useState } from "react";
import { api } from "../api";
import { ExampleMaterial } from "../elements/ExampleMaterial";
import { ProcessCreate } from "../elements/ProcessStart";
import { PageHeader } from "../components/PageHeader";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { go } from "../route";

export function NewCase({ pack, after }: { pack?: string; after?: string }) {
  useLocale();
  const processes = useLoad("processes:new-case", api.processes);
  const startable = (processes.data?.processes ?? []).filter((p) => p.manual);
  const [query, setQuery] = useState("");
  const shownProcesses = startable.filter((p) => !query.trim() || `${t(p.title)} ${p.summary ? t(p.summary) : ""}`.toLowerCase().includes(query.trim().toLowerCase()));
  const chosen = startable.find((p) => p.id === pack) ?? null;
  const missing = chosen?.missing_at_start ?? [];
  const [material, setMaterial] = useState(0);
  const materialChanged = () => { processes.reload(); setMaterial((n) => n + 1); };
  return (
    <>
      <PageHeader crumbs={[{ label: t("Cases"), href: "#/cases" }]} title={t("New case")}
        summary={t("Choose the process; its form asks what a case of it needs.")} />
      {processes.error ? <p className="notice error" role="alert">{processes.error.message}</p> : null}
      {!processes.data && !processes.error ? <p className="muted">{t("Loading…")}</p> : null}
      {processes.data ? (
        <div className="new-case">
          {/* 263 (F3, H26): one line a process, with a search, so the processes fit on the screen; the chosen one's
              description stands beside it, above its form */}
          <section className="card new-case-list" aria-label={t("Which process?")}>
            <input className="new-case-search" type="search" value={query} placeholder={t("Search the processes…")}
              aria-label={t("Search the processes")} onChange={(e) => setQuery(e.target.value)} />
            <fieldset className="wizard-choices compact">
              <legend>{t("Which process?")}</legend>
              {shownProcesses.map((p) => (
                <label key={p.id} className="wizard-choice">
                  <input type="radio" name="new-case-process" checked={p.id === chosen?.id} aria-label={t(p.title)}
                    onChange={() => go({ view: "case-list", create: true, pack: p.id })} />
                  <span>
                    <strong>{t(p.title)}</strong>
                    {p.missing_at_start?.length ? (
                      <span className="todo-text small">{t("Before a case can start: {{what}} needs an active version.",
                        { what: p.missing_at_start.map((m) => t(m.label)).join(", ") })}</span>
                    ) : null}
                  </span>
                </label>
              ))}
              {!shownProcesses.length ? <p className="muted small">{t("No process matches the search.")}</p> : null}
            </fieldset>
          </section>
          <section className="card new-case-form" aria-label={chosen ? t(chosen.title) : t("New case")}>
            {chosen ? <h2>{t(chosen.title)}</h2> : <p className="muted">{t("Choose a process on the left: its form opens here.")}</p>}
            {chosen?.summary ? <p className="small muted">{t(chosen.summary)}</p> : null}
            {chosen?.examples ? <ExampleMaterial pack={chosen.id} needed={missing.length > 0} onChanged={materialChanged} /> : null}
            {chosen && missing.length && !chosen.examples ? (
              <p className="small">{t("Make them active first:")} <a href="#/settings/processes">{t("Settings › Processes")}</a></p>
            ) : null}
            {chosen && !missing.length ? (
              <ProcessCreate key={`${chosen.id}:${material}:${after ?? ""}`} pack={chosen.id} after={after}
                onDone={(caseId) => go({ view: "cases", caseId })} onCancel={() => go({ view: "case-list" })} />
            ) : null}
          </section>
        </div>
      ) : null}
    </>
  );
}
