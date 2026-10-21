// 192 (plan F-quote-package B5; DECISIONS 191, 192): the quote composed beside its request, and its approval. The owner
// asked for a page where the request and its data can be seen and the quote changed on their basis. On the left the
// request: its fields and its numbered requested items. On the right the quote: its header, its lines and its totals.
// Every change is saved at once (the page sends the draft with the state it read; a stale page is refused and
// reloaded); code prices every line. A line says what it was asked for (the requested item's number and words), its
// state mark, and in words what still holds the approval; a line the proposal marked "to check" is confirmed or changed
// by a person (the owner's choice). The approval is the shared element of a logic pack's own versions.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiError, type QuoteApproved, type QuoteDraftBlockerCode, type QuoteDraftIn, type QuoteDraftLine,
  type QuoteDraftView, type QuoteLineIn, type QuoteRequest, type QuoteView,
} from "../../api";
import { ApprovalPanel, EarlierVersions } from "../../components/ApprovalPanel";
import { ConfirmButton } from "../../components/ConfirmButton";
import { Icon } from "../../components/Icon";
import { Picker, type PickerOption } from "../../components/Picker";
import { errorText, useAction } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { fieldLabel, numText, when } from "../../labels";
import { wpHash } from "../../route";
import { amountText } from "./quoteStatus";

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
type Line = QuoteDraftView["lines"][number];

const quantityText = (v: unknown) => (v === null || v === undefined || v === "" ? "" : numText(v, 4));
const requestedText = (r: QuoteDraftLine["requested"]) =>
  r ? [r.description, [quantityText(r.quantity), r.unit].filter(Boolean).join(" ")].filter(Boolean).join(" · ") : "";
const needsNote = (l: QuoteLineIn) => l.sku === null || l.unit_price !== null || l.discount_percent !== null;

/** What a line shows while it has no price or discount of a person's own: the list's price, the rule's discount. */
type Shown = Record<string, { unit_price: string; discount_percent: string }>;

