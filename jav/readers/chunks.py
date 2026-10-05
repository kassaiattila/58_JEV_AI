"""Complete, deterministic request partitions over frozen source elements."""
from __future__ import annotations

from collections import OrderedDict
import json
from typing import Callable


def element_key(row: dict) -> tuple[str, str]:
    return row["occurrence_id"], row["element_id"]


def source_chunks(view: dict, fits: Callable[[dict], bool]) -> tuple[dict, ...]:
    """Keep worksheet rows together and repeat the first two rows as context.

    Every non-empty source element appears in at least one request. A row that
    cannot fit fails before any provider call; no source is silently dropped.
    """
    if fits(view):
        return (view,)
    groups: OrderedDict[tuple, list[dict]] = OrderedDict()
    headings: dict[tuple, list[dict]] = {}
    for row in view["elements"]:
        locator = row["locator"]
        sheet = (row["occurrence_id"], locator.get("sheet"))
        key = (*sheet, locator.get("row", row["element_id"]))
        groups.setdefault(key, []).append(row)
        if locator.get("kind") == "cell" and locator.get("row", 3) <= 2:
            headings.setdefault(sheet, []).append(row)

    def make(rows):
        unique = {element_key(row): row for row in rows}
        return {**view, "elements": list(unique.values())}

    chunks, current, current_sheet = [], [], None
    for key, rows in groups.items():
        sheet = key[:2]
        context = headings.get(sheet, [])
        candidate = make(current + rows)
        if current and (sheet != current_sheet or not fits(candidate)):
            chunks.append(make(current))
            current = []
        if not current:
            current = context.copy()
        candidate = make(current + rows)
        if not fits(candidate):
            raise ValueError("Source row and its context exceed the explicit transfer bound")
        current = candidate["elements"]
        current_sheet = sheet
    if current:
        chunks.append(make(current))
    if not chunks or len(chunks) > 128:
        raise ValueError("Source chunks exceed the explicit transfer bound")
    return tuple(chunks)


def verification_chunks(view: dict, questions: dict, facts: tuple, max_bytes: int) -> tuple[tuple[dict, dict], ...]:
    """Include cited rows and worksheet headings for every semantic question."""
    by_id = {element_key(row): row for row in view["elements"]}

    def selected(keys):
        cited = {element_key(c.model_dump()) for key in keys for c in facts[int(key[1:])].proposal.citations}
        rows = {(row["occurrence_id"], row["locator"].get("sheet"), row["locator"].get("row"))
                for identity in cited if (row := by_id.get(identity)) is not None}
        elements = [row for row in view["elements"] if element_key(row) in cited or (
            row["locator"].get("kind") == "cell" and any(
                occurrence == row["occurrence_id"] and sheet == row["locator"].get("sheet")
                and (number == row["locator"].get("row") or row["locator"].get("row", 3) <= 2)
                for occurrence, sheet, number in rows))]
        return {**view, "elements": elements}

    def fits(part, batch):
        # Include ordinary SDK JSON spacing, escaped Unicode and the model envelope.
        return len(json.dumps({"state": part, "questions": {
            k: q.model_dump(mode="json") for k, q in batch.items()}}).encode("utf-8")) + 512 <= max_bytes

    if fits(view, questions):
        return ((view, questions),)
    chunks, batch = [], {}
    for key, question in questions.items():
        candidate = {**batch, key: question}
        if batch and not fits(selected(candidate), candidate):
            chunks.append((selected(batch), batch))
            candidate = {key: question}
        if not fits(selected(candidate), candidate):
            raise ValueError("JEV citation context exceeds the explicit transfer bound")
        batch = candidate
    if batch:
        chunks.append((selected(batch), batch))
    return tuple(chunks)
