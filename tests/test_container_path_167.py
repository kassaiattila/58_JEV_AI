"""167 (review S-1): a mail bridge attachment path that would reach another host is refused before anything resolves it.

`host_path` maps the bridge's `/data/<relative path>` onto a local data folder and checked containment after resolving
the joined path. A path such as `/data///host/share/x.pdf` (or `/data/\\\\host\\share\\x.pdf`) joined into a network
path, so resolving it already made an outgoing SMB connection (which can leak the Windows sign-in hash); only the
bridge holding the receiver's key could send one. The rest after `/data/` must now be a plain relative path by its
text: no leading separator, no drive or colon, no `..` segment. Synthetic data only.
"""

from pathlib import Path

import pytest

from jav.domains.email import emails, ingest_server
from jav.core import path_text

REFUSED = [
    "/data///attacker.example/share/x.pdf",
    "/data//attacker.example/share/x.pdf",
    "/data/\\\\attacker.example\\share\\x.pdf",
    "/data/\\attacker.example\\share\\x.pdf",
    "\\data\\\\\\attacker.example\\share\\x.pdf",
    "/data/C:/Windows/win.ini",
    "/data/Q:x.pdf",
    "/data/inbox/../../x.pdf",
    "/data/inbox/..\\..\\x.pdf",
    "/data/inbox/x.pdf:secret",
    "/data/inbox//x.pdf",
    "/data/",
]


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "inbox").mkdir(parents=True)
    (data / "inbox" / "ok.pdf").write_bytes(b"%PDF-1.4 synthetic")
    monkeypatch.setattr(ingest_server, "BRIDGE_DATA_ROOT", tmp_path / "bridge")
    monkeypatch.setattr(ingest_server, "OLD_DATA_ROOT", data)
    return data


@pytest.mark.parametrize("container_path", REFUSED)
def test_a_path_that_could_reach_another_host_is_refused_unresolved(roots, monkeypatch, container_path):
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: pytest.fail(f"{self} was resolved"))
    monkeypatch.setattr(Path, "is_file", lambda self: pytest.fail(f"{self} was looked up"))
    assert ingest_server.host_path(container_path) is None


def test_the_record_keeps_a_refused_path_only_as_text(roots, monkeypatch):
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: pytest.fail(f"{self} was resolved"))
    record = ingest_server._record({"attachments": [{"path": REFUSED[0], "filename": "x.pdf"}]}, "m1", "a@example.com")
    assert record["attachments"] == [{"filename": "x.pdf", "path": None, "container_path": REFUSED[0]}]


def test_a_plain_path_under_the_data_root_is_still_found(roots):
    assert ingest_server.host_path("/data/inbox/ok.pdf") == (roots / "inbox" / "ok.pdf").resolve()
    assert ingest_server.host_path("\\data\\inbox\\ok.pdf") == (roots / "inbox" / "ok.pdf").resolve()


@pytest.mark.parametrize("text, expected", [
    ("\\\\host\\share\\x.pdf", True), ("//host/share/x.pdf", True), ("/\\host\\share", True), ("\\\\?\\C:\\x", True),
    ("Q:x.pdf", True), ("C:\\Users\\x.pdf", False), ("/data/inbox/x.pdf", False), ("inbox/x.pdf", False),
])
def test_one_rule_names_a_path_that_could_reach_another_host(text, expected):
    assert path_text.reaches_another_host(text) is expected


@pytest.mark.parametrize("text, expected", [
    ("inbox/email/acct/eid/x.pdf", True), ("inbox\\x.pdf", True), ("./x.pdf", True),
    ("", False), ("/x.pdf", False), ("\\x.pdf", False), ("C:x.pdf", False), ("a/../x.pdf", False), ("..", False),
    ("a//x.pdf", False), ("x.pdf:stream", False),
])
def test_a_plain_relative_path_by_its_text(text, expected):
    assert path_text.plain_relative(text) is expected


def test_the_email_loader_uses_the_same_rule(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(path_text, "reaches_another_host", lambda text: seen.append(text) or True)
    assert emails._allowed_attachment(tmp_path / "invoice.pdf", tmp_path) is False
    assert seen == [str(tmp_path / "invoice.pdf")]
