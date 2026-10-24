"""The helpers written once (194, plan G-tidy R2, R3).

Plain-language summary: every stored time is written by one shared clock (`jav/core/clock.py`), every file fingerprint by
one shared digest (`jav/core/digest.py`), and both flows that start from a PDF read it through one shared step
(`jav/documents/pdf_input.py`); the modules no longer carry their own copies. These tests keep it that way: no module writes its
own `_now` again (the backup keeps its local time on purpose) or its own file digest, neither flow reads or OCRs a PDF
by itself, and no two modules name their refusal the same.

No AI call, no store: the modules are read as syntax trees.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from jav.app import package_release, work

from jav.documents import source_instances
from jav.core import clock, digest
from jav.domains.finance import fx
from jav.core.config import PROJECT_ROOT

JAV = PROJECT_ROOT / "jav"

# the backup names its folders and times in the machine's local time, for a person reading them beside its clock
OWN_CLOCK = {"backup.py"}


def _trees() -> list[tuple[Path, ast.Module]]:
    return [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(JAV.rglob("*.py"))]


def test_a_stored_time_is_utc_to_the_second():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", clock.utc_stamp())
    assert clock.utc_now().utcoffset().total_seconds() == 0


def test_no_module_writes_its_own_clock():
    own = [str(path.relative_to(JAV)) for path, tree in _trees() if path.name not in OWN_CLOCK
           for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_now"]
    assert own == []


def test_a_module_keeps_its_own_name_for_the_shared_clock():
    # a test can still stop the clock of one module (`monkeypatch.setattr(work, "_now", ...)`)
    assert work._now is clock.utc_stamp
    assert package_release._now is clock.utc_stamp
    assert fx._now is clock.utc_now


def test_no_two_modules_name_an_error_the_same():
    names = Counter(node.name for _path, tree in _trees() for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name.endswith("Error"))
    assert [name for name, count in names.items() if count > 1] == []


def test_no_module_writes_its_own_file_digest():
    names = {"_sha256", "_sha256_file", "_file_sha256", "sha256_file"}
    own = [f"{path.relative_to(JAV)}:{node.name}" for path, tree in _trees() for node in tree.body
           if isinstance(node, ast.FunctionDef) and node.name in names]
    assert own == []
    assert work.sha256_file is digest.file_sha256 and source_instances.sha256_file is digest.file_sha256


def test_a_file_digest_is_the_sha256_of_its_bytes(tmp_path):
    import hashlib

    path = tmp_path / "doc.bin"
    path.write_bytes(b"x" * (digest.CHUNK + 5))  # more than one chunk
    assert digest.file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_both_flows_read_a_pdf_through_the_shared_step():
    for name in ("jav/flows/flow.py", "jav/flows/flow_detect.py"):
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert "pdf_input.read_source(" in text and "pdf_input.recognise(" in text
        assert "read_pdf(" not in text and "ocr_with_escalation(" not in text and "azure_alias(" not in text
