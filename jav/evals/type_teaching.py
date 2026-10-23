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
makes a candidate type pack the way the legacy converter made the converted packs (`jav/legacy/typepack_convert.py`, 047): the
pack, its extraction prompt and schema, and a verification call site that inherits the shared questions. A candidate
is never picked by detection (`auto_detect` false), so it changes no processing; it is measured on the family's
evaluation half only (its golden type key is its own, so no legacy case measures it in-sample). The entries of the
shared registries (the field labels, the type registry's category map, the capability catalog, the engine matrix and
the request pins of the tests) are listed for the person to add, so a registry file's own layout is never rewritten.

Detection picks a pack only by the person's command (K2d, `type-activate` / `type-withdraw`): the pack's own detection
switch (`auto_detect`) is turned, as a new version with a changelog line, and the files stay. A taught pack is turned
on only with the latest shared measurement of its evaluation half on a clean working tree, with every case answered,
on the files it has now (the legacy activation gate, `10_AIFLOW_V4/flows/DOCTYPE-ONBOARDING.md` §3); the result is
shown, no threshold decides. With `--replace`, its family's pack it takes over is turned off in the same step. A pack
without detection anchors is turned on only as its family's one pack, because the anchor score would pick it without a
question next to another (`jav/ai/detect_detail.py`).

