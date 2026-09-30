"""047 T1.1: régi típus-másolat (`configs/legacy_types/<kulcs>/`) → teljes típuscsomag (`configs/types/<kulcs>.json`).

A felhasználó döntése (2026-09-28, `docs/DECISIONS.md` „047”): a 15 csak másolatként meglévő régi típus teljes csomag
lesz, hogy a felismerés után ugyanazon a folyamaton, felületen és ellenőrzési úton fusson, mint a számlák.

Mit csinál (determinisztikus, AI-hívás nélkül):
- a régi `schema.json` és `prompt.md` VERBATIM a `jav/prompts/`-ba (a G-kar kimeneti modellje és utasítása változatlan);
- mezőnként FAJTA a névből, a JSON-típusból, a leírásból és a régi `rules.json` `money_fields` listájából
  (`guess_kind`); tételes lista (`list_fields`) és felsorolt értékek (`enums`) a sémából;
- validátorok a régi `rules.json` `named` listájából és a `fields.<mező>.regex` formátum-szabályokból;
- a felismeréshez: durva kategória (`parent`, a `configs/doc_types.json` `old_type_map`-jéből) és a régi `detect.json`
  (kötelező / támogató / kizáró kulcsszavak); `auto_detect=false` a régiben is függő típusoknál;
- G-kar ellenőrző hívási hely (`configs/callsites/verify_<kulcs>.json`, a `verify` Noul-kérdéseit örökli) angol
  mező-leírásokkal; S-kar nincs (a jelöltkeresők számla-specifikusak), ezért `arms = ["G"]`;
- származás: forrás-útvonal, a régi fájlok sha256-ja a manifestből (`meta.source`).

A kimenet kódként ellenőrzött adat: a futtató a csomagot tölti be, nem ezt a modult. Újrafuttatás ugyanazt adja.
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
REQUEST_CHAR_BUDGET = 110000  # a JEV kérés-korlátja (~62 k token; magyar szöveg ~2,5 karakter / token), mint a közmű-hívási helyen
PENDING = ("csapatmenedzser_utasitas", "meghivo", "terkep_adat")  # a régiben is függő típusok (DECISIONS 047/3)

# Angol dokumentum-leírás (JEV-ellenőrzőlista: angol instrukció; a state verbatim magyar szöveg marad).
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
    """Mező-fajta a régi sémából. Pénz: a régi `money_fields` vagy a „decimal STRING” leírás; dátum: név szerint
    (időponttal együtt nem: az `…datetime` szöveg marad); kétes esetben `text` (a normalizálás csak szóközt igazít)."""
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
    if name in ("event_name", "area_name"):  # esemény / terület neve: nem személy vagy szervezet
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
    """Egy régi típus teljes csomaggá: a csomag-, séma-, prompt- és hívásihely-fájlok tartalma (írás nélkül)."""
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
