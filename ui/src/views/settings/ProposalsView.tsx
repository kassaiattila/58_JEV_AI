// 231 (stage D, D-c7g): rule proposals in Settings › Products. A person asks for the rules of a condition document's
// file (the free stand-in, or GPT within a budget the button shows; JEV may judge each proposal), sees each run and its
// proposals: the code's check (ready, numbers to confirm, blocked), JEV's mark and the decision. A proposal opens with
// its decision table, the clause it was read from, the code's findings and where each number stands; a person accepts
// it as a draft rule (confirming the numbers the document does not print), corrects it or rejects it with a reason.
import { Fragment, useMemo, useState } from "react";
import {
  api, ApiError, type ConditionDocument, type ProductRegistry, type ProposalNumber, type RuleProposal, type RuleProposalRun, type Said,
} from "../../api";
import { BrowseButton } from "../../components/BrowseButton";
import { DataTable } from "../../components/DataTable";
import { ConfirmButton } from "../../components/ConfirmButton";
import { FormActions } from "../../components/FormActions";
import { Picker } from "../../components/Picker";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { numText, tmap, usdBudget, when } from "../../labels";
import { go } from "../../route";
import { Citation, current, DecisionTable, documentsByRef, levelLabel, RULE_KIND, SaidLines } from "./RegistryParts";
import { useSettingsTitle } from "./settingsTree";

const LIST = "settings_proposal_runs";

const RUN_STATE: Record<string, [string, string]> = {
  queued: ["s-queued", "Queued"], running: ["s-running", "Running"], done: ["s-done", "Done"], failed: ["s-failed", "Failed"],
};
const READINESS: Record<string, [string, string]> = {
  ready: ["s-done", "Ready"], confirm: ["s-review", "Numbers to confirm"], blocked: ["s-failed", "Blocked"],
};
const SUPPORT: Record<string, [string, string]> = {
  supported: ["s-done", "Supported"], check: ["s-warn", "To check"], contradicted: ["s-failed", "Contradicted"],
  not_asked: ["s-held", "Not asked"],
};
const DECISION: Record<string, [string, string]> = {
  proposed: ["s-pending", "To decide"], accepted: ["s-approved", "Accepted"], corrected: ["s-approved", "Corrected"],
  rejected: ["s-removed", "Rejected"],
};
// JEV's reasons (`jav/app/rule_support.py`), as a person reads them
const SUPPORT_REASON: Record<string, string> = tmap({
  "the page states no such rule": "the page states no such rule", "the page does not state a row": "the page does not state a row",
  "a row is not clearly stated": "a row is not clearly stated",
  "the page may name something the rule leaves out": "the page may name something the rule leaves out",
  "the page states another kind of rule": "the page states another kind of rule",
});
const WHERE: Record<string, string> = tmap({
  quote: "in the quote", page: "on the cited page", elsewhere: "on another page", word: "written as a word",
  derived: "follows from a stated number", neutral: "a factor of 1", ocr: "read by text recognition", not_found: "not in the document",
});

function Mark({ table, value }: { table: Record<string, [string, string]>; value: string }) {
  const [cls, label] = table[value] ?? ["s-pending", value];
  return <span className={`status ${cls}`}>{t(label)}</span>;
}

/** 263 (E1): the list's page - asking for proposals, then the runs in the one list; or a run's own page (`runId`). */
export function ProposalsView({ registry, runId, onChanged }: { registry: ProductRegistry; runId?: string; onChanged: () => void }) {
  useLocale();
  const list = useLoad("rule-proposals", api.ruleProposalRuns);
  const documents = useMemo(() => documentsByRef(registry.documents), [registry.documents]);
  if (runId) return <RunCard key={runId} runId={runId} registry={registry} documents={documents} onChanged={onChanged} />;
  return (
    <>
      <StartCard registry={registry} standIns={list.data?.stand_ins ?? []}
        onStarted={(run) => { onChanged(); go({ view: "settings", section: "products", item: "proposals", tab: run.run_id }); }} />
      <DataTable dataset={LIST} label={t("Proposal runs")} storageId={LIST} persist={LIST} pollMs={3000} emptyText={t("No proposal run yet.")} />
    </>
  );
}

