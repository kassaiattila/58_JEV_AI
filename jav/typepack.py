"""Type pack: ALL type-specific data of a document type's data-point extraction in one JSON
(`configs/types/<type>.json`, `cfg.load("type:<type>")`), while the code is a type-independent mechanism.

What the pack contains (a mirror of the legacy 10_AIFLOW_V4 `types/<key>/` pack, as data):
- `fields`: the header fields in order, each with its KIND (`name`, `tax_id`, `date`, `money`, `iban`, `currency`,
  `country`, `invoice_number`, `address`, `text`, `number`) - the kind decides normalisation, comparison (golden set),
  the candidate kind (S path) and evidence matching (G path);
- `scored_fields` / `informational_fields` (the legacy `_compare_contract` and `rules.json non_scored_fields`),
  `required` (rules.json), `high_stakes` (policy), `validators` (rules.json `named` + `fields` format rules);
- `prompt_file` + `schema_file` (the legacy prompt.md and schema.json verbatim, `jav/prompts/`), from which the G path's
  output model is built (`llm_model()`: a Pydantic model from the JSON schema, `extra="forbid"`);
- `select_callsite` / `verify_callsite`: the settings files of the JEV call sites; `candidate_profile`: the regex set of
  the candidate finders (`hu` = the Hungarian invoice's existing behaviour, bit for bit, `intl` = international
  extension, `utility` = the OCR-tolerant set for Hungarian utility bills);
- `text_labels` (2026-09-20, utility round): the labels of the free-text fields (`text` kind) on the document (a regex
  list per field) - the labelled text finder (`candidates.find_labelled_text`) yields candidates from it, JEV chooses;
- `extends` (2026-09-20): a base pack (`configs/types/_base/<name>.json`, e.g. the legacy `_shared/utility_bill_hu`),
  whose fields, lists, validators and schema file are placed before the child's (the legacy `extends` semantics:
  base + child); a base pack is not a runnable type on its own (it has no prompt), and `keys()` does not list it.

New type = new JSON (+ prompt, schema, two call-site files) - without Python code, if the kinds suffice.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from jav import cfg
from jav.config import PROMPTS_DIR

KINDS = ("name", "tax_id", "date", "money", "iban", "currency", "country", "invoice_number", "address", "text", "number",
         "boolean", "list")  # 047: yes/no field; itemised list (the kinds of the item fields are in `list_fields`)
CANDIDATE_KIND_OF = {  # field kind -> candidate kind (S path); others: no candidate pick (Choice list or nothing)
    "name": "name", "tax_id": "tax_id", "date": "date", "money": "money", "iban": "iban", "invoice_number": "invoice_number", "address": "address",
    "number": "quantity",  # kWh, m3, MJ, meter reading: numbers of unit/meter-labelled rows (candidates.find_quantities)
}
DEFAULT_KEY = "invoice_hu"
BASE_PREFIX = "_base/"


class TypePack(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    version: str
    document: str
    golden_type_key: str
    candidate_profile: str = "hu"
    prompt_file: str
    schema_file: str
    base_schema_file: str | None = None  # the base pack's schema (the start of the fields), with `extends`
    extends: str | None = None
    select_callsite: str | None  # None: no S path (047: packs converted from legacy types, G path only)
    verify_callsite: str
    arms: tuple[str, ...] = ("S", "G")  # the paths runnable with the pack
    default_arm: str | None = None  # 053 T3: pack's path for an `auto` recipe (utility: G, it also yields line items)
    parent: str | None = None  # 047: the coarse detection category (configs/doc_types.json) of this detailed type
    auto_detect: bool = True  # 047: may detection pick it (no for types that were dependent in the legacy project too)
    detect: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # 047: legacy detect.json keyword lists
    fields: dict[str, str]  # field -> kind (order = the schema's order)
    scored_fields: tuple[str, ...]
    informational_fields: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    high_stakes: tuple[str, ...] = ()
    validators: tuple[dict[str, Any], ...] = ()
    text_labels: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # `text`-kind field -> label regexes (finder)
    list_fields: dict[str, dict[str, str]] = Field(default_factory=dict)  # 047: `list` field -> item field -> kind ({"*": kind}: plain list)
    enums: dict[str, tuple[Any, ...]] = Field(default_factory=dict)  # 047: `field` / `field[].item` -> allowed values
    config_hash: str

    # --- field lists by kind ---------------------------------------------------------------

    @property
    def header_fields(self) -> tuple[str, ...]:
        """The scalar (single-valued) fields: these have candidates, verification, source location and field
        correction."""
        return tuple(f for f, k in self.fields.items() if k != "list")

    @property
    def record_fields(self) -> tuple[str, ...]:
        """Every field in the schema's order, including the itemised lists (the keys of the saved `datapoints`)."""
        return tuple(self.fields)

    def normalize(self, data: dict[str, Any]) -> tuple[Any, list[str]]:
        """Generative extract -> normalised record according to the pack's kinds, item descriptions and enumerations."""
        from jav.models import record_from_llm

        return record_from_llm(data, self.fields, list_fields=self.list_fields, enums={k: list(v) for k, v in self.enums.items()})

    def kind(self, field: str) -> str:
        return self.fields.get(field, "text")

    def of_kind(self, *kinds: str) -> tuple[str, ...]:
        return tuple(f for f, k in self.fields.items() if k in kinds)

    @property
    def money_fields(self) -> tuple[str, ...]:
        return self.of_kind("money")

    @property
    def date_fields(self) -> tuple[str, ...]:
        return self.of_kind("date")

    @property
    def tax_id_fields(self) -> tuple[str, ...]:
        return self.of_kind("tax_id")

    @property
    def strict_scored(self) -> tuple[str, ...]:
        """Scored fields that are not merely informational (the legacy contract: IBAN and addresses do not count towards
        accuracy)."""
        return tuple(f for f in self.scored_fields if f not in self.informational_fields)

    @property
    def is_default(self) -> bool:
        return self.key == DEFAULT_KEY

    # --- schema / prompt -------------------------------------------------------------------

    @property
    def schema_files(self) -> tuple[str, ...]:
        return ((self.base_schema_file,) if self.base_schema_file else ()) + (self.schema_file,)

    def schema(self) -> dict[str, Any]:
        """The legacy schema (base + child merged: `properties` starting in the base's order, `required` as the
        union)."""
        return _merged_schema(self.schema_files)

    def llm_model(self) -> type[BaseModel]:
        """The G path's output model. For the Hungarian invoice, the hand-written `InvoiceLLM` (a 1:1 mirror of the
        legacy schema, referenced by tests); for other types, a model generated from the legacy schema.json (base +
        child) (`extra="forbid"`, every field nullable)."""
        if self.is_default:
            from jav.models import InvoiceLLM

            return InvoiceLLM
        return _model_from_schema(self.key, self.schema_files)


