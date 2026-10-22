"""Teaching a new document type from its documents' general facts (197, plan 197 K2).

Plain-language summary: a document without a type pack gets general facts, each under a name GPT chose (197 K1: on
the tickets, most of a type pack's information is there, under its own names and in its own form). Teaching a type
starts from the development half of a held-out family (`configs/golden_facts.json`): the names that recur in at least
a few of its documents become field proposals, each with how many documents carry it, how many of its facts JEV
supports and the kind its values suggest (a date when every value is exactly one date, else text). GPT names the same
fact differently from document to document; code joins only the spellings of one name (case, spacing) and a document's
bilingual label ("Sor/Row" is "sor"), never synonyms ("mérkőzés", "meccs"): a person joins those, names the fields,
writes their meaning and decides which to keep; that edited draft becomes a type pack in a later step.
Only the development half is read, so the evaluation half stays unseen; no value is printed or kept, only names and
counts.

The edited draft (K2b, `configs/type_drafts/<key>.json`) names the type, its detection category, an English
description and its fields: each with its Hungarian label, kind, English meaning and whether it is scored. From it code
makes a candidate type pack the way the legacy converter made the converted packs (`jav/typepack_convert.py`, 047): the
pack, its extraction prompt and schema, and a verification call site that inherits the shared questions. A candidate
is never picked by detection (`auto_detect` false), so it changes no processing; it is measured on the family's
evaluation half only (its golden type key is its own, so no legacy case measures it in-sample). The entries of the
shared registries (the field labels, the type registry's category map, the capability catalog, the engine matrix and
the request pins of the tests) are listed for the person to add, so a registry file's own layout is never rewritten.

Layer: business module (reads the measured facts from the store, writes the candidate's config files); no AI call.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav import store
from jav.config import PROJECT_ROOT, PROMPTS_DIR

MIN_DOCUMENTS = 3
DRAFTS_DIR = PROJECT_ROOT / "configs" / "type_drafts"
TYPES_DIR = PROJECT_ROOT / "configs" / "types"
CALLSITES_DIR = PROJECT_ROOT / "configs" / "callsites"
REQUEST_CHAR_BUDGET = 110000  # as the converted packs' call sites (047 T1.5)
KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class TeachingError(ValueError):
    """The facts a proposal needs are missing, or a candidate cannot be made as asked."""


@dataclass(frozen=True)
class FieldProposal:
    """One recurring name of the development half's facts.

    - `key`: an identifier made from its most common spelling; `label`: that spelling;
    - `names`: every `entity.property` spelling it was found under;
    - `documents`: the development documents that carry it; `repeated`: those that carry it more than once;
    - `supported`: its facts JEV supports; `kind`: "date" when every value is exactly one date, else "text".
    """

    key: str
    label: str
    names: tuple[str, ...]
    documents: int
    repeated: int
    supported: int
    kind: str


def _norm(name: str) -> str:
    """The name a fact's spelling counts under: case and spacing folded; a bilingual label's first part ("Sor/Row",
    "kapu/csoport" -> "sor", "kapu")."""
    return " ".join(name.split("/", 1)[0].split()).casefold() or " ".join(name.split()).casefold()


def field_key(label: str) -> str:
    """An ASCII identifier of a fact's name ("Kapu/Gate" -> "kapu_gate", "Időpont" -> "idopont")."""
    plain = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "_", plain.casefold()).strip("_")
    return key if key and key[0].isalpha() else f"field_{key}" if key else "field"


def _one_date(value: Any) -> bool:
    from jav.dates import AmbiguousDate, read_date_input

    try:
        read_date_input(value)
    except AmbiguousDate:
        return True
    except ValueError:
        return False
    return True


def development_facts(family: str) -> dict[str, list[dict[str, Any]]]:
    """The checked facts of each development document of the family, from its latest measurement that gave an answer
    (`measure facts:<family>`); read only. A document without one is refused, so a proposal never rests on part of the
    half."""
    from jav import cfg

    shas = cfg.load("golden_facts")["families"][family]["development"]
    out: dict[str, list[dict[str, Any]]] = {}
    with store.connect() as c:
        for sha in shas:
            rows = c.execute("SELECT payload FROM native_outcomes WHERE item_id=? AND run_id LIKE ? ORDER BY rowid DESC",
                             (sha, f"measure-%-facts_{family}%")).fetchall()
            answered = [json.loads(r["payload"]) for r in rows]
            answered = [d for d in answered if d.get("interpretation")]
            if not answered:
                raise TeachingError(f"{family}: development document {sha[:12]} has no measured facts "
                                    f"(python -m jav.cli measure facts:{family})")
            out[sha] = [f for f in answered[0]["interpretation"]["facts"]
                        if f["grounding"] == "literal_match" and f["proposal"]["state"] == "stated"]
    return out