function sent(draft: NonNullable<QuoteDraftView["draft"]>, edits: Record<string, Partial<Record<Edited, string>>>,
  header: Record<string, string>, shown: Shown): QuoteDraftIn {
  return {
    price_list: draft.price_list, version: draft.version,
    header: { ...draft.header, ...Object.fromEntries(Object.entries(header).map(([k, v]) => [k, v.trim() || null])) },
    lines: draft.lines.map((l) => {
      const e = edits[l.id] ?? {};
      const pick = (k: Edited) => {
        if (!(k in e)) return l[k];
        const text = e[k]!.trim();
        const listed = (k === "unit_price" || k === "discount_percent") && text !== "" && text === shown[l.id]?.[k];
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
  const [edits, setEdits] = useState<Record<string, Partial<Record<Edited, string>>>>({});
  const [header, setHeader] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown: Shown = Object.fromEntries(dv.lines.map((l) => [l.id, {
    unit_price: l.priced?.list_price ? amountText(l.priced.list_price, dv.currency) : "",
    discount_percent: l.priced && l.priced.discount_from === "rule" ? numText(l.priced.discount_percent, 4) : "",
  }]));
  const latest = useRef({ edits, header, shown });
  latest.current = { edits, header, shown };
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
    const { edits: e, header: h, shown: s } = latest.current;
    if (!cur.draft) return;
    const body = (change ?? ((d) => d))(sent(cur.draft, e, h, s));
    setSaving(true);
    setError(null);
    try {
      const next = await api.saveQuoteDraft(wpId, body, cur.state);
      adopt(next);
      // what was sent is saved; what was typed since stays to be saved
      setEdits((now) => {
        const left: typeof now = {};
        for (const [id, fields] of Object.entries(now)) {
          const kept = Object.fromEntries(Object.entries(fields).filter(([k, v]) => e[id]?.[k as Edited] !== v));
          if (Object.keys(kept).length) left[id] = kept;
        }
        return left;
      });
      setHeader((now) => Object.fromEntries(Object.entries(now).filter(([k, v]) => h[k] !== v)));
      setSavedAt(new Date().toISOString());
      onChanged();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(t("The quote changed since it was shown; it has been reloaded. Check it and try again."));
        setEdits({});
        setHeader({});
        onChanged();
      } else setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }
  const editLine = (id: string, field: Edited, value: string) => setEdits((e) => ({ ...e, [id]: { ...e[id], [field]: value } }));
  const commitLine = (id: string) => { if (latest.current.edits[id]) void save(); };
  const withLine = (id: string, patch: Partial<QuoteLineIn>) => void save((d) => ({
    ...d, lines: d.lines.map((l) => (l.id === id ? { ...l, ...patch } : l)),
  }));

  if (locked) {
    return (
      <section className="card wide quote-draft" aria-label={t("The quote")}>
        <div className="card-head"><h3>{t("The quote")}</h3></div>
        <p className="notice ok-box">
          {t("Approved: version {{n}}, by {{who}}, {{when}}.", { n: locked.version, who: locked.approved_by, when: when(locked.approved_at) })}{" "}
          <a href={wpHash(wpId, "result")}>{t("To change it, reopen it in Approval.")}</a>
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
  const superseded = dv.warnings.find((w) => w.code === "quote:price_list_superseded");
  return (
    <section className="card wide quote-draft" aria-label={t("The quote")}>
      <div className="card-head">
        <div className="quote-draft-title">
          <h3>{t("The quote")}</h3>
          {ready ? <span className="status s-done">{t("ready to approve")}</span>
            : <span className="status s-review">{t("{{n}} thing(s) to settle before the approval", { n: dv.blockers.length })}</span>}
          <span className="muted small" role="status">{saving ? t("Saving…") : savedAt ? t("Saved {{when}}", { when: when(savedAt) }) : t("Every change is saved at once.")}</span>
        </div>
        {/* the page header's next step is the view's one solid action (approving once nothing holds it) */}
        <a className="secondary small-btn" href={wpHash(wpId, "result")}>{t("To the approval")}</a>
      </div>

      {error ? <p className="notice error" role="alert">{error}</p> : null}
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
                onConfirm={() => void api.startQuoteDraft(wpId, { source: "proposal", expected_state: dv.state, replace: true })
                  .then((next) => { adopt(next); setEdits({}); onChanged(); })
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
              onBlur={() => { if (f in latest.current.header) void save(); }} />
          </label>
        ))}
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
                    <ConfirmButton className="quiet small-btn" ariaLabel={t("Remove line {{n}}", { n })} disabled={saving}
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
export function QuoteApprovalStage({ wpId, view, archived, onChanged }: {
  wpId: string; view: QuoteView; archived: boolean; onChanged: () => void;
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
  const blockers = !dv.draft
    ? <p className="small">{t("The quote has not been composed yet.")} <a href={wpHash(wpId, "review")}>{t("Compose it in Quote")}</a></p>
    : dv.blockers.length ? (
      <ul className="plain">
        {dv.blockers.map((b, i) => (
          <li key={`${b.code}:${b.line ?? i}`} className="small">
            <span className="status long s-review">{b.line ? t("Line {{n}}: {{what}}", { n: lineNo(b.line), what: t(QUOTE_LINE_BLOCKER[b.code]) }) : t(QUOTE_LINE_BLOCKER[b.code])}</span>
          </li>
        ))}
        <li className="small"><a href={wpHash(wpId, "review")}>{t("Settle them in Quote")}</a></li>
      </ul>
    ) : null;
  const doc = dv.approval.active ? dv.approved : preview(dv);
  return (
    <div className="rc-stack">
      <ApprovalPanel approval={dv.approval} archived={archived} busy={busy}
        lockedText={t("The quote is not changed while this version stands. To change it, reopen the approval with a reason; this version stays as an earlier one.")}
        pendingText={t("Not approved yet. The approval records the quote below, with the price list version it is priced from, as an unchangeable version.")}
        blockers={blockers}
        approveLabel={dv.totals ? t("Approve the quote ({{gross}} {{currency}} gross)", { gross: amountText(dv.totals.gross, dv.currency), currency: dv.currency ?? "" }) : t("Approve the quote")}
        onApprove={() => void act(() => api.approveQuote(wpId, dv.fingerprint ?? ""), t("The quote has been approved."))}
        onReopen={(note) => act(() => api.reopenQuote(wpId, note), t("The approval has been reopened; the quote can be changed again."))}
        error={error} notice={notice} />
      {doc ? (
        <section className="card wide" aria-label={dv.approval.active ? t("The approved quote") : t("The quote to approve")}>
          <h2>{dv.approval.active ? t("The approved quote: version {{n}}", { n: dv.approval.active.version }) : t("The quote to approve")}</h2>
          <QuoteDocument quote={doc} />
        </section>
      ) : null}
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
          <button type="button" className="quiet small-btn" onClick={() => void api.quoteVersion(wpId, v.version)
            .then((r) => setShown({ n: v.version, quote: r.quote }))
            .catch((e) => setError(e instanceof ApiError ? e.message : String(e)))}>{t("Show this version")}</button>
        )} />
    </div>
  );
}
