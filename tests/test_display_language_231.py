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


def test_a_caption_is_searched_sorted_and_offered_in_the_request_s_language():
    from jav.app.tablequery import Column, Query, Sort, facets, select

    col = Column(key="state", label="Status", kind="enum", labels={"d": "Done", "r": "Running"})
    rows = [{"_key": "1", "state": "d"}, {"_key": "2", "state": "r"}]
    by_state = Query(sort=[Sort(col="state")])
    assert [r["state"] for r in select([col], rows, by_state)] == ["r", "d"]  # Fut < Kész
    assert [r["_key"] for r in select([col], rows, Query(q="kész"))] == ["1"]
    assert facets([col], rows)["state"] == ["r", "d"]
    with display.use("en"):
        assert [r["state"] for r in select([col], rows, by_state)] == ["d", "r"]  # Done < Running
        assert select([col], rows, Query(q="kész")) == [] and [r["_key"] for r in select([col], rows, Query(q="done"))] == ["1"]
        assert facets([col], rows)["state"] == ["d", "r"]


DATASET_MODULES = ("jav/app/datasets.py", "jav/domains/email/email_datasets.py", "jav/domains/finance/finance_datasets.py")


def test_every_dataset_caption_is_an_english_source_the_dictionary_shows_in_hungarian():
    """D4/4: the datasets' column names, the datasets' names and the value captions are English sources; each has its
    Hungarian in the interface's dictionary, so the Hungarian interface and its downloads show what they showed."""
    import json
    import re
    from pathlib import Path

    from jav.core import cfg
    from jav.core.config import UI_HUNGARIAN

    hungarian = json.loads(Path(UI_HUNGARIAN).read_text(encoding="utf-8"))
    accented = re.compile(r"[áéíóöőúüűÁÉÍÓÖŐÚÜŰ]")
    literal = r'"((?:[^"\\]|\\.)*)"'
    sources = []
    for module in DATASET_MODULES:
        text = Path(module).read_text(encoding="utf-8")
        for pattern in (rf'\bcol\("[^"]+", {literal}', rf'\bDataset\("[^"]+", {literal}',
                        rf'\("[a-z_]+", {literal}, "(?:text|id|enum|number)"\)'):
            sources += [json.loads(f'"{m}"') for m in re.findall(pattern, text)]
    captions = cfg.load("datasets")["labels"]
    sources += [c for group in captions.values() for c in group.values()]
    assert len(sources) > 300
    assert [s for s in sources if accented.search(s)] == []
    assert sorted({s for s in sources if s not in hungarian}) == []


def test_a_download_is_written_in_the_request_s_language(tmp_path):
    """D4/5: a result's sheet names, fixed headers and marks, and the reconciliation statement's labels, in the
    requesting interface's language (the owner's decision); a type's fields keep their keys."""
    from jav.app import export
    from jav.core import store
    from jav.domains.finance import reconcile_statement
    from tests import test_characterisation_178 as c178

    with store.use_store(tmp_path / "s.sqlite"):
        hungarian = export.result_data(c178._records(), {"emails": c178._mails()}, [])
        with display.use("en"):
            english = export.result_data(c178._records(), {"emails": c178._mails()}, [])
    assert [t.title for t in hungarian.tables][:2] == ["Levelek", "Feladatok"]
    assert [t.title for t in english.tables][:2] == ["Emails", "Tasks"]
    hu_heads, en_heads = ({t.key: t.head for t in d.tables} for d in (hungarian, english))
    assert hu_heads["datapoints"][:4] == ("Irat", "Tétel-azonosító", "Típus", "Mező")
    assert en_heads["datapoints"][:4] == ("Document", "Item ID", "Type", "Field")
    assert en_heads["documents"][7:11] == ("Duplicate", "Duplicate of", "Direction", "supplier_name")
    with display.use("en"):
        assert reconcile_statement._labels()["sheets"] == {"invoices": "Invoices", "lines": "Items"}
        assert reconcile_statement._labels()["file"]["prefix"] == "egyeztetes"  # a file name's parts: slice 7
    assert reconcile_statement._labels()["sheets"] == {"invoices": "Számlák", "lines": "Tételek"}


def test_the_recipe_help_and_the_service_s_english_follow_the_interface():
    """D4/6: the recipe help's texts are English sources with a Hungarian entry; the service's English is the
    interface's whole English dictionary, so a text that stays a Hungarian source (an intent's name, a task's action, a
    recipe's title: a model call's or a package's saved settings' identity holds them) reads in English too."""
    import json
    import re
    from pathlib import Path

    from jav.core import cfg
    from jav.core.config import UI_HUNGARIAN

    hungarian = json.loads(Path(UI_HUNGARIAN).read_text(encoding="utf-8"))
    texts: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k != "meta":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and " " in x:
            texts.append(x)

    walk(cfg.load("recipe_help"))
    assert len(texts) > 40
    assert [t for t in texts if re.search(r"[áéíóöőúüű]", t)] == []
    assert [t for t in texts if t not in hungarian] == []
    assert display.text("Számlaküldés", "en") == "Invoice sent"  # an intent's name
    assert display.text(cfg.load("email_tasks")["actions"]["review_invoice"], "en") == "Review invoice / payment request"


def test_a_file_name_is_built_in_the_request_s_language():
    """D4/7: the naming rules' words are English sources; a Hungarian interface (and the worker, the command line)
    gets the earlier Hungarian words, an English one English words."""
    import json
    from pathlib import Path

    from jav.app import naming
    from jav.core import cfg
    from jav.core.config import UI_HUNGARIAN

    hu = naming.rules()
    with display.use("en"):
        en = naming.rules()
    assert (hu.types["invoice_hu"].token, en.types["invoice_hu"].token) == ("SZAMLA", "HU-INVOICE")
    assert (hu.types["unknown"].token, en.types["unknown"].token) == ("ISMERETLEN", "UNKNOWN")
    assert (hu.review_folder, en.review_folder) == ("ellenorzendo", "to-check")
    assert (hu.manifest_file, en.manifest_file) == ("jegyzek.csv", "manifest.csv")
    assert (hu.placeholders["date"], en.placeholders["date"]) == ("datum-nelkul", "no-date")
    assert (hu.status_labels["review"], en.status_labels["review"]) == ("ellenőrzendő", "to check")
    raw = cfg.load("naming")
    words = [spec["token"] for spec in raw["types"].values()] + [raw["review_folder"], raw["manifest_file"]]
    words += [w for part in ("placeholders", "reason_labels", "manifest_columns", "status_labels") for w in raw[part].values()]
    hungarian = json.loads(Path(UI_HUNGARIAN).read_text(encoding="utf-8"))
    assert sorted({w for w in words if w not in hungarian}) == []
    assert len({spec["token"] for spec in raw["types"].values()}) == len({hu.types[k].token for k in raw["types"]})