def propose(facts_by_document: dict[str, list[dict[str, Any]]], *, min_documents: int = MIN_DOCUMENTS) -> list[FieldProposal]:
    """The names that recur in at least `min_documents` documents, most frequent first (then by name)."""
    from jav import policy
    from jav.flow_native import SUPPORT_BAND

    spellings: dict[str, Counter] = defaultdict(Counter)
    names: dict[str, set[str]] = defaultdict(set)
    documents: Counter = Counter()
    repeated: Counter = Counter()
    supported: Counter = Counter()
    values: dict[str, list[Any]] = defaultdict(list)
    for facts in facts_by_document.values():
        seen: Counter = Counter()
        for f in facts:
            prop = f["proposal"]["property"]
            norm = _norm(prop)
            spellings[norm][prop.strip()] += 1
            names[norm].add(f"{f['proposal']['entity']}.{prop}")
            seen[norm] += 1
            values[norm].append(f["proposal"]["value"])
            support = f.get("semantic_support")
            supported[norm] += support is not None and policy.noul_band(support, SUPPORT_BAND) == "yes"
        for norm, n in seen.items():
            documents[norm] += 1
            repeated[norm] += n > 1
    out = []
    for norm, n in documents.items():
        if n < min_documents:
            continue
        label = spellings[norm].most_common(1)[0][0]
        kind = "date" if all(_one_date(v) for v in values[norm]) else "text"
        out.append(FieldProposal(key=field_key(norm), label=label, names=tuple(sorted(names[norm])), documents=n,
                                 repeated=repeated[norm], supported=supported[norm], kind=kind))
    return sorted(out, key=lambda p: (-p.documents, p.key))


def proposal_report(family: str, *, min_documents: int = MIN_DOCUMENTS) -> dict[str, Any]:
    """The family's field proposals from its development half's measured facts (names and counts only)."""
    facts = development_facts(family)
    proposals = propose(facts, min_documents=min_documents)
    return {"family": family, "half": "development", "documents": len(facts), "min_documents": min_documents,
            "fields": [asdict(p) for p in proposals]}


def shape(value: Any) -> str:
    """A value's written form without its content: a letter is `a`, a digit `d`, the rest stays ("2026-01-22T21:00" ->
    "dddd-dd-ddTdd:dd" keeps the separators, not the date)."""
    return re.sub(r"\d", "d", re.sub(r"[^\W\d_]", "a", str(value))) if value not in (None, "") else "(empty)"


def expected_shapes(family: str) -> dict[str, dict[str, int]]:
    """The written forms of the development half's expected values, per field: what a taught field has to be written
    like to match its labels (the evaluation half is not read)."""
    from jav import evals_facts

    out: dict[str, Counter] = defaultdict(Counter)
    for fc in evals_facts.cases(family):
        if fc.half == "development":
            for field, value in fc.case.expected.items():
                out[field][shape(value)] += 1
    return {field: dict(counts.most_common()) for field, counts in out.items()}


def print_proposal(report: dict[str, Any]) -> None:
    print(f"### Field proposals - {report['family']}, from the {report['documents']} development documents' facts\n")
    print("| key | label | documents | repeated | supported by JEV | kind |\n|---|---|---|---|---|---|")
    for p in report["fields"]:
        print(f"| {p['key']} | {p['label']} | {p['documents']} | {p['repeated']} | {p['supported']} | {p['kind']} |")


# --- the draft a person edits, and the candidate type pack made from it (K2b) -----------------------------------------


class DraftField(BaseModel):
    """One field of a taught type: its key, the Hungarian label shown, its kind, its English meaning (the extraction
    prompt's and the verification's description: what it is and how it is written), whether it is scored, and the
    fact names of the development half it joins (from `type-propose`; a record of where it came from)."""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1)
    kind: str
    meaning: str = Field(min_length=1)
    scored: bool = True
    names: tuple[str, ...] = ()

    @field_validator("kind")
    @classmethod
    def _kind(cls, kind: str) -> str:
        from jav.typepack import KINDS

        if kind not in KINDS or kind == "list":
            raise ValueError(f"a taught field's kind is one of {[k for k in KINDS if k != 'list']}")
        return kind


