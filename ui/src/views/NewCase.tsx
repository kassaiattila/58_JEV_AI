// 231 (stage U, U0; the owner's decisions of 2026-10-27): a new case of any process, from the case list. The processes a
// person may start by hand, each with what it is for; one whose case cannot start yet (a product or a tariff with no
// active version) says what it needs, and offers its example material where it has some. The chosen process's own
// start form (the shared one, `elements/ProcessStart.tsx`) asks what a case of it needs and starts it.
import { api } from "../api";
import { ExampleMaterial } from "../elements/ExampleMaterial";
import { ProcessCreate } from "../elements/ProcessStart";
import { PageHeader } from "../components/PageHeader";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { go } from "../route";

export function NewCase({ pack }: { pack?: string }) {
  useLocale();
  const processes = useLoad("processes:new-case", api.processes);
  const startable = (processes.data?.processes ?? []).filter((p) => p.manual);
  const chosen = startable.find((p) => p.id === pack) ?? null;
  const missing = chosen?.missing_at_start ?? [];
  return (
    <>
      <PageHeader crumbs={[{ label: t("Cases"), href: "#/cases" }]} title={t("New case")}
        summary={t("Choose the process; its form asks what a case of it needs.")} />
      {processes.error ? <p className="notice error" role="alert">{processes.error.message}</p> : null}
      {!processes.data && !processes.error ? <p className="muted">{t("Loading…")}</p> : null}
      {processes.data ? (
        <section className="card create wizard new-case" aria-label={t("New case")}>
          <fieldset className="wizard-choices">
            <legend>{t("Which process?")}</legend>
            {startable.map((p) => (
              <label key={p.id} className="wizard-choice">
                <input type="radio" name="new-case-process" checked={p.id === chosen?.id} aria-label={t(p.title)}
                  onChange={() => go({ view: "case-list", create: true, pack: p.id })} />
                <span>
                  <strong>{t(p.title)}</strong>
                  {p.summary ? <span className="muted small">{t(p.summary)}</span> : null}
                  {p.missing_at_start?.length ? (
                    <span className="todo-text small">{t("Before a case can start: {{what}} needs an active version.",
                      { what: p.missing_at_start.map((m) => t(m.label)).join(", ") })}</span>
                  ) : null}
                </span>
              </label>
            ))}
          </fieldset>
          {chosen?.examples ? <ExampleMaterial pack={chosen.id} needed={missing.length > 0} onChanged={processes.reload} /> : null}
          {chosen && missing.length && !chosen.examples ? (
            <p className="small">{t("Make them active first:")} <a href="#/settings/processes">{t("Settings › Processes")}</a></p>
          ) : null}
          {chosen && !missing.length ? (
            <ProcessCreate key={chosen.id} pack={chosen.id} onDone={(caseId) => go({ view: "cases", caseId })} />
          ) : null}
        </section>
      ) : null}
    </>
  );
}
