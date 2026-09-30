"""Content-based file names (078; owner decisions of 2026-09-30).

Copies of the processed documents get a uniform name built from their content, for example
`2026-09-12_SZAMLA_Minta-Kft_SZ-2026-001234.pdf`; the original file never changes. The name is built in code from the
run's effective values (machine data merged with the human corrections), never by an AI call, so it costs nothing.

Rules (`configs/naming.json`, one pattern per type; a type without a pattern uses the default):
- `{a|b}`: the first non-empty field; `{@type}`: the type's token; `{@date}`: the record's first dated field;
  `{@original}`: the stem of the original file name. `@date` and `@original` are fillers: they never send a copy to
  review;
- modifiers: `:date` (read a date from a text field), `:last8` (digits only, the last 8: an account number),
  `:street` (the part of an address after the last comma: street and number; without a comma a leading postcode and
  town are dropped, unless nothing else is left; one letter case, so the same place is written the same way on every
  provider's bill);
- the field's kind (type pack) decides the form: a date becomes `YYYY-MM-DD`, anything else ASCII letters, digits and
  hyphens (no accents: owner decision); `_` only ever separates the parts; a name's long legal form is shortened
  (`legal_forms` in the configuration), and a part over the length limit is cut at a word boundary.

A copy goes to the review folder when its name rests on something uncertain: the item did not finish, the type is
unknown or uncertain, a name field is empty, or an open to-do concerns a field the name was built from and no person
corrected that field (`review_reasons`). A to-do about the whole document (the model call failed, weak OCR, a hidden
instruction) counts even after corrections.

Reuse (CLAUDE.md §3): ported from the legacy project's `orchestrator/framework/outputnaming.py` (`safe_component`,
the collision suffix), `scripts/ingest_folder.py` (`content_filename`, the `_review/` folder, the street part of the
address) and `orchestrator/framework/batchdelivery.py` (copies with a sha256 manifest), generalised: the per-type rules
moved from code to configuration, and the to-dos decide the review folder.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import IO, Any

from jav import cfg, store, work

log = logging.getLogger("jav.naming")

SPECIALS = ("@type", "@date", "@original")
MODIFIERS = ("date", "last8", "street")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_LITERAL = re.compile(r"^[A-Za-z0-9_-]*$")
_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")
_FIELD = re.compile(r"^[a-z_][a-z0-9_]*$")
_NON_WORD = re.compile(r"[^A-Za-z0-9]+")
_DATE = re.compile(r"(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})")
_EXT = re.compile(r"^\.[a-z0-9]{1,8}$")
_POSTCODE_TOWN = re.compile(r"^\s*\d{4}\s+\S+\s*")  # a Hungarian address without a comma: "<postcode> <TOWN> <STREET> <no>"
# letters that Unicode decomposition does not reduce to a base letter
_TRANSLIT = str.maketrans({"ß": "ss", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "đ": "d", "Đ": "D",
                           "ł": "l", "Ł": "L", "þ": "th", "Þ": "Th", "ı": "i"})


class NamingConfigError(ValueError):
    """The naming configuration is invalid (a pattern, token or modifier)."""


@dataclass(frozen=True)
class Part:
    """One placeholder of a pattern: fields in order of preference, or a special (`@type`, `@date`, `@original`)."""

    fields: tuple[str, ...] = ()
    special: str | None = None
    modifier: str | None = None


@dataclass(frozen=True)
class TypeRule:
    token: str | None
    pattern: str | None
    literals: tuple[str, ...]  # the text around the parts: len(parts) + 1 pieces
    parts: tuple[Part, ...]


@dataclass(frozen=True)
class Rules:
    separator: str
    review_folder: str
    manifest_file: str
    part_max_chars: int
    stem_max_chars: int
    path_max_chars: int
    placeholders: dict[str, str]
    default: TypeRule
    types: dict[str, TypeRule]
    unknown_key: str
    reason_scope: dict[str, str]
    reason_labels: dict[str, str]
    manifest_columns: dict[str, str]
    status_labels: dict[str, str]
    legal_forms: tuple[tuple[re.Pattern[str], str], ...] = ()


@dataclass(frozen=True)
class Name:
    """A built name. `used`: per part, the field its value came from (None: a special or an empty part)."""

    stem: str
    ext: str
    parts: tuple[Part, ...]
    used: tuple[str | None, ...]
    missing: tuple[str, ...]
    type_unknown: bool

    @property
    def filename(self) -> str:
        return self.stem + self.ext

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(f for f in self.used if f)


# --- configuration --------------------------------------------------------------------------------------------


def _parse_pattern(pattern: str, where: str) -> tuple[tuple[str, ...], tuple[Part, ...]]:
    literals: list[str] = []
    parts: list[Part] = []
    pos = 0
    for m in _PLACEHOLDER.finditer(pattern):
        literals.append(pattern[pos:m.start()])
        body, _, modifier = m.group(1).partition(":")
        names = tuple(n.strip() for n in body.split("|"))
        if modifier and modifier not in MODIFIERS:
            raise NamingConfigError(f"{where}: unknown modifier {modifier!r}")
        if any(n in SPECIALS for n in names):
            if len(names) > 1 or modifier:
                raise NamingConfigError(f"{where}: a special part stands alone, without a modifier")
            parts.append(Part(special=names[0]))
        else:
            if not names or not all(_FIELD.match(n) for n in names):
                raise NamingConfigError(f"{where}: invalid field list {m.group(1)!r}")
            parts.append(Part(fields=names, modifier=modifier or None))
        pos = m.end()
    literals.append(pattern[pos:])
    for lit in literals:
        if not _LITERAL.match(lit) or "{" in lit or "}" in lit:
            raise NamingConfigError(f"{where}: only letters, digits, '_' and '-' may stand between the parts: {lit!r}")
    if not parts:
        raise NamingConfigError(f"{where}: a pattern needs at least one part")
    return tuple(literals), tuple(parts)


def parse_rules(raw: dict[str, Any]) -> Rules:
    """The checked rules of `configs/naming.json` (`NamingConfigError` on a broken pattern, token or modifier)."""
    d_lits, d_parts = _parse_pattern(raw["default_pattern"], "default_pattern")
    types: dict[str, TypeRule] = {}
    for key, spec in raw["types"].items():
        token = spec.get("token")
        if not token or not _TOKEN.match(token):
            raise NamingConfigError(f"types.{key}: the token must be capital letters, digits, '_' or '-'")
        pattern = spec.get("pattern")
        lits, parts = _parse_pattern(pattern, f"types.{key}") if pattern else (d_lits, d_parts)
        types[key] = TypeRule(token=token, pattern=pattern, literals=lits, parts=parts)
    for scope in raw["reason_scope"].values():
        if scope not in ("*", "@type") and not scope.startswith("kind:"):
            raise NamingConfigError(f"reason_scope: unknown scope {scope!r}")
    # the long legal forms, longest first, as whole words and ignoring case
    forms = sorted(raw.get("legal_forms", {}).items(), key=lambda kv: -len(kv[0]))
    legal_forms = tuple((re.compile(rf"(?<!\w){re.escape(long)}(?!\w)", re.IGNORECASE), short) for long, short in forms)
    return Rules(separator=raw["separator"], review_folder=raw["review_folder"], manifest_file=raw["manifest_file"],
                 part_max_chars=int(raw["part_max_chars"]), stem_max_chars=int(raw["stem_max_chars"]),
                 path_max_chars=int(raw["path_max_chars"]), placeholders=dict(raw["placeholders"]),
                 default=TypeRule(token=None, pattern=raw["default_pattern"], literals=d_lits, parts=d_parts), types=types,
                 unknown_key=cfg.load("doc_types")["unknown_key"], reason_scope=dict(raw["reason_scope"]),
                 reason_labels=dict(raw["reason_labels"]), manifest_columns=dict(raw["manifest_columns"]),
                 status_labels=dict(raw["status_labels"]), legal_forms=legal_forms)


def rules() -> Rules:
    return parse_rules(cfg.load("naming"))


# --- parts ----------------------------------------------------------------------------------------------------


def safe_part(value: Any, *, limit: int | None = None) -> str | None:
    """ASCII letters and digits joined by hyphens (accents folded, everything else a hyphen); None if nothing is left.
    Over `limit` it is cut at the last word boundary (unless that would drop more than half: then inside the word)."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKD", str(value).translate(_TRANSLIT))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _NON_WORD.sub("-", text).strip("-")
    if limit and len(text) > limit:
        head = text[:limit]
        if text[limit] != "-":
            cut = head.rfind("-")
            head = head[:cut] if cut >= limit // 2 else head
        text = head.rstrip("-")
    return text or None


