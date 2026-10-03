"""Synthetic acceptance examples for the isolated source contract."""

import json
import socket

import pytest
from pydantic import ValidationError

from jav.readers.contracts import ContractError, ParseAttempt, SourceBundle, canonical_bytes, read_bundle, verify_evidence
from reader_samples import raw_evidence_payload, sample_bundles, synthetic_payloads


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Source contract checks must not use the network")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.mark.parametrize("name", ["spreadsheet", "word_image", "email_manifest"])
def test_round_trip_is_lossless_and_has_no_human_approval(name):
    bundle = sample_bundles()[name]
    restored = read_bundle(canonical_bytes(bundle))
    assert restored == bundle
    assert restored.digest() == bundle.digest()
    assert all(result.interpretation_status == "not_run" for result in restored.results)
    assert all(result.human_review_status == "not_reviewed" for result in restored.results)


def test_cells_keep_empty_position_leading_zero_and_missing_formula_cache():
    result = sample_bundles()["spreadsheet"].results[0]
    cells = {element.locator.cell: element for element in result.elements if element.kind == "cell"}
    assert cells["A2"].cell.value.lexical == "0007"
    assert cells["B2"].cell.value.kind == "empty"
    assert cells["C2"].cell.formula == "=1+2"
    assert cells["C2"].cell.cached_state == "missing"
    assert cells["C2"].cell.cached_value is None
    assert cells["A2"].locator.row == 2
    assert result.status == "partial"


def test_word_keeps_order_and_identifies_unread_image_without_fake_page():
    result = sample_bundles()["word_image"].results[0]
    assert [element.kind for element in result.elements] == ["paragraph", "table", "paragraph", "image"]
    assert [element.order for element in result.elements] == [0, 1, 2, 3]
    assert "page" not in result.elements[0].locator.model_dump()
    assert result.elements[-1].availability == "unreadable"
    assert result.elements[-1].locator.host.structural_path == "/body/p[3]/drawing[1]"
    assert any(issue.code == "needs_ocr" for issue in result.issues)


def test_manifest_accounts_for_missing_inline_and_duplicate_content():
    bundle = sample_bundles()["email_manifest"]
    occurrences = {item.occurrence_id: item for item in bundle.manifest.occurrences}
    assert occurrences["attachment"].object_sha256 == occurrences["upload"].object_sha256
    assert occurrences["attachment"].parent_id == "message"
    assert occurrences["upload"].parent_id is None
    assert occurrences["missing"].object_sha256 is None
    assert occurrences["missing"].acquisition == "missing"
    assert occurrences["inline"].role == "inline"
    assert bundle.manifest.acquisition_status() == "partial"
    assert len(bundle.manifest.inventories) == 1
    assert bundle.manifest.inventories[0].expected_children == 4
    assert bundle.reading_status("attachment") == "not_attempted"
    assert bundle.reading_status("missing") == "unavailable"
    assert bundle.reading_status("unsupported") == "unsupported"


@pytest.mark.parametrize("mutation", ["missing_object", "cycle", "wrong_count", "lost_issue", "unknown_total"])
def test_manifest_rejects_false_completeness_and_broken_references(mutation):
    value = sample_bundles()["email_manifest"].model_dump(mode="json")
    manifest = value["manifest"]
    if mutation == "missing_object":
        manifest["objects"] = []
    elif mutation == "cycle":
        manifest["occurrences"][0]["parent_id"] = "attachment"
    elif mutation == "wrong_count":
        manifest["inventories"][0]["expected_children"] = 3
    elif mutation == "lost_issue":
        next(item for item in manifest["occurrences"] if item["occurrence_id"] == "missing")["issues"] = []
    else:
        manifest["inventories"][0]["expected_children"] = None
    with pytest.raises((ValidationError, ContractError)):
        read_bundle(json.dumps(value).encode())


@pytest.mark.parametrize("mutation", ["parent", "order", "source", "element_ref", "cell_address", "evidence"])
def test_result_rejects_broken_structural_or_source_links(mutation):
    value = sample_bundles()["spreadsheet"].model_dump(mode="json")
    result = value["results"][0]
    if mutation == "parent":
        result["elements"][1]["parent_id"] = "absent"
    elif mutation == "order":
        result["elements"][2]["order"] = result["elements"][1]["order"]
    elif mutation == "source":
        result["attempt"]["source_sha256"] = "a" * 64
    elif mutation == "element_ref":
        result["issues"][0]["element_id"] = "absent"
    elif mutation == "cell_address":
        result["elements"][1]["locator"]["cell"] = "B2"
    else:
        result["raw_evidence"]["reader_key"] = "b" * 64
    with pytest.raises((ValidationError, ContractError)):
        read_bundle(json.dumps(value).encode())


