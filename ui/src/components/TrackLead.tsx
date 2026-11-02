// 277 (O4; the owner's decision of 2026-11-02): a track shown under another belongs to the part chosen above it. Its row
// starts with that part's number and name, as the track above shows them, so the two rows read as one; the parts of the
// row under it carry no numbers of their own (one numbered row per page). The tablist names it with aria-describedby.
import { t, useLocale } from "../i18n";

/** The part of the track above that a track under it belongs to: its number there (a step's) and its source label. */
export interface Lead {
  n?: number;
  label: string;
}

export function TrackLead({ id, lead }: { id: string; lead: Lead }) {
  useLocale();
  return (
    <span className="track-lead" id={id}>
      {lead.n !== undefined ? <span className="stage-no">{lead.n}</span> : null}
      <strong>{t(lead.label)}</strong>
    </span>
  );
}