def _iso_date(value: Any) -> str | None:
    m = _DATE.search(str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def format_value(value: Any, kind: str | None, modifier: str | None = None, *, limit: int | None = None,
                 rules: Rules | None = None) -> str | None:
    """One field's value as a name part, or None when it is empty or unusable (an unreadable date, a too short
    account number, a town without a street). A name (`name` kind) gets its legal form shortened (`legal_forms`)."""
    if value is None or not str(value).strip():
        return None
    if modifier == "date" or (modifier is None and kind == "date"):
        return _iso_date(value)
    if modifier == "last8":
        digits = re.sub(r"\D", "", str(value))
        return digits[-8:] if len(digits) >= 8 else None
    if modifier == "street":
        # the part after the last comma; without a comma, a leading postcode and town are dropped. One case for every
        # provider (the same place is written "Minta utca 1" on one bill and "MINTA UTCA 1" on another)
        text = str(value)
        part = text.rsplit(",", 1)[-1] if "," in text else _POSTCODE_TOWN.sub("", text)
        street = safe_part(part, limit=limit) or safe_part(text, limit=limit)  # only a postcode and town: that stays
        return street[:1].upper() + street[1:].lower() if street else None
    text = str(value)
    if kind == "name" and rules is not None:
        for pattern, short in rules.legal_forms:
            text = pattern.sub(short, text)
    return safe_part(text, limit=limit)


def _is_date_part(part: Part, kinds: dict[str, str]) -> bool:
    return part.modifier == "date" or any(kinds.get(f) == "date" for f in part.fields)


def _first_date(values: dict[str, Any], kinds: dict[str, str]) -> str | None:
    for f, k in kinds.items():
        if k == "date":
            v = _iso_date(values.get(f)) if values.get(f) else None
            if v:
                return v
    return None


def name_for(doc_type: str | None, values: dict[str, Any], kinds: dict[str, str], *, original: str, rules: Rules) -> Name:
    """The content-based name of one document (without collision handling: `unique`)."""
    rule = rules.types.get(doc_type) if doc_type else None
    type_unknown = rule is None or doc_type == rules.unknown_key
    token = rules.placeholders["type"] if type_unknown or rule is None else rule.token
    lits, parts = (rule.literals, rule.parts) if rule is not None and not type_unknown else (rules.default.literals, rules.default.parts)
    ph, limit = rules.placeholders, rules.part_max_chars
    orig = Path(original)
    pieces = [lits[0]]
    used: list[str | None] = []
    missing: list[str] = []
    for part, lit in zip(parts, lits[1:], strict=True):
        text: str | None
        if part.special == "@type":
            text, src = token, None
        elif part.special == "@date":
            text, src = _first_date(values, kinds) or ph["date"], None
        elif part.special == "@original":
            text, src = safe_part(orig.stem, limit=limit) or ph["value"], None
        else:
            text, src = None, None
            for f in part.fields:
                text = format_value(values.get(f), kinds.get(f), part.modifier, limit=limit, rules=rules)
                if text:
                    src = f
                    break
            if not text:
                missing.append(part.fields[0])
                text = ph["date"] if _is_date_part(part, kinds) else ph["value"]
        used.append(src)
        pieces += [text, lit]
    stem = "".join(pieces)[:rules.stem_max_chars].rstrip("-_")
    ext = orig.suffix.lower() if _EXT.match(orig.suffix.lower()) else ""
    return Name(stem=stem, ext=ext, parts=parts, used=tuple(used), missing=tuple(missing), type_unknown=type_unknown)


def unique(folder: str, filename: str, used: set[str]) -> str:
    """`filename`, or with `__2`, `__3`... if the folder already has it (case-insensitively, as on Windows). Records the
    result in `used`."""
    stem, ext = os.path.splitext(filename)
    candidate, n = filename, 2
    while f"{folder}/{candidate}".casefold() in used:
        candidate, n = f"{stem}__{n}{ext}", n + 1
    used.add(f"{folder}/{candidate}".casefold())
    return candidate


# --- review rule ----------------------------------------------------------------------------------------------


def _scope_of(code: str, rules: Rules) -> str | None:
    hits = [k for k in rules.reason_scope if code == k or code.startswith((k + ":", k + "."))]
    return rules.reason_scope[max(hits, key=len)] if hits else None


def review_reasons(name: Name, *, open_reasons: list[str], corrected: list[str] | tuple[str, ...] | set[str],
                   kinds: dict[str, str], rules: Rules) -> list[str]:
    """Why the copy belongs in the review folder (empty: it does not). Codes: `type`, `missing:<field>`,
    `todo:<field>`, `todo:*` (a to-do about the whole document)."""
    fixed = set(corrected)
    out: list[str] = []

    def add(code: str) -> None:
        if code not in out:
            out.append(code)

    if name.type_unknown:
        add("type")
    for f in name.missing:
        add(f"missing:{f}")
    for code in open_reasons:
        scope = _scope_of(code, rules)
        if scope == "*":
            add("todo:*")
        elif scope == "@type":
            add("type")
        elif scope is not None:  # "kind:<kind>": every used field of that kind
            kind = scope.split(":", 1)[1]
            for part, f in zip(name.parts, name.used, strict=True):
                hit = _is_date_part(part, kinds) if kind == "date" else any(kinds.get(x) == kind for x in part.fields)
                if f and hit and f not in fixed:
                    add(f"todo:{f}")
        else:
            p = code.split(":")
            if len(p) > 2 and p[2] in name.fields and p[2] not in fixed:
                add(f"todo:{p[2]}")
    return out


def reason_text(codes: list[str] | tuple[str, ...]) -> str:
    """The review reasons as everyday words (the display language's labels from the configuration)."""
    labels = cfg.load("naming")["reason_labels"]
    fields = cfg.load("field_labels")["fields"]
    out = []
    for code in codes:
        kind, _, rest = code.partition(":")
        if code == "todo:*":
            out.append(labels["todo_all"])
        elif kind in ("missing", "todo"):
            out.append(labels[kind].format(field=fields.get(rest, rest)))
        elif kind in labels:
            out.append(labels[kind])
        else:
            out.append(code)
    return "; ".join(out)


# --- a run's copies -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NamedCopy:
    """One document of a run with its new name. `folder`: "" (ready) or the review folder."""

    item_id: str
    source_path: str
    sha256: str
    original: str
    doc_type: str | None
    folder: str
    filename: str
    reasons: tuple[str, ...]

    @property
    def status(self) -> str:
        return "review" if self.folder else "ready"

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.filename}" if self.folder else self.filename