def test_parse_identity_changes_with_parser_configuration_or_models():
    attempt = sample_bundles()["spreadsheet"].results[0].attempt
    for field, replacement in [("parser_version", "next"), ("config_sha256", "c" * 64), ("models_sha256", "d" * 64)]:
        data = attempt.model_dump()
        data[field] = replacement
        assert type(attempt)(**data).reader_key() != attempt.reader_key()
    data = attempt.model_dump()
    data["occurrence_id"] = "other-occurrence"
    assert type(attempt)(**data).reader_key() == attempt.reader_key()


def test_model_is_deeply_immutable_and_result_changes_invalidate_digest():
    bundle = sample_bundles()["spreadsheet"]
    with pytest.raises(ValidationError):
        bundle.results[0].status = "complete"
    assert isinstance(bundle.results[0].elements, tuple)
    value = bundle.model_dump(mode="json")
    value["results"][0]["elements"][1]["cell"]["value"]["lexical"] = "0008"
    assert read_bundle(json.dumps(value).encode()).digest() != bundle.digest()


@pytest.mark.parametrize("payload", [b"{}" * 1_100_000, b'[' * 1100 + b']' * 1100, b'{"schema_version":NaN}'],
                         ids=["oversize", "too_deep", "non_finite"])
def test_external_input_limits_are_named_errors(payload):
    with pytest.raises(ContractError):
        read_bundle(payload)


def test_unknown_fields_and_fabricated_office_page_are_rejected():
    value = sample_bundles()["word_image"].model_dump(mode="json")
    value["results"][0]["elements"][0]["locator"]["page"] = 1
    with pytest.raises(ValidationError):
        SourceBundle.model_validate(value)


def test_no_real_reader_can_report_success_with_unenforced_protections():
    value = sample_bundles()["spreadsheet"].model_dump(mode="json")
    value["results"][0]["attempt"]["execution"] = "reader"
    attempt = ParseAttempt.model_validate_json(json.dumps(value["results"][0]["attempt"]))
    value["results"][0]["raw_evidence"]["reader_key"] = attempt.reader_key()
    with pytest.raises(ValidationError, match="enforce its protections"):
        read_bundle(json.dumps(value).encode())


def test_partial_inventory_keeps_unknown_denominator_visible():
    value = sample_bundles()["email_manifest"].model_dump(mode="json")
    inventory = value["manifest"]["inventories"][0]
    inventory.update(completeness="unknown", expected_children=None)
    inventory["issues"] = [{"stage": "acquisition", "code": "inventory_unknown", "message": "The sender did not supply a count."}]
    bundle = read_bundle(json.dumps(value).encode())
    assert bundle.manifest.inventories[0].expected_children is None
    assert bundle.manifest.acquisition_status() == "partial"


def test_evidence_loading_checks_source_and_payload_without_rereading():
    result = sample_bundles()["spreadsheet"].results[0]
    name = "spreadsheet.blueprint.json"
    source = synthetic_payloads()[name]
    evidence = raw_evidence_payload(result, name)
    verify_evidence(result.raw_evidence, source, evidence)
    for altered_source, altered_evidence in [(source + b" ", evidence), (source, evidence + b" ")]:
        with pytest.raises(ContractError):
            verify_evidence(result.raw_evidence, altered_source, altered_evidence)


def test_duplicate_json_keys_are_not_silently_discarded():
    with pytest.raises(ContractError):
        read_bundle(b'{"schema_version":"a","schema_version":"b"}')


def test_boolean_is_not_a_cell_coordinate():
    value = sample_bundles()["spreadsheet"].model_dump(mode="json")
    value["results"][0]["elements"][1]["locator"]["row"] = True
    with pytest.raises(ValidationError):
        read_bundle(json.dumps(value).encode())


def test_an_unrelated_image_is_not_evidence_for_a_document():
    value = sample_bundles()["word_image"].model_dump(mode="json")
    value["manifest"]["occurrences"][1]["parent_id"] = None
    value["manifest"]["inventories"][0]["expected_children"] = 0
    with pytest.raises(ValidationError, match="descendant occurrence"):
        read_bundle(json.dumps(value).encode())
