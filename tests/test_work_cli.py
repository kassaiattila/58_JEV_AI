"""A munkacsomag → futtatás parancssori életútja (040 K1), hamis JEV-klienssel, fizetős hívás nélkül."""

import json
from pathlib import Path

from jav import cli, store
from jav.adapters import jev as jev_mod
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient


def _run(capsys, *argv) -> dict:
    assert cli.main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_lifecycle(tmp_path: Path, capsys):
    folder = tmp_path / "bejovo"
    folder.mkdir()
    write_text_pdf(folder / "szamla.pdf", INVOICE_LINES)
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = _run(capsys, "wp-create", str(folder), "--name", "Próba")
        assert len(wp["items"]) == 1
        _run(capsys, "wp-assign", wp["id"], "invoice-extraction", "--arm", "S")
        shown = _run(capsys, "wp-show", wp["id"])
        assert shown["readiness"]["ready"]
        started = _run(capsys, "run-start", wp["id"], "--mode", "apply")
        again = _run(capsys, "run-start", wp["id"], "--mode", "apply")
        assert again["deduped"] and again["run_id"] == started["run_id"]
        info = _run(capsys, "worker", "--once")
        assert info["processed"] == 1
        run = _run(capsys, "run-show", started["run_id"])["run"]
        assert run["status"] in ("done", "needs_review") and run["items"][0]["status"] == "done"
        listed = _run(capsys, "run-list", wp["id"])
        assert [r["run_id"] for r in listed] == [started["run_id"]]
        assert cli.main(["recipes"]) == 0 and "invoice-extraction" in capsys.readouterr().out


def test_tests_never_write_the_ops_log():
    """065: a `worker` parancs az üzemi naplót kapcsolja be; a tesztek alatt ez ideiglenes mappába mutat (conftest)."""
    from jav.config import PROJECT_ROOT
    from jav.runtime import applog

    assert not applog.LOG_DIR.is_relative_to(PROJECT_ROOT / "runs")


def test_cli_run_start_refuses_unready(tmp_path: Path, capsys):
    folder = tmp_path / "ures"
    folder.mkdir()
    with store.use_store(tmp_path / "w.sqlite"):
        wp = _run(capsys, "wp-create", str(folder))
        assert cli.main(["run-start", wp["id"]]) == 2
        out = capsys.readouterr().out
        assert "Nem indítható" in out and "nincs tétel" in out


def test_cli_wp_create_from_files(tmp_path: Path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    write_text_pdf(a / "x.pdf", INVOICE_LINES)
    write_text_pdf(b / "y.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-009") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "w.sqlite"):
        wp = _run(capsys, "wp-create", "--files", str(a / "x.pdf"), str(b / "y.pdf"), "--name", "Válogatás")
        assert len(wp["items"]) == 2 and wp["source_kind"] == "manual"
        assert cli.main(["wp-create", "--files", str(a / "x.pdf")]) == 2  # név nélkül
        assert cli.main(["wp-create"]) == 2
        capsys.readouterr()
        a_ = _run(capsys, "wp-assign", wp["id"], "invoice-extraction", "--jev-cache", "live")
        assert a_["params"] == {"arm": "auto", "doc_type": "invoice_hu", "jev_cache": "live"}  # 053: az irattípus ajánlott útja


def test_uncertain_calls_can_be_listed_and_resolved_from_the_cli(tmp_path: Path, capsys):
    """066 Á30: a bizonytalan kimenetű hívás kézi rendezésének eddig nem volt hívója; most parancssorból listázható és
    rendezhető (ismert költséggel, vagy anélkül, a maximum lekötve marad)."""
    from decimal import Decimal

    from jav.runtime import calls

    with store.use_store(tmp_path / "c.sqlite"):
        calls._reserve(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.5"),
                       budget_scope=None, request_hash=None)
        calls.recover_uncertain()
        listed = _run(capsys, "calls-uncertain")
        assert [(x["run_id"], x["step_id"], x["status"]) for x in listed["uncertain"]] == [("r1", "s1", "uncertain")]
        inv_id = listed["uncertain"][0]["id"]
        done = _run(capsys, "calls-resolve", str(inv_id), "--cost", "0.02", "--note", "a szolgáltatói felületen ellenőrizve")
        assert done["resolved"] == inv_id
        row = calls.journal("r1")[0]
        assert (row["status"], row["cost_usd"], row["cost_known"]) == ("failed", "0.02", 1)
        assert _run(capsys, "calls-uncertain")["uncertain"] == []
