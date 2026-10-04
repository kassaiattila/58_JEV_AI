import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { elementKey, type NativeCitation, type NativeItemResult, type NativeSourcePage } from "../native";
import { NativeFactPanel } from "./NativeFactPanel";
import { NativeSourceViewer } from "./NativeSourceViewer";
import { Split } from "./Split";
import "./native.css";

/** Each page must belong to the same publication. A partial fetch is never labelled complete. */
export async function loadNativeSource(result: NativeItemResult): Promise<NativeSourcePage> {
  if (!result.result_version || !result.native_source) throw new Error("No published source");
  let offset = 0;
  let collected: NativeSourcePage | undefined;
  const seen = new Set<string>();
  for (;;) {
    const page = await api.nativeSources(result.run_id, result.item_id, result.result_version, offset);
    const source = result.native_source;
    if (page.result_version !== result.result_version || page.publication_id !== source.publication_id || page.reading_id !== source.reading_id
      || page.bundle_sha256 !== source.bundle_sha256 || page.source_sha256 !== source.source_sha256 || page.offset !== offset
      || (collected && page.total !== collected.total)) throw new Error(t("The saved source changed. Reload the item."));
    for (const e of page.elements) {
      const id = elementKey(e);
      if (seen.has(id)) throw new Error(t("The saved source page is inconsistent."));
      seen.add(id);
    }
    collected = collected ? { ...collected, elements: [...collected.elements, ...page.elements], texts: { ...collected.texts, ...page.texts } } : page;
    if (!page.has_more) {
      if (collected.elements.length !== page.total) throw new Error(t("The saved source page is incomplete."));
      return { ...collected, has_more: false, next_offset: null };
    }
    if (page.next_offset === null || page.next_offset <= offset || page.next_offset !== offset + page.elements.length)
      throw new Error(t("The saved source page is inconsistent."));
    offset = page.next_offset;
  }
}

export function NativeReview({ data, approved, onChanged }: { data: NativeItemResult; approved: boolean; onChanged: () => void }) {
  useLocale();
  const source = useLoad(data.result_ready ? `native-source:${data.run_id}:${data.item_id}:${data.result_version}` : null, () => loadNativeSource(data));
  const [selected, setSelected] = useState<string | null>(null);
  const [citation, setCitation] = useState<NativeCitation | null>(null);
  const shownSource = source.data?.result_version === data.result_version && !source.error ? source.data : null;
  return <Split label={t("Source and facts panel ratio")} left={<div className="viewer-stack">
    {data.source_file.original === "changed" || data.source_file.original === "missing"
      ? <p className="notice">{t("The original file changed or disappeared. This view uses the saved source used for this result.")}</p> : null}
    {!data.result_ready ? <p className="notice">{t("No published native source is available yet.")}</p>
      : source.error ? <p className="notice error" role="alert">{source.error.message}<button onClick={source.reload}>{t("Reload source")}</button></p>
        : !shownSource ? <p role="status">{t("Loading the complete saved source…")}</p>
          : <NativeSourceViewer source={shownSource} selected={selected} citation={citation?.result_version === data.result_version ? citation : null} onPick={(e) => { setSelected(elementKey(e)); setCitation(null); }} />}
  </div>} right={<NativeFactPanel result={data} source={shownSource} selected={selected} readOnly={approved} onChanged={onChanged}
    onCitation={(next) => { setSelected(elementKey(next)); setCitation(next); }} />} />;
}
