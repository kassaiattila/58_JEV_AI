import { useEffect, useRef, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR } from "../api";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { reasonText } from "../labels";
import { elementKey, type Citation, type NativeCitation, type NativeCorrectionRequest, type NativeFact, type NativeItemResult, type NativeSourcePage } from "../native";
import { clearDraft, draftKey, getDraft, isDirty, rebaseDraft, setNativeCitationEdit, setNativeField, setNativeSources, settleNativeDraft, useDraft, type Draft } from "./drafts";
import { locatorText } from "./NativeSourceViewer";
import { useResolve } from "./useResolve";
import { nativeStateLabel } from "./nativeLabels";

/** The correction endpoint replaces its maps: retain every previously saved override. */
export function nativeSaveBody(result: NativeItemResult, draft: Draft | undefined, only?: string): NativeCorrectionRequest {
  if (!result.result_version) throw new Error("No published result");
  const pick = <T,>(values: Record<string, T> | undefined): Record<string, T> => Object.fromEntries(Object.entries(values ?? {}).filter(([id]) => !only || id === only));
  const values = { ...result.correction.fields, ...pick(draft?.nativeValues) };
  const native_sources = { ...result.correction.native_sources, ...pick(draft?.nativeSources) };
  // A source-only correction must explicitly name the value to which its citations apply.
  for (const id of Object.keys(native_sources)) if (!Object.hasOwn(values, id)) {
    const fact = result.native_facts.find((candidate) => candidate.fact_id === id);
    if (!fact) throw new Error("Unknown native fact identifier");
    values[id] = fact.effective_value;
  }
  return { kind: "native", values, native_sources,
    expected_revision: draft?.baseRevision ?? result.correction.revision, expected_result_version: draft?.baseResultVersion ?? result.result_version,
    ...(only ? { confirm: [only] } : {}) };
}

