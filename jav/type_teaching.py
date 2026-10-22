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

Layer: business module (reads the measured facts from the store); no AI call.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from jav import store

MIN_DOCUMENTS = 3


class TeachingError(ValueError):
    """The facts a proposal needs are missing."""


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


def print_proposal(report: dict[str, Any]) -> None:
    print(f"### Field proposals - {report['family']}, from the {report['documents']} development documents' facts\n")
    print("| key | label | documents | repeated | supported by JEV | kind |\n|---|---|---|---|---|---|")
    for p in report["fields"]:
        print(f"| {p['key']} | {p['label']} | {p['documents']} | {p['repeated']} | {p['supported']} | {p['kind']} |")