def _detected_types(doc_ids: list[str]) -> dict[str, str | None]:
    """The recognised category of documents without extracted data (detection only, or failed extraction)."""
    out: dict[str, str | None] = {}
    with store.connect() as c:
        for start in range(0, len(doc_ids), 500):  # stays under the SQLite parameter limit
            chunk = doc_ids[start:start + 500]
            out.update({r["doc_id"]: r["doc_type"] for r in c.execute(
                f"SELECT doc_id, doc_type FROM documents WHERE doc_id IN ({','.join('?' * len(chunk))})", chunk)})
    return out


def _fit(stem: str, ext: str, folder: str, budget: int | None) -> str:
    """The stem shortened so that `folder/stem__NN.ext` fits into `budget` characters (the output folder's path is
    already subtracted); `ValueError` if not even a short name fits."""
    if budget is None:
        return stem
    room = budget - (len(folder) + 1 if folder else 0) - len(ext) - 4  # 4: room for a collision suffix "__NN"
    if room < 20:
        raise ValueError("the output folder's path is too long for the file names (Windows allows 260 characters)")
    return stem[:room].rstrip("-_")


def plan(run_id: str, *, path_budget: int | None = None) -> list[NamedCopy]:
    """The new names of the run's documents (email items are skipped; their PDF attachments are documents), in the
    run's item order, collisions resolved. `path_budget`: the characters left for `folder/name` under the output
    folder."""
    from jav import datasets

    r = rules()
    run = work.get_run(run_id)
    items = [i for i in run["input"]["items"] if i.get("kind") != "email"]
    records = {rec["item_id"]: rec for rec in datasets.run_records(run_id)}
    results = {x["item_id"]: x for x in run["items"]}
    others = [i for i in items if i["item_id"] not in records]
    splits = work.items_reasons(run_id, others) if others else {}
    types = _detected_types([i["item_id"] for i in others])
    used: set[str] = set()
    out = []
    for item in items:
        rec = records.get(item["item_id"])
        if rec is not None:
            doc_type, values, kinds, corrected, codes = rec["doc_type"], rec["fields"], rec["kinds"], rec["corrected"], rec["open_reasons"]
        else:
            doc_type, values, kinds, corrected = types.get(item["item_id"]), {}, {}, []
            codes = [x["reason"] for x in splits[item["item_id"]]["run"]]
        original = Path(item["source_path"]).name
        name = name_for(doc_type, values, kinds, original=original, rules=r)
        why = review_reasons(name, open_reasons=codes, corrected=corrected, kinds=kinds, rules=r)
        status = (results.get(item["item_id"]) or {}).get("status")
        if status != "done":
            why.insert(0, f"not_done:{status or 'pending'}")
        folder = r.review_folder if why else ""
        filename = unique(folder, _fit(name.stem, name.ext, folder, path_budget) + name.ext, used)
        out.append(NamedCopy(item_id=item["item_id"], source_path=item["source_path"], sha256=item["sha256"], original=original,
                             doc_type=doc_type, folder=folder, filename=filename, reasons=tuple(why)))
    return out