export function NativeFactPanel({ result, source, selected, readOnly, onChanged, onCitation }: {
  result: NativeItemResult; source: NativeSourcePage | null; selected: string | null; readOnly: boolean;
  onChanged: () => void; onCitation: (c: NativeCitation) => void;
}) {
  useLocale();
  const actor = useActor();
  const key = draftKey(result.run_id, result.item_id);
  const draft = useDraft(key);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const conflictResult = useRef<NativeItemResult | null>(null);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const resolve = useResolve(onChanged);
  const differentResult = Boolean(draft && draft.baseResultVersion !== result.result_version);
  const revisionChanged = Boolean(draft && draft.baseRevision !== result.correction.revision);
  const disabled = readOnly || !result.result_ready || differentResult || revisionChanged || conflict || busy;
  const hasSave = Boolean(Object.keys(draft?.nativeValues ?? {}).length || Object.keys(draft?.nativeSources ?? {}).length);
  async function save(only?: string) {
    if (disabled || saving.current || (!only && !hasSave)) return;
    if (!getActor().trim()) { setError(t(NO_ACTOR)); return; }
    saving.current = true; setBusy(true); setError(null);
    const current = getDraft(key);
    const sent = only && current ? { ...current, nativeValues: Object.fromEntries(Object.entries(current.nativeValues ?? {}).filter(([id]) => id === only)),
      nativeSources: Object.fromEntries(Object.entries(current.nativeSources ?? {}).filter(([id]) => id === only)) } : current;
    try {
      const saved = await api.saveNativeCorrection(result.run_id, result.item_id, nativeSaveBody(result, current, only));
      settleNativeDraft(key, sent, saved.correction.revision, result.result_version!);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) { conflictResult.current = result; setConflict(true); onChanged(); }
      setError(e instanceof Error ? e.message : String(e));
    } finally { saving.current = false; setBusy(false); }
  }
  return <section className="native-facts" aria-label={t("Native facts")} onKeyDown={(e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); if (!e.repeat) void save(); }
  }}>
    <h2>{t("Native facts")}</h2>
    <div className="native-summary">
      <p>{t("Reading coverage")}: <strong>{nativeStateLabel(result.reading.status)}</strong> · {t("Acquisition")}: {nativeStateLabel(result.reading.acquisition_status)}</p>
      <p>{t("Interpretation")}: <strong>{nativeStateLabel(result.interpretation_outcome.status)}</strong>{result.interpretation_outcome.reason ? ` · ${result.interpretation_outcome.reason}` : ""}</p>
      {result.interpretation ? <p>{result.interpretation.provider} · {result.interpretation.model} · <strong>{result.interpretation.execution === "synthetic_test" ? t("Synthetic test execution") : result.interpretation.execution === "saved_response" ? t("Saved response reused") : t("Live provider execution")}</strong></p> : null}
      <p className="notice small">{t("Reading coverage, extracted claims and human correctness are separate. Review each value and its source before approval.")}</p>
      {[...result.reading.results.flatMap((r) => r.issues), ...(source?.occurrences.flatMap((o) => o.issues) ?? [])].map((issue, i) =>
        <p key={i} className="notice small">{issue.code}: {issue.message}{issue.element_id ? ` · ${issue.element_id}` : ""}</p>)}
      {(result.interpretation?.gaps ?? []).map((gap, i) => <p className="notice" key={i}>{t("Extraction gap")}: {gap}</p>)}
    </div>
    {readOnly ? <p className="notice">{t("This run is approved; corrections are locked.")}</p> : null}
    {differentResult ? <div className="notice error" role="alert"><p>{t("This draft belongs to an earlier result. Your text is retained below; review it against the new source before discarding and entering a new correction.")}</p>
      <pre>{JSON.stringify({ values: draft?.nativeValues, sources: draft?.nativeSources, citationEdits: draft?.nativeCitationEdits }, null, 2)}</pre></div> : null}
    {(conflict || revisionChanged) && !differentResult ? <div className="notice" role="alert"><p>{t("The saved correction changed. Your draft is retained. Compare it with the refreshed machine and saved values before continuing.")}</p>
      <button type="button" disabled={conflict && conflictResult.current === result} onClick={() => { rebaseDraft(key, result.correction.revision); setConflict(false); setError(null); }}>{t("I reviewed the refreshed correction")}</button></div> : null}
    {error || resolve.error ? <p className="notice error" role="alert">{error ?? resolve.error}</p> : null}
    {Object.keys(draft?.nativeCitationEdits ?? {}).length ? <p className="notice small">{t("Unchecked citation text is kept in your draft. Check and attach it before saving its source.")}</p> : null}
    <div className="native-actions"><button type="button" className="primary" disabled={disabled || !hasSave} onClick={() => void save()}>{busy ? t("Saving…") : t("Save corrections")}</button>
      <button type="button" disabled={!isDirty(draft) || busy} onClick={() => clearDraft(key)}>{t("Discard draft")}</button>
      <button type="button" disabled={busy} onClick={onChanged}>{t("Reload result")}</button></div>
    {!result.native_facts.length ? <p className="notice">{result.result_ready ? t("No valid native facts were published. Review the reading and interpretation outcomes.") : t("No native result has been published yet.")}</p> : null}
    {result.native_facts.map((fact) => <NativeFactEditor key={fact.fact_id} fact={fact} result={result} draft={draft} source={source} selected={selected}
      disabled={disabled} onConfirm={() => void save(fact.fact_id)} onCitation={onCitation} onError={setError} />)}
    <h3>{t("Open review reasons")}</h3>
    {result.open_reasons.map((reason) => <div key={reason.id} className="notice"><p>{reasonText(reason.reason)}</p>
      <button type="button" disabled={readOnly || busy || resolve.pending !== null || !actor.trim()} onClick={() => void resolve.resolve(reason)}>{t("Mark resolved")}</button></div>)}
    {result.earlier_open_reasons.length ? <details><summary>{t("Earlier review reasons")}</summary>{result.earlier_open_reasons.map((r) => <p key={r.id}>{reasonText(r.reason)}</p>)}</details> : null}
  </section>;
}