class TaughtDraft(BaseModel):
    """A taught type as a person wrote it (`configs/type_drafts/<key>.json`)."""

    model_config = ConfigDict(extra="forbid")
    meta: dict[str, Any]
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1)  # the type's Hungarian name in the interface
    family: str
    parent: str
    document: str = Field(min_length=1)
    fields: tuple[DraftField, ...] = Field(min_length=1)
    required: tuple[str, ...] = ()

    @field_validator("fields")
    @classmethod
    def _distinct(cls, fields: tuple[DraftField, ...]) -> tuple[DraftField, ...]:
        keys = [f.key for f in fields]
        if len(set(keys)) != len(keys):
            raise ValueError("a field key appears twice")
        if not any(f.scored for f in fields):
            raise ValueError("at least one field is scored")
        return fields


def load_draft(key: str, drafts_dir: Path = DRAFTS_DIR) -> TaughtDraft:
    path = drafts_dir / f"{key}.json"
    if not path.exists():
        raise TeachingError(f"no draft {path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path}")
    draft = TaughtDraft.model_validate_json(path.read_text(encoding="utf-8"))
    if draft.key != key:
        raise TeachingError(f"the draft {key} names itself {draft.key}")
    if set(draft.required) - {f.key for f in draft.fields}:
        raise TeachingError(f"{key}: a required field is not one of its fields")
    return draft


_SCHEMA_TYPE = {"number": ["number", "null"], "boolean": ["boolean", "null"]}
_WRITTEN = {"date": " Write it as an ISO date (YYYY-MM-DD).",
            "money": " Write it as a decimal number with a point, without thousands separators or currency."}


def candidate(draft: TaughtDraft, *, today: date | None = None) -> dict[str, Any]:
    """The candidate's files as data: the pack, the verification call site, the prompt text and the output schema."""
    day = (today or date.today()).isoformat()
    note = (f"197 (plan 197 K2): taught from the {draft.family} family's development half "
            f"(configs/type_drafts/{draft.key}.json, version {draft.meta.get('version', '?')}); a candidate: detection "
            "never picks it (auto_detect false); measured on the family's evaluation half only.")
    fields = {f.key: f.kind for f in draft.fields}
    pack = {
        "meta": {"name": f"type:{draft.key}", "version": "0.1.0", "changelog": [{"version": "0.1.0", "date": day, "note": note}],
                 "taught": {"family": draft.family, "draft": f"configs/type_drafts/{draft.key}.json", "state": "candidate"}},
        "document": draft.document,
        "golden_type_key": draft.key,
        "candidate_profile": "intl",
        "arms": ["G"],
        "parent": draft.parent,
        "auto_detect": False,
        "prompt_file": f"{draft.key}_prompt.md",
        "schema_file": f"{draft.key}_schema.json",
        "select_callsite": None,
        "verify_callsite": f"verify_{draft.key}",
        "fields": fields,
        "scored_fields": [f.key for f in draft.fields if f.scored],
        "informational_fields": [],
        "required": list(draft.required),
        "validators": [],
    }
    callsite = {
        "meta": {"name": f"verify_{draft.key}", "version": "0.1.0", "changelog": [{"version": "0.1.0", "date": day, "note": note}]},
        "inherits": "verify",
        "request_id": f"verify_{draft.key}",
        "document": draft.document,
        "glossary": f"Document type: {draft.document}. Field names are English identifiers; the document text is verbatim, "
                    "usually Hungarian.",
        "glossary_in_state": True,
        "request_char_budget": REQUEST_CHAR_BUDGET,
        "field_specs": {f.key: f.meaning for f in draft.fields},
        "incomplete_fields": [f.key for f in draft.fields if f.kind in ("name", "address")],
        "wrong_kind_fields": [f.key for f in draft.fields if f.kind in ("tax_id", "iban", "invoice_number")],
    }
    lines = [f"- `{f.key}`: {f.meaning.rstrip('.')}.{_WRITTEN.get(f.kind, '')}" for f in draft.fields]
    prompt = (f"<!-- 197 (plan 197 K2): made from configs/type_drafts/{draft.key}.json by jav/type_teaching.py; "
              "edit the draft, not this file. -->\n"
              f"You read {draft.document[0].lower()}{draft.document[1:]}. The source text is the document itself, one line "
              "per printed line.\n\nExtract these fields; leave a field null when the document does not state it:\n\n"
              + "\n".join(lines) + "\n\nCopy each value as it is printed, unless its description says how to write it.\n")
    schema = {"type": "object", "additionalProperties": False,
              "properties": {f.key: {"type": _SCHEMA_TYPE.get(f.kind, ["string", "null"]), "description": f.meaning}
                             for f in draft.fields}}
    return {"pack": pack, "callsite": callsite, "prompt": prompt, "schema": schema}


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def candidate_paths(key: str, *, types_dir: Path = TYPES_DIR, callsites_dir: Path = CALLSITES_DIR,
                    prompts_dir: Path = PROMPTS_DIR) -> dict[str, Path]:
    return {"pack": types_dir / f"{key}.json", "callsite": callsites_dir / f"verify_{key}.json",
            "prompt": prompts_dir / f"{key}_prompt.md", "schema": prompts_dir / f"{key}_schema.json"}


