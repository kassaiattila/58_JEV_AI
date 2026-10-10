// 132: the statement page and the invoice side by side, on request. The statement opens at the page where the line
// stands, with the line framed (the service finds it in the statement's word layer by its amount and date); the
// invoice opens at its first page. A document processed on the command line belongs to no package, so its image
// cannot be opened here.
import { useEffect, useRef, useState } from "react";
import { api, type ReconcileInvoice, type ReconcileLine, type ReconcileOpen } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { wpHash } from "../../route";

function Page({ open, page, box, label }: { open: ReconcileOpen; page: number; box: [number, number, number, number] | null; label: string }) {
  const frame = useRef<HTMLDivElement>(null);
  useEffect(() => { if (box) frame.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [box, page]);
  return (
    <div className="rc-page">
      <img src={api.pageUrl(open.workpackage_id, open.item_id, page)} alt={label} loading="lazy" />
      {box ? (
        <div ref={frame} className="rc-box" aria-hidden="true" style={{
          left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`,
        }} />
      ) : null}
    </div>
  );
}

function Doc({ title, file, open, page, setPage, box, note }: {
  title: string; file: string | null; open: ReconcileOpen | null | undefined; page: number; setPage: (n: number) => void;
  box: [number, number, number, number] | null; note?: string | null;
}) {
  useLocale();
  const pages = open?.pages ?? 1;
  return (
    <figure className="rc-doc" aria-label={title}>
      <figcaption className="rc-doc-head">
        <strong>{title}</strong>
        <span className="muted small">{file ?? "–"}</span>
        <span className="spacer" />
        {open ? (
          <>
            <button type="button" className="quiet small-btn" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label={t("Previous page")}>‹</button>
            <span className="small">{t("Page {{n}} of {{total}}", { n: page, total: pages })}</span>
            <button type="button" className="quiet small-btn" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label={t("Next page")}>›</button>
            <a className="small" href={wpHash(open.workpackage_id, "review", open.item_id)} target="_blank" rel="noreferrer">{t("Open in its package")}</a>
          </>
        ) : null}
      </figcaption>
      {note ? <p className="small warn-text">{note}</p> : null}
      {open ? <Page open={open} page={page} box={box} label={title} />
        : <p className="muted small">{t("This document was processed on the command line, not in a work package, so its image cannot be opened here.")}</p>}
    </figure>
  );
}

export function DocumentPair({ wpId, line, invoice, opens }: {
  wpId: string; line: ReconcileLine | null; invoice: ReconcileInvoice | null; opens: Record<string, ReconcileOpen>;
}) {
  useLocale();
  const where = useLoad(line ? `reconcile-locate:${wpId}:${line.id}` : null, () => api.reconcileLocate(wpId, line!.id));
  const [linePage, setLinePage] = useState(1);
  const [invoicePage, setInvoicePage] = useState(1);
  const found = where.data && where.data.line_id === line?.id ? where.data : null;
  useEffect(() => { setLinePage(found?.page ?? 1); }, [found?.page, line?.id]);
  useEffect(() => { setInvoicePage(1); }, [invoice?.id]);
  const lineNote = found && found.open && !found.page ? t("The line could not be found on the statement's pages; look for it by its date and amount.") : null;
  return (
    <section className="rc-docs" aria-label={t("Documents")}>
      {line ? (
        <Doc title={t("Statement")} file={line.file} open={found ? found.open : opens[line.statement_id]} page={linePage} setPage={setLinePage}
          box={found && found.page === linePage ? found.box : null} note={lineNote} />
      ) : <p className="muted small">{t("Select a statement line to see its statement.")}</p>}
      {invoice ? (
        <Doc title={t("Invoice")} file={invoice.file} open={opens[invoice.id]} page={invoicePage} setPage={setInvoicePage} box={null} />
      ) : <p className="muted small">{t("Select an invoice to see it next to the statement.")}</p>}
    </section>
  );
}