function NativeFactEditor({ fact, result, draft, source, selected, disabled, onConfirm, onCitation, onError }: {
  fact: NativeFact; result: NativeItemResult; draft: Draft | undefined; source: NativeSourcePage | null; selected: string | null;
  disabled: boolean; onConfirm: () => void; onCitation: (c: NativeCitation) => void; onError: (s: string | null) => void;
}) {
  const key = draftKey(result.run_id, result.item_id);
  const changed = Object.hasOwn(draft?.nativeValues ?? {}, fact.fact_id);
  const value = changed ? draft!.nativeValues![fact.fact_id] : fact.effective_value;
  const citations = draft?.nativeSources?.[fact.fact_id] ?? fact.native_citations;
  const [validating, setValidating] = useState(false);
  const [sourceEditing, setSourceEditing] = useState(false);
  const verifying = useRef(false);
  const context = useRef({ version: result.result_version, mounted: true });
  context.current.version = result.result_version;
  useEffect(() => { context.current.mounted = true; return () => { context.current.mounted = false; }; }, []);
  const edit = draft?.nativeCitationEdits?.[fact.fact_id];
  const chosen = edit?.element || selected || "";
  const quote = edit?.quote ?? "";
  const updateEdit = (element: string, quote: string) => setNativeCitationEdit(key, result.correction.revision, result.result_version!, fact.fact_id, { element, quote });
  const updateSources = (next: Citation[]) => setNativeSources(key, result.correction.revision, result.result_version!, fact.fact_id,
    next.map(({ occurrence_id, element_id, quote }) => ({ occurrence_id, element_id, quote })));
  async function addCitation() {
    if (!source || !result.result_version || verifying.current || disabled) return;
    const target = source.elements.find((e) => elementKey(e) === chosen);
    if (!target || !quote.length) return;
    const before = getDraft(key);
    const editAtRequest = before?.nativeCitationEdits?.[fact.fact_id];
    if (!editAtRequest || editAtRequest.element !== chosen || editAtRequest.quote !== quote) return;
    // A discarded or replaced edit is a different request, even if its text is identical.
    const stillCurrent = () => context.current.mounted && context.current.version === result.result_version
      && getDraft(key)?.nativeCitationEdits?.[fact.fact_id] === editAtRequest;
    verifying.current = true; setValidating(true); onError(null);
    const candidate = { occurrence_id: target.occurrence_id, element_id: target.element_id, quote };
    const valueAtRequest = Object.hasOwn(before?.nativeValues ?? {}, fact.fact_id) ? before!.nativeValues![fact.fact_id] : fact.effective_value;
    try {
      const resolved = await api.resolveNativeCitations(result.run_id, result.item_id, result.result_version, [candidate]);
      if (!stillCurrent()) return;
      if (resolved.result_version !== result.result_version || resolved.citations.length !== 1) throw new Error(t("The source citation was not verified."));
      const now = getDraft(key);
      const valueNow = Object.hasOwn(now?.nativeValues ?? {}, fact.fact_id) ? now!.nativeValues![fact.fact_id] : fact.effective_value;
      if (valueAtRequest !== valueNow) throw new Error(t("The value changed while its source was checked. Check the citation again."));
      const current = now?.nativeSources?.[fact.fact_id] ?? result.correction.native_sources[fact.fact_id] ?? fact.native_citations;
      updateSources([...current.map(({ occurrence_id, element_id, quote }) => ({ occurrence_id, element_id, quote })), candidate]);
      onCitation(resolved.citations[0]);
      const latestEdit = getDraft(key)?.nativeCitationEdits?.[fact.fact_id];
      if (latestEdit?.element === chosen && latestEdit.quote === quote) setNativeCitationEdit(key, result.correction.revision, result.result_version!, fact.fact_id, null);
    } catch (e) { if (stillCurrent()) onError(e instanceof Error ? e.message : String(e)); }
    finally { verifying.current = false; if (context.current.mounted) setValidating(false); }
  }
  async function showOriginal(c: Citation) {
    if (!result.result_version || verifying.current) return;
    verifying.current = true; setValidating(true); onError(null);
    try {
      const resolved = await api.resolveNativeCitations(result.run_id, result.item_id, result.result_version, [c]);
      if (context.current.mounted && context.current.version === resolved.result_version && resolved.citations[0]) onCitation(resolved.citations[0]);
    } catch (e) { if (context.current.mounted) onError(e instanceof Error ? e.message : String(e)); }
    finally { verifying.current = false; if (context.current.mounted) setValidating(false); }
  }
  const proposal = fact.proposal;
  return <article className="native-fact" data-fact-id={fact.fact_id}>
    <h3>{proposal.entity} · {proposal.property}</h3>
    <small className="muted">{fact.fact_id}</small>
    <dl><dt>{t("Machine proposal")}</dt><dd>{proposal.value === null ? t("No value") : proposal.value === "" ? t("Empty text") : proposal.value}</dd>
      <dt>{t("Saved effective value")}</dt><dd>{fact.effective_value === null ? t("No value") : fact.effective_value === "" ? t("Empty text") : fact.effective_value}</dd>
      <dt>{t("Claim state")}</dt><dd>{nativeStateLabel(proposal.state)}</dd><dt>{t("Literal grounding")}</dt><dd>{nativeStateLabel(fact.grounding)}</dd>
      <dt>{t("Semantic support")}</dt><dd>{fact.semantic_support ?? t("Not measured")}</dd>
      <dt>{t("Selection confidence")}</dt><dd>{fact.selection_confidence ?? t("Not measured")}</dd>
      {proposal.unit !== null ? <><dt>{t("Unit")}</dt><dd>{proposal.unit}</dd></> : null}
      {proposal.role !== null ? <><dt>{t("Role")}</dt><dd>{proposal.role}</dd></> : null}
      {proposal.related_entity !== null ? <><dt>{t("Related entity")}</dt><dd>{proposal.related_entity}</dd></> : null}</dl>
    {fact.reasons.map((reason, i) => <p className="notice small" key={i}>{reason}</p>)}
    <details><summary>{t("Original machine citations")}</summary>{proposal.citations.map((c, i) => <div key={i}><blockquote>{c.quote}<small> · {c.occurrence_id} / {c.element_id}</small></blockquote>
      <button type="button" disabled={validating || !source} onClick={() => void showOriginal(c)}>{t("Show original source")}</button></div>)}</details>
    <label className="block">{t("Effective value")}<textarea aria-label={t("Effective value for {{property}} ({{id}})", { property: proposal.property, id: fact.fact_id })}
      value={value ?? ""} disabled={disabled || value === null} rows={2} onChange={(e) => setNativeField(key, result.correction.revision, result.result_version!, fact.fact_id, e.target.value)} /></label>
    <label className="check"><input type="checkbox" checked={value === null} disabled={disabled} onChange={(e) => setNativeField(key, result.correction.revision, result.result_version!, fact.fact_id, e.target.checked ? null : "")} />{t("No value")}</label>
    <p className="small">{fact.confirmed && !changed && !Object.hasOwn(draft?.nativeSources ?? {}, fact.fact_id) ? t("Human confirmed") : t("Human review pending")}</p>
    <h4>{t("Effective source citations")}</h4>
    {!citations.length ? <p className="notice small">{t("No source citation is attached to this effective value.")}</p> : null}
    {citations.map((c, i) => <div className="native-citation" key={`${c.occurrence_id}:${c.element_id}:${i}`}><blockquote>{c.quote}</blockquote>
      {"locator" in c ? <><button type="button" onClick={() => onCitation(c as NativeCitation)}>{locatorText((c as NativeCitation).quote_span ?? (c as NativeCitation).locator)}</button>
        {(c as NativeCitation).quote_match_count > 1 ? <p className="notice small">{t("This quote occurs {{n}} times in the element; no unique text span is claimed.", { n: (c as NativeCitation).quote_match_count })}</p> : null}</> : <small>{c.occurrence_id} / {c.element_id} · {t("Draft source")}</small>}
      <button type="button" disabled={disabled} onClick={() => updateSources(citations.filter((_, n) => n !== i))}>{t("Remove citation")}</button></div>)}
    <details onToggle={(e) => setSourceEditing(e.currentTarget.open)}><summary>{t("Edit source citations")}</summary>
      {sourceEditing ? <>
      <label className="block">{t("Source element")}<select value={chosen} disabled={disabled || !source} onChange={(e) => updateEdit(e.target.value, quote)}>
        <option value="">{t("Select a saved source element")}</option>{source?.elements.map((e) => <option value={elementKey(e)} key={elementKey(e)}>{e.occurrence_id} · {locatorText(e.locator)} · {e.element_id}</option>)}</select></label>
      <label className="block">{t("Exact source quote")}<textarea value={quote} disabled={disabled} onChange={(e) => updateEdit(chosen, e.target.value)} rows={3} /></label>
      <button type="button" disabled={disabled || validating || !source || !chosen || !quote} onClick={() => void addCitation()}>{validating ? t("Checking source…") : t("Check and attach source")}</button>
      </> : null}
    </details>
    <button type="button" disabled={disabled || validating || Boolean(edit)} onClick={onConfirm}>{t("Confirm this fact")}</button>
  </article>;
}
