"""Native review, publication binding and approval against synthetic persisted readings."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, corrections, native_results, store, work
from jav.native_contracts import Failed, Succeeded
from jav.readers.interpretation import Citation, ProposedExtraction, ProposedFact, ground
from jav.runtime import queue

HUMAN = {"X-Actor": "native.reviewer"}


def published_run(root: Path, *, outcome=None, empty=False, name="source.txt", content: bytes | None = None):
    """Real source/read/publication; interpretation is explicitly synthetic, with no provider invocation."""
    source = root / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content if content is not None else b"Reference: 00123\nCorrected: 00456\nPartner: Example\n")
    wp = work.create_from_files([source], name="Synthetic native review")
    work.assign_recipe(wp["id"], "multi-format-processing", params={"jev": "off"}, expected_revision=0, actor="reviewer")
    ready = work.readiness(wp["id"])
    rid = work.start_run(wp["id"], mode="apply", expected_assignment_revision=1,
                         input_hash=ready["input_hash"], actor="reviewer")["run_id"]
    item = work.get_run(rid)["input"]["items"][0]
    reading = native_results.prepare_reading(work.source_file(item), original_name=source.name, expected_sha256=item["sha256"])
    delivery = native_results.load_reading(reading.reading_id)
    result = next(result for result in delivery.bundle.results if result.elements)
    element = next(element for element in result.elements if element.text and "00123" in element.text)
    cite = Citation(occurrence_id=result.attempt.occurrence_id, element_id=element.element_id, quote="00123")
    proposal = ProposedExtraction(facts=() if empty else (ProposedFact(entity="document", property="reference", value="00123",
                                            state="stated", citations=(cite,)),))
    interpretation = ground(delivery, proposal, provider="openai", model="synthetic-native-model", execution="synthetic_test")
    outcome = outcome or Succeeded()
    publication = native_results.publish(run_id=rid, item_id=item["item_id"], source_sha256=item["sha256"],
        recipe_hash=work.get_run(rid)["recipe_hash"], reading_id=reading.reading_id,
        outcome=outcome, interpretation=interpretation if outcome.status == "succeeded" else None)
    job = queue.claim("native-synthetic")
    queue.complete(job.id)
    work.record_item_result(rid, item["item_id"], status="done", final_status="done", flow_run_id=work.flow_run_id(rid, item["item_id"]))
    work.refresh_run_status(rid)
    return rid, item, publication, cite


@pytest.fixture()
def native_env(tmp_path, monkeypatch):
    db = tmp_path / "native.sqlite"
    monkeypatch.setenv("JAV_API_ROOTS", str(tmp_path))
    with store.use_store(db):
        rid, item, publication, cite = published_run(tmp_path)
        yield {"root": tmp_path, "db": db, "run_id": rid, "item": item, "publication": publication, "cite": cite,
               "client": TestClient(api.create_app(store_path=db), base_url="http://127.0.0.1:8930")}


def test_native_result_sources_and_read_only_get(native_env, monkeypatch):
    env = native_env
    rid, iid = env["run_id"], env["item"]["item_id"]
    monkeypatch.setattr(native_results, "prepare_reading", lambda *_a, **_k: pytest.fail("GET invoked a reader"))
    result = env["client"].get(f"/api/runs/{rid}/items/{iid}")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["result_kind"] == "native" and body["result_ready"]
    assert "page_count" not in body and "source" not in body
    sources = env["client"].get(f"/api/runs/{rid}/items/{iid}/sources", params={"limit": 1})
    assert sources.status_code == 200, sources.text
    page = sources.json()
    assert page["result_version"] == body["result_version"] and len(page["elements"]) == 1
    assert page["total"] >= 1
    citation = env["cite"].model_dump(mode="json")
    resolved = env["client"].post(f"/api/runs/{rid}/items/{iid}/citations/resolve",
        json={"expected_result_version": body["result_version"], "citations": [citation]})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["citations"][0]["quote_match_count"] == 1
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == 0


def test_correction_keeps_proposal_requires_current_revision_and_result(native_env):
    env = native_env
    rid, iid = env["run_id"], env["item"]["item_id"]
    url = f"/api/runs/{rid}/items/{iid}"
    original = env["client"].get(url).json()
    fact = original["native_facts"][0]
    payload = {"kind": "native", "values": {fact["fact_id"]: "00456"}, "native_sources": {},
               "confirm": [fact["fact_id"]], "expected_revision": 0, "expected_result_version": original["result_version"]}
    saved = env["client"].post(url + "/correction", headers=HUMAN, json=payload)
    assert saved.status_code == 200, saved.text
    actual = saved.json()["native_facts"][0]
    assert actual["effective_value"] == "00456" and actual["confirmed"]
    assert actual["proposal"] == fact["proposal"] and actual["grounding"] == fact["grounding"]
    assert actual["native_citations"] == []
    assert env["client"].post(url + "/correction", headers=HUMAN, json=payload).status_code == 409
    payload.update(expected_revision=1, expected_result_version="0" * 64)
    assert env["client"].post(url + "/correction", headers=HUMAN, json=payload).status_code == 409
    assert corrections.current(rid, iid)["fields"][fact["fact_id"]] == "00456"
    with pytest.raises(work.RevisionConflict):
        work.approve_run(rid, actor="reviewer", review_version=original["review_version"])
    with pytest.raises(work.RevisionConflict):
        work.approve_run(rid, actor="reviewer")
    work.approve_run(rid, actor="reviewer", review_version=corrections.review_version(rid))
    payload.update(expected_revision=1, expected_result_version=original["result_version"])
    assert env["client"].post(url + "/correction", headers=HUMAN, json=payload).status_code == 409


@pytest.mark.parametrize("citation_patch", [{"occurrence_id": "foreign"}, {"element_id": "foreign"}, {"quote": "invented quote"}])
def test_foreign_or_fabricated_citation_is_refused(native_env, citation_patch):
    env = native_env
    rid, iid, pub = env["run_id"], env["item"]["item_id"], env["publication"]
    fact = native_results.machine_facts(pub)[0]
    cite = {**env["cite"].model_dump(mode="json"), **citation_patch}
    with pytest.raises(ValueError):
        corrections.save_native(rid, iid, values={fact.fact_id: "00123"}, native_sources={fact.fact_id: [cite]},
            expected_revision=0, expected_result_version=pub.result_version, actor="reviewer")
    assert corrections.current(rid, iid)["revision"] == 0


def test_unpublished_and_failed_native_items_cannot_be_approved(tmp_path):
    with store.use_store(tmp_path / "failed.sqlite"):
        rid, item, _pub, _cite = published_run(tmp_path, outcome=Failed(reason="Synthetic extraction failure"))
        result = corrections.item_result(rid, item["item_id"])
        assert result["result_ready"] and result["interpretation"] is None and result["native_facts"] == []
        with pytest.raises(work.NotReady):
            work.approve_run(rid, actor="reviewer", review_version=result["review_version"])


def test_empty_success_remains_distinct_from_failure(tmp_path):
    with store.use_store(tmp_path / "empty.sqlite"):
        rid, item, _pub, _cite = published_run(tmp_path, empty=True)
        result = corrections.item_result(rid, item["item_id"])
        assert result["interpretation_outcome"]["status"] == "succeeded"
        assert result["interpretation"]["status"] == "empty" and result["native_facts"] == []


def test_unpublished_item_never_uses_pdf_reader_or_approves(tmp_path, monkeypatch):
    from jav import page_image

    with store.use_store(tmp_path / "unpublished.sqlite"):
        source = tmp_path / "pending.txt"
        source.write_text("Synthetic pending input", encoding="utf-8")
        wp = work.create_from_files([source], name="Pending")
        work.assign_recipe(wp["id"], "multi-format-processing", params={"jev": "off"}, expected_revision=0, actor="reviewer")
        ready = work.readiness(wp["id"])
        rid = work.start_run(wp["id"], mode="apply", expected_assignment_revision=1,
            input_hash=ready["input_hash"], actor="reviewer")["run_id"]
        item = wp["items"][0]
        monkeypatch.setattr(page_image, "page_count", lambda *_a, **_k: pytest.fail("Native GET reached PDF reader"))
        result = corrections.item_result(rid, item["item_id"])
        assert result["result_kind"] == "native" and not result["result_ready"]
        assert result["result_version"] is None and result["native_source"] is None
        assert result["reading"]["status"] == "not_attempted"
        with pytest.raises(work.NotReady):
            corrections.native_publication(rid, item["item_id"])
        queue.complete(queue.claim("synthetic-finished-without-result").id)
        work.record_item_result(rid, item["item_id"], status="done", final_status="done")
        with pytest.raises(work.NotReady):
            work.approve_run(rid, actor="reviewer", review_version=result["review_version"])


def test_value_change_drops_only_that_confirmation(native_env):
    env = native_env
    rid, iid, pub = env["run_id"], env["item"]["item_id"], env["publication"]
    fact = native_results.machine_facts(pub)[0]
    corrections.save_native(rid, iid, values={fact.fact_id: "00123"}, native_sources={}, confirm=[fact.fact_id],
        expected_revision=0, expected_result_version=pub.result_version, actor="reviewer")
    corrections.save_native(rid, iid, values={fact.fact_id: "00456"}, native_sources={},
        expected_revision=1, expected_result_version=pub.result_version, actor="reviewer")
    assert corrections.current(rid, iid)["confirmed"] == {}
    # Reloading from a new application/connection preserves the corrected value and original proposal.
    fresh = TestClient(api.create_app(store_path=env["db"]), base_url="http://127.0.0.1:8930")
    result = fresh.get(f"/api/runs/{rid}/items/{iid}").json()
    assert result["native_facts"][0]["effective_value"] == "00456"
    assert result["native_facts"][0]["proposal"]["value"] == "00123"


def test_partial_reading_stays_partial_after_human_confirmation_and_approval(tmp_path):
    from io import BytesIO

    from docx import Document
    from docx.oxml import parse_xml

    document = Document()
    document.add_paragraph("Reference: 00123")
    document.element.body.insert(1, parse_xml(
        '<w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:sdtContent><w:p><w:r><w:t>Unmapped synthetic content</w:t></w:r></w:p></w:sdtContent></w:sdt>'))
    source = BytesIO()
    document.save(source)
    with store.use_store(tmp_path / "partial.sqlite"):
        rid, item, publication, _cite = published_run(tmp_path, name="partial.docx", content=source.getvalue())
        assert publication.reading.status == "partial"
        store.review_enqueue(subject_kind="document", subject_id=item["item_id"],
            run_id=work.flow_run_id(rid, item["item_id"]), producer="native", reasons=["native:reading:partial"])
        fact = native_results.machine_facts(publication)[0]
        corrections.save_native(rid, item["item_id"], values={}, native_sources={}, confirm=[fact.fact_id],
            expected_revision=0, expected_result_version=publication.result_version, actor="reviewer")
        result = corrections.item_result(rid, item["item_id"])
        assert result["native_facts"][0]["confirmed"] and result["reading"]["status"] == "partial"
        assert result["open_reasons"]
        with pytest.raises(work.NotReady):
            work.approve_run(rid, actor="reviewer", review_version=result["review_version"])
        for reason in result["open_reasons"]:
            work.resolve_reason(reason["id"], actor="reviewer", resolution={"accepted_gap": True}, note="Reviewed missing content")
        work.approve_run(rid, actor="reviewer", review_version=corrections.review_version(rid))
        result = corrections.item_result(rid, item["item_id"])
        assert result["reading"]["status"] == "partial"
        assert result["interpretation"]["correctness"] == "not_established"
