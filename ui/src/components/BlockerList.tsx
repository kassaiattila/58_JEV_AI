// 195 (plan G-tidy R6; DECISIONS 195): the one list of what holds a step back. A line is a blocker (a red ✕ before its
// reason) or a warning (an amber !). A reason with many lines is one line with its count, its lines opening below it
// (153: a reconciliation of a few hundred unapproved documents used to list each one). The readiness of a run, the
// start's confirmation, the quote's gaps, the reconciliation's approval and the template and price list checks each
// wrote this list by hand; they now share it, with the same markup as before.
import type { ReactNode } from "react";

/** One line: what holds the step back, or (`warning`) what to know before it. */
export type BlockerLine = { key: string; content: ReactNode; warning?: boolean };
/** The lines of one reason, shown as the reason with its count; they open below it. */
export type BlockerGroup = { key: string; summary: ReactNode; lines: BlockerLine[] };

export function BlockerList({ items, small = false, parts = false, label }: {
  items: (BlockerLine | BlockerGroup)[];
  /** the smaller type of a long list (the reconciliation's approval) */
  small?: boolean;
  /** each line's parts side by side (a location, the reason, a detail), as the template and price list checks show them */
  parts?: boolean;
  label?: string;
}) {
  const tone = (item: BlockerLine | BlockerGroup) =>
    ("lines" in item || !item.warning ? "blocker" : "warning") + (small ? " small" : "");
  return (
    <ul className={parts ? "plain template-issues" : "plain"} aria-label={label}>
      {items.map((item) => ("lines" in item ? (
        <li key={item.key} className={tone(item)}>
          <details>
            <summary>{item.summary}</summary>
            <ul className="plain">{item.lines.map((line) => <li key={line.key}>{line.content}</li>)}</ul>
          </details>
        </li>
      ) : <li key={item.key} className={tone(item)}>{item.content}</li>))}
    </ul>
  );
}

/** The lines grouped by their reason, in the order each reason first occurs; a reason with one line stays a line. */
export function groupedBlockers<T>(entries: T[], reason: (entry: T) => string, line: (entry: T) => BlockerLine,
  summary: (reason: string, n: number) => ReactNode): (BlockerLine | BlockerGroup)[] {
  const groups = new Map<string, T[]>();
  for (const entry of entries) groups.set(reason(entry), [...(groups.get(reason(entry)) ?? []), entry]);
  return [...groups].map(([key, group]) => (group.length === 1 ? { ...line(group[0]), key }
    : { key, summary: summary(key, group.length), lines: group.map(line) }));
}
