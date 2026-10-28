"""231 (stage U, U0; the owner's decisions of 2026-10-27): any process's case is started by hand, and a process's invented
example material is installed and loaded from the interface.

The processes list says which process a person may start by hand, what each one is for, and what a case of it cannot
start without (a resource it needs at its start that has no active version, by name). A process names its example
material as data: the sets of versioned things it installs (the invented product set) and the packets of invented
documents a case can start on. Installing the material makes the machine the maker and the person the approver (the
four eyes a product needs), so a case of the process can start; every thing it made is marked as an example. The
material goes in one go while no case keeps any of it, and is refused, naming the cases, while one does. A packet's
documents are written as PDFs beside the store, and a case starts on them. The examples' printed pages are the golden
set's, as the measurement prints them. Invented data; no paid call.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav.app import examples, product_sets
from jav.core import cfg, store
from jav.evals import property_documents as pd
from jav.service.api import create_app

ANNA = {"X-Actor": "Minta Anna"}
PACK = "insurance_offer"


@pytest.fixture()
def client(tmp_path):
    with store.use_store(tmp_path / "u0.sqlite"):
        with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
            yield c


def _process(c: TestClient, pack: str) -> dict:
    return next(p for p in c.get("/api/processes").json()["processes"] if p["id"] == pack)


def test_the_processes_list_says_what_a_start_by_hand_needs(client) -> None:
    listed = client.get("/api/processes").json()["processes"]
    assert all(p["manual"] for p in listed)  # every process today may be started by a person
    assert all(isinstance(p["summary"], str) and p["summary"] for p in listed)
    assert [m["key"] for m in _process(client, PACK)["missing_at_start"]] == ["product", "tariff"]
    assert all(m["label"] for m in _process(client, PACK)["missing_at_start"])
    assert _process(client, "it_quote")["missing_at_start"] == []
    assert _process(client, PACK)["examples"] is True and _process(client, "it_quote")["examples"] is False
    refused = client.post("/api/cases", headers=ANNA, json={"pack": PACK, "name": "x", "source": {"kind": "folder", "folder": "C:/x"}})
    assert refused.status_code == 422, refused.text


def test_the_example_material_installs_marked_and_a_case_starts_on_its_documents(client) -> None:
    shown = client.get(f"/api/processes/{PACK}/examples").json()
    assert [(s["kind"], s["name"], s["state"]) for s in shown["sets"]] == [("product_set", "golden_products", "missing")]
    assert "reference" in [p["id"] for p in shown["packets"]] and all(p["title"] and p["documents"] for p in shown["packets"])
    made = client.post(f"/api/processes/{PACK}/examples/install", headers=ANNA, json={})
    assert made.status_code == 200, made.text
    assert [s["state"] for s in made.json()["sets"]] == ["installed"] and made.json()["sets"][0]["example"] is True
    assert _process(client, PACK)["missing_at_start"] == []
    registry = client.get("/api/product-registry").json()
    things = [t for kind in ("products", "documents", "rules", "tariffs") for t in registry[kind]]
    assert things and all(t["example"] for t in things)
    assert client.post(f"/api/processes/{PACK}/examples/install", headers=ANNA, json={}).status_code == 200  # again: kept

    files = client.post(f"/api/processes/{PACK}/examples/packets/reference/files", headers=ANNA, json={}).json()["files"]
    assert len(files) == 3 and all(Path(f).is_file() and f.endswith(".pdf") for f in files)
    assert Path(files[0]).parent.parent.parent == store.current_path().parent / examples.FOLDER
    started = client.post("/api/cases", headers=ANNA, json={"pack": PACK, "name": "Example: reference",
                                                             "source": {"kind": "files", "files": files}})
    assert started.status_code == 201, started.text
    assert client.post(f"/api/processes/{PACK}/examples/packets/no_such/files", headers=ANNA, json={}).status_code == 404


def test_the_example_material_goes_in_one_go_unless_a_case_keeps_it(client) -> None:
    assert client.post(f"/api/processes/{PACK}/examples/install", headers=ANNA, json={}).status_code == 200
    gone = client.post(f"/api/processes/{PACK}/examples/remove", headers=ANNA, json={})
    assert gone.status_code == 200, gone.text
    assert [s["state"] for s in gone.json()["sets"]] == ["missing"]
    assert all(not client.get("/api/product-registry").json()[k] for k in ("products", "documents", "rules", "tariffs"))

    assert client.post(f"/api/processes/{PACK}/examples/install", headers=ANNA, json={}).status_code == 200  # back again
    files = client.post(f"/api/processes/{PACK}/examples/packets/reference/files", headers=ANNA, json={}).json()["files"]
    case_id = client.post("/api/cases", headers=ANNA, json={"pack": PACK, "name": "Example", "source": {"kind": "files", "files": files}}
                          ).json()["case_id"]
    kept = client.post(f"/api/processes/{PACK}/examples/remove", headers=ANNA, json={})
    assert kept.status_code == 409 and case_id in kept.text
    assert _process(client, PACK)["missing_at_start"] == []  # nothing went


def test_things_a_person_made_are_not_the_examples_to_remove(tmp_path) -> None:
    with store.use_store(tmp_path / "own.sqlite"):
        product_sets.install(product_sets.load(), maker="Minta Anna", approver="Minta Bela")
        [state] = examples.of(PACK)["sets"]
        assert state["state"] == "installed" and state["example"] is False
        with pytest.raises(examples.ExampleRefused):
            examples.remove(PACK, "Minta Anna")


def test_the_examples_print_what_the_golden_set_prints() -> None:
    packets = {p["id"]: p for p in cfg.load(examples.DOCUMENTS_PREFIX + "property_documents")["packets"]}
    assert set(packets) == {s.id for s in pd.load().sets}
    for doc_set in pd.load().sets:
        printed = {d["file"]: d["pages"] for d in packets[doc_set.id]["documents"]}
        assert printed == {f"{d.id}.pdf": pd.pages(d) for d in doc_set.documents}, doc_set.id


def test_the_documents_process_offers_invented_invoices_and_quote_requests(tmp_path) -> None:
    """U1e (the owner's decision of 2026-10-28): the documents process has example material of its own: the invented
    invoices of the measurement and the invented quote requests' printed forms, written as PDFs a case starts on; the
    file is what `examples --set documents` prints."""
    from jav.evals import document_examples

    packets = {p["id"]: p["documents"] for p in examples.of("documents")["packets"]}
    assert packets == {"invoices": 5, "foreign": 7, "quote_requests": 2}
    current = cfg.load(examples.DOCUMENTS_PREFIX + "documents")["packets"]
    assert document_examples.example_packets({p["id"]: p["title"] for p in current}) == current
    with store.use_store(tmp_path / "docs.sqlite"):
        files = examples.packet_files("documents", "quote_requests")
    assert [Path(f).name for f in files] == ["keroiv_halozat.pdf", "igenyek.pdf"] and all(Path(f).stat().st_size for f in files)


def test_every_example_packet_s_id_is_one_the_service_s_route_takes() -> None:
    """U-A7 (the walkthrough on 2026-10-28): the real product's packets were named with hyphens (az-metalworks), which
    the route of a packet's files refuses (422), so no case could start on them. Every examples file's packet ids fit
    the route's pattern."""
    import re

    from jav.core.cfg import CONFIG_DIR

    route = re.compile(r"^[a-z][a-z0-9_]{0,63}$")  # jav/service/api_processes.py PacketId
    for path in sorted(CONFIG_DIR.glob("examples_*.json")):
        ids = [p["id"] for p in cfg.load(path.stem)["packets"]]
        assert ids and all(route.match(i) for i in ids), (path.name, ids)
