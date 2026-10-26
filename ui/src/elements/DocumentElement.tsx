// 231 (stage D, D-f7): the document a step printed (document_view): the Word file a priced document's step stored with
// the approved version it printed, its fingerprint and its download. The file never changes; a new approval prints a
// new one. Until the version is approved the element says what it waits for; a step that could not print it says so.
import { api, type DocumentViewData } from "../api";
import { t, useLocale } from "../i18n";
import { documentStatus } from "./caseStatus";
import type { ElementProps } from "./registry";

const loading = <p className="muted">{t("Loading…")}</p>;

export function DocumentView(p: ElementProps) {
  useLocale();
  const d = p.element.data as DocumentViewData | null;
  if (!d) return loading;
  const step = p.element.step ?? "";
  const title = p.page.steps[step]?.title;
  const fromTitle = d.from_step ? p.page.steps[d.from_step]?.title : null;
  const from = fromTitle ? t(fromTitle) : d.from_step ?? "–";
  const state = documentStatus(d);
  return (
    <section className="card" aria-label={title ? t(title) : t("Document")}>
      <div className="card-head">
        <h2>{title ? t(title) : t("Document")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {d.file ? (
        <>
          <dl className="kv">
            <dt>{t("File")}</dt>
            <dd><a href={api.caseStepFileUrl(p.caseId, step)} download={d.file.name}>{d.file.name}</a></dd>
            <dt>{t("Printed from")}</dt>
            <dd>{t("version {{n}} of “{{step}}”", { n: d.version ?? "–", step: from })}</dd>
            <dt>{t("Fingerprint")}</dt>
            <dd className="mono small" title={d.file.sha256}>{d.file.sha256.slice(0, 12)}</dd>
          </dl>
          <p className="muted small">{t("Stored with the version: its download never changes.")}</p>
        </>
      ) : d.state === "failed" ? (
        <p className="notice error small">{t("The document could not be printed; the step's note says why.")}</p>
      ) : (
        <p className="muted">{t("Printed once “{{step}}” is approved.", { step: from })}</p>
      )}
    </section>
  );
}