def _manifest(rows: list[tuple[NamedCopy, str, str]]) -> bytes:
    """`jegyzek.csv`: new path, status, why, original name and path, content hash, type, item id (the export's CSV
    rules: BOM, `;`, CRLF, formula guard)."""
    from jav import export

    raw = cfg.load("naming")
    cols, status_labels = raw["manifest_columns"], raw["status_labels"]
    doc_types = cfg.load("field_labels")["doc_types"]
    head = [cols[k] for k in ("path", "status", "why", "original", "source_path", "sha256", "doc_type", "item_id")]
    body = [[c.path if status != "skipped" else "", status_labels[status], why, c.original, c.source_path, c.sha256,
             doc_types.get(c.doc_type or "", c.doc_type or ""), c.item_id] for c, status, why in rows]
    return export.csv_bytes(head, body)


def _materialise(copies: list[NamedCopy], put: Callable[[str, bytes], None], manifest_file: str) -> dict[str, int]:
    """Copies the verified bytes of each document under its new name, then the manifest. A source that changed since
    it was added is skipped (listed in the manifest): the copy is always exactly what was processed."""
    max_bytes = work.max_source_bytes()
    rows: list[tuple[NamedCopy, str, str]] = []
    counts: Counter[str] = Counter()
    for c in copies:
        try:
            data = work.read_verified(Path(c.source_path), c.sha256, max_bytes=max_bytes)
        except work.RevisionConflict:
            counts["skipped"] += 1
            rows.append((c, "skipped", reason_text(["source_changed"])))
            continue
        put(c.path, data)
        counts[c.status] += 1
        rows.append((c, c.status, reason_text(c.reasons)))
    put(manifest_file, _manifest(rows))
    return {"ready": counts["ready"], "review": counts["review"], "skipped": counts["skipped"]}


