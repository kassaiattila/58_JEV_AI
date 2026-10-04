"""Immutable native readings, interpretation outcomes and run-item publications.

Delivery files are verified before a database reference becomes visible. Caller
transactions are borrowed without commit or close; no read operation reparses a
document or contacts a provider.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Mapping, Sequence
from uuid import uuid4

from pydantic import TypeAdapter

from jav import store
from jav.native_contracts import (
    ArtifactRef, Failed, InterpretationOutcome, NativeCitation, NativeFact,
    NativeProgress, NativeSourceElement, NATIVE_SUFFIXES, Publication, ReadingRef,
    ReadingResult, ReadingSummary, Running, SourcePage,
)
from jav.readers.contracts import ReadLimits, SourceBundle, TextLocator, canonical_bytes
from jav.readers.interpretation import Citation, Interpretation
from jav.readers.limits import DEFAULT_LIMITS
from jav.readers import pipeline
from jav.readers.pipeline import Delivery, digest, json_bytes


class NativeIntegrityError(ValueError):
    """A saved identity, source or artifact is missing or no longer intact."""


class PublicationConflict(ValueError):
    """A run item already has a different immutable publication."""


store.register_schema("native_results", """
CREATE TABLE IF NOT EXISTS native_readings (
 reading_id TEXT PRIMARY KEY, reading_key TEXT UNIQUE NOT NULL,
 payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS native_outcomes (
 outcome_id TEXT PRIMARY KEY, graph_id TEXT UNIQUE NOT NULL,
 run_id TEXT NOT NULL, item_id TEXT NOT NULL, reading_id TEXT NOT NULL,
 payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS native_publications (
 run_id TEXT NOT NULL, item_id TEXT NOT NULL, publication_id TEXT UNIQUE NOT NULL,
 payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 PRIMARY KEY (run_id, item_id)
);
""")

_OUTCOME = TypeAdapter(InterpretationOutcome)


@contextmanager
def _connection(c: sqlite3.Connection | None = None):
    if c is not None:
        yield c
    else:
        with store.connect() as own:
            yield own


def _path(relative: str) -> Path:
    path = PurePosixPath(relative)
    if (path.is_absolute() or "\\" in relative or ":" in relative
            or not path.parts or path.parts[0] != "native"
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise NativeIntegrityError("Invalid native artifact path")
    base = store.current_path().parent.absolute()
    proposed = base.joinpath(*path.parts)
    if proposed.resolve() != proposed or not proposed.is_relative_to(base):
        raise NativeIntegrityError("Redirected native artifact path")
    return proposed


def _checked(row, model):
    if row is None:
        raise NativeIntegrityError("Required native record is missing")
    raw = row["payload"].encode("utf-8")
    if digest(raw) != row["payload_sha256"]:
        raise NativeIntegrityError("Native record differs from its saved digest")
    return model.model_validate_json(raw)


def _reading(reading_id: str, c=None) -> ReadingRef:
    with _connection(c) as conn:
        row = conn.execute("SELECT * FROM native_readings WHERE reading_id=?", (reading_id,)).fetchone()
        ref = _checked(row, ReadingRef)
    if ref.reading_id != reading_id:
        raise NativeIntegrityError("Reading identity differs from its record")
    return ref


def _summary(delivery: Delivery) -> ReadingSummary:
    results = tuple(ReadingResult(occurrence_id=r.attempt.occurrence_id,
        attempt_id=r.attempt.attempt_id, reader_key=r.attempt.reader_key(), status=r.status,
        issues=r.issues) for r in delivery.bundle.results)
    states = {r.status for r in results}
    acquisition = delivery.bundle.manifest.acquisition_status()
    status = ("complete" if states == {"complete"} and acquisition == "complete" else
              next(iter(states)) if len(states) == 1 and "complete" not in states else "partial")
    return ReadingSummary(status=status, acquisition_status=acquisition,
                          attempt_ids=tuple(r.attempt_id for r in results), results=results)


def prepare_reading(read_path: Path, *, original_name: str, expected_sha256: str,
                    limits: ReadLimits = DEFAULT_LIMITS) -> ReadingRef:
    """Read once for the exact source/name/reader configuration, with OCR disabled."""
    path = Path(read_path)
    if Path(original_name).name != original_name or Path(original_name).suffix.lower() not in NATIVE_SUFFIXES:
        raise ValueError("A native reading needs a supported original file name")
    source = pipeline.bounded_file(path, limits.input_bytes)
    if digest(source) != expected_sha256:
        raise NativeIntegrityError("Source differs from the frozen work item")
    key = digest(json_bytes({"source": expected_sha256, "name": original_name,
                            "reader": pipeline.implementation_version(), "limits": limits.model_dump(mode="json")}))
    with store.connect() as c:
        row = c.execute("SELECT * FROM native_readings WHERE reading_key=?", (key,)).fetchone()
        if row:
            ref = _checked(row, ReadingRef)
            load_reading(ref.reading_id, c=c)
            return ref
    delivery = pipeline.read_files([path], limits=limits, ocr=False)
    roots = [o for o in delivery.bundle.manifest.occurrences if o.parent_id is None]
    if len(roots) != 1 or roots[0].object_sha256 != expected_sha256 or delivery.objects.get(expected_sha256) != source:
        raise NativeIntegrityError("Acquired source differs from the frozen work item")
    root = roots[0]
    manifest = delivery.bundle.manifest.model_copy(update={"occurrences": tuple(
        o.model_copy(update={"original_name": original_name}) if o.occurrence_id == root.occurrence_id else o
        for o in delivery.bundle.manifest.occurrences)})
    delivery.bundle = SourceBundle.model_validate_json(canonical_bytes(delivery.bundle.model_copy(update={"manifest": manifest})))
    reading_id = "reading:" + key
    relative = f"native/readings/{uuid4().hex}"
    delivery.save(_path(relative))
    saved = Delivery.load(_path(relative))
    if saved.bundle.digest() != delivery.bundle.digest():
        raise NativeIntegrityError("Delivery changed while saving")
    ref = ReadingRef(reading_id=reading_id, source_sha256=expected_sha256,
        bundle_sha256=saved.bundle.digest(), original_name=original_name, artifact_relpath=relative,
        attempt_ids=tuple(r.attempt.attempt_id for r in saved.bundle.results), reading=_summary(saved))
    payload = canonical_bytes(ref)
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO native_readings VALUES (?,?,?,?)",
                  (reading_id, key, payload.decode(), digest(payload)))
        # A concurrent identical reader may have published first. Its verified
        # reference wins; an unreferenced directory is never published implicitly.
        selected = _reading(reading_id, c)
        load_reading(reading_id, c=c)
        return selected


def load_reading(reading_id: str, c=None) -> Delivery:
    ref = _reading(reading_id, c)
    try:
        delivery = Delivery.load(_path(ref.artifact_relpath))
        if pipeline.bounded_file(_path(ref.artifact_relpath + "/bundle.json"), 2_000_000) != canonical_bytes(delivery.bundle):
            raise NativeIntegrityError("Saved bundle bytes differ from the canonical frozen envelope")
        roots = [o for o in delivery.bundle.manifest.occurrences if o.parent_id is None]
        if (delivery.bundle.digest() != ref.bundle_sha256 or _summary(delivery) != ref.reading
                or tuple(r.attempt.attempt_id for r in delivery.bundle.results) != ref.attempt_ids
                or len(roots) != 1 or roots[0].object_sha256 != ref.source_sha256
                or roots[0].original_name != ref.original_name):
            raise NativeIntegrityError("Saved reading identity or evidence differs")
        return delivery
    except (OSError, ValueError, KeyError) as exc:
        raise NativeIntegrityError(f"Reading {reading_id} has damaged or missing evidence: {exc}") from exc


def save_outcome(*, graph_id: str, run_id: str, item_id: str, reading_id: str,
                 outcome: InterpretationOutcome, interpretation: Interpretation | None = None) -> str:
    """Persist a terminal interpretation before the Burr step returns references."""
    ref = _reading(reading_id)
    if outcome.status in {"not_started", "running"}:
        raise ValueError("Only terminal interpretation outcomes can be saved")
    if (outcome.status == "succeeded") != (interpretation is not None):
        raise ValueError("Success requires a valid Interpretation")
    if interpretation is not None and interpretation.source_bundle_sha256 != ref.bundle_sha256:
        raise NativeIntegrityError("Interpretation belongs to another reading")
    data = {"graph_id": graph_id, "run_id": run_id, "item_id": item_id, "reading_id": reading_id,
            "outcome": outcome.model_dump(mode="json"),
            "interpretation": interpretation.model_dump(mode="json") if interpretation else None}
    payload = json_bytes(data)
    outcome_id = "outcome:" + digest(payload)
    with store.connect() as c:
        row = c.execute("SELECT outcome_id,payload FROM native_outcomes WHERE graph_id=?", (graph_id,)).fetchone()
        if row:
            if row["payload"] != payload.decode():
                raise PublicationConflict("This graph already has a different terminal outcome")
            return row["outcome_id"]
        c.execute("INSERT INTO native_outcomes VALUES (?,?,?,?,?,?,?)",
                  (outcome_id, graph_id, run_id, item_id, reading_id, payload.decode(), digest(payload)))
    return outcome_id


def load_outcome(outcome_id: str, c=None) -> tuple[dict, InterpretationOutcome, Interpretation | None]:
    with _connection(c) as conn:
        row = conn.execute("SELECT * FROM native_outcomes WHERE outcome_id=?", (outcome_id,)).fetchone()
    if row is None or digest(row["payload"].encode()) != row["payload_sha256"] or outcome_id != "outcome:" + row["payload_sha256"]:
        raise NativeIntegrityError("Interpretation outcome is missing or damaged")
    data = json.loads(row["payload"])
    for name in ("graph_id", "run_id", "item_id", "reading_id"):
        if data[name] != row[name]:
            raise NativeIntegrityError("Outcome binding differs from its record")
    outcome = _OUTCOME.validate_json(json_bytes(data["outcome"]))
    interpretation = Interpretation.model_validate_json(json_bytes(data["interpretation"])) if data["interpretation"] is not None else None
    if (outcome.status == "succeeded") != (interpretation is not None):
        raise NativeIntegrityError("Invalid outcome and interpretation pair")
    return data, outcome, interpretation


def outcome_for_graph(graph_id: str, c=None) -> str | None:
    with _connection(c) as conn:
        row = conn.execute("SELECT outcome_id FROM native_outcomes WHERE graph_id=?", (graph_id,)).fetchone()
        if row:
            load_outcome(row[0], c=conn)
            return row[0]
    return None


def _check_work(c, *, run_id, item_id, source_sha256, recipe_hash):
    row = c.execute("SELECT input,recipe_hash,approval FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None or row["recipe_hash"] != recipe_hash:
        raise NativeIntegrityError("Publication does not match its frozen work run")
    items = [i for i in json.loads(row["input"])["items"] if i["item_id"] == item_id]
    if len(items) != 1 or items[0]["sha256"] != source_sha256 or items[0]["kind"] != "document":
        raise NativeIntegrityError("Publication does not match its frozen work item")
    return row


def publish(*, run_id: str, item_id: str, source_sha256: str, recipe_hash: str,
            reading_id: str, outcome: InterpretationOutcome,
            interpretation: Interpretation | None = None, c=None) -> Publication:
    """Publish once under the caller's writer transaction, after evidence checks."""
    with _connection(c) as conn:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        ref = _reading(reading_id, conn)
        load_reading(reading_id, c=conn)
        if ref.source_sha256 != source_sha256:
            raise NativeIntegrityError("Reading belongs to another source")
        payload_sha = interpretation.digest() if interpretation else None
        outcome_payload = {"outcome": outcome.model_dump(mode="json"),
                           "interpretation": interpretation.model_dump(mode="json") if interpretation else None}
        outcome_sha = digest(json_bytes(outcome_payload))
        rows = conn.execute("SELECT outcome_id FROM native_outcomes WHERE run_id=? AND item_id=? AND reading_id=?",
                            (run_id, item_id, reading_id)).fetchall()
        saved_outcome_id = None
        for row in rows:
            _, stored_outcome, stored_interpretation = load_outcome(row[0], c=conn)
            if stored_outcome == outcome and stored_interpretation == interpretation:
                saved_outcome_id = row[0]
                break
        if saved_outcome_id is None:
            graph_id = "publication:" + digest(json_bytes([run_id, item_id]))
            data = {"graph_id": graph_id, "run_id": run_id, "item_id": item_id, "reading_id": reading_id,
                    **outcome_payload}
            payload = json_bytes(data)
            saved_outcome_id = "outcome:" + digest(payload)
            try:
                conn.execute("INSERT INTO native_outcomes VALUES (?,?,?,?,?,?,?)", (saved_outcome_id, graph_id,
                    run_id, item_id, reading_id, payload.decode(), digest(payload)))
            except sqlite3.IntegrityError as exc:
                raise PublicationConflict("This item already has a different interpretation outcome") from exc
        identity = {"run_id": run_id, "item_id": item_id, "source_sha256": source_sha256,
                    "recipe_hash": recipe_hash, "reading_id": reading_id, "bundle_sha256": ref.bundle_sha256,
                    "reading": ref.reading.model_dump(mode="json"), "outcome_sha256": outcome_sha,
                    "outcome_id": saved_outcome_id, "interpretation_outcome": outcome.model_dump(mode="json"),
                    "interpretation_id": "interpretation:" + payload_sha if payload_sha else None,
                    "payload_sha256": payload_sha, "interpretation": outcome_payload["interpretation"]}
        version = digest(json_bytes(identity))
        publication = Publication.model_validate_json(json_bytes({**identity, "publication_id": "publication:" + version,
                                                                   "result_version": version}))
        work = _check_work(conn, run_id=run_id, item_id=item_id, source_sha256=source_sha256, recipe_hash=recipe_hash)
        existing = get_publication(run_id, item_id, c=conn)
        if existing:
            if existing != publication:
                raise PublicationConflict("Run item already has a different immutable publication")
            verify_publication(existing, c=conn)
            return existing
        if work["approval"] is not None:
            raise PublicationConflict("An approved run cannot gain a new publication")
        _verify_receipts(publication, conn)
        payload = canonical_bytes(publication)
        conn.execute("INSERT INTO native_publications VALUES (?,?,?,?,?)",
                     (run_id, item_id, publication.publication_id, payload.decode(), digest(payload)))
        return publication


def get_publication(run_id: str, item_id: str, c=None) -> Publication | None:
    with _connection(c) as conn:
        row = conn.execute("SELECT * FROM native_publications WHERE run_id=? AND item_id=?", (run_id, item_id)).fetchone()
        if row is None:
            return None
        publication = _checked(row, Publication)
        if (publication.run_id, publication.item_id, publication.publication_id) != (run_id, item_id, row["publication_id"]):
            raise NativeIntegrityError("Publication identity differs from its record")
        return publication


def _verify_receipts(publication: Publication, c):
    for ref in publication.interpretation_outcome.receipt_refs:
        if ref.kind == "invocation":
            row = c.execute("SELECT * FROM invocations WHERE id=?", (ref.invocation_id,)).fetchone()
            if row is None or (row["run_id"], row["step_id"], row["provider"], row["request_hash"]) != (
                    ref.run_id, ref.step_id, ref.provider, ref.request_sha256):
                raise NativeIntegrityError("Provider receipt is missing or belongs to another call")
            if row["budget_scope"] != publication.run_id:
                raise NativeIntegrityError("Provider receipt belongs to another work-run budget")
        if ref.artifact_id is not None:
            row = c.execute("SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?", (ref.artifact_kind, ref.artifact_id)).fetchone()
            if row is None or digest(json_bytes(json.loads(row[0]))) != ref.response_sha256:
                raise NativeIntegrityError("Provider receipt artifact is missing or damaged")


def verify_publication(publication: Publication, c=None) -> None:
    with _connection(c) as conn:
        current = get_publication(publication.run_id, publication.item_id, c=conn)
        if current != publication:
            raise NativeIntegrityError("Publication is not the current immutable record")
        _check_work(conn, run_id=publication.run_id, item_id=publication.item_id,
                    source_sha256=publication.source_sha256, recipe_hash=publication.recipe_hash)
        delivery = load_reading(publication.reading_id, c=conn)
        if delivery.bundle.digest() != publication.bundle_sha256 or _summary(delivery) != publication.reading:
            raise NativeIntegrityError("Publication reading identity differs")
        data = publication.model_dump(mode="json", exclude={"publication_id", "result_version"})
        if digest(json_bytes(data)) != publication.result_version or publication.publication_id != "publication:" + publication.result_version:
            raise NativeIntegrityError("Publication version differs from its content")
        outcome_sha = digest(json_bytes({"outcome": publication.interpretation_outcome.model_dump(mode="json"),
            "interpretation": publication.interpretation.model_dump(mode="json") if publication.interpretation else None}))
        data, outcome, interpretation = load_outcome(publication.outcome_id, c=conn)
        if (publication.outcome_sha256 != outcome_sha or outcome != publication.interpretation_outcome
                or interpretation != publication.interpretation or data["run_id"] != publication.run_id
                or data["item_id"] != publication.item_id or data["reading_id"] != publication.reading_id):
            raise NativeIntegrityError("Publication outcome digest differs")
        if publication.interpretation is not None and (publication.interpretation.digest() != publication.payload_sha256
                or publication.interpretation_id != "interpretation:" + publication.payload_sha256):
            raise NativeIntegrityError("Publication interpretation digest differs")
        _verify_receipts(publication, conn)


def version_parts(run_id: str, c: sqlite3.Connection) -> list[dict]:
    result = []
    for row in c.execute("SELECT item_id FROM native_publications WHERE run_id=? ORDER BY item_id", (run_id,)):
        pub = get_publication(run_id, row[0], c=c)
        verify_publication(pub, c=c)
        result.append({"item_id": pub.item_id, "publication_id": pub.publication_id, "result_version": pub.result_version,
                       "source_sha256": pub.source_sha256, "reading_id": pub.reading_id, "bundle_sha256": pub.bundle_sha256,
                       "attempts": [r.model_dump(mode="json") for r in pub.reading.results],
                       "outcome_sha256": pub.outcome_sha256, "payload_sha256": pub.payload_sha256})
    return result


def resolve_citations(publication: Publication, citations: Sequence[Citation | dict], c=None) -> tuple[NativeCitation, ...]:
    verify_publication(publication, c=c)
    delivery = load_reading(publication.reading_id, c=c)
    return _resolve(publication, citations, delivery)


def _resolve(publication, citations, delivery):
    elements = {(r.attempt.occurrence_id, e.element_id): (r.attempt, e) for r in delivery.bundle.results for e in r.elements}
    result = []
    for raw in citations:
        cite = raw if isinstance(raw, Citation) else Citation.model_validate_json(json_bytes(raw))
        selected = elements.get((cite.occurrence_id, cite.element_id))
        if selected is None or not selected[1].text or cite.quote not in selected[1].text:
            raise NativeIntegrityError("Citation is absent from this publication's source element")
        attempt, element = selected
        matches, start = [], 0
        while (index := element.text.find(cite.quote, start)) >= 0:
            matches.append(index)
            start = index + 1
        span = None
        if isinstance(element.locator, TextLocator) and len(matches) == 1:
            start = element.locator.start + matches[0]
            span = TextLocator(kind="text", text_sha256=element.locator.text_sha256, start=start, end=start + len(cite.quote))
        result.append(NativeCitation(**cite.model_dump(), locator=element.locator,
            attempt_id=attempt.attempt_id, reader_key=attempt.reader_key(), reading_id=publication.reading_id,
            publication_id=publication.publication_id, result_version=publication.result_version,
            source_sha256=publication.source_sha256, quote_match_count=len(matches), quote_span=span))
    return tuple(result)


def machine_facts(publication: Publication, c=None) -> tuple[NativeFact, ...]:
    verify_publication(publication, c=c)
    if publication.interpretation is None:
        return ()
    facts = []
    delivery = load_reading(publication.reading_id, c=c)
    for index, fact in enumerate(publication.interpretation.facts):
        citations = []
        for cite in fact.proposal.citations:
            try:
                citations.extend(_resolve(publication, (cite,), delivery))
            except NativeIntegrityError:
                # Invalid model proposals remain visible, but never become
                # verified source locations merely because a model supplied them.
                if fact.grounding != "rejected":
                    raise
        facts.append(NativeFact(fact_id="fact:" + digest(json_bytes([publication.payload_sha256, index])),
            **fact.model_dump(), effective_value=fact.proposal.value, native_citations=tuple(citations)))
    return tuple(facts)


def validate_sources(publication: Publication, native_sources: Mapping[str, Sequence[Citation | dict]], c=None) -> dict[str, tuple[Citation, ...]]:
    identifiers = {fact.fact_id for fact in machine_facts(publication, c=c)}
    if set(native_sources) - identifiers:
        raise ValueError("Unknown native fact identifier")
    return {key: tuple(Citation(occurrence_id=cite.occurrence_id, element_id=cite.element_id, quote=cite.quote)
                       for cite in resolve_citations(publication, values, c=c)) for key, values in native_sources.items()}


def source_elements(publication: Publication, *, offset: int = 0, limit: int = 200,
                    occurrence_id: str | None = None) -> SourcePage:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Source pagination requires offset >= 0 and limit between 1 and 500")
    verify_publication(publication)
    delivery = load_reading(publication.reading_id)
    if occurrence_id is not None and occurrence_id not in {o.occurrence_id for o in delivery.bundle.manifest.occurrences}:
        raise ValueError("Unknown source occurrence")
    elements = [NativeSourceElement(**e.model_dump(), occurrence_id=r.attempt.occurrence_id,
        attempt_id=r.attempt.attempt_id, reader_key=r.attempt.reader_key()) for r in delivery.bundle.results
        if occurrence_id is None or r.attempt.occurrence_id == occurrence_id for e in r.elements]
    page = tuple(elements[offset:offset + limit])
    keys = {e.locator.text_sha256 for e in page if isinstance(e.locator, TextLocator)}
    more = offset + len(page) < len(elements)
    return SourcePage(publication_id=publication.publication_id, reading_id=publication.reading_id,
        result_version=publication.result_version, bundle_sha256=publication.bundle_sha256, source_sha256=publication.source_sha256,
        occurrences=delivery.bundle.manifest.occurrences, results=publication.reading.results, elements=page,
        texts={key: delivery.texts[key].decode("utf-8") for key in keys}, offset=offset, limit=limit,
        total=len(elements), has_more=more, next_offset=offset + len(page) if more else None)


def referenced_artifacts(c: sqlite3.Connection) -> tuple[ArtifactRef, ...]:
    files = {}
    for row in c.execute("SELECT reading_id FROM native_readings ORDER BY reading_id"):
        ref = _reading(row[0], c)
        delivery = load_reading(ref.reading_id, c=c)
        expected = {"bundle.json": canonical_bytes(delivery.bundle)}
        for name in ("objects", "evidence", "texts", "rasters"):
            expected.update({f"{name}/{key}": value for key, value in getattr(delivery, name).items()})
        for name, data in expected.items():
            relative = ref.artifact_relpath + "/" + name
            _path(relative)
            files[relative] = ArtifactRef(relative_path=relative, byte_size=len(data), sha256=digest(data))
    return tuple(files[name] for name in sorted(files))


def unpublished_state(run_id: str, item_id: str, c=None) -> NativeProgress:
    """Read only saved state and call-log evidence; never create Burr state."""
    with _connection(c) as conn:
        row = conn.execute("SELECT * FROM native_outcomes WHERE run_id=? AND item_id=?", (run_id, item_id)).fetchone()
        if row:
            data, outcome, _ = load_outcome(row["outcome_id"], c=conn)
            return NativeProgress(reading=_reading(data["reading_id"], conn).reading, interpretation_outcome=outcome)
        item = conn.execute("SELECT status,error,flow_run_id FROM run_items WHERE run_id=? AND item_id=?", (run_id, item_id)).fetchone()
    graph_id = item["flow_run_id"] if item else f"{run_id}:{item_id[:16]}"
    path = store.current_path().with_name("burr_state.sqlite")
    state = {}
    if path.is_file():
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as burr:
            if burr.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='burr_state'").fetchone():
                row = burr.execute("SELECT state FROM burr_state WHERE partition_key='native' AND app_id=? ORDER BY sequence_id DESC LIMIT 1", (graph_id,)).fetchone()
                if row:
                    state = json.loads(row[0])
    reading = _reading(state["reading_id"], c).reading if state.get("reading_id") else ReadingSummary()
    if item and item["status"] in {"failed", "cancelled"}:
        return NativeProgress(reading=reading, interpretation_outcome=Failed(reason="Processing stopped before publication"))
    if state.get("reading_id"):
        return NativeProgress(reading=reading, interpretation_outcome=Running())
    return NativeProgress(reading=reading)
