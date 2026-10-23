"""203 (speed-up by measurement): the isolated reader process loads no network client.

Every native read starts a fresh process (`jav/documents/readers/isolation.py`). Its start took about 1.1 s, more than half of it
in the JEV SDK and its HTTP library, which the package's configuration module imported for the client it can build.
A reader never builds one, and a process that parses untrusted files should not carry network code either.
"""

from __future__ import annotations

import json
import subprocess
import sys
import sysconfig

from jav.core.config import PROJECT_ROOT

NETWORK_CLIENTS = ("typesafe_sdk", "httpx2", "httpx", "openai", "pydantic_ai")

# the trusted imports of `jav/documents/readers/worker.py`, in its order, before it installs its policy
WORKER_IMPORTS = """
import sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from jav.documents.readers.contracts import ReadLimits
from jav.documents.readers.limits import ReadFailure
from jav.documents.readers.native import evidence_view, read
from jav.documents.readers import visual
import docx, openpyxl
from PIL import Image
import json
print(json.dumps(sorted(m for m in sys.modules if m.split(".")[0] in sys.argv[3].split(","))))
"""


def test_the_reader_process_imports_no_network_client():
    executable = getattr(sys, "_base_executable", sys.executable)
    packages = sysconfig.get_paths()["purelib"]
    r = subprocess.run([executable, "-I", "-B", "-c", WORKER_IMPORTS, packages, str(PROJECT_ROOT), ",".join(NETWORK_CLIENTS)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []


def test_the_jev_client_is_still_built_with_the_configured_retry_policy(monkeypatch):
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    from jav.core import config

    monkeypatch.setenv(config.API_KEY_ENV_VARS[0], "test-key")
    with config.make_client() as client:
        assert isinstance(client, TypeSafeClient)
    assert isinstance(config.build_retry_policy(), RetryPolicy)
