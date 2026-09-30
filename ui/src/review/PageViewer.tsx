// Oldalkép-néző kerettel (045 K3b). A V4 GroundedSource viselkedése saját kóddal, két újdonsággal:
//  - a kiválasztott mező többi jelöltje szaggatott, kattintható keretként látszik (valószínűséggel);
//  - kijelölő módban szavakra kattintva vagy téglalapot húzva lehet szöveget választani a mezőhöz.
// 053 (döntés 2026-09-28): minden megtalált mező kerete halványan, a bizonyosság színével látszik, a kiválasztott erősen
// kiemelve (a V4-ben csak az aktív látszott). Szabályok a V4-ből: a keret az oldalkép betöltése után jelenik meg (nincs keret
// a régi oldalon); a mező oldalára automatikusan lapoz és a keretet a látható részbe görgeti; kattintás a képen a pont
// alatti mezők között lépked.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Alternative, Provenance, SourcePage, SourceWord } from "../api";
import { t, useLocale } from "../i18n";
import { cyclePick, fieldsAtPoint, frameBoxes, inflate, wordAt, wordsInRect } from "./geometry";

export const BAND_COLOR: Record<string, string> = {
  confident: "#008A2E", check: "#0057FF", likely_wrong: "#E00024", unknown: "#5b5b66", manual: "#7a3fb0",
};

interface Props {
  pageUrl: (page: number) => string;
  pages: SourcePage[];
  pageCount?: number | null; // 048: az irat tényleges oldalszáma (szóréteg nélkül / az OCR oldalkorlátja fölött is lapozható)
  prov: Record<string, Provenance>;
  activeField: string | null;
  focusRequest: number;
  colorOf: (field: string) => string;
  labelOf: (field: string) => string;
  onPickField: (field: string) => void;
  onChooseAlternative: (field: string, alt: Alternative) => void;
  selectMode: boolean;
  words: SourceWord[] | null;
  selected: number[];
  onSelect: (ids: number[]) => void;
}

interface Pt { x: number; y: number }