def _read_schema(name: str) -> dict[str, Any]:
    return json.loads((PROMPTS_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _merged_schema(files: tuple[str, ...]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for name in files:
        s = _read_schema(name)
        for k, v in s.get("properties", {}).items():
            props.setdefault(k, v)
        for k in s.get("required", []):
            if k not in required:
                required.append(k)
    return {"type": "object", "additionalProperties": False, "properties": props, "required": required}


def _py_type(prop: dict[str, Any], name: str, owner: str) -> Any:
    types = prop.get("type", ["string", "null"])
    if isinstance(types, str):
        types = [types]
    if "array" in types:
        item_schema = prop.get("items", {})
        item_model = _sub_model(f"{owner}_{name}_item", item_schema)
        return list[item_model]  # type: ignore[valid-type]
    base = [t for t in types if t != "null"]
    t = base[0] if base else "string"
    return {"string": str, "number": float, "integer": int, "boolean": bool}.get(t, str) | None  # type: ignore[return-value]


def _sub_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for prop_name, prop in schema.get("properties", {}).items():
        fields[prop_name] = (_py_type(prop, prop_name, name), Field(default=None, description=prop.get("description")))
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


@lru_cache(maxsize=None)
def _model_from_schema(key: str, schema_files: tuple[str, ...]) -> type[BaseModel]:
    schema = _merged_schema(schema_files)
    fields: dict[str, Any] = {}
    for prop_name, prop in schema["properties"].items():
        if prop.get("type") == "array":
            fields[prop_name] = (_py_type(prop, prop_name, f"LLM_{key}"), Field(default_factory=list, description=prop.get("description")))
        else:
            fields[prop_name] = (_py_type(prop, prop_name, f"LLM_{key}"), Field(default=None, description=prop.get("description")))
    model = create_model(f"LLM_{key}", __config__=ConfigDict(extra="forbid"), **fields)
    model.__doc__ = f"{key} kivonata a régi schema.json-ból generálva ({', '.join(schema_files)}); minden mező nullable, pénz decimális string ponttal, dátum ISO."
    return model


def _dedup(*lists: list[Any]) -> tuple[Any, ...]:
    out: list[Any] = []
    for lst in lists:
        for x in lst:
            if x not in out:
                out.append(x)
    return tuple(out)


@lru_cache(maxsize=None)
def get(key: str = DEFAULT_KEY) -> TypePack:
    """The type pack, loaded and checked (`FileNotFoundError` if there is no such type pack). With `extends`, the base
    pack's fields / lists / validators / schema are merged in before the child's; `config_hash` covers both."""
    data = cfg.load(f"type:{key}")
    extends = data.get("extends")
    base: dict[str, Any] = cfg.load(f"type:{BASE_PREFIX}{extends}") if extends else {}
    fields = {**dict(base.get("fields", {})), **dict(data["fields"])}
    bad = [f"{f}:{k}" for f, k in fields.items() if k not in KINDS]
    if bad:
        raise ValueError(f"ismeretlen mező-fajta a(z) {key} típus-csomagban: {bad}")
    lists = {name: _dedup(list(base.get(name, [])), list(data.get(name, []))) for name in ("scored_fields", "informational_fields", "required", "high_stakes")}
    for name, lst in lists.items():
        unknown = [f for f in lst if f not in fields]
        if unknown:
            raise ValueError(f"{key}.{name}: nem a csomag mezője: {unknown}")
    validators = _dedup([dict(v) for v in base.get("validators", ())], [dict(v) for v in data.get("validators", ())])
    text_labels = {**{f: tuple(v) for f, v in base.get("text_labels", {}).items()}, **{f: tuple(v) for f, v in data.get("text_labels", {}).items()}}
    unknown_labels = [f for f in text_labels if fields.get(f) != "text"]
    if unknown_labels:
        raise ValueError(f"{key}.text_labels: csak `text` fajtájú mezőhöz adható címke: {unknown_labels}")
    list_fields = {**{f: dict(v) for f, v in base.get("list_fields", {}).items()}, **{f: dict(v) for f, v in data.get("list_fields", {}).items()}}
    bad_lists = [f for f in list_fields if fields.get(f) != "list"] + [f for f, k in fields.items() if k == "list" and f not in list_fields]
    bad_items = [f"{f}.{sub}:{k}" for f, v in list_fields.items() for sub, k in v.items() if k in ("list",) or k not in KINDS]
    if bad_lists or bad_items:
        raise ValueError(f"{key}.list_fields: a `list` mezők és a tétel-leírások nem egyeznek: {bad_lists + bad_items}")
    enums = {**{f: tuple(v) for f, v in base.get("enums", {}).items()}, **{f: tuple(v) for f, v in data.get("enums", {}).items()}}
    bad_enums = [e for e in enums if e.split("[")[0] not in fields]
    if bad_enums:
        raise ValueError(f"{key}.enums: nem a csomag mezője: {bad_enums}")
    inherit = lambda name, default=None: data.get(name, base.get(name, default))  # noqa: E731
    arms = tuple(inherit("arms", ["S", "G"]))
    default_arm = inherit("default_arm")
    if default_arm is not None and default_arm not in arms:
        raise ValueError(f"{key}.default_arm: {default_arm} nem a csomag kara ({', '.join(arms)})")
    # 067 (066 Á18): the identifier covers the type JSON(s) and the contents of the G path's prompt and schema files
    type_names = [f"type:{key}", *([f"type:{BASE_PREFIX}{extends}"] if extends else [])]
    prompt_files = [data["prompt_file"], *([base["schema_file"]] if base.get("schema_file") else []), data["schema_file"]]
    return TypePack(
        key=key,
        version=str(data["meta"]["version"]),
        document=inherit("document"),
        golden_type_key=data.get("golden_type_key", key),
        candidate_profile=inherit("candidate_profile", "hu"),
        prompt_file=data["prompt_file"],
        schema_file=data["schema_file"],
        base_schema_file=base.get("schema_file"),
        extends=extends,
        select_callsite=inherit("select_callsite"),
        verify_callsite=inherit("verify_callsite"),
        arms=arms,
        default_arm=default_arm,
        parent=inherit("parent"),
        auto_detect=bool(inherit("auto_detect", True)),
        detect={k: tuple(v) for k, v in dict(inherit("detect", {})).items()},
        fields=fields,
        scored_fields=lists["scored_fields"],
        informational_fields=lists["informational_fields"],
        required=lists["required"],
        high_stakes=lists["high_stakes"],
        validators=validators,
        text_labels=text_labels,
        list_fields=list_fields,
        enums=enums,
        config_hash=cfg.combine(cfg.config_hash(*type_names), *(cfg.file_digest(PROMPTS_DIR / f) for f in prompt_files)),
    )


def keys() -> list[str]:
    return [n.split(":", 1)[1] for n in cfg.all_names() if n.startswith("type:") and not n.split(":", 1)[1].startswith(BASE_PREFIX)]


def catalog_hash() -> str:
    """067 (066 Á18): the joint identifier of all type packs (the options of the detailed-type question are the packs'
    descriptions)."""
    return cfg.combine(*(get(k).config_hash for k in sorted(keys())))


def resolve_arm(doc_type: str, preferred: str) -> str:
    """The type's actual path: the requested path if the pack supports it; otherwise the pack's first path (047: packs
    converted from legacy types run with the G path only). `auto` (053 T3): the pack's recommended path
    (`default_arm`), failing that its first path. The shared rule of the worker (`runtime/worker.arm_for`) and of the
    run's budget reservation (`work.run_budget`, 065)."""
    pack = get(doc_type)
    if preferred == "auto":
        return pack.default_arm or pack.arms[0]
    return preferred if preferred in pack.arms else pack.arms[0]


def reload() -> None:
    get.cache_clear()
    _model_from_schema.cache_clear()
    _merged_schema.cache_clear()


__all__ = ["KINDS", "CANDIDATE_KIND_OF", "DEFAULT_KEY", "BASE_PREFIX", "TypePack", "get", "keys", "resolve_arm", "reload"]
