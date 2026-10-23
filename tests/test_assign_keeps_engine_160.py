"""160 (plan F-csak-gpt, L2): a command-line reassignment keeps the package's settings that it does not name.

`wp-assign` used to send only the path, the type and the "earlier answers" setting, so every other setting fell back
to the recipe's default: a package switched to processing without JEV silently got JEV back. The command now starts
from the current assignment of the same recipe and changes only what it is told; `--engine gpt|jev` sets the engine.
"""

import json
from pathlib import Path

from jav import cli
from jav.core import store
from tests.pdfgen import INVOICE_LINES, write_text_pdf


def _run(capsys, *argv) -> dict:
    assert cli.main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def _package(tmp_path: Path, capsys) -> str:
    folder = tmp_path / "in"
    folder.mkdir()
    write_text_pdf(folder / "invoice.pdf", INVOICE_LINES)
    return _run(capsys, "wp-create", str(folder), "--name", "Engine")["id"]


def test_engine_gpt_switches_jev_off(tmp_path: Path, capsys):
    with store.use_store(tmp_path / "w.sqlite"):
        wp = _package(tmp_path, capsys)
        assigned = _run(capsys, "wp-assign", wp, "processing", "--engine", "gpt")
        assert assigned["params"]["jev"] == "off"


def test_a_reassignment_keeps_the_settings_it_does_not_name(tmp_path: Path, capsys):
    with store.use_store(tmp_path / "w.sqlite"):
        wp = _package(tmp_path, capsys)
        _run(capsys, "wp-assign", wp, "processing", "--engine", "gpt")
        again = _run(capsys, "wp-assign", wp, "processing", "--jev-cache", "live")
        assert again["params"]["jev"] == "off" and again["params"]["jev_cache"] == "live"
        back = _run(capsys, "wp-assign", wp, "processing", "--engine", "jev")
        assert back["params"]["jev"] == "on" and back["params"]["jev_cache"] == "live"


def test_another_recipe_starts_from_its_own_defaults(tmp_path: Path, capsys):
    """Only the same recipe's settings carry over; the internal extraction recipe has no engine setting at all."""
    with store.use_store(tmp_path / "w.sqlite"):
        wp = _package(tmp_path, capsys)
        _run(capsys, "wp-assign", wp, "processing", "--engine", "gpt", "--jev-cache", "live")
        other = _run(capsys, "wp-assign", wp, "invoice-extraction")
        assert other["params"] == {"arm": "auto", "doc_type": "invoice_hu", "jev_cache": "reuse", "azure_ocr": "on"}


def test_engine_on_a_recipe_without_the_setting_is_refused(tmp_path: Path, capsys):
    with store.use_store(tmp_path / "w.sqlite"):
        wp = _package(tmp_path, capsys)
        assert cli.main(["wp-assign", wp, "invoice-extraction", "--engine", "gpt"]) == 2
        assert "no engine setting" in capsys.readouterr().out
