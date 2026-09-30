"""Read-only-to-production audit: synthetic files and SQLite under an isolated run root.

No provider calls, no mailbox access, no production store writes.
Records observed weaknesses as findings, not passing security assertions.
"""

from __future__ import annotations
import ast
import importlib.metadata as metadata
import argparse
import json
from pathlib import Path
from unittest.mock import patch
from jav import store
from jav.config import PROJECT_ROOT
from jav import ingest_server
from jav.emails import load_message_dir
from jav.extract_llm import extract, use_agent_factory
from jav.experiments.long_document_trial import TrialBudget, write, sha

ROOT = PROJECT_ROOT / "runs/20260922_framework_audit"


def main(output):
    root = Path(output).resolve()
    if not root.is_relative_to((PROJECT_ROOT / "runs").resolve()):
        raise ValueError("Audit output must stay under the workspace runs directory")
    root.mkdir(parents=True, exist_ok=False)
    global ROOT
    ROOT = root
    sandbox = ROOT / "synthetic-v2"
    sandbox.mkdir(exist_ok=True)
    inbox = sandbox / "inbox"
    inbox.mkdir(exist_ok=True)
    findings = []

    def record(key, observed, evidence):
        findings.append({"id": key, "observed": observed, "evidence": evidence})

    target = sandbox / "escaped-account"
    folder, _ = ingest_server.write_message(
        {
            "account": str(target.resolve()),
            "message_id": "audit-only",
            "body_preview": "synthetic",
        },
        inbox,
    )
    assert folder.resolve().is_relative_to(sandbox.resolve())
    record(
        "absolute_mailbox_path_escape",
        not folder.resolve().is_relative_to(inbox.resolve()),
        "Absolute account wrote synthetic message outside configured inbox, inside audit sandbox.",
    )
    fake_data = sandbox / "old-data"
    fake_data.mkdir(exist_ok=True)
    marker = sandbox / "synthetic-marker.txt"
    marker.write_text("synthetic marker only", encoding="utf-8")
    with patch.object(ingest_server, "OLD_DATA_ROOT", fake_data):
        resolved = ingest_server.host_path("/data/../synthetic-marker.txt")
    record(
        "attachment_host_path_escape",
        resolved is not None and resolved.resolve() == marker.resolve(),
        "Traversal resolved a synthetic file outside fake OLD_DATA_ROOT.",
    )
    p = {
        "account": "audit@example.invalid",
        "message_id": "duplicate",
        "body_preview": "first",
    }
    first, _ = ingest_server.write_message(p, inbox)
    second, dedup = ingest_server.write_message(p | {"body_preview": "second"}, inbox)
    record(
        "dedup_flag_still_overwrites",
        dedup
        and json.loads((second / "message.json").read_text(encoding="utf-8"))["body"]
        == "second",
        "Same message ID returns deduped while replacing saved body; HTTP --run branch has no dedup guard.",
    )
    (first / "message.json").write_text(
        json.dumps(
            {
                "message_id": "attachment-audit",
                "attachments": [
                    {"filename": "synthetic-marker.txt", "path": str(marker.resolve())}
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_message_dir(first)
    record(
        "inbox_loader_accepts_external_path",
        loaded.attachments[0].path is not None and Path(loaded.attachments[0].path).resolve() == marker.resolve(),
        "Inbox JSON attachment path can resolve outside its message directory; no file content sent.",
    )
    handler = object.__new__(ingest_server._Handler)
    # 040 K1: a szonda a mindenkori határ fölé kér (a 2 MB alatti törzs szándékosan olvasható)
    oversized = getattr(ingest_server, "MAX_BODY_BYTES", 1024 * 1024 - 1) + 1
    handler.headers = {"Content-Length": str(oversized)}

    class RecordingReader:
        requested = None

        def read(self, n):
            self.requested = n
            return b"{}"

    reader = RecordingReader()
    handler.rfile = reader
    try:
        handler._read()
    except Exception:  # noqa: BLE001 - a korlátos olvasó elutasít; a szonda az olvasott méretet méri
        pass
    record(
        "http_reader_unbounded_by_policy",
        reader.requested == oversized,
        "A fake input stream received full caller-declared byte count without cap; no large allocation used.",
    )
    with store.use_store(sandbox / "business.sqlite"):
        store.review_enqueue(
            subject_kind="email",
            subject_id="mixed",
            run_id="one",
            reasons=["intent:low_conf", "security:unreviewed"],
        )
        store.review_close(
            subject_kind="email", subject_id="mixed", reason_prefix="intent:"
        )
        with store.connect() as db:
            row = db.execute(
                "SELECT status,reasons FROM review_queue WHERE subject_id='mixed'"
            ).fetchone()
        record(
            "review_close_drops_unrelated_reason",
            row["status"] != "open" and "security:unreviewed" in row["reasons"],
            "Closing an intent-prefixed reason closes the entire row including a separate synthetic review reason.",
        )

        class FailingAgent:
            def run_sync(self, *args, **kwargs):
                raise TimeoutError("synthetic provider failure; no network")

        with use_agent_factory(lambda pack: FailingAgent()):
            try:
                extract("synthetic source", run_id="failed-extract")
            except TimeoutError:
                pass
        record(
            "normal_gpt_failure_missing_ledger",
            len(store.ledger_for_run("failed-extract")) == 0,
            "Normal extract path logs success only; synthetic provider exception leaves no call ledger.",
        )
        store.save_artifact("audit", "immutable", {"value": 1})
        try:
            store.save_artifact("audit", "immutable", {"value": 2})
        except ValueError:
            protected = True
        else:
            protected = False
        record(
            "immutable_artifact_guard_works",
            protected,
            "Conflicting artifact replacement refused.",
        )
    from jav.flow import ocr_pdf as invoice_ocr
    from jav.flow_detect import ocr_pdf as detect_ocr, DetectState
    from jav.models import FlowState
    from jav.pdf import PdfText

    partial = PdfText(
        path="synthetic.pdf",
        text="Synthetic OCR text",
        page_count=13,
        text_source="ocr",
        ocr={
            "mean_conf": 0.99,
            "low_conf_ratio": 0.0,
            "engine": "native",
            "pages_ocr": 12,
        },
    )
    with patch("jav.ocr.ocr_with_escalation", return_value=(partial, False)):
        invoice = invoice_ocr(
            FlowState(
                source_path="synthetic.pdf", case_id="audit", arm="S", page_count=13
            )
        )
        detected = detect_ocr(DetectState(source_path="synthetic.pdf", page_count=13))
    record(
        "partial_ocr_has_no_coverage_review",
        not invoice.needs_review
        and not invoice.review_reasons
        and not detected.review_reasons,
        "Synthetic 13-page input / 12 OCR pages, high OCR confidence: neither OCR action adds coverage review. No real PDF or model used; not a full graph outcome.",
    )
    costs = ROOT / "budget-probe-v2"
    budget = TrialBudget(costs, {"openai": (2, 1.0)})
    with store.use_store(costs / "business.sqlite"):
        budget.reserve("openai")
        store.ledger_add(
            run_id="cost-1",
            step="fake",
            provider="openai",
            cost_usd=0.99,
            model="synthetic",
            input_tokens=0,
            output_tokens=0,
            seconds=0,
        )
        budget.reserve("openai")
        store.ledger_add(
            run_id="cost-2",
            step="fake",
            provider="openai",
            cost_usd=0.20,
            model="synthetic",
            input_tokens=0,
            output_tokens=0,
            seconds=0,
        )
    record(
        "budget_last_call_can_overshoot",
        budget.usage()["openai"]["usd"] > 1.0,
        "Synthetic ledger only: 0.99 USD allows next call; final 1.19 exceeds stop=1.00. No paid calls.",
    )
    # 040 K1: az új közös hívásréteg ugyanazon a szintetikus eseten (a régi TrialBudget a régi kísérleteké, változatlan)
    from decimal import Decimal
    from jav.runtime import calls as runtime_calls
    with store.use_store(ROOT / "budget-probe-v3" / "business.sqlite"):
        runtime_calls.set_budget("probe", "openai", Decimal("1.00"))
        runtime_calls.invoke(run_id="p", step_id="a", provider="openai", model="synthetic", max_cost_usd=Decimal("0.99"),
                             budget_scope="probe", fn=lambda: runtime_calls.Outcome(response={}, cost_usd=Decimal("0.99")))
        reached = []
        try:
            runtime_calls.invoke(run_id="p", step_id="b", provider="openai", model="synthetic", max_cost_usd=Decimal("0.20"),
                                 budget_scope="probe", fn=lambda: reached.append(1) or runtime_calls.Outcome(response={}))
        except runtime_calls.BudgetExceeded:
            pass
        committed = runtime_calls.budget_usage("probe")["committed_usd"]
    record(
        "shared_call_layer_budget_can_overshoot",
        bool(reached) or committed > Decimal("1.00"),
        "Synthetic: 0.99 USD committed, next 0.20 USD maximum must stop before the provider function. No paid calls.",
    )
    sources = []
    for base in ("jav", "tests", "scripts"):
        for path in sorted((PROJECT_ROOT / base).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(text)
            sources.append(
                {
                    "path": path.relative_to(PROJECT_ROOT).as_posix(),
                    "lines": len(text.splitlines()),
                    "functions": sum(
                        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        for n in ast.walk(tree)
                    ),
                    "sha256": sha(path),
                }
            )
    deps = []
    for d in metadata.distributions():
        deps.append(
            {
                "name": d.metadata["Name"],
                "version": d.version,
                "license_expression": d.metadata.get("License-Expression"),
                "license_classifiers": [
                    c
                    for c in d.metadata.get_all("Classifier", [])
                    if c.startswith("License ::")
                ],
            }
        )
    write(
        ROOT / "probes.json",
        {
            "scope": "synthetic isolated audit; observations are not claims of remote exploitability",
            "external_calls": 0,
            "production_writes": 0,
            "probes": findings,
        },
    )
    write(
        ROOT / "source-inventory.json",
        {"files": sources, "total_lines": sum(s["lines"] for s in sources)},
    )
    write(ROOT / "dependencies.json", sorted(deps, key=lambda d: d["name"].lower()))
    print(
        json.dumps(
            {
                "probes": findings,
                "source_files": len(sources),
                "source_lines": sum(s["lines"] for s in sources),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        required=True,
        help="New directory under workspace runs; existing paths refused",
    )
    main(parser.parse_args().out)
