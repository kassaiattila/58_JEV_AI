"""The priced document of an approved version, a general capability (231, stage D0, D0-c; the reassessment of 2026-10-26,
F05, P03). Until D0-c it was the quote's and read the quote's own draft.

Plain-language summary: a step of a case is done with an approved version of its own (a quote, later an insurance
offer); this capability fills an output template - a Word document - from that version, as it was approved. It reads the
version through the step it names (`from_step`, which gives the version's number, checked against that step's result
form), and the output's own domain says how the version's content becomes the document's values and tables (a
`VersionDocument` it registers for its output in `jav/app/outputs/parts.py`: the quote's is the quote's document). So
another process prints its own approved versions with its own output and builder, and this code stays the same.

- `CAPABILITY` (`priced_document@1`): params `output` (an output contract of `configs/outputs.json` in Word format) and
  `from_step`; its result: the output, the version printed and how many values it holds. D-f7: a document its domain
  does not store at the approval (the insurance offer's; the quote's is stored then) is stored here with the version,
  once, with the case's chosen template: the result names the file and its sha256, and the version's download and a
  letter read that file ever after.
- 231 (U3b): a step's output is chosen from those that print the version of the step it names (an output's
  `VersionDocument.prints`); a pack naming another is refused.
- `step_file(case_id, step)`: the stored document of a priced document's step (D-f7).
- D-f7: the shared element `document_view` for such a step: the file, its fingerprint, the version printed.

Layer: application; it uses the capability registry, the version store and the outputs' registry.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import capabilities, package_release
from jav.app.outputs import parts, templates
from jav.core import cfg, store
from jav.core.process import cases, kinds

_OWNER = __name__


class _Approved(capabilities.Result):
    """D-b2: what the printed document expects of the step it prints: the number of its approved version."""

    version: int


class PricedDocument(BaseModel):
    """The output contract it fills, and the step whose approved version it prints."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    output: str = Field(min_length=1, title="Output")
    from_step: str = capabilities.step_ref(min_length=1, expects=_Approved)

    @field_validator("output")
    @classmethod
    def _known_output(cls, value: str) -> str:
        if value not in (cfg.load("outputs").get("outputs") or {}):
            raise ValueError(f"no output {value!r}")
        return value


