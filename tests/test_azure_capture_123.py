"""123 (F-azure-text-native, step 1): the original Azure recognition is kept, content-addressed.

Until 123 the Azure answer was reduced to axis-aligned word boxes at once, and the original (polygons, page size,
unit, angle) was thrown away, so no later step could verify where a recognised word came from. Now the original is
saved once under the sha256 of its canonical JSON, and that digest travels with the recognition signals. The text,
the lines, the OCR cache key and the call's request hash do not change. The HTTP client is a fake; no network.
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from jav import ocr, store
from jav.adapters import azure_di
from tests.test_azure_direct_121 import RESULT, FakeAzure, _escalate, keys, weak_scan  # noqa: F401 - fixtures


def test_evidence_words_name_the_digest_of_the_original_recognition():
    evidence = azure_di.evidence(RESULT["analyzeResult"])
    pages, confs, meta = ocr.azure_evidence_words(evidence)
    assert [w["text"] for w in pages[0]] == ["Payable", "1000"] and confs == [99.0, 98.0]
    assert meta == {"model_id": "prebuilt-read", "api_version": "2024-11-30",
                    "recognition_sha256": ocr.recognition_digest(evidence)}
    # The digest does not depend on key order.
    assert ocr.recognition_digest(dict(reversed(list(evidence.items())))) == meta["recognition_sha256"]


def test_escalation_keeps_the_original_recognition_without_changing_the_call(weak_scan, keys):  # noqa: F811
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(weak_scan)
    assert escalated and "Payable 1000" in pdf.lines
    sha = pdf.ocr["recognition_sha256"]
    assert ocr.load_recognition(sha) == azure_di.evidence(RESULT["analyzeResult"])
    source_sha = hashlib.sha256(weak_scan.read_bytes()).hexdigest()
    with store.connect() as c:
        rows = [tuple(r) for r in c.execute("SELECT request_hash, step_id FROM invocations WHERE provider='azure_di'")]
    assert rows == [(source_sha, f"azure_di:ocr:{source_sha[:16]}")]


def test_load_recognition_refuses_a_missing_or_changed_original(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        evidence = azure_di.evidence(RESULT["analyzeResult"])
        sha = ocr.save_recognition(evidence)
        assert ocr.save_recognition(evidence) == sha  # an identical repeat is allowed
        with pytest.raises(KeyError):
            ocr.load_recognition("0" * 64)
        store.save_artifact(ocr.AZURE_RECOGNITION_KIND, "f" * 64, {**evidence, "content": "changed"})
        with pytest.raises(ValueError, match="does not match"):
            ocr.load_recognition("f" * 64)