def write_candidate(draft: TaughtDraft, *, today: date | None = None, **dirs: Path) -> list[Path]:
    """Writes the candidate's four files. An existing pack is replaced only while it is still this draft's candidate,
    so a pack detection may pick, or one not taught, is never overwritten."""
    paths = candidate_paths(draft.key, **dirs)
    if paths["pack"].exists():
        meta = json.loads(paths["pack"].read_text(encoding="utf-8")).get("meta", {})
        if meta.get("taught", {}).get("state") != "candidate":
            raise TeachingError(f"{draft.key}: a type pack of that name exists and is not this draft's candidate")
    files = candidate(draft, today=today)
    for name in ("pack", "callsite", "schema"):
        paths[name].write_text(_dump(files[name]), encoding="utf-8", newline="\n")
    paths["prompt"].write_text(files["prompt"], encoding="utf-8", newline="\n")
    return list(paths.values())


def registry_entries(draft: TaughtDraft, root: Path = PROJECT_ROOT) -> list[str]:
    """What the person still has to add to the shared registries by hand, in their own layout (one line each); an
    entry already there is not listed, so an empty list means the candidate is registered everywhere."""
    def read(rel: str) -> Any:
        return json.loads((root / rel).read_text(encoding="utf-8"))

    labels, catalog = read("configs/field_labels.json"), read("configs/capability_catalog.json")
    named = draft.key in read("configs/naming.json")["types"]
    shared, own_names = labels["fields"], labels.get("by_type", {}).get(draft.key, {})
    new = {f.key: f.label for f in draft.fields if f.key not in shared}
    own = {f.key: f.label for f in draft.fields
           if f.key in shared and shared[f.key] != f.label and own_names.get(f.key) != f.label}
    pins = (root / "tests" / "test_request_keys_190.py").read_text(encoding="utf-8").count(f'"{draft.key}":')
    out = [f'configs/field_labels.json "doc_types": "{draft.key}": "{draft.label}" and its English name in '
           "ui/src/i18n/en-server.json" if labels["doc_types"].get(draft.key) != draft.label else None,
           f'configs/field_labels.json "fields": {json.dumps(new, ensure_ascii=False)}' if new else None,
           f'configs/field_labels.json "by_type": {{"{draft.key}": {json.dumps(own, ensure_ascii=False)}}}' if own else None,
           f'configs/doc_types.json "old_type_map": "{draft.key}": "{draft.parent}"'
           if read("configs/doc_types.json")["old_type_map"].get(draft.key) != draft.parent else None,
           f'configs/capability_catalog.json "expected_document_keys" and "legacy_pending_document_keys" (not detected): '
           f'"{draft.key}"' if not {draft.key} <= set(catalog["expected_document_keys"]) & set(
               catalog["legacy_pending_document_keys"]) else None,
           f'configs/naming.json "types": "{draft.key}": its file-name token and pattern' if not named else None,
           f'configs/engine_matrix.json "sites": "verify_{draft.key}" as the other converted packs\' verification sites'
           if f"verify_{draft.key}" not in read("configs/engine_matrix.json")["sites"] else None,
           f'tests/test_request_keys_190.py GPT_KEYS and JEV_KEYS: "{draft.key}" (its fingerprints, as the test computes '
           "them)" if pins < 2 else None]
    return [line for line in out if line]
