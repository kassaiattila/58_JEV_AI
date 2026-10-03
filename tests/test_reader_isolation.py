"""The protection claims must be exercised in real Windows subprocesses."""
import pytest
import os

from jav.readers.isolation import run
from jav.readers.limits import DEFAULT_LIMITS, ReadFailure

pytest.importorskip("docx", reason="Native reader dependencies await integration")
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object reader boundary")


@pytest.mark.parametrize("operation,code", [
    ("network", "excluded"), ("path", "excluded"),
    ("time", "resource_limit"), ("memory", "resource_limit"), ("output", "resource_limit"),
])
def test_enforced_process_boundaries(operation, code):
    limits = DEFAULT_LIMITS.model_copy(update={"wall_seconds": 4, "memory_bytes": 256_000_000})
    with pytest.raises(ReadFailure) as caught:
        run(b"synthetic", "sample.txt", limits, probe=operation)
    assert caught.value.code == code


def test_missing_os_protection_prevents_parsing(monkeypatch):
    from jav.readers import isolation
    def unavailable(*args):
        raise OSError("synthetic unavailable Job Object")
    monkeypatch.setattr(isolation, "Job", unavailable)
    with pytest.raises(ReadFailure) as caught:
        run(b"synthetic", "sample.txt", DEFAULT_LIMITS)
    assert caught.value.code == "protection_unavailable"