export function PageViewer(props: Props) {
  const { pageUrl, pages, pageCount, prov, activeField, focusRequest, colorOf, labelOf, onPickField, onChooseAlternative, selectMode, words, selected, onSelect } = props;
  useLocale();
  const total = Math.max(1, pages.length, pageCount ?? 0);
  const active = activeField ? prov[activeField] : undefined;
  const [page, setPage] = useState(active?.page ?? 1);
  const [zoom, setZoom] = useState(1);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [drag, setDrag] = useState<{ a: Pt; b: Pt } | null>(null);
  const canvas = useRef<HTMLDivElement | null>(null);
  const activeBox = useRef<HTMLDivElement | null>(null);
  const src = pageUrl(page);
  const ready = loadedSrc === src && !failed;

  // a kiválasztott mező oldalára lapozás (új kijelölésnél akkor is, ha kézzel máshová lapoztunk)
  useEffect(() => {
    if (frameBoxes(active).length && active?.page && active.page !== page) setPage(active.page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeField, focusRequest]);

  useEffect(() => setFailed(false), [src]);

  useEffect(() => {
    if (ready && activeBox.current) activeBox.current.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [ready, activeField, focusRequest, zoom, page]);

  const alternatives = useMemo(
    () => (active?.alternatives ?? []).filter((a) => a.page === page && a.bbox),
    [active, page],
  );

  function rel(e: React.PointerEvent): Pt {
    const r = canvas.current!.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  }

  function onPointerDown(e: React.PointerEvent) {
    if (!ready || e.button !== 0) return;
    const p = rel(e);
    setDrag({ a: p, b: p });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    if (drag && selectMode) setDrag({ ...drag, b: rel(e) });
  }

  function onPointerUp(e: React.PointerEvent) {
    if (!drag) return;
    const end = rel(e);
    const moved = Math.abs(end.x - drag.a.x) + Math.abs(end.y - drag.a.y) > 0.01;
    setDrag(null);
    if (selectMode && words) {
      if (moved) {
        onSelect(wordsInRect(words, page, drag.a, end).map((w) => w.id));
      } else {
        const w = wordAt(words, page, end.x, end.y);
        if (w) onSelect(selected.includes(w.id) ? selected.filter((i) => i !== w.id) : [...selected, w.id]);
      }
      return;
    }
    if (!moved) {
      const next = cyclePick(fieldsAtPoint(prov, page, end.x, end.y), activeField);
      if (next) onPickField(next);
    }
  }

  const activeBoxes = active?.page === page ? frameBoxes(active) : [];
  const others = Object.entries(prov).filter(([k, p]) => k !== activeField && p.page === page && frameBoxes(p).length);
  const approx = active?.status === "approximate";
  const selectedSet = new Set(selected);
  const status = failed ? t("Az oldalkép nem tölthető be.") : !ready ? t("Az oldalkép betöltődik…") : null;

  return (
    <div className="viewer">
      <div className="viewer-bar" role="toolbar" aria-label={t("Oldalkép")}>
        {total > 1 ? (
          <span className="pager">
            <button type="button" className="icon-btn" aria-label={t("Előző oldal")} disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>‹</button>
            <span className="mono small">{page} / {total}</span>
            <button type="button" className="icon-btn" aria-label={t("Következő oldal")} disabled={page >= total} onClick={() => setPage((p) => Math.min(total, p + 1))}>›</button>
          </span>
        ) : <span className="muted small">{t("1 oldal")}</span>}
        <span className="zoom">
          <button type="button" className="icon-btn" aria-label={t("Kicsinyítés")} disabled={zoom <= 0.5} onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>−</button>
          <button type="button" className="quiet small-btn mono" aria-label={t("Nagyítás alaphelyzetbe")} onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
          <button type="button" className="icon-btn" aria-label={t("Nagyítás")} disabled={zoom >= 3} onClick={() => setZoom((z) => Math.min(3, z + 0.25))}>+</button>
        </span>
      </div>
      <div className={`viewer-canvas ${selectMode ? "selecting" : ""}`}>
        <div
          ref={canvas}
          className="page-wrap"
          style={{ width: `${zoom * 100}%` }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          data-testid="page-canvas"
        >
          <img key={src} src={src} alt={t("Az irat {{n}}. oldala", { n: page })} className="page-img" draggable={false}
            onLoad={() => setLoadedSrc(src)} onError={() => setFailed(true)} />
          {status ? <div className="page-status" role="status">{status}</div> : null}
          {ready && !selectMode ? others.flatMap(([k, p]) => frameBoxes(p).map((b, i) => {
            const r = inflate(b, 0.003);
            return (
              <div key={`o${k}${i}`} className={`field-box all ${p.status === "approximate" ? "approx" : ""}`} title={labelOf(k)}
                style={{ left: `${r.left}%`, top: `${r.top}%`, width: `${r.width}%`, height: `${r.height}%`, outlineColor: colorOf(k) }} />
            );
          })) : null}
          {ready && activeField ? activeBoxes.map((b, i) => {
            const r = inflate(b, 0.004);
            return (
              <div key={`a${i}`} ref={i === 0 ? activeBox : undefined} className={`field-box active ${approx ? "approx" : ""}`} data-testid={i === 0 ? `box-${activeField}` : undefined}
                title={approx ? t("{{field}} – közelítő hely (a sor, ahonnan a gép választott)", { field: labelOf(activeField) }) : labelOf(activeField)}
                style={{ left: `${r.left}%`, top: `${r.top}%`, width: `${r.width}%`, height: `${r.height}%`, outlineColor: colorOf(activeField) }} />
            );
          }) : null}
          {ready && activeField ? alternatives.map((a, i) => {
            const r = inflate(a.bbox!, 0.003);
            const label = a.machine ? t("gépi érték") : a.p !== null ? `${Math.round(a.p * 100)}%` : t("lehetséges hely");
            return (
              <div key={`alt${i}`} className="alt-box" style={{ left: `${r.left}%`, top: `${r.top}%`, width: `${r.width}%`, height: `${r.height}%` }}>
                <button type="button" className="alt-chip" onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => onChooseAlternative(activeField, a)} title={t("Ezt választom: „{{text}}”", { text: a.quote ?? a.value ?? "" })}>
                  {label}
                </button>
              </div>
            );
          }) : null}
          {ready && selectMode && words ? words.filter((w) => w.page === page && selectedSet.has(w.id)).map((w) => {
            const r = inflate([w.x0, w.y0, w.x1, w.y1], 0.001);
            return <div key={`w${w.id}`} className="word-sel" style={{ left: `${r.left}%`, top: `${r.top}%`, width: `${r.width}%`, height: `${r.height}%` }} />;
          }) : null}
          {drag && selectMode ? (() => {
            const x0 = Math.min(drag.a.x, drag.b.x), y0 = Math.min(drag.a.y, drag.b.y);
            return <div className="drag-rect" style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${Math.abs(drag.b.x - drag.a.x) * 100}%`, height: `${Math.abs(drag.b.y - drag.a.y) * 100}%` }} />;
          })() : null}
        </div>
      </div>
    </div>
  );
}
