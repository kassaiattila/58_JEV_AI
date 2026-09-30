"""047 T1.1: legacy type copy (`configs/legacy_types/<key>/`) → full type pack (`configs/types/<key>.json`).

The owner's decision (2026-09-28, `docs/DECISIONS.md` "047"): the 15 legacy types that exist only as copies become full
packs, so that after detection they run on the same flow, UI and review path as the invoices.

What it does (deterministic, without AI calls):
- the legacy `schema.json` and `prompt.md` go VERBATIM into `jav/prompts/` (the G path's output model and prompt are
  unchanged);
- a KIND per field from the name, the JSON type, the description and the legacy `rules.json` `money_fields` list
  (`guess_kind`); itemised lists (`list_fields`) and enumerated values (`enums`) from the schema;
- validators from the legacy `rules.json` `named` list and the `fields.<field>.regex` format rules;
- for detection: the coarse category (`parent`, from `old_type_map` in `configs/doc_types.json`) and the legacy
  `detect.json` (required / supporting / excluding keywords); `auto_detect=false` for types that were dependent in the
  legacy project too;
- a G path verification call site (`configs/callsites/verify_<key>.json`, inheriting the Noul questions of `verify`)
  with English field descriptions; no S path (the candidate finders are invoice-specific), hence `arms = ["G"]`;
- provenance: source path, the sha256 of the legacy files from the manifest (`meta.source`).

The output is data reviewed like code: the runtime loads the pack, not this module. Rerunning gives the same result.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from jav.config import PROJECT_ROOT, PROMPTS_DIR

LEGACY_DIR = PROJECT_ROOT / "configs" / "legacy_types"
TYPES_DIR = PROJECT_ROOT / "configs" / "types"
CALLSITES_DIR = PROJECT_ROOT / "configs" / "callsites"
REQUEST_CHAR_BUDGET = 110000  # JEV request limit (~62k tokens; Hungarian text ~2.5 chars/token), as at the utility site
PENDING = ("csapatmenedzser_utasitas", "meghivo", "terkep_adat")  # were dependent in legacy V4 too (DECISIONS 047/3)

# English document description (JEV checklist: English instructions; the state stays verbatim Hungarian text).
DOCUMENT = {
    "altalanos_szerzodesi_feltetelek": "Hungarian general terms and conditions (ÁSZF) of a seller or service provider",
    "belepo_jegy": "Event admission ticket (e.g. a stadium or concert ticket), Hungarian or English",
    "certificate": "Certificate or attestation issued to a person (training, qualification, membership), not a tax authority document",
    "csapatmenedzser_utasitas": "Instruction issued to a sports team manager by an organising body",
    "id_document": "Personal identity document (ID card, social security card, passport, address card)",
    "insurance_claim_form": "Insurance claim or notification form (possibly blank), Hungarian",
    "invoice_out": "Outgoing (issued) Hungarian invoice, where our company is the SUPPLIER",
    "meeting_minutes": "Minutes of a meeting (general assembly, board meeting) with attendees, agenda and resolutions, Hungarian",
    "meghivo": "Invitation to an event or meeting",
    "nav_certificate": "Hungarian tax authority (NAV) certificate or income statement issued to a taxpayer",
    "nav_receipt": "Hungarian tax authority (NAV) receipt, acknowledgement or notification (e.g. filing accepted, card payment confirmed)",
    "nav_tax_return": "Hungarian tax return form or its summary (NAV form code, tax year, total tax)",
    "statement_cib": "CIB Bank account or credit card statement with balances and a transaction list, Hungarian",
    "statement_erste": "Erste Bank account or credit card statement with balances and a transaction list, Hungarian",
    "terkep_adat": "Map extract or map data sheet listing notable locations",
}

_NAME_WORDS = ("issuer", "authority", "insurer", "organizer", "issuing_body", "recipient", "claimant_name")


def guess_kind(name: str, prop: dict[str, Any], money: set[str]) -> str:
    """Field kind from the legacy schema. Money: the legacy `money_fields` or the "decimal STRING" description; date: by
    name (not with a time of day: `…datetime` stays text); in doubtful cases `text` (normalisation only adjusts
    whitespace)."""
    types = prop.get("type", "string")
    types = [t for t in (types if isinstance(types, list) else [types]) if t != "null"]
    t = types[0] if types else "string"
    desc = str(prop.get("description", "")).lower()
    if t == "array":
        return "list"
    if t == "boolean":
        return "boolean"
    if t in ("integer", "number"):
        return "number"
    if name in money or "decimal string" in desc or re.search(r"(^|_)(amount|balance)$", name):
        return "money"
    if name.endswith("iban"):
        return "iban"
    if name.endswith("tax_id"):
        return "tax_id"
    if name == "currency":
        return "currency"
    if name == "invoice_number":
        return "invoice_number"
    if "datetime" in name:
        return "text"
    if name.endswith("_date") or name in ("date", "valid_until", "period_start", "period_end") or "yyyy-mm-dd" in desc:
        return "date"
    if "address" in name:
        return "address"
    if name in ("event_name", "area_name"):  # name of an event / area: not a person or organisation
        return "text"
    if name.endswith("_name") or name in _NAME_WORDS:
        return "name"
    return "text"


def _item_kinds(field: str, prop: dict[str, Any], money: set[str]) -> dict[str, str]:
    items = prop.get("items", {})
    if "properties" not in items:
        return {"*": guess_kind(field, items, money)}
    return {sub: guess_kind(sub, p, money) for sub, p in items["properties"].items()}


def _enums(schema: dict[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for f, p in schema["properties"].items():
        if "enum" in p:
            out[f] = list(p["enum"])
        for sub, sp in p.get("items", {}).get("properties", {}).items():
            if "enum" in sp:
                out[f"{f}[].{sub}"] = list(sp["enum"])
    return out


def _validators(rules: dict[str, Any], fields: dict[str, str]) -> list[dict[str, Any]]:
    out = [dict(v) for v in rules.get("named", [])]
    for f, spec in rules.get("fields", {}).items():
        if "regex" in spec and f in fields:
            out.append({"check": "format", "field": f, "regex": spec["regex"], "optional": True})
    return out


def _field_spec(field: str, prop: dict[str, Any]) -> str:
    words = field.replace("_", " ")
    desc = str(prop.get("description", "")).strip()
    return f"the {words} as printed on the document" + (f" ({desc})" if desc and desc.isascii() else "")


def convert(key: str, *, old_type_map: dict[str, str]) -> dict[str, Any]:
    """One legacy type into a full pack: the contents of the pack, schema, prompt and call-site files (without
    writing)."""
    src = LEGACY_DIR / key
    schema = json.loads((src / "schema.json").read_text(encoding="utf-8"))
    rules = json.loads((src / "rules.json").read_text(encoding="utf-8"))
    detect = json.loads((src / "detect.json").read_text(encoding="utf-8"))
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    money = set(rules.get("money_fields", []))
    props: dict[str, Any] = schema["properties"]
    fields = {f: guess_kind(f, p, money) for f, p in props.items()}
    list_fields = {f: _item_kinds(f, props[f], money) for f, k in fields.items() if k == "list"}
    scalars = [f for f, k in fields.items() if k != "list"]
    required = [f for f in rules.get("required", []) if f in fields]
    non_scored = set(rules.get("non_scored_fields", []))
    pack = {
        "meta": {
            "name": f"type:{key}",
            "version": "1.0.0",
            "changelog": [{"version": "1.0.0", "date": "2026-09-28",
                           "note": "047 T1.1: a régi típus-másolatból átalakítva (jav/typepack_convert.py); séma és prompt verbatim; csak G-kar"}],
            "source": {"path": f"10_AIFLOW_V4/flows/doc-extract-bare/types/{key}", "via": f"configs/legacy_types/{key}",
                       "sha256": manifest["files"]},
        },
        "document": DOCUMENT[key],
        "golden_type_key": key,
        "candidate_profile": "intl",
        "arms": ["G"],
        "parent": old_type_map[key],
        "auto_detect": key not in PENDING,
        "detect": {k: detect[k] for k in ("required_any", "supporting", "excluders") if k in detect},
        "prompt_file": f"{key}_prompt.md",
        "schema_file": f"{key}_schema.json",
        "select_callsite": None,
        "verify_callsite": f"verify_{key}",
        "fields": fields,
        "list_fields": list_fields,
        "enums": _enums(schema),
        "scored_fields": [f for f in scalars if f not in non_scored],
        "informational_fields": [],
        "required": required,
        "validators": _validators(rules, fields),
        "legacy_transforms": list(rules.get("transforms", [])),
    }
    callsite = {
        "meta": {"name": f"verify_{key}", "version": "1.1.0",
                 "changelog": [{"version": "1.1.0", "date": "2026-09-28",
                                "note": "047 T1.5: request_char_budget 110000 (mint a közmű-hívási helyen): a hosszú iratoknál (általános szerződési feltételek) a teljes szöveg-state max_tokens_exceeded hibát adott"},
                               {"version": "1.0.0", "date": "2026-09-28",
                                "note": "047 T1.1: G-kar ellenőrző hívási hely a régi típusból átalakítva; a Noul-kérdések a verify.json-ból öröklődnek"}]},
        "inherits": "verify",
        "request_id": f"verify_{key}",
        "document": DOCUMENT[key],
        "glossary": f"Document type: {DOCUMENT[key]}. Field names are English identifiers; the document text is verbatim, usually Hungarian.",
        "glossary_in_state": True,
        "request_char_budget": REQUEST_CHAR_BUDGET,
        "field_specs": {f: _field_spec(f, props[f]) for f in scalars},
        "incomplete_fields": [f for f in scalars if fields[f] in ("name", "address")],
        "wrong_kind_fields": [f for f in scalars if fields[f] in ("tax_id", "iban", "invoice_number")],
    }
    return {"pack": pack, "callsite": callsite, "prompt_src": src / "prompt.md", "schema_src": src / "schema.json"}


def write(key: str, *, old_type_map: dict[str, str]) -> list[Path]:
    out = convert(key, old_type_map=old_type_map)
    paths = [TYPES_DIR / f"{key}.json", CALLSITES_DIR / f"verify_{key}.json", PROMPTS_DIR / f"{key}_prompt.md", PROMPTS_DIR / f"{key}_schema.json"]
    for path, data in zip(paths[:2], (out["pack"], out["callsite"])):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    shutil.copyfile(out["prompt_src"], paths[2])
    shutil.copyfile(out["schema_src"], paths[3])
    return paths


def main() -> int:
    doc_types = json.loads((PROJECT_ROOT / "configs" / "doc_types.json").read_text(encoding="utf-8"))
    old_type_map = doc_types["old_type_map"]
    keys = sorted(p.name for p in LEGACY_DIR.iterdir() if p.is_dir())
    for key in keys:
        for p in write(key, old_type_map=old_type_map):
            print(p.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
