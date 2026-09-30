"""075 (repeated security audit, S03): the source document and its page images are served only from bytes whose full
content hash is the one recorded when the item was added.

Before 075 the service trusted a fingerprint memoised by file size + modification time, so a file changed in place with
the same size and a restored timestamp was served under the original item. Synthetic PDFs only.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from jav import api, store, work
from tests.pdfgen import INVOICE_LINES, write_text_pdf


@pytest.fixture
def served(tmp_path):
    source = tmp_path / "invoice.pdf"
    write_text_pdf(source, INVOICE_LINES)
    db = tmp_path / "w.sqlite"
    with store.use_store(db):
        wp = work.create_from_files([source], name="Synthetic identity test")
        item = work.get(wp["id"])["items"][0]
        work.fingerprint(source)  # the memoised fingerprint the old check trusted
        client = TestClient(api.create_app(store_path=db), base_url="http://127.0.0.1:8930")
        base = f"/api/workpackages/{wp['id']}/items/{item['item_id']}"
        yield source, client, base


def _swap_in_place(source):
    """Same length, restored timestamps: the size + modification time memo cannot notice it."""
    original = source.read_bytes()
    changed = original.replace(b"MINTA", b"ALTER")
    assert changed != original and len(changed) == len(original)
    before = source.stat()
    source.write_bytes(changed)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_unchanged_source_is_served_byte_for_byte(served):
    source, client, base = served
    response = client.get(f"{base}/source")
    assert response.status_code == 200 and response.content == source.read_bytes()
    assert response.headers["cache-control"] == "no-store"
    page = client.get(f"{base}/pages/1.png")
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")


def test_swapped_source_is_a_conflict_not_the_changed_bytes(served):
    source, client, base = served
    _swap_in_place(source)
    assert client.get(f"{base}/source").status_code == 409
    assert client.get(f"{base}/pages/1.png").status_code == 409


def test_missing_source_is_a_conflict(served):
    source, client, base = served
    source.unlink()
    assert client.get(f"{base}/source").status_code == 409


def test_oversized_source_is_not_read_into_memory(served, monkeypatch):
    source, client, base = served
    monkeypatch.setattr(api, "_max_source_bytes", lambda: 10)  # smaller than the synthetic PDF
    read = []
    monkeypatch.setattr(type(source), "read_bytes", lambda self: read.append(self) or b"")
    assert client.get(f"{base}/source").status_code == 409
    assert not read
