// 179 (plan 170 L4, DECISIONS 178/179): which template a package's download is made with, chosen next to the download
// (the owner's decision of 2026-10-19): the built-in template or an active own one (Settings › Output templates). The
// choice is the package's: the download, the next release and a reconciliation's approval use it. Without an own
// template to choose there is nothing to show, so the screen stays as it was; a chosen template retired since is said.
import { useState } from "react";
import { api, type ApiError, type OutputName } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { Picker } from "./Picker";

const BUILTIN = "builtin";

const hint = (o: OutputName) => ({
  package_result: t("The full Excel package and the package's next release are made with this template."),
  utility_cost: t("The utility cost's workbook and the package's next release are made with this template."),
  reconcile_statement: t("The draft's download and the approval's stored file are made with this template."),
})[o];

export function TemplateChoice({ wpId, output }: { wpId: string; output: OutputName }) {
  useLocale();
  const data = useLoad(`output-templates:${wpId}`, () => api.packageOutputTemplates(wpId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const choice = data.data?.outputs[output];
  if (!choice || (!choice.templates.length && !choice.chosen)) return null;
  const chosen = choice.chosen;
  const retired = !!chosen && !chosen.active;

  async function choose(value: string) {
    setBusy(true);
    setError(null);
    try {
      await api.choosePackageOutputTemplate(wpId, output, value === BUILTIN ? null : value, choice?.decision_state);
      data.reload();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="template-choice" title={hint(output)}>
      <span className="template-choice-label" aria-hidden="true">{t("Template")}</span>
      <Picker label={t("Template of the download")} hideLabel compact disabled={busy} value={chosen?.active ? chosen.template : BUILTIN}
        options={[{ value: BUILTIN, label: t("Built-in") },
          ...choice.templates.map((x) => ({ value: x.template, label: x.name, detail: t("version {{n}}", { n: x.version }) }))]}
        onChange={(v) => void choose(v)} />
      {retired ? <span className="status s-warn">{t("the chosen template was retired; the built-in one is used")}</span> : null}
      {error ? <span role="alert" className="error-text small">{error}</span> : null}
    </span>
  );
}
