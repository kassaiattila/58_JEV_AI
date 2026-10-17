// 132: the statement page and the invoice side by side, on request. The statement opens at the page where the line
// stands, with the line framed (the service finds it in the statement's word layer by its amount and date); the
// invoice opens at its first page. A document processed on the command line belongs to no package, so its image
// cannot be opened here.
// 144 (DECISIONS 144): the statement pane shows the line's facts first, as the statement prints them. A statement read
// by code (a CIB PDF's text, a bank's table or XML export) has no page of its own — the pane showed a broken image —
// so its page is the bank's PDF behind it, found again by the service (jav/statement_original.py) and framed the same
// way; a table or XML export has no PDF, and the statement as read stands in its place, the line highlighted.
import { useEffect, useRef, useState } from "react";
import { api, type ReconcileInvoice, type ReconcileLine, type ReconcileLocation, type ReconcileOpen, type ReconcileStatementView } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { wpHash } from "../../route";
import { signedAmount, TransactionFacts } from "./LineFacts";
import { display, show } from "./money";

const AROUND = 3; // the lines shown before and after the selected one in the statement as read; all on request

function Page({ src, page, box, label }: { src: string; page: number; box: [number, number, number, number] | null; label: string }) {
  const frame = useRef<HTMLDivElement>(null);
  useEffect(() => { if (box) frame.current?.scrollIntoView?.({ block: "center", behavior: "smooth" }); }, [box, page]);
  return (
    <div className="rc-page">
      <img src={src} alt={label} loading="lazy" />
      {box ? (
        <div ref={frame} className="rc-box" aria-hidden="true" style={{
          left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`,
        }} />
      ) : null}
    </div>
  );
}

function Pager({ page, pages, setPage }: { page: number; pages: number; setPage: (n: number) => void }) {
  useLocale();
  return (
    <>
      <button type="button" className="quiet small-btn" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label={t("Previous page")}>‹</button>
      <span className="small">{t("Page {{n}} of {{total}}", { n: page, total: pages })}</span>
      <button type="button" className="quiet small-btn" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label={t("Next page")}>›</button>
    </>
  );
}

const PackageLink = ({ open }: { open: ReconcileOpen }) => (
  <a className="small" href={wpHash(open.workpackage_id, "review", open.item_id)} target="_blank" rel="noreferrer">{t("Open in its package")}</a>
);

function Doc({ title, file, open, page, setPage }: {
  title: string; file: string | null; open: ReconcileOpen | null | undefined; page: number; setPage: (n: number) => void;
}) {
  useLocale();
  return (
    <figure className="rc-doc" aria-label={title}>
      <figcaption className="rc-doc-head">
        <strong>{title}</strong>
        <span className="muted small">{file ?? "–"}</span>
        <span className="spacer" />
        {open ? <><Pager page={page} pages={open.pages ?? 1} setPage={setPage} /><PackageLink open={open} /></> : null}
      </figcaption>
      {open ? <Page src={api.pageUrl(open.workpackage_id, open.item_id, page)} page={page} box={null} label={title} />
        : <p className="muted small">{t("This document was processed on the command line, not in a work package, so its image cannot be opened here.")}</p>}
    </figure>
  );
}

/** 144: the statement as the reader read it: its heading, then its lines around the selected one (all on request). */
function StatementAsRead({ statement, lineId, open }: { statement: ReconcileStatementView; lineId: string; open: boolean }) {
  useLocale();
  const [all, setAll] = useState(false);
  useEffect(() => { setAll(false); }, [lineId]);
  const at = Math.max(0, statement.lines.findIndex((l) => l.id === lineId));
  const long = statement.lines.length > 2 * AROUND + 1;
  const shown = all || !long ? statement.lines : statement.lines.slice(Math.max(0, at - AROUND), at + AROUND + 1);
  const cur = statement.currency;
  const heading = [statement.institution, statement.account, [statement.period_start, statement.period_end].filter(Boolean).join(" – ")]
    .filter(Boolean).join(" · ");
  return (
    <details className="rc-asread" open={open}>
      <summary>{t("The statement as read ({{n}} lines)", { n: statement.lines.length })}</summary>
      <p className="small muted">
        {heading}
        {statement.opening_balance ? ` · ${t("Opening balance")}: ${show(statement.opening_balance, cur)}` : ""}
        {statement.closing_balance ? ` · ${t("Closing balance")}: ${show(statement.closing_balance, cur)}` : ""}
        {" · "}{statement.verified ? t("balances check out") : <span className="warn-text">{t("statement balances do not check out")}</span>}
      </p>
      <div className="rc-asread-scroll">
        <table className="rc-asread-table">
          <thead>
            <tr><th>{t("Booking day")}</th><th className="num">{t("Amount")}</th><th>{t("Counterparty")}</th><th>{t("Memo")}</th><th className="num">{t("Balance after")}</th></tr>
          </thead>
          <tbody>
            {shown.map((l) => (
              <tr key={l.id} className={l.id === lineId ? "is-line" : undefined} aria-current={l.id === lineId ? "true" : undefined}>
                <td>{l.booking_date ?? "–"}</td>
                <td className="num">{display(signedAmount(l), cur)}</td>
                <td>{l.counterparty_name || l.description || "–"}</td>
                <td>{l.memo || ""}</td>
                <td className="num">{l.running_balance ? show(l.running_balance, cur) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {long ? (
        <button type="button" className="quiet small-btn" onClick={() => setAll(!all)}>
          {all ? t("Only the lines around it") : t("All {{n}} lines", { n: statement.lines.length })}
        </button>
      ) : null}
    </details>
  );
}

function StatementDoc({ wpId, line, found, error }: { wpId: string; line: ReconcileLine; found: ReconcileLocation | null; error?: string | null }) {
  useLocale();
  const [page, setPage] = useState(1);
  useEffect(() => { setPage(found?.page ?? 1); }, [found?.page, line.id]);
  const open = found?.open ?? null;
  const image = found?.image ?? null; // only from the service's answer: a statement read by code has no page of its own
  const src = image === "original" ? api.originalPageUrl(wpId, line.id, page)
    : image === "item" && open ? api.pageUrl(open.workpackage_id, open.item_id, page) : null;
  const pages = found?.pages ?? 1;
  const original = found?.original ?? null;
  const file = image === "original" ? original?.file ?? null : found?.statement.file ?? line.file;
  let note: string | null = null;
  // 167 (review 160 U-11): the lookup of the line's place failed: say so, not an empty pane
  if (error) note = t("The line's place on the statement could not be looked up: {{reason}}", { reason: error });
  else if (src && found && !found.page) note = t("The line could not be found on the statement's pages; look for it by its date and amount.");
  else if (original?.state === "export") note = t("This statement was read from the bank's table or XML export, so it has no PDF page.");
  else if (original?.state === "missing") {
    note = t("The bank's PDF ({{file}}) is not in the package's source folder, or it changed since it was read.", { file: original.file ?? "–" });
  } else if (!src && found && !original) {
    note = t("This document was processed on the command line, not in a work package, so its image cannot be opened here.");
  }
  return (
    <figure className="rc-doc" aria-label={t("Statement")}>
      <figcaption className="rc-doc-head">
        <strong>{t("Statement")}</strong>
        <span className="muted small">{file ?? "–"}</span>
        <span className="spacer" />
        {src ? <Pager page={page} pages={pages} setPage={setPage} /> : null}
        {open ? <PackageLink open={open} /> : null}
      </figcaption>
      <dl className="rc-doc-facts" aria-label={t("The line on the statement")}>
        <TransactionFacts line={line} currency={line.currency} account={line.account} />
      </dl>
      {note ? <p className="small warn-text">{note}</p> : null}
      {found?.statement.lines.length ? <StatementAsRead statement={found.statement} lineId={line.id} open={!src} /> : null}
      {src ? <Page src={src} page={page} box={found && found.page === page ? found.box : null} label={t("Statement")} /> : null}
    </figure>
  );
}

export function DocumentPair({ wpId, line, invoice, opens }: {
  wpId: string; line: ReconcileLine | null; invoice: ReconcileInvoice | null; opens: Record<string, ReconcileOpen>;
}) {
  useLocale();
  const where = useLoad(line ? `reconcile-locate:${wpId}:${line.id}` : null, () => api.reconcileLocate(wpId, line!.id));
  const [invoicePage, setInvoicePage] = useState(1);
  const found = where.data && where.data.line_id === line?.id ? where.data : null;
  useEffect(() => { setInvoicePage(1); }, [invoice?.id]);
  return (
    <section className="rc-docs" aria-label={t("Documents")}>
      {line ? <StatementDoc wpId={wpId} line={line} found={found} error={found ? null : where.error?.message} />
        : <p className="muted small">{t("Select a statement line to see its statement.")}</p>}
      {invoice ? (
        <Doc title={t("Invoice")} file={invoice.file} open={opens[invoice.id]} page={invoicePage} setPage={setInvoicePage} />
      ) : <p className="muted small">{t("Select an invoice to see it next to the statement.")}</p>}
    </section>
  );
}
