"""Önálló, offline típuscsomag-tervezet és szerkezeti bizonylat. Nem aktivál."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jav import cfg, store
from jav.config import load_prompt
from jav.document_learning import digest
from jav.typepack import TypePack, KINDS, get, keys
from jav.validators import _RECORD_CHECKS, _FIELD_CHECKS


class SampleRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    group: str = Field(min_length=1)
    split: Literal["development", "evaluation", "regression"]
    label: Literal["positive", "negative"]


class TypeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal["1.0"] = "1.0"
    parent_key: str
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    recognition_description: str = Field(min_length=1)
    exclusions: list[str] = Field(default_factory=list)
    pack: TypePack
    output_schema: dict
    extraction_prompt: str = Field(min_length=1)
    callsites: dict[str, dict]
    samples: list[SampleRef] = Field(default_factory=list)


def make_draft(base_key: str, key: str) -> TypeDraft:
    # Csak a meglévő regiszter kulcsait fogadjuk el; nincs tetszőleges fájlbetöltés.
    if base_key not in keys():
        raise ValueError("unknown base type")
    pack = get(base_key)
    return TypeDraft(parent_key=base_key,key=key,version="0.1.0",recognition_description=pack.document,
        pack=pack.model_copy(update={"key":key,"version":"0.1.0"}),output_schema=pack.schema(),
        extraction_prompt=load_prompt(pack.prompt_file),
        callsites={name:cfg.load("callsite:"+name) for name in (pack.select_callsite,pack.verify_callsite) if name})


def inspect_draft(draft: TypeDraft) -> dict:
    errors = []
    pack = draft.pack
    if pack.key != draft.key or pack.version != draft.version:
        errors.append("pack_identity_mismatch")
    fields = set(pack.fields)
    properties = draft.output_schema.get("properties", {})
    if draft.output_schema.get("type") != "object" or not isinstance(properties,dict):
        errors.append("object_schema_required")
        properties = {}
    for field,kind in pack.fields.items():
        if kind not in KINDS:
            errors.append("unsupported_field_kind:"+field)
        if field not in properties:
            errors.append("missing_schema_field:"+field)
        elif not isinstance(properties[field],dict):
            errors.append("invalid_schema_property:"+field)
        elif kind == "money":
            field_type = properties[field].get("type")
            if field_type != "string" and field_type not in (["string","null"], ["null","string"]):
                errors.append("money_requires_decimal_string:"+field)
    for name in ("required", "scored_fields", "informational_fields", "high_stakes"):
        if set(getattr(pack,name)) - fields:
            errors.append("unknown_field_reference:"+name)
    required = draft.output_schema.get("required", [])
    if not isinstance(required,list) or any(not isinstance(name,str) for name in required):
        errors.append("invalid_schema_required")
    elif set(required) - set(properties):
        errors.append("unknown_schema_required_field")
    for name in (n for n in (pack.select_callsite,pack.verify_callsite) if n):
        if name not in draft.callsites:
            errors.append("missing_callsite:"+name)
    for validator in pack.validators:
        name = validator.get("check")
        if name not in {*_RECORD_CHECKS, *_FIELD_CHECKS, "format"}:
            errors.append("unsupported_validator:"+str(name))
        elif name not in _RECORD_CHECKS and validator.get("field") not in fields:
            errors.append("unknown_validator_field:"+str(validator.get("field")))
        if name == "format":
            try:
                re.compile(validator["regex"])
            except (KeyError, TypeError, re.error):
                errors.append("invalid_validator_regex")
    dev = [s for s in draft.samples if s.split == "development"]
    evaluation = [s for s in draft.samples if s.split == "evaluation"]
    others = [s for s in draft.samples if s.split != "evaluation"]
    if ({s.source_sha256 for s in evaluation} & {s.source_sha256 for s in others}
            or {s.group for s in evaluation} & {s.group for s in others}):
        errors.append("sample_leakage")
    blockers = ["evaluation_not_run", "activation_not_implemented"]
    if not dev:
        blockers.append("development_samples_missing")
    if not evaluation:
        blockers.append("evaluation_samples_missing")
    if not any(s.label == "negative" for s in evaluation):
        blockers.append("evaluation_counterexamples_missing")
    payload = draft.model_dump(mode="json")
    return dict(draft_sha256=digest(json.dumps(payload,sort_keys=True,ensure_ascii=False)),
        key=draft.key,version=draft.version,status="invalid" if errors else "structurally_valid",
        errors=errors,activation_eligible=False,blockers=blockers,
        scope="draft field/schema/reference checks only; not semantic accuracy or production compatibility",
        draft=payload)


def save_receipt(work_id: str, report: dict) -> None:
    store.save_artifact("typepack_inspection",work_id,report)
