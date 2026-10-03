"""Synthetic guards for cropped PDF evidence and process-specific protections."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

import dotenv
from PIL import Image
from pydantic import ValidationError
import pytest

from jav.readers import native, pipeline, visual_ocr
from jav.readers.contracts import ParsedDocument
from jav.readers.isolation import exchange
from jav.readers.limits import DEFAULT_LIMITS


def cropped_pdf() -> bytes:
    stream = "BT /F1 11 Tf 14 TL 50 800 Td (OUTSIDE CROP 999) Tj T* () Tj T* (VISIBLE VALUE 123) Tj ET"
    bodies = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /CropBox [0 0 595 780] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
    ]
    data, offsets = bytearray(b"%PDF-1.4\n"), []
    for index, body in enumerate(bodies, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n{body}\nendobj\n".encode())
    xref = len(data)
    data.extend(f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


@pytest.mark.parametrize("recognise", [False, True])
def test_crop_geometry_is_rejected_before_words_can_support_facts(recognise):
    result = native.read(cropped_pdf(), "cropped.pdf", DEFAULT_LIMITS, recognise=recognise)
    assert result["status"] == "partial"
    assert any(issue["code"] == "unread_content" and "geometry" in issue["message"] for issue in result["issues"])
    assert not [element for element in result["elements"] if element.get("text")]
    assert not result.get("rasters")
    for layer in result["source_layers"].values():
        assert not layer["words"]
        assert [(page["width_pt"], page["height_pt"]) for page in layer["pages"]] == [(595, 780)]


@pytest.fixture
def recognised_source(tmp_path, monkeypatch):
    class FakeOCR:
        fingerprint = "a" * 64

        def recognise(self, png, limits, *, timeout):
            assert png.startswith(b"\x89PNG")
            return ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                    "5\t1\t1\t1\t1\t1\t10\t10\t30\t20\t95\tSYNTHETIC\n")

    monkeypatch.setattr(visual_ocr.LocalOCR, "discover", lambda: FakeOCR())
    stream = BytesIO()
    Image.new("RGB", (100, 80), "white").save(stream, format="PNG")
    path = tmp_path / "source.png"
    path.write_bytes(stream.getvalue())
    return pipeline.read_files([path], ocr=True)


def test_ocr_reports_its_weaker_boundary_and_preserves_scopes_on_reload(recognised_source, tmp_path):
    delivery = recognised_source
    result = delivery.bundle.results[0]
    assert result.status == "partial"
    assert any(issue.code == "protection_unavailable" for issue in result.issues)
    assert [element.text for element in result.elements if element.text] == ["SYNTHETIC"]
    assert result.attempt.protections.network == result.attempt.protections.paths == "unavailable"
    assert all(value == "enforced" for value in result.attempt.parser_protections.model_dump().values())
    assert result.attempt.recognition_protections.network == "unavailable"
    assert result.attempt.recognition_protections.paths == "unavailable"
    assert result.attempt.recognition_protections.time == "enforced"
    assert result.attempt.recognition_protections.memory == "enforced"
    raw = json.loads(delivery.evidence[result.raw_evidence.sha256])
    assert raw["protection_scopes"]["parser"] == result.attempt.parser_protections.model_dump()
    assert raw["protection_scopes"]["recognition"] == result.attempt.recognition_protections.model_dump()
    output = tmp_path / "saved"
    delivery.save(output)
    assert pipeline.Delivery.load(output).bundle == delivery.bundle


@pytest.mark.parametrize("forgery", ["aggregate", "parser", "scope", "missing_scope", "complete", "missing_issue"])
def test_ocr_scopes_cannot_bypass_the_parser_contract(recognised_source, forgery):
    payload = recognised_source.bundle.results[0].model_dump(mode="json")
    attempt = payload["attempt"]
    if forgery == "aggregate":
        attempt["protections"]["network"] = "enforced"
    elif forgery == "parser":
        attempt["parser_protections"]["network"] = "unavailable"
    elif forgery == "scope":
        attempt["recognition_protections"]["memory"] = "unavailable"
        attempt["protections"]["memory"] = "unavailable"
    elif forgery == "missing_scope":
        attempt["parser_protections"] = None
    elif forgery == "complete":
        payload["status"] = "complete"
        payload["issues"] = []
    else:
        payload["issues"] = [issue for issue in payload["issues"] if issue["code"] != "protection_unavailable"]
    with pytest.raises(ValidationError):
        ParsedDocument.model_validate_json(json.dumps(payload))


def test_child_disables_actual_dotenv_loading_without_changing_normal_loading(monkeypatch):
    package_path = str(Path(dotenv.__file__).resolve().parent.parent)
    code = (
        "import io,json,os,sys;"
        f"sys.path.insert(0,{package_path!r});"
        "from dotenv import load_dotenv;"
        "loaded=load_dotenv(stream=io.StringIO('JAV_READER_SENTINEL=synthetic-only\\n'));"
        "print(json.dumps({'disabled':os.getenv('PYTHON_DOTENV_DISABLED'),"
        "'loaded':loaded,'sentinel':os.getenv('JAV_READER_SENTINEL')}))"
    )
    executable = getattr(sys, "_base_executable", sys.executable)
    command = [executable, "-I", "-B", "-c", code]
    normal_environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    control = subprocess.run(command, env=normal_environment, capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(control.stdout) == {"disabled": None, "loaded": True, "sentinel": "synthetic-only"}
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "0")
    isolated = exchange(command, b"", DEFAULT_LIMITS, output_bound=4096)
    assert json.loads(isolated) == {"disabled": "1", "loaded": False, "sentinel": None}


def test_legacy_saved_delivery_retains_its_original_bundle_digest(tmp_path):
    source = tmp_path / "legacy.txt"
    source.write_text("Synthetic legacy document", encoding="utf-8")
    delivery = pipeline.read_files([source])
    saved = tmp_path / "legacy-delivery"
    delivery.save(saved)
    payload = json.loads((saved / "bundle.json").read_bytes())
    for result in payload["results"]:
        result["attempt"].pop("parser_protections", None)
        result["attempt"].pop("recognition_protections", None)
    legacy_bytes = pipeline.json_bytes(payload)
    (saved / "bundle.json").write_bytes(legacy_bytes)
    loaded = pipeline.Delivery.load(saved)
    assert loaded.bundle.digest() == pipeline.digest(legacy_bytes)
    copied = tmp_path / "resaved-delivery"
    loaded.save(copied)
    assert (copied / "bundle.json").read_bytes() == legacy_bytes


def test_saved_ocr_cannot_forge_scopes_in_its_envelope(recognised_source, tmp_path):
    saved = tmp_path / "forged-delivery"
    recognised_source.save(saved)
    payload = json.loads((saved / "bundle.json").read_bytes())
    attempt = payload["results"][0]["attempt"]
    for scope in ("protections", "recognition_protections"):
        attempt[scope]["network"] = attempt[scope]["paths"] = "enforced"
    (saved / "bundle.json").write_bytes(pipeline.json_bytes(payload))
    with pytest.raises(ValueError, match="protection scopes"):
        pipeline.Delivery.load(saved)
