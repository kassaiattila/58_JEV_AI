"""The priced document of an approved version, a general capability (231, stage D0, D0-c; the reassessment of 2026-10-26,
F05, P03). Until D0-c it was the quote's and read the quote's own draft.

Plain-language summary: a step of a case is done with an approved version of its own (a quote, later an insurance
offer); this capability fills an output template - a Word document - from that version, as it was approved. It reads the
version through the step it names (`from_step`, which gives the version's number, checked against that step's result
form), and the output's own domain says how the version's content becomes the document's values and tables (a
`VersionDocument` it registers for its output in `jav/app/outputs/parts.py`: the quote's is the quote's document). So
another process prints its own approved versions with its own output and builder, and this code stays the same.

- `CAPABILITY` (`priced_document@1`): params `output` (an output contract of `configs/outputs.json` in Word format) and
  `from_step`; its result: the output, the version printed and how many values it holds.

Layer: application; it uses the capability registry, the version store and the outputs' registry.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import capabilities, package_release
from jav.app.outputs import parts
from jav.core import cfg
from jav.core.process import kinds

_OWNER = __name__


class PricedDocument(BaseModel):
    """The output contract it fills, and the step whose approved version it prints."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    output: str = Field(min_length=1, title="Output")
    from_step: str = capabilities.step_ref(min_length=1, reads=("version",))

    @field_validator("output")
    @classmethod
    def _known_output(cls, value: str) -> str:
        if value not in (cfg.load("outputs").get("outputs") or {}):
            raise ValueError(f"no output {value!r}")
        return value


class DocumentResult(capabilities.Result):
    """The priced document: its output contract, the approved version it printed and how many values it holds."""

    output: str
    version: int
    values: int


def _outputs() -> list[tuple[str, str]]:
    """231 (B4): the Word outputs a priced document may fill."""
    return [(key, key) for key, o in (cfg.load("outputs").get("outputs") or {}).items() if o.get("format") == "docx"]


def _run(ctx: Any, params: PricedDocument) -> kinds.StepOutcome:
    version = capabilities.read_result(ctx, params, "from_step")["version"]  # checked against the other step's form
    case_id = str(ctx.data["container"])
    try:
        builder = parts.version_document(params.output)
        approved = package_release.own_version(case_id, version, step=params.from_step)
    except (parts.UnknownOutput, KeyError) as exc:
        return kinds.Fail(str(exc))
    data = builder.data(approved["content"], package=ctx.data.get("name") or case_id, version=version,
                        approved_by=approved.get("approved_by"), approved_at=approved.get("approved_at"),
                        output=params.output)
    return kinds.Done({"output": data.output, "version": version, "values": len(data.values)})


CAPABILITY = capabilities.Capability(
    name="priced_document", version=1, module=_OWNER, run=_run, kind="machine", params=PricedDocument, state="step",
    output=DocumentResult, rule_files=("outputs",), choices={"output": _outputs},
    summary="Fills a priced document from an output template: an approved version of the step it names, as that"
            " output's domain builds it.")


def register() -> None:
    capabilities.register(CAPABILITY)


__all__ = ["CAPABILITY", "DocumentResult", "PricedDocument", "register"]