function StartCard({ registry, standIns, onStarted }: { registry: ProductRegistry; standIns: string[]; onStarted: (r: RuleProposalRun) => void }) {
  useLocale();
  const documentOptions = registry.documents.flatMap((d) => d.versions.map((v) => ({ value: v.ref, label: v.content.title, detail: v.ref })));
  const productOptions = [{ value: "", label: t("No product") },
    ...registry.products.map((p) => ({ value: p.ident, label: current(p).name, detail: p.ident }))];
  const catalogues = Object.keys(registry.catalogues);
  const [document, setDocument] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [product, setProduct] = useState("");
  const [gpt, setGpt] = useState(false);
  const [openai, setOpenai] = useState("");
  const [jev, setJev] = useState("");
  const [verify, setVerify] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cap = (Number(openai.replace(",", ".")) || 0) + (verify ? Number(jev.replace(",", ".")) || 0 : 0);
  const ready = !!document && path.trim() !== "" && (!gpt || cap > 0) && (gpt || standIns.length > 0) && catalogues.length > 0;
  async function start() {
    setBusy(true);
    setError(null);
    try {
      const limits: Record<string, string> = {};
      if (gpt && openai) limits.openai = openai.replace(",", ".");
      if (gpt && verify && jev) limits.jev = jev.replace(",", ".");
      const run = await api.startRuleProposals({ document: document!, path: path.trim(), catalogue: catalogues[0], product: product || null,
        proposer: gpt ? "gpt" : `stand_in:${standIns[0]}`, limits, verify: gpt && verify });
      onStarted(run);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card wide registry-card" aria-label={t("Propose rules from a document")}>
      <h3>{t("Propose rules from a document")}</h3>
      <p className="muted small">{t("The file is read page by page; a page marked internal is never sent. Each proposal is checked by code; you accept, correct or reject each, and an accepted one becomes a draft rule.")}</p>
      <div className="form-row">
        <Picker label={t("The document version the rules cite")} value={document} options={documentOptions} onChange={setDocument}
          emptyText={t("No condition document yet.")} className="proposal-document" />
        <Picker label={t("Product (its cover modules)")} value={product} options={productOptions} onChange={setProduct} className="proposal-product" />
      </div>
      <div className="form-row">
        <label className="block grow">{t("The document's file (.pdf)")}
          <input value={path} maxLength={2000} spellCheck={false} autoComplete="off" onChange={(e) => setPath(e.target.value)} />
        </label>
        <BrowseButton kind="files" initial={path} onPick={([p]) => setPath(p)} />
      </div>
      <fieldset className="proposal-proposer">
        <legend>{t("Proposer")}</legend>
        <label className="check"><input type="radio" name="proposer" checked={!gpt} onChange={() => setGpt(false)} />
          {t("Stand-in: the invented insurer's rules (free, for trying)")}</label>
        <label className="check"><input type="radio" name="proposer" checked={gpt} onChange={() => setGpt(true)} />
          {t("GPT, within a budget")}</label>
      </fieldset>
      {gpt ? (
        <div className="form-row">
          <label className="block">{t("OpenAI budget (USD)")}<input className="tnum" inputMode="decimal" value={openai} maxLength={8} onChange={(e) => setOpenai(e.target.value)} /></label>
          <label className="check proposal-verify"><input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} />
            {t("JEV judges each proposal")}</label>
          {verify ? <label className="block">{t("JEV budget (USD)")}<input className="tnum" inputMode="decimal" value={jev} maxLength={8} onChange={(e) => setJev(e.target.value)} /></label> : null}
        </div>
      ) : null}
      <FormActions busy={busy}>
        <button type="button" className={ready ? "primary" : "secondary"} disabled={busy || !ready} onClick={() => void start()}
          title={gpt ? t("Can spend up to {{usd}}", { usd: usdBudget(cap) }) : undefined}>
          {busy ? t("Starting…") : t("Propose rules")}
          {gpt && cap > 0 ? <span className="spend" aria-hidden="true">≤ {usdBudget(cap)}</span> : null}
        </button>
      </FormActions>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}

function RunCard({ runId, registry, documents, onChanged }: {
  runId: string; registry: ProductRegistry; documents: Map<string, ConditionDocument>; onChanged: () => void;
}) {
  useLocale();
  const loaded = useLoad(`rule-proposal-run:${runId}`, () => api.ruleProposalRun(runId), 3000);
  const [open, setOpen] = useState<number | null>(null);
  const run = loaded.data;
  useSettingsTitle(run ? documents.get(run.document_ref)?.title ?? run.document_ref : null);
  if (!run) return loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : <p className="muted">{t("Loading…")}</p>;
  const skipped = Object.entries(run.skipped);
  return (
    <section className="sheet registry-card" aria-label={t("Proposal run")}>
      <p className="registry-line">
        <Mark table={RUN_STATE} value={run.state} />
        <span className="muted small">
          {run.file} · {run.stand_in ? t("Stand-in (free)") : "GPT"}
          {run.page_count != null ? ` · ${t("{{read}} of {{pages}} page(s) read", { read: run.page_count - skipped.length, pages: run.page_count })}` : ""}
          {run.text_source === "ocr" ? ` · ${t("read by text recognition")}` : ""}
        </span>
      </p>
      {skipped.length ? <p className="notice warn small">{t("Left out by their marking (never sent): {{pages}}", { pages: skipped.map(([p, m]) => `${p} (${m})`).join(", ") })}</p> : null}
      {run.state === "failed" ? <p className="notice error small" role="alert">{run.error}</p> : null}
      {run.proposals?.length ? (
        <table className="table compact" aria-label={t("Proposals")}>
          <thead><tr><th className="num">#</th><th>{t("Title")}</th><th>{t("Kind")}</th><th>{t("Read from")}</th><th>{t("Code's check")}</th><th>{t("JEV")}</th><th>{t("Decision")}</th></tr></thead>
          <tbody>
            {run.proposals.map((p) => (
              <Fragment key={p.id}>
              <tr aria-selected={p.id === open}>
                <td className="num muted">{p.n}</td>
                <td><button type="button" className="link-btn registry-open" aria-expanded={p.id === open} onClick={() => setOpen(p.id === open ? null : p.id)}>{p.title}</button></td>
                <td>{RULE_KIND[p.kind] ?? p.kind}</td>
                <td className="nowrap">{t("p. {{n}}", { n: p.page })} · {t("clause {{clause}}", { clause: p.clause || "–" })}</td>
                <td><Mark table={READINESS} value={p.readiness} /></td>
                <td>{p.support ? <Mark table={SUPPORT} value={p.support.mark} /> : <span className="muted">–</span>}</td>
                <td><Mark table={DECISION} value={p.state} /></td>
              </tr>
              {p.id === open ? ( // 263 (E1): a proposal opens under its own row
                <tr className="row-detail"><td colSpan={7}>
                  <ProposalDetail key={`${p.id}:${p.decision_state}`} proposal={p} registry={registry} documents={documents}
                    onDone={() => { loaded.reload(); onChanged(); }} />
                </td></tr>
              ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      ) : run.state === "done" ? <p className="muted">{t("No rule was proposed.")}</p> : null}
    </section>
  );
}

/** A number as a person reads it: in the language's notation with its unit or currency; a code as written. */
function numberText(n: ProposalNumber): string {
  if (n.kind === "code") return n.value;
  const [figure, ...rest] = n.value.split(" ");
  return [numText(figure, 4), ...rest].join(" ");
}

const unconfirmed = (numbers: ProposalNumber[]) => numbers.filter((n) => n.where === "not_found" || n.where === "ocr");

function ProposalDetail({ proposal: p, registry, documents, onDone }: {
  proposal: RuleProposal; registry: ProductRegistry; documents: Map<string, ConditionDocument>; onDone: () => void;
}) {
  useLocale();
  const toConfirm = unconfirmed(p.numbers);
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [json, setJson] = useState(() => JSON.stringify(p.rule, null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; problems: Said[] } | null>(null);
  const blocking = p.findings.filter((f) => f.severity === "blocking");
  const attention = p.findings.filter((f) => f.severity === "attention");
  const open = p.state === "proposed";
  const canAccept = open && !!p.rule && !blocking.length && toConfirm.every((n) => confirmed.includes(n.value));
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? { text: e.message, problems: e.detail.problems ?? [] } : { text: String(e), problems: [] });
    } finally {
      setBusy(false);
    }
  }
  const cat = p.rule ? registry.catalogues[p.rule.catalogue] : undefined;
  return (
    <div className="registry-rule" role="group" aria-label={p.title}>
      <h4>{p.title}</h4>
      <p className="muted small">
        {RULE_KIND[p.kind] ?? p.kind}{p.rule ? ` · ${t("on each {{level}}", { level: levelLabel(cat, p.rule.level) })}` : ""}
        {` · ${t("proposed from page(s) {{pages}}", { pages: p.pages.join(", ") })}`}
      </p>
      {p.problem ? <SaidLines items={[p.problem]} /> : null}
      {p.rule ? <><DecisionTable rule={p.rule} cat={cat} /><Citation source={p.rule.source} documents={documents} /></> : null}
      {blocking.length ? <><h4>{t("What blocks it")}</h4><SaidLines items={blocking.map((f) => f.text)} label={t("What blocks it")} /></> : null}
      {attention.length ? <><h4>{t("What to look at")}</h4><SaidLines warning items={attention.map((f) => f.text)} label={t("What to look at")} /></> : null}
      {p.numbers.length ? (
        <table className="table compact" aria-label={t("Its numbers")}>
          <thead><tr><th>{t("Number")}</th><th>{t("Where it stands")}</th><th className="num">{t("Page")}</th></tr></thead>
          <tbody>
            {p.numbers.map((n) => (
              <tr key={`${n.value}:${n.where}`}>
                <td className={n.kind === "code" ? "mono" : "tnum"}>{numberText(n)}</td>
                <td className={n.where === "not_found" || n.where === "ocr" ? "todo-text" : undefined}>{WHERE[n.where] ?? n.where}</td>
                <td className="num">{n.page ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {p.support ? (
        <p className="registry-line"><span className="muted small">{t("JEV:")}</span> <Mark table={SUPPORT} value={p.support.mark} />
          {p.support.reason ? <span className="muted small">{p.support.reason.startsWith("jev_unavailable") ? t("JEV was not available")
            : SUPPORT_REASON[p.support.reason] ?? p.support.reason}</span> : null}
        </p>
      ) : null}
      {open ? (
        <div className="registry-activation">
          {toConfirm.length ? (
            <fieldset className="proposal-confirm">
              <legend>{t("Confirm the numbers the document does not print")}</legend>
              {toConfirm.map((n) => (
                <label key={n.value} className="check">
                  <input type="checkbox" checked={confirmed.includes(n.value)}
                    onChange={(e) => setConfirmed(e.target.checked ? [...confirmed, n.value] : confirmed.filter((v) => v !== n.value))} />
                  <span className={n.kind === "code" ? "mono" : "tnum"}>{numberText(n)}</span> <span className="muted small">{WHERE[n.where]}</span>
                </label>
              ))}
            </fieldset>
          ) : null}
          <FormActions busy={busy} note={t("A draft rule is made active as usual, by its own checks.")}>
            <ConfirmButton className={canAccept ? "primary" : "secondary"} disabled={busy || !canAccept}
              question={t("Accept it as a draft rule? It changes nothing until it is made active.")}
              onConfirm={() => void run(() => api.acceptRuleProposal(p.id, p.decision_state, confirmed))}>{t("Accept as a draft rule")}</ConfirmButton>
          </FormActions>
          <div className="form-row">
            <label className="block grow">{t("Reason for rejecting")}
              <input value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
            </label>
            <ConfirmButton className="secondary" disabled={busy || !reason.trim()}
              onConfirm={() => void run(() => api.rejectRuleProposal(p.id, p.decision_state, reason.trim()))}>{t("Reject")}</ConfirmButton>
          </div>
          <details className="proposal-correct">
            <summary>{t("Correct the rule (as a record)")}</summary>
            <textarea className="mono" rows={12} spellCheck={false} value={json} onChange={(e) => setJson(e.target.value)} />
            <button type="button" className="secondary" disabled={busy}
              onClick={() => { let rule: unknown; try { rule = JSON.parse(json); } catch { setError({ text: t("The record is not valid JSON."), problems: [] }); return; }
                void run(() => api.correctRuleProposal(p.id, p.decision_state, rule, confirmed)); }}>
              {t("Save the correction as a draft rule")}
            </button>
          </details>
        </div>
      ) : (
        <p className="registry-line"><Mark table={DECISION} value={p.state} />
          <span className="muted small">{p.decided_by ? t("by {{who}}, {{when}}", { who: p.decided_by, when: when(p.decided_at) }) : ""}
            {p.rule_ref ? ` · ${t("draft rule {{ref}}", { ref: p.rule_ref })}` : ""}{p.reason ? ` · ${p.reason}` : ""}</span>
        </p>
      )}
      {error ? (error.problems.length ? <div role="alert"><p className="error-text">{t("Not saved:")}</p><SaidLines items={error.problems} /></div>
        : <p className="notice error" role="alert">{error.text}</p>) : null}
    </div>
  );
}

