import { useEffect } from "react";
import { t, useLocale } from "../i18n";
import { codePointSlice, elementKey, type NativeCitation, type NativeElement, type NativeLocator, type NativeSourcePage } from "../native";
import { nativeStateLabel } from "./nativeLabels";

export function locatorText(l: NativeLocator): string {
  switch (l.kind) {
    case "cell": return `${l.sheet}!${l.cell}`;
    case "sheet": return l.sheet;
    case "word": return `${l.part === "word/document.xml" ? t("Document body") : /(?:^|\/)header\d*\.xml$/.test(l.part) ? t("Header") : /(?:^|\/)footer\d*\.xml$/.test(l.part) ? t("Footer") : l.part} · ${l.part} · ${l.structural_path} · #${l.block_index}`;
    case "text": return t("Code points [{{start}}, {{end}})", { start: l.start, end: l.end });
    case "image": return t("Image frame {{n}}", { n: l.frame });
    case "pdf": return t("Page {{n}}", { n: l.page });
  }
}

export function NativeSourceViewer({ source, selected, citation, onPick }: {
  source: NativeSourcePage; selected: string | null; citation: NativeCitation | null; onPick: (e: NativeElement) => void;
}) {
  useLocale();
  useEffect(() => {
    if (!selected) return;
    const block = document.getElementById(`native-source-${selected}`);
    (block?.querySelector("mark") ?? block)?.scrollIntoView?.({ block: "nearest" });
  }, [selected, citation]);
  const elements = [...source.elements].sort((a, b) => a.order - b.order);
  const sheetOptions = elements.filter((e) => e.locator.kind === "sheet" || e.locator.kind === "cell")
    .filter((e, i, candidates) => candidates.findIndex((candidate) => candidate.occurrence_id === e.occurrence_id
      && "sheet" in candidate.locator && "sheet" in e.locator && candidate.locator.sheet === e.locator.sheet) === i);
  const current = elements.find((e) => elementKey(e) === selected);
  const activeSheet = sheetOptions.find((e) => e.occurrence_id === current?.occurrence_id && "sheet" in e.locator
    && current && "sheet" in current.locator && e.locator.sheet === current.locator.sheet);
  const content = (e: NativeElement) => {
    const span = citation && elementKey(citation) === elementKey(e) ? citation.quote_span : null;
    if (e.locator.kind === "text") {
      const text = source.texts[e.locator.text_sha256];
      if (text === undefined) return <p className="notice error">{t("Saved text is unavailable.")}</p>;
      const { start, end } = e.locator;
      return <pre className="native-text">{span && span.text_sha256 === e.locator.text_sha256 && span.start >= start && span.end <= end
        ? <>{codePointSlice(text, start, span.start)}<mark>{codePointSlice(text, span.start, span.end)}</mark>{codePointSlice(text, span.end, end)}</>
        : codePointSlice(text, start, end)}</pre>;
    }
    if (e.cell) return <>
      <div className="native-lexical">{e.cell.value.lexical ?? <span className="muted">{e.cell.formula !== null ? t("No literal cell value") : t("Empty cell")}</span>}</div>
      <small>{t("Value type")}: {nativeStateLabel(e.cell.value.kind)}</small>
      {e.cell.formula !== null ? <div><strong>{t("Formula")}: </strong><code>{e.cell.formula}</code><br />
        <small>{t("Saved formula value")}: {e.cell.cached_value?.lexical ?? t("Unavailable")} · {e.cell.cached_state === "missing" ? t("Missing cache") : t("Unverified cache; not recalculated")}</small></div> : null}
      {e.cell.merged_range ? <small>{t("Merged range")}: {e.cell.merged_range}</small> : null}
    </>;
    return e.text !== null ? <div className="native-lexical">{e.text}</div> : null;
  };
  const block = (e: NativeElement) => <article key={elementKey(e)} id={`native-source-${elementKey(e)}`}
    className={`native-block ${selected === elementKey(e) ? "native-selected" : ""}`} data-element-id={e.element_id}>
    <button type="button" className="native-source-location" onClick={() => onPick(e)} aria-pressed={selected === elementKey(e)}>{locatorText(e.locator)}</button>
    <small className="muted">{nativeStateLabel(e.kind)} · {nativeStateLabel(e.availability)}{e.hidden || e.cell?.hidden ? ` · ${t("Hidden source content")}` : ""}</small>
    {content(e)}
    {e.availability === "unreadable" || e.availability === "unsupported" ? <p className="notice">{t("This element was not read.")}</p> : null}
  </article>;
  const wordTree = (e: NativeElement): React.ReactNode => <div key={elementKey(e)} className={e.kind === "table" ? "native-word-table" : ""}>
    {block(e)}{elements.filter((child) => child.occurrence_id === e.occurrence_id && child.parent_id === e.element_id).map(wordTree)}</div>;
  const cellTable = (name: string, cells: NativeElement[]) => {
    const rows = [...new Set(cells.map((e) => e.locator.kind === "cell" ? e.locator.row : 0))].sort((a, b) => a - b);
    return <div className="native-cell-scroll"><table className="native-cells"><caption>{name}</caption>
      <tbody>{rows.map((row) => <tr key={row}>{cells.filter((e) => e.locator.kind === "cell" && e.locator.row === row)
        .sort((a, b) => (a.locator as { column: number }).column - (b.locator as { column: number }).column)
        .map((e) => <td key={elementKey(e)}>{block(e)}</td>)}</tr>)}</tbody></table></div>;
  };
  return <section className="native-source" aria-label={t("Saved source")}>
    <h2>{t("Saved source")}</h2>
    <p className="muted small">{t("All {{n}} saved elements are shown, including empty and hidden cells.", { n: source.total })}</p>
    {sheetOptions.length ? <label className="block">{t("Sheet")}<select value={activeSheet ? elementKey(activeSheet) : ""} onChange={(event) => {
      const target = sheetOptions.find((e) => elementKey(e) === event.target.value); if (target) onPick(target);
    }}><option value="">{t("Choose a sheet")}</option>{sheetOptions.map((e) => <option key={elementKey(e)} value={elementKey(e)}>
      {source.occurrences.find((o) => o.occurrence_id === e.occurrence_id)?.original_name} · {"sheet" in e.locator ? e.locator.sheet : ""}</option>)}</select></label> : null}
    {source.occurrences.map((occurrence) => {
      const own = elements.filter((e) => e.occurrence_id === occurrence.occurrence_id);
      const roots = own.filter((e) => e.parent_id === null || !own.some((p) => p.element_id === e.parent_id));
      return <section key={occurrence.occurrence_id} aria-label={occurrence.original_name}>
        <h3>{occurrence.original_name}</h3>
        {roots.map((root) => {
          // CSV publishes cells directly. Group by their real sheet locator without inventing source elements.
          if (root.locator.kind === "cell") {
            const sheet = root.locator.sheet;
            const cells = roots.filter((e) => e.locator.kind === "cell" && e.locator.sheet === sheet);
            return cells[0] === root ? <section key={elementKey(root)}>{cellTable(sheet, cells)}</section> : null;
          }
          if (root.kind !== "sheet") return wordTree(root);
          const cells = own.filter((e) => e.parent_id === root.element_id && e.locator.kind === "cell");
          return <section key={elementKey(root)}>{block(root)}{cellTable(locatorText(root.locator), cells)}
            {own.filter((e) => e.parent_id === root.element_id && e.locator.kind !== "cell").map(wordTree)}</section>;
        })}
      </section>;
    })}
  </section>;
}
