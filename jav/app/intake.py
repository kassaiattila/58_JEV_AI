"""How a case of a process pack starts from what arrives (231, plan stage C, C1a; DECISIONS 231).

Plain-language summary: a process pack says what starts its cases (`intake`): an email whose intent fits it (a quote
request starts an IT quote), or a person by hand. When an email arrives, every process whose intake takes emails is
asked whether the email holds what its cases start from: the step that reads its record from the case's scope
(a capability with a `preview`) reads the email as it would at the case's start. Each process that finds it is an
offer on the email's page: what the record holds, what it lacks, the cases already started from it, and how its case
starts (a person starts it, or, by the owner's decision of 2026-10-25, it starts by itself).

- `offers(wp_id, item_id)`: the processes an email item may start a case of, each with its record's preview, its
  gaps, a name for the case, and the cases already started from it.

Layer: application, the shared library; it uses the process packs, the capabilities, the scope parts and the package
scopes. It names no process and no domain: the record's reading is the capability's.
"""

from __future__ import annotations

from typing import Any

from jav.app import capabilities, package_scope, process_packs, scopes

__all__ = ["EMAIL_INTENT", "MANUAL", "offers"]

EMAIL_INTENT, MANUAL = "email_intent", "manual"


def _label(pack: process_packs.ProcessPack, record: dict[str, Any] | None) -> str | None:
    """What the case is about, for its name: the value its first partner link's name field reads, else the record's
    title."""
    fields = (record or {}).get("fields") or {}
    for link in pack.partners:
        name = fields.get(link.fields.get("name", ""))
        if isinstance(name, str) and name.strip():
            return name.strip()
    title = (record or {}).get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def offers(wp_id: str, item_id: str) -> list[dict[str, Any]]:
    """The processes whose intake takes emails and whose record step finds its record in this email: each with how its
    case starts, the record (`{"workpackage_id", "item_id"}`), the preview its capability gives, the record's gaps, a
    name for the case and the cases already started from this record. Empty when no process takes it."""
    from jav.app import process_settings

    record = {"workpackage_id": wp_id, "item_id": item_id}
    out = []
    for pack in process_packs.packs():
        entries = [e for e in pack.intake if e.on == EMAIL_INTENT]
        if not entries or scopes.RECORD not in pack.scope.parts:
            continue
        step = next((s for s in pack.steps if capabilities.of(s.uses).preview is not None), None)
        if step is None:
            continue
        resources = process_settings.effective_resources(pack)
        params = process_packs.definition(pack.model_copy(update={"resources": resources})).step(step.id).params
        shown = capabilities.of(step.uses).preview(record, {k: v for k, v in params.items() if not k.startswith("_")})
        if shown is None:
            continue
        out.append({"pack": pack.id, "title": pack.title, "starts": entries[0].starts, "record": record,
                    "preview": shown.get("record"), "list_field": shown.get("list_field"),
                    "record_type": shown.get("record_type"),
                    "gaps": list(shown.get("gaps") or []),
                    "label": _label(pack, shown.get("record")),
                    "cases": package_scope.holding(scopes.RECORD, record)})
    return out
