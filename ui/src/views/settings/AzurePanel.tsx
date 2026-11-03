// 279 (the owner's decisions of 2026-11-02): Azure Document Intelligence on the Operations page — whether this machine
// has its own Azure endpoint and key (the only route: nothing of the legacy project is used), whether the provider is
// switched on, what a document costs at most, and the last free check of the endpoint and key, which the card can run
// again (nothing is analysed or billed). The service never shows the key.
import { useState } from "react";
import { api, ApiError, type AzureCheck, type AzureInfo, type Recipe } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { tmap, usd, when } from "../../labels";

const CHECK_REASON: Record<string, string> = tmap({
  not_configured: "the endpoint and the key are not set on this machine",
  not_https: "the endpoint is not an https address",
  switched_off: "Azure is switched off on this machine",
  refused_key: "the service refused the key",
  not_found: "the endpoint does not belong to a Document Intelligence resource",
  unreachable: "the service could not be reached",
  bad_answer: "the answer did not come from a Document Intelligence resource",
});

/** Why the last check failed, in words (an HTTP error code is named as such). */
export function checkReason(reason: string | null): string {
  if (!reason) return "";
  const code = /^http_(\d+)$/.exec(reason);
  if (code) return t("the service answered with an error ({{code}})", { code: code[1] });
  return CHECK_REASON[reason] ?? reason;
}

/** The Azure state in one sentence and its level (shared by the card, the processing settings and the test). */
export function azureState(info: AzureInfo): { level: "ok" | "warn" | "error"; text: string } {
  if (!info.enabled) {
    return { level: "warn", text: t("Azure recognition is switched off on this machine: weak scans keep their local text.") };
  }
  if (!info.configured) {
    return { level: "warn", text: t("Azure recognition is not set up on this machine: weak scans keep their local text, with a to-do.") };
  }
  const last: AzureCheck | null = info.last_check;
  const host = info.host ?? "";
  if (!last) return { level: "warn", text: t("Azure recognition is set up ({{host}}), but it has not been checked yet.", { host }) };
  if (last.ok) return { level: "ok", text: t("Azure recognition is set up and answers ({{host}}, checked {{when}}).", { host, when: when(last.at) }) };
  return { level: "error", text: t("The last check of Azure recognition failed: {{why}} ({{when}}).", { why: checkReason(last.reason), when: when(last.at) }) };
}

/** Whether a run with Azure recognition switched on can reach Azure on this machine (the processing settings' notice). */
export function azureUsable(info: AzureInfo | undefined): boolean {
  return !info || (info.enabled && info.configured);
}

/** Whether a processing's settings switch Azure recognition on (the saved value, else the recipe's default). */
export function azureOn(recipe: Recipe | undefined, params: Record<string, string>): boolean {
  const spec = recipe?.params.azure_ocr;
  return !!spec && (params.azure_ocr ?? spec.default) === "on";
}

/** 279: under the processing settings, when Azure recognition is on but this machine cannot reach Azure. */
export function AzureSettingNotice({ on }: { on: boolean }) {
  useLocale();
  const d = useLoad("azure", api.azure, 300000);
  if (!on || !d.data || azureUsable(d.data)) return null;
  return <p className="notice small" role="note">{azureState(d.data).text} {t("The Operations page under Settings says how to set it up.")}</p>;
}

export function AzurePanel() {
  useLocale();
  const d = useLoad("azure", api.azure, 300000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const state = d.data ? azureState(d.data) : null;
  async function check() {
    setBusy(true);
    setMsg(null);
    try {
      await api.azureCheck();
      d.reload();
    } catch (e) {
      setMsg((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  const info = d.data;
  return (
    <section className="card wide" aria-label={t("Azure recognition")}>
      <div className="card-head">
        <h3>{t("Azure recognition")}</h3>
        {info?.enabled && info.configured ? (
          <button type="button" className="secondary small-btn" disabled={busy} onClick={() => void check()}>
            {busy ? t("Checking…") : t("Check now (free)")}
          </button>
        ) : null}
      </div>
      {d.error ? <p className="notice error">{d.error.message}</p> : null}
      {state ? (
        <p role="status" className={state.level === "ok" ? "" : state.level === "error" ? "notice error" : "notice"}>
          <span className={`status ${state.level === "ok" ? "s-done" : state.level === "error" ? "s-failed" : "s-warn"}`}>
            {state.level === "ok" ? t("OK") : state.level === "error" ? t("Error") : t("Attention")}
          </span>{" "}{state.text}
        </p>
      ) : null}
      {info ? (
        <p className="small tnum">
          {t("Model {{model}} · at most {{pages}} pages per document · about {{price}} per page", { model: info.model, pages: info.max_pages, price: usd(info.usd_per_page) })}
        </p>
      ) : null}
      {msg ? <p className="notice error">{msg}</p> : null}
      <p className="muted small">
        {t("Azure reads weak scans more accurately, for a fee, within each run's Azure budget. Its endpoint and key go into the .env file of this machine (the setup guide, section 3); the free check asks the resource for its details and analyses nothing:")}{" "}
        <span className="mono">python -m jav.cli ocr --check-azure</span>
      </p>
    </section>
  );
}
