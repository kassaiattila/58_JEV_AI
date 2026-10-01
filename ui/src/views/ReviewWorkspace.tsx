import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { api, type Alternative, type ItemResult, type Provenance, type RunItem, type Workpackage } from "../api";
import { DatasetPicker, runOption } from "../components/DatasetPicker";
import { useDataset, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { FIELD, fieldLabel, fold, ITEM_STATUS, itemName } from "../labels";
import { go } from "../route";
import { draftKey, getDraft, setField, useDraft } from "../review/drafts";
import { EmailReview } from "../review/EmailReview";
import { FieldPanel } from "../review/FieldPanel";
import { bandOf, orderFields, selectionText, type Bands } from "../review/geometry";
import { BAND_COLOR, PageViewer } from "../review/PageViewer";
import { Split } from "../review/Split";

const DEFAULT_BANDS: Bands = { confident: 0.9, check: 0.5 };

/** The item's status in the list (062): based on the current to-dos, not on the moment of the run — an item that had
 *  to-dos at run time is „rendezve” (resolved) once its own to-dos have been closed since. */
export function queueStatus(res: Pick<RunItem, "status" | "final_status"> | undefined, openOwn: number): string {
  if (!res) return t("még nem futott");
  if (res.status !== "done") return ITEM_STATUS[res.status] ?? res.status;
  if (res.final_status === "done") return t("lezárva");
  return openOwn > 0 ? t("teendő") : t("rendezve");
}
// 048: the tab viewed last (fields / line list) stays on the next item too, if that item has such a list as well
let lastTab = "fields";

/** The notice above the page view when the original file changed or disappeared since the document was added: with a
 *  source instance the document is still shown (the copy the result was made from); without one it cannot be. */
export function sourceFileNote(sf: ItemResult["source_file"]): string | null {
  if (!sf || sf.original === "same") return null;
  if (sf.copy) {
    return sf.original === "changed"
      ? t("Az eredeti fájl a felvétel óta megváltozott. Itt a felvételkori példány látható; az eredmény ebből készült.")
      : t("Az eredeti fájl a felvétel óta eltűnt vagy nem olvasható. Itt a felvételkori példány látható; az eredmény ebből készült.");
  }
  return sf.original === "changed"
    ? t("Az eredeti fájl a felvétel óta megváltozott, ezért nem jeleníthető meg (az irat még azelőtt került a csomagba, hogy a rendszer példányt tett volna el róla).")
    : t("Az eredeti fájl a felvétel óta eltűnt vagy nem olvasható, ezért nem jeleníthető meg (az irat még azelőtt került a csomagba, hogy a rendszer példányt tett volna el róla).");
}

function withNote(note: string | null, node: ReactNode): ReactNode {
  if (!note) return node;
  return <div className="viewer-stack"><p className="notice small" role="status">{note}</p>{node}</div>;
}

/** To-dos: the items on the left, the page image with the field frames in the middle, the to-dos and the fields on
 *  the right (045 K3b). We work on the result of one run (the latest by default); a correction belongs to that run. */
export function ReviewWorkspace({ wp, itemId }: { wp: Workpackage; itemId?: string }) {
  useLocale();
  const latest = useDataset("runs", { workpackage_id: wp.id }, { limit: 1 });
  const [runId, setRunId] = useState<string | null>(null);
  const chosen = runId ?? latest.data?.rows[0]?._key ?? null;
  const view = useLoad(chosen ? `run:${chosen}` : null, () => api.run(chosen!));
  // 056 U1: the item list stays manageable even with several hundred items: filtering by name, only those with to-dos
  const [queueQ, setQueueQ] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(false);

  if (latest.error) return <p className="notice error" role="alert">{latest.error.message}</p>;
  if (!latest.data) return <p className="muted">{t("Betöltés…")}</p>;
  if (latest.data.total === 0) {
    return <div className="empty">{t("Ezen a csomagon még nem futott feldolgozás, ezért nincs mit ellenőrizni. Indíts futást a")} <a href={`#/workpackages/${wp.id}/process`}>{t("Feldolgozás")}</a> {t("szakaszban.")}</div>;
  }
  if (!view.data) return view.error ? <p className="notice error">{view.error.message}</p> : <p className="muted">{t("Betöltés…")}</p>;

  const run = view.data.run;
  const items = run.input.items;
  const own = view.data.open_reasons;
  const earlier = view.data.earlier_open_reasons;
  const firstWithWork = items.find((i) => (own[i.item_id] ?? []).length > 0) ?? items[0];
  const selectedId = itemId ?? firstWithWork?.item_id;
  const selected = items.find((i) => i.item_id === selectedId);
  const index = items.findIndex((i) => i.item_id === selectedId);
  const pick = (id: string) => go({ view: "workpackages", wpId: wp.id, stage: "review", itemId: id });
  const ownTotal = Object.values(own).reduce((n, r) => n + r.length, 0);

  return (
    <>
      <div className="review-bar">
        <DatasetPicker dataset="runs" scope={{ workpackage_id: wp.id }} label={t("Futás")} hideLabel value={chosen} valueCol="run_id"
          toOption={runOption} onChange={setRunId} />
        <span className="muted small">{ownTotal ? t("{{n}} nyitott teendő ebben a futásban", { n: ownTotal }) : t("Ebben a futásban nincs nyitott teendő.")}</span>
        <a className="small" href={`#/runs/${run.run_id}`}>{t("A futás részletei")}</a>
        <span className="muted small kbd-help">{t("↑/↓ mező · N/P tétel · S kijelölés · Ctrl+Enter mentés · Esc")}</span>
      </div>
      <div className="review-grid">
        <nav className="queue" aria-label={t("Tételek")}>
          <div className="queue-filter">
            <input type="search" aria-label={t("Tétel keresése")} placeholder={t("Keresés {{n}} tétel között…", { n: items.length })} value={queueQ}
              onChange={(e) => setQueueQ(e.target.value)} />
            <label className="check small"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />{t("csak teendős")}</label>
          </div>
          {items.filter((i) => (!onlyOpen || (own[i.item_id] ?? []).length > 0)
            && (!queueQ.trim() || fold(itemName(i, view.data?.titles)).includes(fold(queueQ.trim())))).map((i) => {
            const n = (own[i.item_id] ?? []).length;
            const m = (earlier[i.item_id] ?? []).length;
            const res = run.items.find((x) => x.item_id === i.item_id);
            return (
              <QueueItem key={i.item_id} runId={run.run_id} itemId={i.item_id} name={itemName(i, view.data?.titles)} active={i.item_id === selectedId}
                status={queueStatus(res, n)}
                own={n} earlier={m} onClick={() => pick(i.item_id)} />
            );
          })}
        </nav>
        {!selected ? (
          <div className="empty">{t("A kért tétel ({{id}}) nem része ennek a futásnak. Válassz a listából.", { id: selectedId?.slice(0, 12) ?? "" })}</div>
        ) : (
          <ItemReview key={`${run.run_id}:${selected.item_id}`} wpId={wp.id} runId={run.run_id} itemId={selected.item_id}
            approved={Boolean(run.approval)} onChanged={view.reload}
            onNext={() => index < items.length - 1 && pick(items[index + 1].item_id)}
            onPrev={() => index > 0 && pick(items[index - 1].item_id)} />
        )}
      </div>
    </>
  );
}

function QueueItem({ runId, itemId, name, active, status, own, earlier, onClick }: {
  runId: string; itemId: string; name: string; active: boolean; status: string; own: number; earlier: number; onClick: () => void;
}) {
  useLocale();
  const draft = useDraft(draftKey(runId, itemId));
  return (
    <button type="button" className="work-item" aria-pressed={active} onClick={onClick}>
      <span className="work-title" title={name}>{name}</span>
      <small>{status}</small>
      {own ? <span className="tag">{t("{{n}} teendő", { n: own })}</span> : null}
      {earlier ? <span className="tag quiet-tag" title={t("Korábbi futásból vagy mérésből nyitva maradt teendő ezen a tételen. Ennek a futásnak az állapotát és jóváhagyását nem befolyásolja.")}>{t("{{n}} korábbi teendő", { n: earlier })}</span> : null}
      {draft ? <span className="tag draft-tag">{t("mentetlen")}</span> : null}
    </button>
  );
}

function ItemReview({ wpId, runId, itemId, approved, onChanged, onNext, onPrev }: {
  wpId: string; runId: string; itemId: string; approved: boolean; onChanged: () => void; onNext: () => void; onPrev: () => void;
}) {
  useLocale();
  const res = useLoad(`item:${runId}:${itemId}`, () => api.item(runId, itemId));
  const settings = useLoad("settings", api.settings);
  const [selectMode, setSelectMode] = useState(false);
  const words = useLoad(selectMode ? `words:${runId}:${itemId}` : null, () => api.words(runId, itemId));
  const [active, setActive] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [selected, setSelected] = useState<number[]>([]);
  const [tab, setTabState] = useState(lastTab);
  const setTab = useCallback((next: string) => { lastTab = next; setTabState(next); }, []);
  const data = res.data;
  const onList = tab !== "fields" && Boolean(data?.lists?.[tab]);
  const bands = settings.data?.confidence_bands ?? DEFAULT_BANDS;
  const key = draftKey(runId, itemId);

  const band = useCallback((f: string) => {
    const p = data?.provenance[f];
    return bandOf(p?.confidence, bands, Boolean(p?.corrected) || getDraft(key)?.values[f] !== undefined);
  }, [data, bands, key]);

  const fields = useMemo(() => {
    const machine = data?.extraction?.datapoints ?? {};
    const order = Object.keys(FIELD);
    // only fields with a simple value (line items and other compound fields do not belong here)
    const scalar = Object.keys(machine).filter((f) => machine[f] === null || typeof machine[f] !== "object");
    const base = scalar.sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
    const reasonFields = new Set((data?.open_reasons ?? []).map((r) => r.reason.split(":")[2]).filter(Boolean));
    return orderFields(base, reasonFields, band);
  }, [data, band]);

  // on first opening, the most important field (to-do > weak estimate > first)
  useEffect(() => {
    if (data && active === null && fields.length) setActive(fields[0]);
  }, [data, fields, active]);

  const activate = useCallback((f: string) => {
    setActive(f);
    setFocusRequest((n) => n + 1);
  }, []);

  // keyboard shortcuts (outside input fields; Esc leaves the field)
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      const typing = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
      if (e.key === "Escape") {
        if (typing) (el as HTMLInputElement).blur();
        else if (selected.length) setSelected([]);
        else setSelectMode(false);
        return;
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      if (onList && e.key !== "n" && e.key !== "p") return; // on the line list tab only item switching works
      const i = active ? fields.indexOf(active) : -1;
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); if (fields.length) activate(fields[Math.min(fields.length - 1, i + 1)]); }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); if (fields.length) activate(fields[Math.max(0, i - 1)]); }
      else if (e.key === "n") onNext();
      else if (e.key === "p") onPrev();
      else if (e.key === "s" && data?.source) setSelectMode((v) => !v);
      else if (e.key === "Enter" && active) document.getElementById(`fv-${active}`)?.focus();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [active, fields, activate, onNext, onPrev, selected.length, data, onList]);

  if (res.error) return <p className="notice error" role="alert">{res.error.message}</p>;
  if (!data) return <p className="muted pad">{t("Betöltés…")}</p>;
  if (data.kind === "email" && data.email) return <EmailReview data={data} wpId={wpId} onChanged={() => { res.reload(); onChanged(); }} />;

  const machine = data.extraction?.datapoints ?? {};
  // 053: on the list tab the image shows where the rows are (with the key `lista[n]`), on the fields tab the fields
  const viewerProv: Record<string, Provenance> = onList
    ? Object.fromEntries((data.provenance[tab]?.rows ?? []).map((r, i) => [`${tab}[${i + 1}]`, r]))
    : Object.fromEntries(Object.entries(data.provenance).filter(([, v]) => v.status !== "list"));
  const labelOf = (k: string) => {
    const m = k.match(/^(.+)\[(\d+)\]$/);
    return m ? t("{{field}}: {{n}}. sor", { field: fieldLabel(m[1]), n: m[2] }) : fieldLabel(k);
  };
  const chooseAlternative = (f: string, a: Alternative) => {
    const value = a.machine ? String(machine[f] ?? "") : String(a.value ?? a.quote ?? "");
    setField(key, data.correction.revision, f, value, a.word_ids ?? null);
    activate(f);
  };
  const colorOf = (f: string) => {
    const row = viewerProv[f];
    if (row?.method === "rows") return row.status === "located" ? BAND_COLOR.confident : BAND_COLOR.check;
    return data.provenance[f]?.method === "manual" ? BAND_COLOR.manual : BAND_COLOR[band(f)];
  };
  const pages = data.source?.pages ?? [];
  const selText = words.data ? selectionText(words.data.words, selected) : "";

  return (
    <Split variant={onList ? "list" : "fields"}
      left={withNote(sourceFileNote(data.source_file), data.source ? (
        <PageViewer pageUrl={(n) => api.pageUrl(wpId, itemId, n)} pages={pages} pageCount={data.page_count} prov={viewerProv} activeField={active}
          focusRequest={focusRequest} colorOf={colorOf} labelOf={labelOf} onPickField={activate}
          onChooseAlternative={chooseAlternative} selectMode={selectMode} words={words.data?.words ?? null}
          selected={selected} onSelect={setSelected} />
      ) : (
        <div className="viewer-stack">
          <p className="notice small">{t("Ehhez az irathoz nincs szóréteg (korábbi futás vagy régi OCR-eredmény), ezért a mezők helye nem keretezhető és a mezőre nem ugrik. Lapozni lehet; a keretekhez futtasd újra a receptet (a helyi OCR a szóhelyeket pótolja).")}</p>
          <PageViewer pageUrl={(n) => api.pageUrl(wpId, itemId, n)} pages={[]} pageCount={data.page_count} prov={{}} activeField={null}
            focusRequest={0} colorOf={colorOf} labelOf={fieldLabel} onPickField={activate} onChooseAlternative={chooseAlternative}
            selectMode={false} words={null} selected={[]} onSelect={() => {}} />
        </div>
      ))}
      right={
        <FieldPanel result={data} fields={fields} bandOf={band} activeField={active} onActivate={activate}
          selection={{ ids: selected, text: selText }} onClearSelection={() => setSelected([])}
          selectMode={selectMode} onToggleSelect={() => { setSelectMode((v) => !v); setSelected([]); }}
          onSaved={() => { res.reload(); onChanged(); }} onResolved={() => { res.reload(); onChanged(); }}
          onChooseAlternative={chooseAlternative} readOnly={approved} hasWords={Boolean(data.source)} tab={tab} onTab={setTab}
          onRowPick={(f, n) => activate(`${f}[${n}]`)} />
      }
    />
  );
}
