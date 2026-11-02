"""278: what a fresh installation on another Windows machine ran into, fixed.

A clone from GitHub, installed by the setup guide, worked, with four gaps. The native recogniser's language packs are
not in git, and nothing said where exactly to get them or that they were missing: the OCR state said "native", and the
first scanned document failed with only `CalledProcessError`. The packs are now pinned in `configs/ocr.json` (the
release and each file's SHA-256), `ocr --fetch-langs` fetches the missing ones, and the state, the start-up check, the
failure and the worker's log name what is missing. A taken port made the local service stop with nothing on the screen (uvicorn wrote
the reason only into its log); the service now names it before it loads. A stop requested while a worker was still
loading was taken for an old one and deleted, so the start script killed the worker after its time limit. Nothing
here asks an AI or the network: the downloads go through a stand-in opener.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import socket
import subprocess
import time
import urllib.error
from pathlib import Path

import pytest

from jav.core import cfg, store
from jav.documents import ocr, tessdata
from jav.runtime import worker

ROOT = Path(__file__).resolve().parents[1]


# --- the language packs -------------------------------------------------------------------------------------------


def test_the_configured_packs_cover_the_languages_asked_from_a_tagged_release() -> None:
    packs = cfg.load("ocr")["tesseract"]["language_packs"]
    assert set(tessdata.required()) <= set(tessdata.pinned())  # hun and eng: what `-l hun+eng` reads with
    assert all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in tessdata.pinned().values())
    source = packs["source"]
    assert source.startswith("https://") and "{name}" in source
    assert "/main/" not in source and "/raw/4.1.0/" in source  # a tag, so the files cannot move under the pins


def test_the_pins_are_not_part_of_the_ocr_cache_key() -> None:
    conf = cfg.load("ocr")
    assert "language_packs" not in ocr.output_settings(conf)["tesseract"]
    without = json.loads(json.dumps(conf))
    del without["tesseract"]["language_packs"]
    assert ocr.output_hash(conf) == ocr.output_hash(without)  # every earlier recognised text stays reusable


def _opener(contents: dict[str, bytes], seen: list[str]):
    def open_(request, timeout):  # the urllib.request.urlopen signature the module calls with
        url = request.full_url
        seen.append(url)
        name = url.rsplit("/", 1)[-1].removesuffix(tessdata.SUFFIX)
        if name not in contents:
            raise urllib.error.URLError("no route")
        return io.BytesIO(contents[name])

    return open_


def _pin(monkeypatch, contents: dict[str, bytes]) -> None:
    monkeypatch.setattr(tessdata, "pinned", lambda: {n: hashlib.sha256(b).hexdigest() for n, b in contents.items()})


def test_fetch_keeps_only_files_whose_fingerprint_matches(tmp_path, monkeypatch) -> None:
    good = {"hun": b"hungarian model", "eng": b"english model", "osd": b"orientation model"}
    _pin(monkeypatch, good)
    served = {**good, "eng": b"a changed file on the server"}
    seen: list[str] = []
    outcomes = {o.name: o for o in tessdata.fetch(tmp_path / "tessdata", opener=_opener(served, seen))}
    assert outcomes["hun"].outcome == "fetched" and outcomes["osd"].outcome == "fetched"
    assert outcomes["eng"].outcome == "failed" and "nothing was kept" in outcomes["eng"].detail
    folder = tmp_path / "tessdata"
    assert (folder / "hun.traineddata").read_bytes() == good["hun"]
    assert not (folder / "eng.traineddata").exists()
    assert not list(folder.glob("*.part"))  # no half-written download is left behind
    assert all(u.startswith("https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/") for u in seen)
    assert tessdata.missing(folder) == ["eng"]


def test_fetch_leaves_a_file_in_place_and_never_overwrites_a_different_one(tmp_path, monkeypatch) -> None:
    good = {"hun": b"hungarian model", "eng": b"english model"}
    _pin(monkeypatch, good)
    folder = tmp_path / "tessdata"
    folder.mkdir()
    (folder / "hun.traineddata").write_bytes(good["hun"])
    (folder / "eng.traineddata").write_bytes(b"someone's own, better model")
    seen: list[str] = []
    outcomes = {o.name: o.outcome for o in tessdata.fetch(folder, opener=_opener(good, seen))}
    assert outcomes == {"hun": "in_place", "eng": "kept_different"} and seen == []
    assert (folder / "eng.traineddata").read_bytes() == b"someone's own, better model"
    st = tessdata.state(folder)
    assert (st["present"], st["missing"], st["differs"]) == (["eng", "hun"], [], ["eng"])


def test_a_failed_download_is_an_outcome_not_a_crash(tmp_path, monkeypatch) -> None:
    _pin(monkeypatch, {"hun": b"x", "eng": b"y"})
    outcomes = tessdata.fetch(tmp_path, opener=_opener({}, []))
    assert [o.outcome for o in outcomes] == ["failed", "failed"]
    assert "URLError" in outcomes[0].detail


def test_a_source_that_is_not_https_is_refused(monkeypatch) -> None:
    real = tessdata._settings
    monkeypatch.setattr(tessdata, "_settings", lambda: {**real(), "language_packs": {
        "source": "http://example.invalid/{name}.traineddata", "files": {"hun": "0" * 64}}})
    with pytest.raises(tessdata.LanguagePackError, match="https"):
        tessdata.fetch(Path("unused"), opener=_opener({}, []))


def _no_engine(*_a, **_k):
    raise ocr.OcrUnavailableError("no OCR engine (auto)")


def test_the_ocr_state_names_the_missing_packs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JAV_TESSDATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "engine", _no_engine)
    st = ocr.status()
    assert st["tessdata"] == [] and st["tessdata_missing"] == ["hun", "eng"]
    assert st["tessdata_dir"] == str(tmp_path) and st["tessdata_differs"] == []


def test_a_failed_native_run_names_the_missing_packs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JAV_TESSDATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "native_exe", lambda: "tesseract")

    def fail(cmd, **_k):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(ocr.subprocess, "run", fail)
    with pytest.raises(ocr.OcrEngineFailed, match=r"hun, eng are missing .*--fetch-langs"):
        ocr._run_tesseract(tmp_path / "p1.png", tmp_path / "p1")
    (tmp_path / "hun.traineddata").write_bytes(b"x")
    (tmp_path / "eng.traineddata").write_bytes(b"y")
    with pytest.raises(ocr.OcrEngineFailed) as exc:  # with the packs there, the failure is the engine's own
        ocr._run_tesseract(tmp_path / "p1.png", tmp_path / "p1")
    assert "missing" not in str(exc.value)


def test_the_reason_ocr_could_not_run_reaches_the_log(monkeypatch, caplog) -> None:
    from jav.documents import pdf_input

    def missing(*_a, **_k):
        raise ocr.OcrEngineFailed("the OCR engine (native) failed on p1.png: CalledProcessError; the language pack(s) "
                                  "hun, eng are missing from D:/t (python -m jav.cli ocr --fetch-langs)")

    monkeypatch.setattr(ocr, "ocr_with_escalation", missing)
    with caplog.at_level("WARNING", logger="jav.documents.pdf_input"):
        got = pdf_input.recognise("scan.pdf", None, "doc-1", 1)
    assert got.pdf is None and got.unavailable == "ocr:unavailable:OcrEngineFailed"  # the to-do's kind is unchanged
    assert "doc-1" in caplog.text and "hun, eng are missing" in caplog.text


def test_the_start_up_check_shows_the_ocr_state_and_never_fails_on_it(monkeypatch) -> None:
    from jav.devtools import preflight

    base = {"engine": "native", "engine_version": "tesseract v5.4.0", "tessdata": [], "tessdata_dir": "D:/t",
            "tessdata_missing": ["hun", "eng"], "tessdata_differs": []}
    monkeypatch.setattr(ocr, "status", lambda: base)
    ok, msg = preflight.ocr_status()
    assert ok and "hun, eng missing from D:/t" in msg and "ocr --fetch-langs" in msg
    monkeypatch.setattr(ocr, "status", lambda: {**base, "tessdata": ["eng", "hun", "osd"], "tessdata_missing": [],
                                                "tessdata_differs": ["osd"]})
    ok, msg = preflight.ocr_status()
    assert ok and msg == "native tesseract v5.4.0; language packs eng, hun, osd (osd not the pinned file)"
    monkeypatch.setattr(ocr, "status", lambda: {"engine": None, "error": "no OCR engine (auto)"})
    ok, msg = preflight.ocr_status()
    assert ok and "install Tesseract 5" in msg


def test_the_fetch_command_reports_each_file_and_fails_while_one_is_missing(tmp_path, monkeypatch, capsys) -> None:
    from jav.cli import maintenance_cli

    monkeypatch.setenv("JAV_TESSDATA_DIR", str(tmp_path))
    monkeypatch.setattr(tessdata, "fetch", lambda folder: [tessdata.FetchOutcome("hun", "failed", "URLError: no route"),
                                                           tessdata.FetchOutcome("eng", "in_place")])
    args = type("A", (), {"fetch_langs": True, "pdf": None})()
    assert maintenance_cli.cmd_ocr(args) == 2
    out = capsys.readouterr().out
    assert "hun: failed (URLError: no route)" in out and "eng: in place" in out and "Still missing: hun, eng" in out


# --- the local service's start ------------------------------------------------------------------------------------


def test_a_taken_port_is_named_before_the_service_loads() -> None:
    from jav.service import api

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = held.getsockname()[1]
        with pytest.raises(api.PortInUseError, match=rf"127\.0\.0\.1:{port} is taken.*--port"):
            api.check_port_free("127.0.0.1", port)


def test_the_serve_command_says_why_it_did_not_start(monkeypatch, capsys) -> None:
    from jav.cli import work_cli
    from jav.service import api

    def taken(**_k):
        raise api.PortInUseError("127.0.0.1:8930 is taken")

    monkeypatch.setattr(api, "serve", taken)
    assert work_cli.cmd_serve(type("A", (), {"port": None})()) == 2
    assert "The local service did not start: 127.0.0.1:8930 is taken" in capsys.readouterr().err

    def uvicorn_failed(**_k):
        raise SystemExit(3)

    monkeypatch.setattr(api, "serve", uvicorn_failed)
    with pytest.raises(SystemExit):
        work_cli.cmd_serve(type("A", (), {"port": None})())
    assert "exit code 3" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell is not on this machine")
def test_the_start_script_parses_and_waits_for_the_service() -> None:
    script = ROOT / "scripts" / "dev.ps1"
    parse = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
             f"'{script}', [ref]$null, [ref]$e); $e.Count")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", parse],
                         capture_output=True, text=True, timeout=120, check=True)
    assert out.stdout.strip() == "0"
    text = script.read_text(encoding="utf-8")
    assert "/api/health" in text and "Wait-Api $StartTimeoutSec" in text and "exit 1" in text


# --- the worker's stop ----------------------------------------------------------------------------------------------


def test_a_stop_requested_while_the_worker_loads_stops_it(tmp_path, monkeypatch) -> None:
    from jav.runtime import preload

    def loading() -> None:  # the start script's stop arrives while the worker still loads its code
        time.sleep(0.05)  # past the file system's clock step, so the request is visibly newer than the start
        worker.request_stop()

    with store.use_store(tmp_path / "w.sqlite"):
        monkeypatch.setattr(preload, "preload", loading)
        info = worker.run_worker(once=True, slot=0, idle_sleep_s=0)
        assert info["stopped"] is True and info["processed"] == 0
        assert not worker.stop_path().exists()  # the last worker to stop clears it
