"""231 (stage F, D4; the owner's decision of 2026-10-29: downloads and file names follow the interface's language): the
language a request is displayed in.

The interface sets the `jav-language` cookie when its language changes; the service's middleware reads it for the whole
request, so a synchronous endpoint's thread sees it too, and `display.text()` gives a source text in it: English as it
is, Hungarian from the interface's dictionary. Without a request, or without the cookie, it is Hungarian, the
interface's default. A temporary store; no model call.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from jav.core import display
from jav.service import api

BASE = "http://127.0.0.1:8930"


def test_hungarian_outside_a_request_and_for_an_unknown_language():
    assert display.current() == "hu"
    with display.use("en") as chosen:
        assert chosen == "en" and display.current() == "en"
    with display.use("de"):
        assert display.current() == "hu"
    assert display.current() == "hu"


def test_a_source_text_in_each_language():
    assert display.text("Emails", "hu") == "Levelek" and display.text("Emails", "en") == "Emails"
    assert display.text("Page {{n}}", "hu", n=3) == "3. oldal"
    assert display.text("A text the dictionary does not know", "hu") == "A text the dictionary does not know"
    with display.use("en"):
        assert display.text("Emails") == "Emails"
    assert display.text("Emails") == "Levelek"


def test_the_service_reads_the_interface_s_cookie_for_the_whole_request(tmp_path):
    app = api.create_app(store_path=tmp_path / "s.sqlite")

    @app.get("/api/test-display-language")
    def language() -> dict[str, str]:  # a synchronous endpoint runs in a thread of its own
        return {"language": display.current(), "emails": display.text("Emails")}

    app.router.routes.insert(0, app.router.routes.pop())  # before the service's catch-all for unknown endpoints
    client = TestClient(app, base_url=BASE)
    assert client.get("/api/test-display-language").json() == {"language": "hu", "emails": "Levelek"}
    client.cookies.set(display.COOKIE, "en")
    assert client.get("/api/test-display-language").json() == {"language": "en", "emails": "Emails"}
    client.cookies.set(display.COOKIE, "xx")
    assert client.get("/api/test-display-language").json()["language"] == "hu"
