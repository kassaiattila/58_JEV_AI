"""231 (stage D, D-f1): the facts a case's processed documents hold, offered to its field check.

A package holds the invented reference set's three documents and a document of another type, each with the values a
run read and where each was printed. The step takes what counts now (a person's correction over what was read), reads
the facts in the rule file's order (the request before the schedule, so a parent comes first), names the document,
its file, page and words for each fact, and lists the document no reading takes. Every claim is one the field check
takes. Invented data; no paid call.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from jav.app import corrections, fact_claims, field_check, work_runs
from jav.core import store
from jav.core.process import kinds
from jav.evals import property_documents as pd

WP, RUN, AT = "wp-0000000d0f1", "run-d0f1", "2026-10-26T08:00:00+00:00"
SET = next(s for s in pd.load().sets if s.id == "reference")
OTHER = {"invoice_number": "INV-1", "supplier_name": "Minta Kft."}


def _id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


@pytest.fixture()
def package(tmp_path):
    docs = [(d.id, d.pack, d.values) for d in SET.documents] + [("an-invoice", "invoice_hu", OTHER)]
    with store.use_store(tmp_path / "fact-claims.sqlite"):
        with store.connect() as c:
            c.execute("INSERT INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                      (WP, "invented", "manual", AT, AT))
            c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version,"
                      " recipe_hash, recipe, params, input, input_hash, status, approval, actor, created_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (RUN, WP, RUN, "apply", 1, "processing", 1, "h", "{}", "{}",
                       json.dumps({"items": [{"item_id": _id(n), "kind": "document"} for n, _p, _v in docs]}), "h", "done",
                       None, "Minta Anna", AT))
            for name, _pack, _values in docs:
                c.execute("INSERT INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision)"
                          " VALUES (?,?,?,?,?,?)", (WP, _id(name), "document", f"C:/invented/{name}.pdf", _id(name), 1))
                c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at) VALUES (?,?,?,?,?,?)",
                          (RUN, _id(name), "done", "done", work_runs.flow_run_id(RUN, _id(name)), AT))
        for name, pack, values in docs:
            provenance = {"policyholder_name": {"status": "located", "page": 1, "quote": "Szerződő: Minta Kereskedő Kft."}}
            if pack == "property_schedule":
                provenance["asset_groups"] = {"status": "list", "rows": [{"page": 1, "quote": "épület 180 000 000 Ft"}]}
            store.insert_datapoints(run_id=work_runs.flow_run_id(RUN, _id(name)), doc_id=_id(name), doc_type=pack, arm="G",
                                    datapoints=values, field_conf={}, validation=[], route="auto", review_reasons=[],
                                    final_status="done", provenance=provenance)
        yield docs


def _run() -> dict:
    ctx = SimpleNamespace(result_of=lambda ref: (1, {"package": WP, "runs": [RUN]}),
                          definition=SimpleNamespace(step=lambda ref: SimpleNamespace(kind="process_documents@1")))
    outcome = fact_claims._run(ctx, fact_claims.FactClaims(from_step="documents"))
    assert isinstance(outcome, kinds.Done)
    return outcome.result


def test_the_documents_give_their_sets_facts_each_naming_where_it_was_printed(package) -> None:
    result = _run()
    claims = result["claims"]
    assert all(field_check.Claim.model_validate(c) for c in claims)
    units = {}
    for c in claims:
        units.setdefault(c["unit"], {})[c["fact"]] = c["value"]
    assert units == {u.key: u.facts for u in SET.units}
    assert [c["unit"] for c in claims][0] == "holder"  # the request's policyholder first
    name = next(c for c in claims if c["fact"] == "company_name")
    assert name["source"] == {"item": _id("reference-request"), "file": "reference-request.pdf", "page": 1,
                              "quote": "Szerződő: Minta Kereskedő Kft."}
    building = next(c for c in claims if c["unit"] == "site:1/1" and c["fact"] == "sum_insured")
    assert (building["source"]["page"], building["source"]["quote"]) == (1, "épület 180 000 000 Ft")
    assert building["reading"] == "type:property_schedule"
    other = next(d for d in result["documents"] if d["doc_type"] == "invoice_hu")
    assert (other["claims"], other["note"]) == (0, "no reading takes this type")


def test_a_persons_correction_counts_over_what_was_read(package) -> None:
    item = _id("reference-schedule-1")
    values = dict(next(v for n, _p, v in package if n == "reference-schedule-1"))
    corrections.save(RUN, item, fields={"flood_zone": "magas"}, expected_revision=0, actor="Minta Anna")
    claims = _run()["claims"]
    assert next(c["value"] for c in claims if c["unit"] == "site:1" and c["fact"] == "flood_zone") == "high"
    assert values["flood_zone"] == "alacsony"  # the reading itself is unchanged
