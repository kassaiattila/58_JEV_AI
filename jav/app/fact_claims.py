"""The facts a case's processed documents hold, offered to its field check (231, stage D, D-f1).

Plain-language summary: a case processes its documents in a step of its own (`process_documents@1`): each is
recognised, read with its type pack, and a person may correct what was read. This step takes what counts now - the
latest result of each document of that step's package, with the person's corrections over it - and turns it into
facts of the assessed units by the fact readings the case kept as it started (`fact_readings`): each fact names the
document, its file, and the page and words it was printed on. It decides nothing: the field check places the facts,
and a value two documents give differently is left to a person there. A document no reading takes (another type), and
a value that cannot be read, are listed with why.

- `CAPABILITY` (`fact_claims@1`): params `from_step` (a document processing step) and `readings` (a fact readings rule
  file); result: the claims (as the field check reads them), each document with what it gave and what it did not, and
  the values not read.

Layer: application; it names no business (the readings are data).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import capabilities, corrections, fact_readings, field_check, package_result, work
from jav.core.process import kinds

__all__ = ["CAPABILITY", "FactClaims", "FactClaimsResult", "register"]


class _Processed(capabilities.Result):
    """What the step expects of the processing step it reads: its package (none: the source held no document)."""

    package: str | None = None


class FactClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    from_step: str = capabilities.step_ref(min_length=1, of="process_documents", expects=_Processed)
    readings: str = Field("fact_readings_property", min_length=1, title="Fact readings")

    @field_validator("readings")
    @classmethod
    def _known(cls, value: str) -> str:
        try:
            fact_readings.load(value)
        except FileNotFoundError:
            raise ValueError(f"no fact readings {value!r}") from None
        return value


class FactClaimsResult(capabilities.Result):
    """The claims the documents give, each document with what it gave, and what could not be read."""

    claims: list[dict[str, Any]]
    documents: list[dict[str, Any]]


def _where(provenance: dict[str, Any], item: str, file: str, field: str, list_field: str | None, row: int | None) -> dict[str, Any]:
    """The source of a value: the document, its file, and the page and words it was printed on (when known)."""
    entry = provenance.get(list_field or field) or {}
    if list_field is not None and row is not None:
        rows = entry.get("rows") or []
        entry = rows[row - 1] if 0 < row <= len(rows) and isinstance(rows[row - 1], dict) else {}
    page = entry.get("page")
    return {"item": item, "file": file, "page": page if isinstance(page, int) else None,
            "quote": entry.get("quote") if isinstance(entry.get("quote"), str) else None}


def _documents(wp_id: str) -> list[dict[str, Any]]:
    """What counts now for each document of the package: its type, its values with the corrections over them, and where
    each was printed, in the package's order."""
    wp = work.get(wp_id)
    in_use = package_result.in_use(wp)
    out = []
    for item in wp["items"]:
        counted = in_use.get(item["item_id"])
        if counted is None:
            continue
        dp = corrections.datapoints_row(counted.run_id, item["item_id"])
        if dp is None:
            continue
        correction = corrections.current(counted.run_id, item["item_id"])
        provenance = corrections.effective_provenance(dp, correction, corrections.layer_for(dp)) if correction["fields"] \
            else dict(dp.get("provenance") or {})
        out.append({"item": item["item_id"], "file": str(item["source_path"]).replace("\\", "/").rsplit("/", 1)[-1],
                    "doc_type": dp["doc_type"], "run": counted.run_id,
                    "values": package_result.effective_values(dp.get("datapoints"), correction["fields"]),
                    "provenance": provenance})
    return out


def _run(ctx: Any, params: FactClaims) -> kinds.StepOutcome:
    processed = capabilities.read_result(ctx, params, "from_step")
    readings = fact_readings.load(params.readings)
    docs = _documents(processed["package"]) if processed.get("package") else []
    order = list(readings.packs)
    docs.sort(key=lambda d: order.index(d["doc_type"]) if d["doc_type"] in readings.packs else len(order))  # a parent first
    claims: list[dict[str, Any]] = []
    listed: list[dict[str, Any]] = []
    for doc in docs:
        if doc["doc_type"] not in readings.packs:
            listed.append({"item": doc["item"], "file": doc["file"], "doc_type": doc["doc_type"], "claims": 0, "unread": [],
                           "note": "no reading takes this type"})
            continue
        got, unread = fact_readings.claims(
            readings, doc["doc_type"], doc["values"], reading=f"type:{doc['doc_type']}",
            source=lambda field, lst, row, d=doc: _where(d["provenance"], d["item"], d["file"], field, lst, row))
        valid = [field_check.Claim.model_validate(c).model_dump(mode="json") for c in got]
        claims += valid
        listed.append({"item": doc["item"], "file": doc["file"], "doc_type": doc["doc_type"], "run": doc["run"],
                       "claims": len(valid), "unread": unread})
    return kinds.Done({"claims": claims, "documents": listed})


CAPABILITY = capabilities.Capability(
    name="fact_claims", version=1, module=__name__, run=_run, kind="machine", params=FactClaims, state="step",
    output=FactClaimsResult, effects="pure", reads=lambda p: (p.get("readings") or "fact_readings_property",),
    summary="Turns what a case's processed documents hold into facts of its units, each naming where it was printed.")


def _documents_view(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D-f4: the document facts element's data: each document with how many facts it gave and what it did not."""
    from jav.core import store
    from jav.core.process import cases

    from jav.app import facts

    with store.connect() as c:
        case = cases.find_case_in(c, case_id)
        row = cases.find_step_in(c, case_id, str(step)) or {}
    result = row.get("result") or {}
    name = (cases.definition_of(case).step(str(step)).params.get("readings") if case else None) or "fact_readings_property"
    return {"state": row.get("state"), "documents": result.get("documents") or [],
            "catalogue": facts.catalogue(fact_readings.load(str(name)).catalogue).model_dump(mode="json")}


def register() -> None:
    from jav.app import case_views

    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("document_facts", "fact_claims", __name__, _documents_view))
