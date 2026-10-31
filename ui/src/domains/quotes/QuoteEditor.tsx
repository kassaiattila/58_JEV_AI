// 192 (plan F-quote-package B5; DECISIONS 191, 192): the quote composed beside its request, and its approval. The owner
// asked for a page where the request and its data can be seen and the quote changed on their basis. On the left the
// request: its fields and its numbered requested items. On the right the quote: its header, its lines and its totals.
// Every change is saved at once (the page sends the draft with the state it read; a stale page is refused and
// reloaded); code prices every line. A line says what it was asked for (the requested item's number and words), its
// state mark, and in words what still holds the approval; a line the proposal marked "to check" is confirmed or changed
// by a person (the owner's choice). The approval is the shared element of a logic pack's own versions. 196: the quote's
// documents' language is chosen with its header; the draft and each approved version download as a Word document (the
// built-in template, or the package's own one chosen beside the download). 231 (stage D0, D0-g): the shared save
// behaviour (`components/editing.ts`): the save line says changed, saving, saved, not saved or not known; a save refused
// because someone else saved meanwhile keeps the person's changes beside the version saved now, field by field, to keep
// (over theirs) or drop; the unsaved work stays in this page's memory (another case and back), never in the browser's
// storage, and the quote is not approved while it has any.
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { compare, merge, saveState, updateWork, useHasWork, useWork, workOf } from "../../components/editing";
import { SaveConflict, SaveLine, SaveUnknown } from "../../components/SaveConflict";
import type { QuoteApproved, QuoteDraftBlockerCode, QuoteDraftIn, QuoteDraftLine, QuoteDraftView, QuoteLineIn, QuoteRequest, QuoteView } from "./api";
import { ApprovalPanel, EarlierVersions } from "../../components/ApprovalPanel";
import { ConfirmButton } from "../../components/ConfirmButton";
import { Icon } from "../../components/Icon";
import { Picker, type PickerOption } from "../../components/Picker";
import { TemplateChoice } from "../../components/TemplateChoice";
import { errorText, useAction } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { numText, when } from "../../labels";
import { routeHash } from "../../route";

/** 263 (F2): the quote's parts are shown on an IT quote case's page: its links lead to the case's own tabs (the
 *  it_quote pack's `quote` and `approval`), not to a work package's stage, which opened the case's first tab. */
const caseTab = (caseId: string, tab: "quote" | "approval") => routeHash({ view: "cases", caseId, tab });
import { QuoteLetterCard } from "./QuoteLetter";
import { amountText, quoteFieldLabel as fieldLabel } from "./quoteStatus";

export const QUOTE_LINE_BLOCKER: Record<QuoteDraftBlockerCode, string> = {
  "quote:line_no_item": "No item: choose a price list item, or give a price of your own with a note",
  "quote:line_no_description": "A line of your own needs a description",
  "quote:line_unknown_item": "The item is not in this price list version: choose another",
  "quote:line_no_quantity": "No quantity: give one above zero",
  "quote:line_unchecked": "To check: confirm the proposed item or choose another",
  "quote:line_note_missing": "A price of your own or a line outside the list needs a note",
  "quote:no_lines": "The quote has no line",
  "quote:no_customer": "The quote names no customer: fill in the customer",
};

// a proposed line's mark (DESIGN.md §4): sure green, to check a person's turn (orange), not listed amber, failed red
const LINE_MARK: Record<string, { cls: string; label: string }> = {
  sure: { cls: "s-done", label: "sure" }, check: { cls: "s-review", label: "to check" },
  not_listed: { cls: "s-warn", label: "not in the price list" }, failed: { cls: "s-failed", label: "the match failed" },
};
const OWN = "__own__"; // the picker's choice of a line outside the price list
const EDITED = ["quantity", "unit_price", "discount_percent", "description", "unit", "note"] as const;
type Edited = (typeof EDITED)[number];
/** D0-g: what a refused save's comparison calls a line's fields and the quote's own */
const LINE_FIELD: Record<string, string> = { sku: "Item", quantity: "Quantity", unit: "Unit", unit_price: "Unit price",
  discount_percent: "Discount %", description: "Description", note: "Note", checked: "Checked" };
const TOP_FIELD: Record<string, string> = { price_list: "Price list", version: "Price list version",
  language: "Language of the quote's documents" };
type Line = QuoteDraftView["lines"][number];

const quantityText = (v: unknown) => (v === null || v === undefined || v === "" ? "" : numText(v, 4));
const requestedText = (r: QuoteDraftLine["requested"]) =>
  r ? [r.description, [quantityText(r.quantity), r.unit].filter(Boolean).join(" ")].filter(Boolean).join(" · ") : "";
const needsNote = (l: QuoteLineIn) => l.sku === null || l.unit_price !== null || l.discount_percent !== null;
// 196: each language by its own name, as the interface's language switch names them
const LANGUAGE_NAMES: Record<string, string> = { hu: "Magyar", en: "English" };

/** What a line shows while it has no price or discount of a person's own: the list's price, the rule's discount. */
type Shown = Record<string, { unit_price: string; discount_percent: string }>;
type Edits = Record<string, Partial<Record<Edited, string>>>;

/** D0-g: a save the service refused (someone else saved meanwhile) or whose outcome is not known: what it was sent on
 *  (`state`, `base`), what it sent (`mine`), and the typed values it carried. */