Layer: business module (reads the measured facts from the store, writes the candidate's config files); no AI call.
"""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.ai import typepack
from jav.core import cfg, store
from jav.core.config import PROJECT_ROOT, PROMPTS_DIR

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
    from jav.core.dates import AmbiguousDate, read_date_input

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
    from jav.core import cfg

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
    from jav.ai import policy
    from jav.flows.flow_native import SUPPORT_BAND

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
    from jav.evals import evals_facts

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
        from jav.ai.typepack import KINDS

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
    # the header is part of the text sent to the model and of the prompt's fingerprint, so it keeps the generator's path
    # as it was written before the module moved (208, plan G-process-core R2)
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
           f'configs/capability_catalog.json "expected_document_keys": "{draft.key}"'
           if draft.key not in catalog["expected_document_keys"] else None,
           f'configs/naming.json "types": "{draft.key}": its file-name token and pattern' if not named else None,
           f'configs/engine_matrix.json "sites": "verify_{draft.key}" as the other converted packs\' verification sites'
           if f"verify_{draft.key}" not in read("configs/engine_matrix.json")["sites"] else None,
           f'tests/test_request_keys_190.py GPT_KEYS and JEV_KEYS: "{draft.key}" (its fingerprints, as the test computes '
           "them)" if pins < 2 else None]
    return [line for line in out if line]


# --- the detection switch, turned only by the person's command (K2d) ---------------------------------------------------


@dataclass(frozen=True)
class Switch:
    """One pack's new state: its key, its new version and whether detection may pick it now."""

    key: str
    version: str
    detected: bool


Files = Callable[[str, str], dict[str, str] | None]


def files_now(key: str) -> dict[str, str]:
    """A pack's four files as they are now (the pack from the type packs' folder in use); a missing one is left out."""
    paths = candidate_paths(key, types_dir=cfg.TYPES_DIR)
    return {name: p.read_text(encoding="utf-8") for name, p in paths.items() if p.exists()}


def files_at(commit: str, key: str) -> dict[str, str] | None:
    """A pack's four files at a commit (`git show`); None when one of them is not there."""
    out = {}
    for name, path in candidate_paths(key).items():
        shown = subprocess.run(["git", "show", f"{commit}:{path.relative_to(PROJECT_ROOT).as_posix()}"],
                               cwd=PROJECT_ROOT, capture_output=True)
        if shown.returncode:
            return None
        out[name] = shown.stdout.decode("utf-8")
    return out


def content_digest(files: dict[str, str]) -> str:
    """What a measurement of the pack rests on: its files without their version records and its detection switch (a
    switch changes neither its requests nor its answers)."""
    parts = []
    for name in ("pack", "callsite", "prompt", "schema"):
        text = files.get(name, "")
        if text and name != "prompt":
            text = json.dumps({k: v for k, v in json.loads(text).items() if k not in ("meta", "auto_detect")},
                              ensure_ascii=False, sort_keys=True)
        parts.append(f"{name}\0{text}")
    return cfg.combine(*parts)


def evaluation_gate(key: str, *, latest: dict[str, dict[str, Any]] | None = None,
                    files_then: Files | None = None) -> dict[str, Any]:
    """The measurement a taught pack's activation rests on: the latest shared measurement of its evaluation half
    (`measure taught:<key>:evaluation`), on a clean working tree, every case answered, on the files the pack has now."""
    from jav.evals import goldens

    name = f"taught:{key}:evaluation"
    row = (goldens.latest_results() if latest is None else latest).get(name)
    if row is None:
        raise TeachingError(f"{key}: its evaluation half was never measured (python -m jav.cli measure {name})")
    if not row.get("clean"):
        raise TeachingError(f"{key}: its latest measurement ({row['receipt']}) ran with uncommitted changes")
    if row.get("without_result") or row.get("answered") != row.get("cases"):
        raise TeachingError(f"{key}: its latest measurement ({row['receipt']}) has no result for every case")
    then = (files_then or files_at)(row["commit"], key)
    if then is None or content_digest(then) != content_digest(files_now(key)):
        raise TeachingError(f"{key}: its files changed since they were measured at {row['commit']}; measure it again")
    return row


def _next_version(version: str) -> str:
    major, minor = (int(x) for x in version.split(".")[:2])
    return f"{major}.{minor + 1}.0"


def _switchable(key: str) -> tuple[Path, dict[str, Any], typepack.TypePack]:
    """The pack's file, its data and the loaded pack, when its detection switch can be turned by a command."""
    path = cfg.TYPES_DIR / f"{key}.json"
    if key.startswith(typepack.BASE_PREFIX) or not path.exists():
        raise TeachingError(f"{key}: no type pack of that name")
    pack = typepack.get(key)
    if not {"S", "G"} & set(pack.arms):
        raise TeachingError(f"{key}: a pack read by code only; detection never asks for it")
    if pack.parent in (None, key):
        raise TeachingError(f"{key}: its category's own pack; its detection is the type registry's (configs/doc_types.json)")
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if _dump(data) != text:
        raise TeachingError(f"{key}: its file is not in the shared layout; switch it by hand")
    return path, data, pack


def _family_guard(on: str, family: str, off: str | None) -> None:
    """A pack without detection anchors only as its family's one pack: next to another, the anchor score would pick it
    without a question (`jav/ai/detect_detail.py` step 3)."""
    after = {k for k in typepack.keys() if typepack.get(k).auto_detect and typepack.get(k).parent == family}
    after = (after | {on}) - {off}
    if not typepack.get(on).detect and len(after) > 1:
        raise TeachingError(f"{on}: it has no detection anchors, and the {family} family would have {len(after)} packs "
                            "on; the anchor score would pick it without a question (replace the family's pack with "
                            "--replace)")


def _write_switch(path: Path, data: dict[str, Any], *, detected: bool, note: str, day: str,
                  taught: dict[str, Any] | None = None) -> Switch:
    version = _next_version(str(data["meta"]["version"]))
    data["auto_detect"] = detected
    data["meta"]["version"] = version
    data["meta"].setdefault("changelog", []).append({"version": version, "date": day, "note": note})
    if taught is not None:
        data["meta"]["taught"] = taught
    path.write_text(_dump(data), encoding="utf-8", newline="\n")
    return Switch(path.stem, version, detected)


def _reload() -> None:
    cfg.reload()
    typepack.reload()


def activate(key: str, *, replace: str | None = None, latest: dict[str, dict[str, Any]] | None = None,
             files_then: Files | None = None, today: date | None = None) -> list[Switch]:
    """Detection may pick `key` in its family from now on; with `replace`, the family's pack it takes over is turned
    off. A taught pack needs its evaluation gate; a pack never taught (a converted or hand-written one, turned back on)
    does not. Everything is checked before anything is written; a refusal is a `TeachingError`."""
    path, data, pack = _switchable(key)
    if pack.auto_detect:
        raise TeachingError(f"{key}: detection picks it already")
    taught = data["meta"].get("taught")
    if taught is not None and taught.get("state") not in ("candidate", "withdrawn"):
        raise TeachingError(f"{key}: a taught pack in the {taught.get('state')} state")
    family = str(pack.parent)  # _switchable refuses a pack without its category
    old: tuple[Path, dict[str, Any]] | None = None
    if replace is not None:
        if replace == key:
            raise TeachingError(f"{key}: it cannot replace itself")
        old_path, old_data, old_pack = _switchable(replace)
        if not old_pack.auto_detect:
            raise TeachingError(f"{replace}: detection does not pick it; there is nothing to replace")
        if old_pack.parent != family:
            raise TeachingError(f"{replace} is in the {old_pack.parent} family, {key} in the {family} family")
        old = (old_path, old_data)
    _family_guard(key, family, replace)
    day = (today or date.today()).isoformat()
    instead = f", instead of {replace}" if replace else ""
    if taught is None:
        note = f"type-activate (plan 197 K2d): on again; detection may pick it in the {family} family{instead}"
        switched = [_write_switch(path, data, detected=True, note=note, day=day)]
    else:
        row = evaluation_gate(key, latest=latest, files_then=files_then)
        measured = {"receipt": row["receipt"], "commit": row["commit"], "right": row["right"], "scored": row["scored"],
                    "unit": row["unit"]}
        note = (f"type-activate (plan 197 K2d): on; detection may pick it in the {family} family{instead}; its evaluation "
                f"half: {row['right']}/{row['scored']} {row['unit']} ({row['receipt']}, {row['commit']})")
        taught = {k: v for k, v in taught.items() if k != "replaces"}
        taught.update(state="active", measured=measured, **({"replaces": replace} if replace else {}))
        switched = [_write_switch(path, data, detected=True, note=note, day=day, taught=taught)]
    if old is not None:
        note = (f"type-activate (plan 197 K2d): off; replaced by {key}, detection no longer picks it; its files stay "
                "for its earlier results")
        switched.append(_write_switch(*old, detected=False, note=note, day=day))
    _reload()
    return switched


def withdraw(key: str, *, restore: bool = False, today: date | None = None) -> list[Switch]:
    """Detection no longer picks `key`; its files stay for its earlier results. `restore`: the pack it replaced is
    turned back on in the same step. Everything is checked before anything is written."""
    path, data, pack = _switchable(key)
    if not pack.auto_detect:
        raise TeachingError(f"{key}: detection does not pick it")
    taught = data["meta"].get("taught")
    replaced = (taught or {}).get("replaces")
    back: tuple[Path, dict[str, Any]] | None = None
    if restore:
        if not replaced:
            raise TeachingError(f"{key}: it replaced no pack (python -m jav.cli type-activate <pack> turns one on)")
        old_path, old_data, old_pack = _switchable(replaced)
        if old_pack.auto_detect:
            raise TeachingError(f"{replaced}: detection picks it already")
        if old_data["meta"].get("taught"):
            raise TeachingError(f"{replaced}: a taught pack; turn it on with its own measurement (type-activate)")
        _family_guard(replaced, str(pack.parent), key)
        back = (old_path, old_data)
    day = (today or date.today()).isoformat()
    note = "type-withdraw (plan 197 K2d): off; detection no longer picks it; its files stay for its earlier results"
    if taught is not None:
        taught = {**{k: v for k, v in taught.items() if not (restore and k == "replaces")}, "state": "withdrawn"}
    switched = [_write_switch(path, data, detected=False, note=note, day=day, taught=taught)]
    if back is not None:
        note = f"type-withdraw (plan 197 K2d): on again; {key}, which replaced it, was withdrawn"
        switched.append(_write_switch(*back, detected=True, note=note, day=day))
    _reload()
    return switched