def write_zip(run_id: str, fh: IO[bytes]) -> dict[str, int]:
    """The run's named copies and the manifest as a ZIP into `fh` (the PDFs are already compressed: stored as they
    are)."""
    r = rules()
    copies = plan(run_id)
    with zipfile.ZipFile(fh, "w", compression=zipfile.ZIP_STORED) as z:
        return _materialise(copies, z.writestr, r.manifest_file)


def zip_name(run_id: str) -> str:
    run = work.get_run(run_id)
    return f"{safe_part(work.get(run['workpackage_id'])['name'], limit=60) or 'csomag'}_{run_id}.zip"


def write_to_folder(run_id: str, root: Path) -> dict[str, Any]:
    """Writes the run's named copies and the manifest into a new subfolder of the output folder
    (`<package>_<run>`, then `__2`, `__3`...): nothing is ever overwritten or deleted there."""
    from jav import app_settings

    r = rules()
    root = app_settings.check_output_folder(root)
    base = f"{safe_part(work.get(work.get_run(run_id)['workpackage_id'])['name'], limit=60) or 'csomag'}_{run_id}"
    target, n = root / base, 2
    while True:
        try:
            target.mkdir()
            break
        except FileExistsError:
            target, n = root / f"{base}__{n}", n + 1
    copies = plan(run_id, path_budget=r.path_max_chars - len(str(target)) - 1)

    def put(rel: str, data: bytes) -> None:
        p = target / rel
        p.parent.mkdir(exist_ok=True)
        with open(p, "xb") as f:  # exclusive: never overwrites
            f.write(data)

    counts = _materialise(copies, put, r.manifest_file)
    log.info("named copies of %s written to %s: %s", run_id, target, counts)
    return {"path": str(target), **counts}


__all__ = ["Name", "NamedCopy", "NamingConfigError", "Rules", "format_value", "name_for", "parse_rules", "plan",
           "reason_text", "review_reasons", "rules", "safe_part", "unique", "write_to_folder", "write_zip", "zip_name"]