interface Failed { kind: "conflict" | "unknown"; state: number; base: QuoteDraftIn; mine: QuoteDraftIn; edits: Edits; header: Record<string, string> }
/** D0-g: a quote's unsaved work in this page's memory: typed values not saved yet, a failed save, saves under way;
 *  D-a: and the version the typing started from (`base`), so a newer one met later is compared with it. */
interface QuoteWork { edits: Edits; header: Record<string, string>; failed: Failed | null; saving: number;
  base?: { state: number; draft: QuoteDraftIn } | null }
const NO_WORK: QuoteWork = { edits: {}, header: {}, failed: null, saving: 0, base: null };
const typed = (w: QuoteWork) => Object.keys(w.edits).length > 0 || Object.keys(w.header).length > 0;
const idle = (w: QuoteWork) => !w.saving && !w.failed && !Object.keys(w.edits).length && !Object.keys(w.header).length;
/** D0-g: where a case step's quote keeps its unsaved work */
export const quoteWorkKey = (wpId: string, step?: string | null) => `quote:${wpId}:${step ?? ""}`;

/** What was typed and not in `sent` (a save carried the rest). */
function leftEdits(now: Edits, sentEdits: Edits): Edits {
  const left: Edits = {};
  for (const [id, fields] of Object.entries(now)) {
    const kept = Object.fromEntries(Object.entries(fields).filter(([k, v]) => sentEdits[id]?.[k as Edited] !== v));
    if (Object.keys(kept).length) left[id] = kept;
  }
  return left;
}
const leftHeader = (now: Record<string, string>, sentHeader: Record<string, string>) =>
  Object.fromEntries(Object.entries(now).filter(([k, v]) => sentHeader[k] !== v));

/** D-a: the work on the version `view` holds now (the base of what is still typed; none when nothing is). */
function rebased(w: QuoteWork, view: QuoteDraftView): QuoteWork {
  return { ...w, base: typed(w) && view.draft ? { state: view.state, draft: sent(view.draft, {}, {}, {}) } : null };
}

function sent(draft: QuoteDraftIn, edits: Edits, header: Record<string, string>, shown: Shown): QuoteDraftIn {
  return {
    price_list: draft.price_list, version: draft.version, language: draft.language ?? null,
    header: { ...draft.header, ...Object.fromEntries(Object.entries(header).map(([k, v]) => [k, v.trim() || null])) },
    lines: draft.lines.map((l) => {
      const e = (l.id ? edits[l.id] : undefined) ?? {};
      const pick = (k: Edited) => {
        if (!(k in e)) return l[k];
        const text = e[k]!.trim();
        const listed = (k === "unit_price" || k === "discount_percent") && text !== "" && l.id !== null && text === shown[l.id]?.[k];
        return listed ? null : text || null; // the list's own price or the rule's discount typed again: none of a person's own
      };
      return {
        id: l.id, sku: l.sku, checked: l.checked, quantity: pick("quantity"), unit_price: pick("unit_price"),
        discount_percent: pick("discount_percent"), description: pick("description"), unit: pick("unit"), note: pick("note"),
      };
    }),
  };
}

/** The Quote stage once a draft is there: the request beside the quote. */
export function QuoteCompose({ wpId, view, onChanged }: { wpId: string; view: QuoteView; onChanged: () => void }) {
  useLocale();
  const [hovered, setHovered] = useState<number | null>(null);
  return (
    <div className="quote-compose">
      <RequestSide view={view} hovered={hovered} />
      <DraftEditor wpId={wpId} view={view} onChanged={onChanged} onHover={setHovered} />
    </div>
  );
}

function RequestSide({ view, hovered }: { view: QuoteView; hovered: number | null }) {
  useLocale();
  const r: QuoteRequest | null = view.request;
  return (
    <aside className="card quote-side" aria-label={t("The request")}>
      <h3>{t("The request")}</h3>
      {view.source ? (
        <a className="small" href={`#/workpackages/${encodeURIComponent(view.source.workpackage_id)}`}>
          {t("in {{name}}", { name: view.source.workpackage_name ?? view.source.workpackage_id })}
        </a>
      ) : null}
      {r ? (
        <>
          <p className="small quote-side-title">{r.title || t("(no subject)")}</p>
          <p className="small muted tnum">{[r.sender, r.received_at ? when(r.received_at) : null].filter(Boolean).join(" · ")}</p>
          {/* the requested items first: they are what the lines are checked against */}
          <h4>{fieldLabel("requested_items")}</h4>
          <ol className="quote-asked">
            {r.items.map((i, n) => (
              <li key={n} className={hovered === n ? "hot" : ""}>
                <span className="quote-ref" aria-hidden="true">{n + 1}</span>
                <span>{i.description ?? "—"}</span>
                <span className="muted tnum">{[quantityText(i.quantity), i.unit].filter(Boolean).join(" ")}</span>
              </li>
            ))}
          </ol>
          <h4>{t("The request's data")}</h4>
          <dl className="quote-facts">
            {Object.keys(r.fields).map((f) => (
              <div key={f}><dt>{fieldLabel(f)}</dt><dd className={r.fields[f] ? "" : "muted"}>{r.fields[f] ? String(r.fields[f]) : "—"}</dd></div>
            ))}
          </dl>
        </>
      ) : <p className="small muted">{t("The request can no longer be read; the quote's lines stay as they are.")}</p>}
    </aside>
  );
}

