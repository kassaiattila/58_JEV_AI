"""175: the to-dos of a G-path record's missing required fields come in the type pack's order.

They were listed in the order of a set, which depends on the process's string hash seed, so with two or more missing
fields the stored order of to-dos could differ from one run to the next. Synthetic data only; no AI call.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from jav.ai import policy
from jav.ai.models import FlowState, DocumentRecord, JevVerdicts
from jav.ai.typepack import get as get_pack

ROOT = Path(__file__).resolve().parents[1]
_CODE = """
import json
from jav.ai import policy
from jav.ai.models import FlowState, DocumentRecord, JevVerdicts
state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type="statement_cib")
state.record = DocumentRecord()
state.verdicts = JevVerdicts(source="code")
policy.apply_verdict_policy(state)
print(json.dumps(state.review_reasons))
"""


def _missing(doc_type: str) -> list[str]:
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type=doc_type)
    state.record = DocumentRecord()
    state.verdicts = JevVerdicts(source="code")
    policy.apply_verdict_policy(state)
    return state.review_reasons


def test_the_missing_required_fields_come_in_the_packs_order() -> None:
    for doc_type in ("invoice_hu", "statement_cib"):
        assert _missing(doc_type) == [f"llm:required_missing:{f}" for f in get_pack(doc_type).required]


def test_the_order_does_not_depend_on_the_hash_seed() -> None:
    seen = []
    for seed in ("0", "1", "2"):
        out = subprocess.run([sys.executable, "-c", _CODE], capture_output=True, text=True, check=True, cwd=ROOT,
                             env={**os.environ, "PYTHONHASHSEED": seed}).stdout
        seen.append(json.loads(out.strip().splitlines()[-1]))
    assert seen[0] == seen[1] == seen[2] == [f"llm:required_missing:{f}" for f in get_pack("statement_cib").required]
