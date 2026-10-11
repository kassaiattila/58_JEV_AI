"""146 (backlog D-bank-files, the owner's request of 2026-10-11): which bank files the system processes today.

The catalogue (`configs/bank_files.json`) names, per kind of file, its reader - a profile of
`configs/statement_tables.json` (read by code, free) or a bank statement type pack (extracted by AI, paid) - with what a
person needs to know: the bank, the statement, the file formats, the line facts it reads, its checks and notes. What the
readers' own configuration says is added here, so that it cannot drift from them:

- for a code profile: the kind of statement, the file types its layout reads and the readers' configuration version;
- for an AI type: its fields and checks (the type pack's fields, list fields and validators) and its version;
- for both: the line facts it does not read, the statement line fields of the tabular type pack (`statement_table`,
  the fullest line) it lacks.

A reader with no entry is still listed, from its configuration alone, and named by `problems()`; a test keeps that list
empty and holds each code profile's listed facts to what the reader gives on synthetic files. The same catalogue is
served to the interface (`GET /bank-files`) and written as `docs/BANK_FILES.md` (`python -m jav.cli docs`).

Layer: UI/CLI → **this** (read only: no store, no AI call) → `jav.cfg`, `jav.typepack`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jav import cfg, typepack
from jav.config import PROJECT_ROOT

CONFIG = "bank_files"
DOC = PROJECT_ROOT / "docs" / "BANK_FILES.md"
TABLE_TYPE = "statement_table"  # the code-only type pack: its line fields are the fullest statement line
ACCEPTED_PARENT = "bank_statement"
# the header facts of a statement, in the order shown (the bank statement type packs' own fields)
HEADER_FIELDS = ("account_no", "account_iban", "currency", "period_start", "period_end", "opening_balance",
                 "closing_balance", "total_debit", "total_credit")
# a line's direction and its original amount's currency go with the amount: never listed on their own
IMPLIED_FIELDS = ("direction", "original_currency")
# the file types each reader layout reads (jav/statement_table.py: SUFFIXES, TEXT_SUFFIXES and the layouts)
LAYOUT_SUFFIXES = {"table": (".xlsx", ".csv"), "ledger": (".xml", ".pdf"), "camt053": (".xml",)}
VALIDATOR_CHECKS = {"running_balance_check": "running_balance", "closing_balance_check": "closing_balance",
                    "totals_consistency": "totals", "period_dates": "period_dates"}
# English names of the fields whose key does not read as words (the document only; the interface uses field_labels)
DOC_NAMES = {"account_no": "account number", "account_iban": "IBAN", "end_to_end_id": "end-to-end id"}


class BankFilesError(ValueError):
    """The catalogue names a reader, field or check that does not exist."""


def _config() -> dict[str, Any]:
    return cfg.load(CONFIG)


def _profiles() -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in cfg.load("statement_tables")["profiles"]}


def _ai_types() -> list[str]:
    """The bank statement type packs an AI extracts (a code-only pack is a profile's carrier, not a reader)."""
    return sorted(k for k in typepack.extractable_keys() if typepack.get(k).parent == ACCEPTED_PARENT)


def line_fields() -> list[str]:
    """Every fact a statement line can hold, in the tabular type pack's order."""
    return [f for f in typepack.get(TABLE_TYPE).list_fields["transactions"] if f not in IMPLIED_FIELDS]


def _profile_facts(profile: dict[str, Any], version: str) -> dict[str, Any]:
    layout = profile.get("layout") or "table"
    suffixes = profile.get("suffixes") or LAYOUT_SUFFIXES.get(layout, ())
    return {"read_by": "code", "institution": profile.get("institution"), "kinds": [profile.get("statement_type")],
            "suffixes": list(suffixes), "encodings": list(profile.get("encodings") or []), "layout": layout,
            "version": f"statement_tables {version}"}


def _type_facts(key: str) -> dict[str, Any]:
    pack = typepack.get(key)
    lines = [f for f in pack.list_fields.get("transactions", {}) if f not in IMPLIED_FIELDS]
    checks = [VALIDATOR_CHECKS[v["check"]] for v in pack.validators if v.get("check") in VALIDATOR_CHECKS]
    return {"read_by": "ai", "institution": None, "kinds": list(pack.enums.get("statement_type", ())),
            "suffixes": [".pdf"], "encodings": [], "layout": None, "version": f"{key} {pack.version}",
            "document": pack.document, "header": [f for f in HEADER_FIELDS if f in pack.fields], "reads": lines,
            "checks": checks}


def _check(entry: dict[str, Any], known_fields: set[str], known_checks: set[str]) -> None:
    for f in entry.get("header", []) + entry.get("reads", []):
        if f not in known_fields:
            raise BankFilesError(f"{entry['id']}: unknown field {f!r}")
    for c in entry.get("checks", []):
        if c not in known_checks:
            raise BankFilesError(f"{entry['id']}: unknown check {c!r}")


def catalogue() -> dict[str, Any]:
    """The catalogue with every reader's facts from its configuration; a reader without an entry is listed too
    (`described` false)."""
    conf = _config()
    profiles, table_version = _profiles(), cfg.version("statement_tables")
    ai_types = _ai_types()
    lines = line_fields()
    known_fields, known_checks = set(lines) | set(HEADER_FIELDS), set(conf["checks"])
    files: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in conf["files"]:
        reader = raw["reader"]
        if "profile" in reader:
            if reader["profile"] not in profiles:
                raise BankFilesError(f"{raw['id']}: no reader profile {reader['profile']!r}")
            facts = _profile_facts(profiles[reader["profile"]], table_version)
            seen.add(("profile", reader["profile"]))
        else:
            if reader["type"] not in ai_types:
                raise BankFilesError(f"{raw['id']}: no bank statement type pack {reader['type']!r}")
            facts = _type_facts(reader["type"])
            seen.add(("type", reader["type"]))
        entry = {**facts, **raw, "described": True}
        _check(entry, known_fields, known_checks)
        entry["not_read"] = [f for f in lines if f not in entry.get("reads", [])]
        files.append(entry)
    for name, profile in profiles.items():  # a reader nobody described yet: its configuration alone
        if ("profile", name) not in seen:
            facts = _profile_facts(profile, table_version)
            files.append({**facts, "id": name, "reader": {"profile": name}, "bank": profile.get("institution"),
                          "statement": None, "formats": [], "header": [], "reads": [], "checks": [], "notes": [],
                          "not_read": [], "described": False})
    for key in ai_types:
        if ("type", key) not in seen:
            facts = _type_facts(key)
            files.append({**facts, "id": key, "reader": {"type": key}, "bank": None, "statement": facts["document"],
                          "formats": [], "notes": [], "described": False,
                          "not_read": [f for f in lines if f not in facts["reads"]]})
    return {"version": conf["meta"]["version"], "intro": conf["intro"], "read_by": conf["read_by"],
            "checks": conf["checks"], "files": files, "not_read": conf["not_read"]}


def labels() -> dict[str, str]:
    """The interface's names of the facts (`configs/field_labels.json`): a statement's from its fields, a line's from
    the columns."""
    names = cfg.load("field_labels")
    out = {f: names["fields"][f] for f in HEADER_FIELDS if f in names["fields"]}
    out.update({f: names["columns"][f] for f in line_fields() if f in names["columns"]})
    return out


def problems() -> list[str]:
    """The readers the catalogue does not describe yet."""
    return [f"{'profile' if 'profile' in e['reader'] else 'type pack'} {e['id']} has no entry in configs/bank_files.json"
            for e in catalogue()["files"] if not e["described"]]


# --- the codebase document ---------------------------------------------------------------------------------------------


def _name(field: str) -> str:
    return DOC_NAMES.get(field, field.replace("_", " "))


def _names(fields: list[str]) -> str:
    return ", ".join(_name(f) for f in fields) or "–"


def markdown() -> str:
    """`docs/BANK_FILES.md`: the catalogue in English, generated (never edited by hand)."""
    cat = catalogue()
    out = [
        "# Bank files the system reads",
        "",
        "<!-- Generated by `python -m jav.cli docs` from `configs/bank_files.json` and the readers' own configuration"
        " (`configs/statement_tables.json`, the bank statement type packs). Do not edit by hand. -->",
        "",
        "## Plain-language summary",
        "",
        cat["intro"],
        "",
        f"Catalogue version {cat['version']}. The interface shows the same list under New work package › Bank statements.",
        "",
        "| File | Bank | Read by | File types | Checks |",
        "|---|---|---|---|---|",
    ]
    for e in cat["files"]:
        checks = "; ".join(cat["checks"].get(c, c) for c in e["checks"]) or "–"
        out.append(f"| {e['statement'] or e['id']} | {e['bank'] or '–'} | {cat['read_by'][e['read_by']]} | "
                   f"{' '.join(e['suffixes'])} | {checks} |")
    for e in cat["files"]:
        out += ["", f"## {e['bank'] or e['id']}: {e['statement'] or e['id']}", ""]
        out.append(f"- **Read by:** {cat['read_by'][e['read_by']]} ({'profile' if 'profile' in e['reader'] else 'type pack'}"
                   f" `{e['reader'].get('profile') or e['reader'].get('type')}`, {e['version']}).")
        if e["formats"]:
            out.append("- **Files:** " + "; ".join(e["formats"]) + ".")
        out.append(f"- **Statement:** {_names(e['header'])}.")
        out.append(f"- **Each line:** {_names(e['reads'])}.")
        out.append(f"- **Not read:** {_names(e['not_read'])}.")
        if e["checks"]:
            out.append("- **Checks:** " + "; ".join(cat["checks"][c] for c in e["checks"]) + ".")
        for n in e["notes"]:
            out.append(f"- {n}")
        if not e["described"]:
            out.append("- Not described yet: only its configuration is known.")
    out += ["", "## Files no reader knows", ""] + [f"- {t}" for t in cat["not_read"]]
    return "\n".join(out) + "\n"


def write_doc(path: Path = DOC) -> Path:
    path.write_text(markdown(), encoding="utf-8", newline="\n")
    return path
