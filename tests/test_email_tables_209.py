"""209 (plan G-process-core R2c): the email domain's tables are its own.

Plain-language summary: the tables of the received messages, their results per run and a person's decisions on their
task proposals used to be created and read by the shared store. They now live in the email domain's own module, and the
shared code reaches them only through the domain's registrations. These tests check that the store summary still has
its lines in their order, and that the shared store on its own no longer creates the email tables. Synthetic data only,
no AI call.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from jav.core import store
from jav.domains.email import email_store

ROOT = Path(__file__).resolve().parents[1]
EMAIL_TABLES = ("email_results", "email_task_decisions", "emails")


def test_the_store_summary_keeps_its_lines_in_their_order(tmp_path: Path) -> None:
    with store.use_store(tmp_path / "s.sqlite"):
        email_store.upsert_email(message_id="msg-1", mailbox="synthetic", sender="sender@example.com", subject="Synthetic",
                                 received_at="2026-10-23T08:00:00+00:00", body_excerpt=None, attachments=[],
                                 intent="invoice", intent_conf=0.9, signals=None, next_flow=None, run_id="run-1:item-1")
        summary = store.stats()
    assert list(summary) == ["documents", "datapoints", "emails", "review_queue", "ledger", "golden_labels", "artifacts",
                             "review_open", "ledger_by_provider", "ledger_errors", "doc_types", "intents"]
    assert summary["emails"] == 1 and summary["intents"] == [{"intent": "invoice", "n": 1}]


def test_the_shared_store_alone_creates_no_email_table(tmp_path: Path) -> None:
    script = ("import json, sys\n"
              "from pathlib import Path\n"
              "from jav.core import store\n"
              "with store.use_store(Path(sys.argv[1])), store.connect() as c:\n"
              "    names = sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\"))\n"
              "print(json.dumps({'tables': names, 'summary': list(store.stats())}))\n")
    out = subprocess.run([sys.executable, "-c", script, str(tmp_path / "alone.sqlite")], cwd=ROOT, capture_output=True,
                         text=True, check=True, env={**os.environ, "PYTHONPATH": str(ROOT)}).stdout
    found = json.loads(out.strip().splitlines()[-1])
    assert set(EMAIL_TABLES).isdisjoint(found["tables"]) and "documents" in found["tables"]
    assert "emails" not in found["summary"] and "intents" not in found["summary"]
    with store.use_store(tmp_path / "alone.sqlite"), store.connect() as c:  # this process has the domain loaded
        assert set(EMAIL_TABLES) <= {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