class StoredFile(BaseModel):
    """D-f7: the document stored with the version: its file name and the sha256 of its bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    sha256: str


class DocumentResult(capabilities.Result):
    """The priced document: its output contract, the approved version it printed and how many values it holds; D-f7: the
    file stored with the version, when this step stores it."""

    output: str
    version: int
    values: int
    file: StoredFile | None = None


def _outputs() -> list[tuple[str, str]]:
    """231 (B4): the Word outputs a priced document may fill."""
    return [(key, key) for key, o in (cfg.load("outputs").get("outputs") or {}).items() if o.get("format") == "docx"]


def _fits(output: str, pack: Any, step: Any) -> bool | None:
    """231 (U3b): whether the output prints the approved version of the step the priced document names (`from_step`):
    its domain's version document names that step's capability, or any; None when no domain prints the output."""
    try:
        doc = parts.version_document(output)
    except parts.UnknownOutput:
        return None
    if not doc.prints:
        return True
    source = next((s for s in pack.steps if s.id == (step.params or {}).get("from_step")), None)
    return source is not None and source.uses.split("@", 1)[0] in doc.prints


def _outputs_for(pack: Any, step: Any) -> list[tuple[str, str]]:
    """231 (U3b): the Word outputs this step may fill: those that print the version of the step it names."""
    return [(key, label) for key, label in _outputs() if _fits(key, pack, step)]


def _pack_check(pack: Any) -> list[str]:
    """231 (U3b): a priced document's output (its value, or its resource's in the pack's file) prints the version of the
    step it names."""
    problems = []
    for step in pack.steps:
        if step.uses != f"{CAPABILITY.name}@{CAPABILITY.version}":
            continue
        output = (step.params or {}).get("output")
        if isinstance(output, str) and output.startswith("@"):
            output = pack.resources.get(output[1:])
        if isinstance(output, str) and _fits(output, pack, step) is False:
            problems.append(f"step {step.id!r}: the output {output!r} does not print the version of the step it names")
    return problems


def _run(ctx: Any, params: PricedDocument) -> kinds.StepOutcome:
    version = capabilities.read_result(ctx, params, "from_step")["version"]  # checked against the other step's form
    case_id = str(ctx.data["container"])
    package = ctx.data.get("name") or case_id
    try:
        builder = parts.version_document(params.output)
        approved = package_release.own_version(case_id, version, step=params.from_step)
        # U1: the document reads as the how-manyth version of its step (the case numbers its versions across its steps)
        shown = package_release.step_number(case_id, version, params.from_step)
        data = builder.build(approved["content"], case_id=case_id, package=package, version=shown,
                             approved_by=approved.get("approved_by"), approved_at=approved.get("approved_at"),
                             output=params.output)
    except (parts.UnknownOutput, KeyError, ValueError) as exc:  # a version its builder cannot print names why
        return kinds.Fail(str(exc))
    result: dict[str, Any] = {"output": data.output, "version": version, "values": len(data.values)}
    if builder.file is None:  # D-f7: stored with the version once; a rerun prints nothing new
        with ctx.transaction() as c:
            stored = package_release.own_file(case_id, version, package_release.APPROVED, c)
            if stored is None:
                file, made = templates.render(data, case_id, c)
                name = builder.name(approved["content"], package, shown) if builder.name else f"{params.output}-v{shown}.docx"
                package_release.store_own_files(c, case_id, version, package_release.APPROVED,
                                                [(name, sum(len(t.rows) for t in data.tables), file, made)])
                stored = package_release.own_file(case_id, version, package_release.APPROVED, c)
        result["file"] = {"name": stored["name"], "sha256": stored["sha256"]}
    return kinds.Done(result)


class NoDocument(KeyError):
    """D-f7: the step stored no file (yet)."""


def _done_step(c: Any, case_id: str, step: str) -> dict[str, Any] | None:
    case = cases.find_case_in(c, case_id)
    row = cases.find_step_in(c, case_id, step)
    if case is None or row is None or capabilities.of_step_kind(cases.definition_of(case).step(step).kind) is not CAPABILITY:
        return None
    return row


def step_file(case_id: str, step: str) -> tuple[bytes, str]:
    """D-f7: the file a done step stored with the version its result names (a priced document's printed document; D-f8:
    a letter's email file), the one its result's sha256 names (`NoDocument`: none)."""
    with store.connect() as c:
        row = cases.find_step_in(c, case_id, step)
    result = (row or {}).get("result") or {}
    named = result.get("file")
    if row is None or row["state"] != cases.DONE or not isinstance(named, dict) or "version" not in result:
        raise NoDocument(f"{case_id} {step}: no stored document")
    stored = package_release.own_file(case_id, int(result["version"]), package_release.APPROVED)
    if stored is None or stored["sha256"] != named.get("sha256"):
        raise NoDocument(f"{case_id} {step}: no stored document")
    return stored["content"], stored["name"]


def _document_view(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D-f7: the document element's data: the step's state, the step whose approved version it prints, and, once
    printed, the version, the output and the stored file (its name and sha256)."""
    with store.connect() as c:
        row = _done_step(c, case_id, str(step)) or {}
        case = cases.find_case_in(c, case_id)
    params = cases.definition_of(case).step(str(step)).params if case is not None and row else {}
    result = row.get("result") if row.get("state") == cases.DONE else None
    return {"state": row.get("state"), "from_step": params.get("from_step"), "output": params.get("output"),
            "version": (result or {}).get("version"), "file": (result or {}).get("file")}


CAPABILITY = capabilities.Capability(
    name="priced_document", version=1, module=_OWNER, run=_run, kind="machine", params=PricedDocument, state="step",
    output=DocumentResult, rule_files=("outputs",), choices={"output": _outputs}, choices_for={"output": _outputs_for},
    pack_check=_pack_check,
    summary="Fills a priced document from an output template: an approved version of the step it names, as that"
            " output's domain builds it.")


def register() -> None:
    from jav.app import case_views

    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("document_view", None, _OWNER, _document_view,
                                               applies=lambda capability: capability == CAPABILITY.name))


__all__ = ["CAPABILITY", "DocumentResult", "NoDocument", "PricedDocument", "StoredFile", "register", "step_file"]