function DraftEditor({ wpId, view, onChanged, onHover }: {
  wpId: string; view: QuoteView; onChanged: () => void; onHover: (row: number | null) => void;
}) {
  useLocale();
  const [dv, setDv] = useState<QuoteDraftView>(view.draft);
  // D0-g: the unsaved work lives in this page's memory by the case's step, not in the editor (a save finishing after
  // the editor closed still settles it, and the editor opened again shows it)
  const key = quoteWorkKey(wpId, view.draft.step);
  const work = useWork<QuoteWork>(key) ?? NO_WORK;
  const { edits, header, failed } = work;
  const saving = work.saving > 0;
  const update = (fn: (w: QuoteWork) => QuoteWork) => updateWork(key, NO_WORK, idle, fn);
  // D-a: the first typing records the version it starts from
  const started = (w: QuoteWork): QuoteWork => (w.base || !typed(w) || !answered.current.draft ? w
    : { ...w, base: { state: answered.current.state, draft: sent(answered.current.draft, {}, {}, latest.current.shown) } });
  const setEdits = (fn: (e: Edits) => Edits) => update((w) => started({ ...w, edits: fn(w.edits) }));
  const setHeader = (fn: (h: Record<string, string>) => Record<string, string>) => update((w) => started({ ...w, header: fn(w.header) }));
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown: Shown = Object.fromEntries(dv.lines.map((l) => [l.id, {
    unit_price: l.priced?.list_price ? amountText(l.priced.list_price, dv.currency) : "",
    discount_percent: l.priced && l.priced.discount_from === "rule" ? numText(l.priced.discount_percent, 4) : "",
  }]));
  const latest = useRef({ shown });
  latest.current = { shown };
  // the saves go one after another, each on the state the service last answered with (a second change made while
  // one is being saved would otherwise be refused as made on a stale page)
  const answered = useRef(dv);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const adopt = (next: QuoteDraftView) => { answered.current = next; setDv(next); };
  // a newer state from the package's page (another person's change, a reopening) replaces the shown one
  useEffect(() => {
    if (!saving && view.draft.state >= answered.current.state) adopt(view.draft);
  }, [view.draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const draft = dv.draft!;
  const currency = dv.currency;
  const items = dv.price_list?.items ?? [];
  const byLine = useMemo(() => {
    const out: Record<string, QuoteDraftBlockerCode[]> = {};
    for (const b of dv.blockers) if (b.line) (out[b.line] ??= []).push(b.code);
    return out;
  }, [dv.blockers]);
  const general = dv.blockers.filter((b) => !b.line);
  const locked = dv.approval.active;

  function save(change?: (d: QuoteDraftIn) => QuoteDraftIn): Promise<void> {
    queue.current = queue.current.then(() => saveNow(change));
    return queue.current;
  }
  async function saveNow(change?: (d: QuoteDraftIn) => QuoteDraftIn) {
    const cur = answered.current;
    const w = workOf<QuoteWork>(key) ?? NO_WORK;
    const s = latest.current.shown;
    if (!cur.draft) return;
    if (w.failed) {  // D0-g: while a failed save waits for the person, a change joins their own; nothing is sent
      if (change) update((x) => (x.failed ? { ...x, failed: { ...x.failed, mine: change(x.failed.mine) } } : x));
      return;
    }
    const base = sent(cur.draft, {}, {}, s);
    const body = (change ?? ((d) => d))(sent(cur.draft, w.edits, w.header, s));
    update((x) => ({ ...x, saving: x.saving + 1 }));
    setError(null);
    try {
      const next = await api.saveQuoteDraft(wpId, body, cur.state, cur.step);  // D0-b: the composition step's draft
      adopt(next);
      // what was sent is saved; what was typed since stays to be saved, on the version saved now
      update((x) => rebased({ ...x, edits: leftEdits(x.edits, w.edits), header: leftHeader(x.header, w.header) }, next));
      setSavedAt(new Date().toISOString());
      onChanged();
    } catch (err) {
      // D0-g: refused (someone else saved meanwhile) or not known (the connection broke): the person's changes stay
      const kind = err instanceof ApiError && err.status === 409 ? "conflict" : err instanceof ApiError && err.status === 0 ? "unknown" : null;
      if (kind) {
        update((x) => ({ ...x, failed: { kind, state: cur.state, base, mine: body, edits: w.edits, header: w.header } }));
        if (kind === "conflict") onChanged();  // the version saved now, to compare with
      } else setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      update((x) => ({ ...x, saving: Math.max(0, x.saving - 1) }));
    }
  }
  // D0-g: after a refused save, the version saved now (read again) beside the person's changes
  const theirs = failed?.kind === "conflict" && dv.state > failed.state && dv.draft ? sent(dv.draft, {}, {}, shown) : null;
  const conflicts = failed && theirs ? compare(failed.base, failed.mine, theirs) : null;
  // D-a: a change on a row they removed cannot be applied: only the person settles it
  const settled = theirs !== null && failed !== null && !(conflicts ?? []).some((c) => c.gone)
    && JSON.stringify(merge(theirs, failed.base, failed.mine)) === JSON.stringify(theirs);
  useEffect(() => {
    // what the refused save sent is in the version saved now already (an earlier try went through): nothing to keep
    if (settled) update((x) => (x.failed ? rebased({ ...x, failed: null, edits: leftEdits(x.edits, x.failed.edits), header: leftHeader(x.header, x.failed.header) }, dv) : x));
  }, [settled]); // eslint-disable-line react-hooks/exhaustive-deps
  // D-a: a newer version met while typing (another person's save, the editor opened again): where they changed what the
  // person changed, the person compares; elsewhere the typing goes on over the newer version
  useEffect(() => {
    const w = workOf<QuoteWork>(key);
    if (!w || !w.base || w.failed || w.saving || !typed(w) || !dv.draft || dv.state <= w.base.state) return;
    const mine = sent(w.base.draft, w.edits, w.header, shown);
    const now = sent(dv.draft, {}, {}, shown);
    if (compare(w.base.draft, mine, now).some((c) => c.both)) {
      update((x) => ({ ...x, failed: { kind: "conflict", state: w.base!.state, base: w.base!.draft, mine, edits: w.edits, header: w.header } }));
    } else update((x) => rebased(x, dv));
  }, [dv.state, work.base?.state, failed, saving]); // eslint-disable-line react-hooks/exhaustive-deps
  /** My changes over the version saved now (or, when it is not known whether mine went through, over the one shown). */
  const keepMine = () => {
    const f = workOf<QuoteWork>(key)?.failed;
    const now = theirs ?? (answered.current.draft ? sent(answered.current.draft, {}, {}, shown) : null);
    if (!f || !now) return;
    const mine = merge(now, f.base, f.mine);
    update((x) => rebased({ ...x, failed: null }, answered.current));  // D-a: kept over the version shown now
    void save(() => { const w = workOf<QuoteWork>(key) ?? NO_WORK; return sent(mine, w.edits, w.header, latest.current.shown); });
  };
  const takeTheirs = () => update((x) => ({ ...x, failed: null, edits: {}, header: {}, base: null }));
  const changeLabel = (path: string[]) => {
    const [top, at, field] = path;
    if (top === "header") return at === "note" ? t("Note on the quote") : fieldLabel(at);
    if (top === "lines") {
      if (at.startsWith("+")) return t("A new line");
      const n = dv.lines.findIndex((l) => `#${l.id}` === at) + 1;
      const line = n ? t("Line {{n}}", { n }) : t("A line removed by them");
      return field ? `${line}: ${t(LINE_FIELD[field] ?? field)}` : line;
    }
    return t(TOP_FIELD[top] ?? top);
  };
  const changeValue = (path: string[], v: unknown) => {
    if (v === undefined) return <span className="muted">{t("removed")}</span>;
    if (path[0] === "lines" && path.length === 2) {
      if (v === true) return t("the line");
      const row = v as QuoteLineIn;
      return row.description ?? items.find((i) => i.sku === row.sku)?.name ?? row.sku ?? "—";
    }
    if (typeof v === "boolean") return v ? t("confirmed") : t("not confirmed");
    if (path[0] === "lines" && path[2] === "sku") return items.find((i) => i.sku === v)?.name ?? (v === null ? t("A line of my own (outside the price list)") : String(v));
    return v === null || v === "" ? "—" : String(v);
  };
  const editLine = (id: string, field: Edited, value: string) => setEdits((e) => ({ ...e, [id]: { ...e[id], [field]: value } }));
  const commitLine = (id: string) => { if (workOf<QuoteWork>(key)?.edits[id]) void save(); };
  const withLine = (id: string, patch: Partial<QuoteLineIn>) => void save((d) => ({
    ...d, lines: d.lines.map((l) => (l.id === id ? { ...l, ...patch } : l)),
  }));

  if (locked) {
    return (
      <section className="card wide quote-draft" aria-label={t("The quote")}>
        <div className="card-head"><h3>{t("The quote")}</h3></div>
        {/* D0-g: changes kept on this page can no longer be saved once a version is approved */}
        {failed || Object.keys(edits).length || Object.keys(header).length ? (
          <div className="notice warn small" role="alert">
            <p>{t("The quote was approved before your changes were saved; they can no longer be saved to this version.")}</p>
            <ConfirmButton className="secondary small-btn" onConfirm={takeTheirs}>{t("Drop my changes")}</ConfirmButton>
          </div>
        ) : null}
        <p className="notice ok-box">
          {t("Approved: version {{n}}, by {{who}}, {{when}}.", { n: locked.version, who: locked.approved_by, when: when(locked.approved_at) })}{" "}
          <a href={caseTab(wpId, "approval")}>{t("To change it, reopen it in Approval.")}</a>
        </p>
        <p>
          <a className="secondary dl-btn small-btn" href={api.quoteVersionDocxUrl(wpId, locked.version)} download><Icon name="download" />
            {t("Download version {{n}} (Word)", { n: locked.version })}</a>
        </p>
        {dv.approved ? <QuoteDocument quote={dv.approved} /> : null}
      </section>
    );
  }
  const options = (line: Line): PickerOption[] => {
    const cand = new Set(line.candidates.filter((c) => c !== line.sku));
    const opt = (sku: string, group: string): PickerOption | null => {
      const i = items.find((x) => x.sku === sku);
      return i ? { value: i.sku, label: i.name, detail: `${i.sku} · ${amountText(i.unit_price, currency)} / ${i.unit}`, group } : null;
    };
    const near = [...cand].map((c) => opt(c, t("The proposal's other candidates"))).filter((o): o is PickerOption => o !== null);
    const rest = items.filter((i) => !cand.has(i.sku)).map((i) => opt(i.sku, t("Price list"))!);
    return [{ value: OWN, label: t("A line of my own (outside the price list)"), group: t("Outside the price list") }, ...near, ...rest];
  };
  const ready = dv.blockers.length === 0;
  const local = typed(work) || failed !== null;  // D-a: the head says ready only for what is saved
  const superseded = dv.warnings.find((w) => w.code === "quote:price_list_superseded");
  return (
    <section className="card wide quote-draft" aria-label={t("The quote")}>
      <div className="card-head">
        <div className="quote-draft-title">
          <h3>{t("The quote")}</h3>
          {local ? <span className="status s-review">{t("save the changes first")}</span>
            : ready ? <span className="status s-done">{t("ready to approve")}</span>
            : <span className="status s-review">{t("{{n}} thing(s) to settle before the approval", { n: dv.blockers.length })}</span>}
          <SaveLine state={saveState({ saving, failed: failed?.kind ?? null, savedAt,
            changed: Object.keys(edits).length > 0 || Object.keys(header).length > 0 })} savedAt={savedAt} idle={t("Every change is saved at once.")} />
        </div>
        {/* the page header's next step is the view's one solid action (approving once nothing holds it) */}
        <a className="secondary small-btn" href={caseTab(wpId, "approval")}>{t("To the approval")}</a>
      </div>

      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {failed?.kind === "conflict" ? <SaveConflict changes={settled ? [] : conflicts} label={changeLabel} value={changeValue}
        busy={saving} onKeepMine={keepMine} onTakeTheirs={takeTheirs} /> : null}
      {failed?.kind === "unknown" ? <SaveUnknown busy={saving} onAgain={keepMine} /> : null}
      {dv.warnings.length || dv.proposal_newer ? (
        <ul className="plain quote-warnings">
          {superseded ? (
            <li className="small">
              <span className="status long s-warn">{superseded.version
                ? t("The price list has a newer active version ({{n}}); the quote is priced from version {{m}}", { n: superseded.version, m: draft.version })
                : t("This price list version is no longer active")}</span>
              {superseded.version ? (
                <button type="button" className="secondary small-btn" disabled={saving}
                  onClick={() => void save((d) => ({ ...d, version: superseded.version! }))}>
                  {t("Price from version {{n}}", { n: superseded.version })}
                </button>
              ) : null}
            </li>
          ) : null}
          {dv.warnings.some((w) => w.code === "quote:request_changed")
            ? <li className="small"><span className="status long s-warn">{t("The request changed since the quote was started; its lines stay as they are")}</span></li> : null}
          {dv.proposal_newer ? (
            <li className="small">
              <span className="status s-warn">{t("A newer proposal is ready")}</span>
              <ConfirmButton className="secondary small-btn" disabled={saving}
                onConfirm={() => void api.startQuoteDraft(wpId, { source: "proposal", expected_state: dv.state, replace: true }, dv.step)
                  .then((next) => { adopt(next); update((w) => ({ ...w, edits: {}, header: {}, failed: null })); onChanged(); })
                  .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))}>
                {t("Replace the lines with the new proposal")}
              </ConfirmButton>
            </li>
          ) : null}
        </ul>
      ) : null}

      <details className="quote-head" open={!draft.header.customer_name}>
        <summary>
          <span className="quote-head-sum">
            {[draft.header.customer_name ?? t("no customer named"), draft.header.contact_name,
              draft.header.deadline ? t("deadline {{date}}", { date: draft.header.deadline }) : null].filter(Boolean).join(" · ")}
          </span>
          <span className="quote-head-open">{t("Change the quote's header")}</span>
        </summary>
      <div className="quote-head-fields">
        {Object.keys(draft.header).map((f) => (
          <label key={f} className={`block ${f === "note" ? "quote-note-field" : ""}`}>
            {f === "note" ? t("Note on the quote") : fieldLabel(f)}
            <input value={header[f] ?? draft.header[f] ?? ""} maxLength={2000}
              onChange={(e) => setHeader((h) => ({ ...h, [f]: e.target.value }))}
              onBlur={() => { if (f in (workOf<QuoteWork>(key)?.header ?? {})) void save(); }} />
          </label>
        ))}
        {/* 196: the language of the Word document and the reply letter, estimated from the request (a service
            older than 196 names none) */}
        {dv.languages?.length ? (
          <Picker label={t("Language of the quote's documents")} value={dv.language ?? dv.languages[0]} disabled={saving}
            options={dv.languages.map((l) => ({ value: l, label: LANGUAGE_NAMES[l] ?? l }))}
            onChange={(v) => void save((d) => ({ ...d, language: v }))} />
        ) : null}
      </div>
      </details>
      {general.length ? (
        <ul className="plain">
          {general.map((b) => <li key={b.code} className="small"><span className="status long s-review">{t(QUOTE_LINE_BLOCKER[b.code])}</span></li>)}
        </ul>
      ) : null}

      <div className="table-scroll">
        <table className="table compact quote-lines" aria-label={t("The quote's lines")}>
          <colgroup>
            <col className="c-ref" /><col className="c-item" /><col className="c-qty" /><col className="c-unit" />
            <col className="c-price" /><col className="c-disc" /><col className="c-net" /><col className="c-act" />
          </colgroup>
          <thead>
            <tr>
              <th aria-label={t("Requested item")}>#</th><th>{t("Item")}</th><th className="num">{t("Quantity")}</th>
              <th>{t("Unit")}</th><th className="num">{t("Unit price")}</th><th className="num">{t("Disc. %")}</th>
              <th className="num">{t("Net")}</th><th><span className="sr-only">{t("Actions")}</span></th>
            </tr>
          </thead>
          {dv.lines.length ? null : (
            <tbody><tr><td colSpan={8} className="muted small">{t("The quote has no line yet: add one below.")}</td></tr></tbody>
          )}
          {dv.lines.map((line) => {
            const e = edits[line.id] ?? {};
            const val = (k: Edited, shown: string) => (k in e ? e[k]! : shown);
            const p = line.priced;
            const own = line.sku === null;
            const issues = byLine[line.id] ?? [];
            // a line a person confirmed or chose is settled: its mark says by whom, in the done colour
            const mark = line.checked_by ? { cls: "s-done", label: t("checked by {{who}}", { who: line.checked_by }) }
              : line.mark ? { ...LINE_MARK[line.mark], label: t(LINE_MARK[line.mark].label) } : null;
            const unchecked = issues.includes("quote:line_unchecked");
            const noteShown = needsNote(line) || !!line.note || "note" in e;
            const field = (k: Edited, label: string, shown: string, extra?: { placeholder?: string; className?: string }) => (
              <input aria-label={label} className={extra?.className ?? "num-input"} value={val(k, shown)} placeholder={extra?.placeholder}
                inputMode={k === "description" || k === "unit" || k === "note" ? undefined : "decimal"} maxLength={k === "note" ? 2000 : 500}
                onChange={(ev) => editLine(line.id, k, ev.target.value)} onBlur={() => commitLine(line.id)}
                onKeyDown={(ev) => { if (ev.key === "Enter") (ev.target as HTMLInputElement).blur(); }} />
            );
            const n = dv.lines.indexOf(line) + 1;
            return (
              <tbody key={line.id} className={issues.length ? "quote-line open" : "quote-line"}
                onMouseEnter={() => onHover(line.row)} onMouseLeave={() => onHover(null)}>
                <tr>
                  <td>
                    {line.row !== null
                      ? <span className="quote-ref" title={t("Requested item {{n}}", { n: line.row + 1 })}>{line.row + 1}</span>
                      : <span className="quote-ref own" title={t("A line you added")}>+</span>}
                  </td>
                  <td>
                    <div className="quote-item-cell">
                      <Picker compact hideLabel label={t("Line {{n}}: item", { n })} value={own ? OWN : line.sku} options={options(line)}
                        selectedLabel={own ? t("A line of my own (outside the price list)") : p?.name}
                        onChange={(v) => withLine(line.id, v === OWN ? { sku: null } : { sku: v })} />
                      {own ? field("description", t("Line {{n}}: description", { n }), line.description ?? "",
                        { className: "text-input", placeholder: t("Description of the line") }) : null}
                      <span className="quote-line-meta">
                        {mark ? <span className={`status ${mark.cls}`}>{mark.label}</span> : null}
                        {unchecked ? (
                          <button type="button" className="secondary small-btn" disabled={saving}
                            title={t("The proposed item is the right one")} onClick={() => withLine(line.id, { checked: true })}>
                            <Icon name="check" />{t("Confirm the item")}
                          </button>
                        ) : null}
                        {!own ? <code className="mono">{line.sku}</code> : null}
                      </span>
                      {line.requested ? <span className="quote-asked-line muted">{t("Asked: {{what}}", { what: requestedText(line.requested) })}</span> : null}
                      {issues.filter((c) => c !== "quote:line_unchecked").map((c) => <span key={c} className="quote-issue">{t(QUOTE_LINE_BLOCKER[c])}</span>)}
                    </div>
                  </td>
                  <td className="num">{field("quantity", t("Line {{n}}: quantity", { n }), quantityText(line.quantity))}</td>
                  <td>{own ? field("unit", t("Line {{n}}: unit", { n }), line.unit ?? "", { className: "text-input unit-input" })
                    : <span>{p?.unit ?? items.find((i) => i.sku === line.sku)?.unit ?? ""}</span>}</td>
                  <td className="num">
                    {field("unit_price", t("Line {{n}}: unit price", { n }),
                      line.unit_price !== null ? amountText(line.unit_price, currency) : shown[line.id].unit_price)}
                    {p?.manual_price ? <span className="quote-own-price">{t("own price")}</span> : null}
                  </td>
                  <td className="num">
                    {field("discount_percent", t("Line {{n}}: discount", { n }),
                      line.discount_percent !== null ? numText(line.discount_percent, 4) : shown[line.id].discount_percent, { placeholder: "0" })}
                  </td>
                  <td className="num tnum quote-net">{p ? amountText(p.net, currency) : <span className="muted">—</span>}</td>
                  <td className="quote-actions">
                    <ConfirmButton className="quiet small-btn" danger ariaLabel={t("Remove line {{n}}", { n })} disabled={saving}
                      onConfirm={() => void save((d) => ({ ...d, lines: d.lines.filter((l) => l.id !== line.id) }))}>
                      <Icon name="trash" />
                    </ConfirmButton>
                  </td>
                </tr>
                {noteShown ? (
                  <tr className="quote-note-row">
                    <td />
                    <td colSpan={7}>
                      {field("note", t("Line {{n}}: note", { n }), line.note ?? "",
                        { className: "text-input", placeholder: t("Why this price or this line (required for an own price)") })}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            );
          })}
        </table>
      </div>
      <div className="quote-foot">
        <button type="button" className="quiet small-btn" disabled={saving}
          onClick={() => void save((d) => ({ ...d, lines: [...d.lines, { id: null, sku: null, description: null, unit: null, quantity: "1", unit_price: null, discount_percent: null, note: null, checked: false }] }))}>
          <Icon name="plus" />{t("Add a line")}
        </button>
        <Totals totals={dv.totals} currency={currency} vat={dv.vat_percent} />
      </div>
      {dv.totals ? (
        <div className="button-row">
          <TemplateChoice wpId={wpId} output="quote" />
          <a className="secondary dl-btn small-btn" href={api.quoteDraftDocxUrl(wpId, dv.step)} download><Icon name="download" />
            {t("Download the draft (Word)")}</a>
        </div>
      ) : null}
      <p className="small muted">
        {dv.price_list ? t("Priced from the price list {{name}}, version {{n}}; {{currency}}, VAT {{vat}}%", {
          name: dv.price_list.name, n: dv.price_list.version, currency: currency ?? "", vat: numText(dv.vat_percent, 2),
        }) : null}
      </p>
    </section>
  );
}

function Totals({ totals, currency, vat }: { totals: QuoteApproved["totals"]; currency: string | null; vat: string | null }) {
  useLocale();
  if (!totals) return <p className="small muted quote-totals-wait">{t("The totals show once every line is priced.")}</p>;
  return (
    <dl className="quote-totals tnum" aria-label={t("Totals")}>
      <div><dt>{t("Net total")}</dt><dd>{amountText(totals.net, currency)} {currency}</dd></div>
      <div><dt>{t("VAT {{vat}}%", { vat: numText(vat, 2) })}</dt><dd>{amountText(totals.vat, currency)} {currency}</dd></div>
      <div className="gross"><dt>{t("Gross total")}</dt><dd>{amountText(totals.gross, currency)} {currency}</dd></div>
    </dl>
  );
}

/** A quote as it stands or as it was approved: its header, its lines and its totals, to read. */
export function QuoteDocument({ quote }: { quote: QuoteApproved }) {
  useLocale();
  const c = quote.currency;
  return (
    <div className="quote-document">
      <dl className="quote-facts quote-facts-wide">
        {Object.entries(quote.header).map(([f, v]) => (
          <div key={f}><dt>{f === "note" ? t("Note on the quote") : fieldLabel(f)}</dt><dd className={v ? "" : "muted"}>{v || "—"}</dd></div>
        ))}
      </dl>
      <table className="table compact quote-doc-lines" aria-label={t("The quote's lines")}>
        <thead>
          <tr>
            <th>#</th><th>{t("Item")}</th><th className="num">{t("Quantity")}</th><th className="num">{t("Unit price")}</th>
            <th className="num">{t("Discount %")}</th><th className="num">{t("Net")}</th>
          </tr>
        </thead>
        <tbody>
          {quote.lines.map((l, i) => (
            <tr key={l.id}>
              <td className="tnum muted">{i + 1}</td>
              <td>
                <span className="quote-item">{l.sku ? <code className="mono">{l.sku}</code> : null}<span>{l.name ?? "—"}</span></span>
                {l.note ? <span className="small muted">{l.note}</span> : null}
              </td>
              <td className="num tnum">{quantityText(l.quantity)} {l.unit ?? ""}</td>
              <td className="num tnum">{amountText(l.unit_price, c)}{l.manual_price ? <span className="quote-own-price">{t("own price")}</span> : null}</td>
              <td className="num tnum">{l.discount_percent && l.discount_percent !== "0" ? numText(l.discount_percent, 4) : ""}</td>
              <td className="num tnum">{amountText(l.net, c)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Totals totals={quote.totals} currency={c} vat={quote.vat_percent} />
      <p className="small muted">{t("Priced from the price list {{name}}, version {{n}}; {{currency}}, VAT {{vat}}%", {
        name: quote.price_list.name, n: quote.price_list.version, currency: c, vat: numText(quote.vat_percent, 2) })}</p>
    </div>
  );
}

/** The current draft as the approval would record it (the service's fingerprint names the same content). */
function preview(dv: QuoteDraftView): QuoteApproved | null {
  if (!dv.draft || !dv.price_list) return null;
  return {
    header: dv.draft.header, totals: dv.totals, currency: dv.currency ?? "", vat_percent: dv.vat_percent ?? "0",
    price_list: { price_list: dv.price_list.price_list, name: dv.price_list.name, version: dv.price_list.version, fingerprint: "" },
    request: { title: null, key: dv.draft.request_key },
    lines: dv.lines.map((l) => ({ ...(l.priced ?? {}), id: l.id, row: l.row, requested: l.requested, mark: l.mark, note: l.note,
      checked_by: l.checked_by, sku: l.priced?.sku ?? l.sku, name: l.priced?.name ?? l.description })),
  };
}

/** The Approval stage: the shared approval element, the quote it records, the earlier versions. */
export function QuoteApprovalStage({ wpId, view, archived, onChanged, askLetter }: {
  wpId: string; view: QuoteView; archived: boolean; onChanged: () => void;
  /** 231 (A6): on a case's page, asking for the letter starts the case's step */
  askLetter?: () => Promise<unknown>;
}) {
  useLocale();
  const [dv, setDv] = useState<QuoteDraftView>(view.draft);
  useEffect(() => setDv(view.draft), [view.draft]);
  const { busy, error, notice, run, setError } = useAction();
  const [shown, setShown] = useState<{ n: number; quote: QuoteApproved } | null>(null);
  const act = (fn: () => Promise<QuoteDraftView>, done: string) => run(fn, {
    then: (next) => { setDv(next); onChanged(); },
    done,
    failed: (e) => {
      if (!(e instanceof ApiError && e.status === 409)) return errorText(e);
      onChanged();
      return e.code === "not_ready" ? t("The quote cannot be approved yet: see what blocks it.")
        : t("The quote changed since it was shown; it has been reloaded. Check it and try again.");
    },
  });
  const lineNo = (id: string | null) => (id ? dv.lines.findIndex((l) => l.id === id) + 1 : 0);
  // D0-g: the approval records what is saved: not while the quote has changes on this page not saved yet
  const unsaved = useHasWork(quoteWorkKey(wpId, dv.step)) && !dv.approval.active;
  const own = !dv.draft
    ? <p className="small">{t("The quote has not been composed yet.")} <a href={caseTab(wpId, "quote")}>{t("Compose it in Quote")}</a></p>
    : dv.blockers.length ? (
      <ul className="plain">
        {dv.blockers.map((b, i) => (
          <li key={`${b.code}:${b.line ?? i}`} className="small">
            <span className="status long s-review">{b.line ? t("Line {{n}}: {{what}}", { n: lineNo(b.line), what: t(QUOTE_LINE_BLOCKER[b.code]) }) : t(QUOTE_LINE_BLOCKER[b.code])}</span>
          </li>
        ))}
        <li className="small"><a href={caseTab(wpId, "quote")}>{t("Settle them in Quote")}</a></li>
      </ul>
    ) : null;
  const blockers = unsaved ? (
    <>
      <p className="small"><span className="status long s-review">{t("The quote has changes not saved yet")}</span>{" "}
        <a href={caseTab(wpId, "quote")}>{t("Save them in Quote")}</a></p>
      {own}
    </>
  ) : own;
  const doc = dv.approval.active ? dv.approved : preview(dv);
  return (
    <div className="rc-stack">
      <ApprovalPanel approval={dv.approval} archived={archived} busy={busy}
        tools={<>
          {/* 196: the template of the draft's download and of the approval's stored Word document; an approved
              version's document is stored, so it is chosen again only after a reopening */}
          {dv.approval.active ? null : <TemplateChoice wpId={wpId} output="quote" />}
          {dv.approval.active ? (
            <a className="secondary dl-btn small-btn" href={api.quoteVersionDocxUrl(wpId, dv.approval.active.version)} download>
              <Icon name="download" />{t("Download version {{n}} (Word)", { n: dv.approval.active.version })}</a>
          ) : dv.totals ? (
            <a className="secondary dl-btn small-btn" href={api.quoteDraftDocxUrl(wpId, dv.step)} download>
              <Icon name="download" />{t("Download the draft (Word)")}</a>
          ) : null}
        </>}
        lockedText={t("The quote is not changed while this version stands. To change it, reopen the approval with a reason; this version stays as an earlier one.")}
        pendingText={t("Not approved yet. The approval records the quote below, with the price list version it is priced from, as an unchangeable version.")}
        blockers={blockers}
        approveLabel={dv.totals ? t("Approve the quote ({{gross}} {{currency}} gross)", { gross: amountText(dv.totals.gross, dv.currency), currency: dv.currency ?? "" }) : t("Approve the quote")}
        onApprove={() => void act(() => api.approveQuote(wpId, dv.fingerprint ?? "", dv.step), t("The quote has been approved."))}
        onReopen={(note) => act(() => api.reopenQuote(wpId, note, dv.step), t("The approval has been reopened; the quote can be changed again."))}
        state={dv.approval_state ?? null}
        onReturn={dv.step ? (reason) => run(() => api.returnCaseStep(wpId, dv.step!, reason),
          { then: () => onChanged(), done: t("The quote has been returned; it waits for its approval.") }) : undefined}
        error={error} notice={notice} />
      {doc ? (
        <section className="card wide" aria-label={dv.approval.active ? t("The approved quote") : t("The quote to approve")}>
          <h2>{dv.approval.active ? t("The approved quote: version {{n}}", { n: dv.approval.active.version }) : t("The quote to approve")}</h2>
          <QuoteDocument quote={doc} />
        </section>
      ) : null}
      {/* 196: the approved version's reply letter */}
      {dv.approval.active && view.letter ? <QuoteLetterCard wpId={wpId} letter={view.letter} archived={archived} onChanged={onChanged} askLetter={askLetter} /> : null}
      {shown ? (
        <section className="card wide" aria-label={t("Version {{n}}", { n: shown.n })}>
          <div className="card-head">
            <h2>{t("Version {{n}}", { n: shown.n })}</h2>
            <button type="button" className="quiet small-btn" onClick={() => setShown(null)}><Icon name="close" />{t("Close")}</button>
          </div>
          <QuoteDocument quote={shown.quote} />
        </section>
      ) : null}
      <EarlierVersions versions={dv.approval.versions}
        action={(v) => (
          <>
            <button type="button" className="quiet small-btn" onClick={() => void api.quoteVersion(wpId, v.version)
              .then((r) => setShown({ n: v.version, quote: r.quote }))
              .catch((e) => setError(e instanceof ApiError ? e.message : String(e)))}>{t("Show this version")}</button>
            <a href={api.quoteVersionDocxUrl(wpId, v.version)} download>{t("Download (Word)")}</a>
          </>
        )} />
    </div>
  );
}
