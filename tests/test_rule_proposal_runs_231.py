"""231 (stage D, D-c7e): rules proposed from a condition document's file, kept for a person to decide.

A run of the free stand-in over the invented general conditions' PDF proposes their nine rules, each checked in code;
one waits for a person to confirm the numbers the document does not print. A person accepts a proposal (only when
nothing blocks it and its unprinted numbers are confirmed), corrects one (checked again on the pages the run read) or
rejects one with a reason; an accepted or corrected one becomes a draft rule of the registry, its origin naming the
proposal, in the same transaction as the decision. A decided proposal, a stale page, a changed file and an unknown
proposer are refused. Invented data; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import product_rules, product_sets, rule_proposal_runs
from jav.core import decisions, queue, store, versions
from jav.runtime import job_kinds

ANNA = "Minta Anna"
SET = product_sets.load()
GENERAL = "inv_general_conditions@1"


@pytest.fixture()
def env(tmp_path):
    written = product_sets.write_documents(SET, tmp_path / "documents")
    with store.use_store(tmp_path / "runs.sqlite"):
        product_sets.install(SET, maker=ANNA)  # the documents the proposals cite are in the registry (as drafts)
        yield written


def _run(path, *, proposer: str = "stand_in:golden_products", document: str = GENERAL) -> dict:
    started = rule_proposal_runs.start(document, path, catalogue="property", actor=ANNA, proposer=proposer)
    job = queue.claim("test", kinds=(rule_proposal_runs.JOB_KIND,))
    rule_proposal_runs.process_job(job)
    return rule_proposal_runs.run(started["run_id"])


def _by_title(run: dict) -> dict[str, dict]:
    return {p["title"]: p for p in run["proposals"]}


def test_a_stand_in_run_proposes_the_documents_rules_each_checked(env) -> None:
    assert job_kinds.of(rule_proposal_runs.JOB_KIND).module == "jav.app.rule_proposal_runs"
    run = _run(env["inv_general_conditions"])
    assert (run["state"], run["stand_in"], run["page_count"], run["skipped"], run["text_source"]) == ("done", True, 4, {}, "pdf")
    assert len(run["proposals"]) == 9 and run["counts"] == {"proposed": 9}
    readiness = {p["title"]: p["readiness"] for p in run["proposals"]}
    assert readiness.pop(SET.rules["inv_claims_factor"].title) == "confirm"
    assert set(readiness.values()) == {"ready"}
    assert all(p["support"] is None and p["state"] == "proposed" and p["decision_state"] == 0 for p in run["proposals"])


def test_an_accepted_proposal_becomes_a_draft_rule_naming_it(env) -> None:
    run = _run(env["inv_general_conditions"])
    flood = _by_title(run)[SET.rules["inv_flood_high"].title]
    done = rule_proposal_runs.accept(flood["id"], actor=ANNA, expected_state=0)
    assert (done["state"], done["rule_ref"]) == ("accepted", "inv_general_conditions.6.1.exclusion@1")
    draft = product_rules.get("rule", "inv_general_conditions.6.1.exclusion", 1)
    assert draft["state"] == versions.DRAFT and draft["made_by"] == ANNA
    assert draft["content"]["origin"] == {"kind": "proposal", "run": run["run_id"], "proposal": flood["id"],
                                          "proposer": "stand_in:golden_products", "corrected": False, "confirmed": []}
    assert done["decision_state"] > 0
    with pytest.raises(decisions.RevisionConflict):
        rule_proposal_runs.reject(flood["id"], "too late", actor=ANNA, expected_state=0)
    with pytest.raises(rule_proposal_runs.ProposalError, match="decided already"):
        rule_proposal_runs.accept(flood["id"], actor=ANNA, expected_state=done["decision_state"])


def test_numbers_the_document_does_not_print_are_confirmed_before_accepting(env) -> None:
    factor = _by_title(_run(env["inv_general_conditions"]))[SET.rules["inv_claims_factor"].title]
    with pytest.raises(rule_proposal_runs.ProposalRefused) as refused:
        rule_proposal_runs.accept(factor["id"], actor=ANNA, expected_state=0, confirmed=["0"])
    assert [str(p) for p in refused.value.problems] == ["confirm the numbers first: 1"]
    done = rule_proposal_runs.accept(factor["id"], actor=ANNA, expected_state=0, confirmed=["0", "1"])
    assert done["confirmed"] == ["0", "1"] and done["state"] == "accepted"


def test_a_correction_is_checked_again_and_becomes_a_draft(env) -> None:
    flood = _by_title(_run(env["inv_general_conditions"]))[SET.rules["inv_flood_high"].title]
    wrong_page = flood["rule"] | {"source": flood["rule"]["source"] | {"page": 2}}
    with pytest.raises(rule_proposal_runs.ProposalRefused) as refused:
        rule_proposal_runs.correct(flood["id"], wrong_page, actor=ANNA, expected_state=0)
    assert "clause 6.1 is on page 3, not on page 2" in [str(p) for p in refused.value.problems]
    with pytest.raises(rule_proposal_runs.ProposalRefused, match="the corrected rule is no rule"):
        rule_proposal_runs.correct(flood["id"], flood["rule"] | {"kind": "wish"}, actor=ANNA, expected_state=0)
    titled = flood["rule"] | {"title": "Flood damage in a high-risk zone"}
    done = rule_proposal_runs.correct(flood["id"], titled, actor=ANNA, expected_state=0, ident="flood_high_corrected")
    assert (done["state"], done["rule_ref"]) == ("corrected", "flood_high_corrected@1")
    content = product_rules.get("rule", "flood_high_corrected", 1)["content"]
    assert content["title"] == titled["title"] and content["origin"]["corrected"] is True


def test_a_rejection_needs_a_reason(env) -> None:
    flood = _by_title(_run(env["inv_general_conditions"]))[SET.rules["inv_flood_high"].title]
    with pytest.raises(rule_proposal_runs.ProposalError, match="needs a reason"):
        rule_proposal_runs.reject(flood["id"], "  ", actor=ANNA, expected_state=0)
    done = rule_proposal_runs.reject(flood["id"], "the clause is about claims handling", actor=ANNA, expected_state=0)
    assert (done["state"], done["reason"], done["rule_ref"]) == ("rejected", "the clause is about claims handling", None)


def test_a_changed_file_fails_the_run_and_an_unknown_proposer_or_version_is_refused(env) -> None:
    path = env["inv_general_conditions"]
    started = rule_proposal_runs.start(GENERAL, path, catalogue="property", actor=ANNA, proposer="stand_in:golden_products")
    path.write_bytes(path.read_bytes() + b"\n%changed")
    rule_proposal_runs.process_job(queue.claim("test", kinds=(rule_proposal_runs.JOB_KIND,)))
    failed = rule_proposal_runs.run(started["run_id"])
    assert failed["state"] == "failed" and "the file changed since the run was asked" in failed["error"]
    with pytest.raises(rule_proposal_runs.ProposalError, match="no proposer"):
        rule_proposal_runs.start(GENERAL, path, catalogue="property", actor=ANNA, proposer="oracle")
    with pytest.raises(rule_proposal_runs.ProposalError, match="exact document version"):
        rule_proposal_runs.start("inv_general_conditions", path, catalogue="property", actor=ANNA, proposer="gpt")


def test_the_command_line_proposes_lists_and_decides(env, capsys) -> None:
    from jav import cli

    assert cli.main(["rule-propose", GENERAL, "--pdf", str(env["inv_general_conditions"]), "--stand-in", "golden_products",
                     "--maker", ANNA]) == 0
    out = capsys.readouterr().out
    assert "(done)" in out and out.count("[proposed,") == 9
    run_id = out.split()[1]
    proposal = rule_proposal_runs.run(run_id)["proposals"][0]["id"]
    assert cli.main(["rule-proposal-decide", str(proposal), "reject", "--maker", ANNA]) == 2  # no reason
    assert cli.main(["rule-proposal-decide", str(proposal), "accept", "--maker", ANNA]) == 0
    assert "a draft rule" in capsys.readouterr().out
    assert cli.main(["rule-proposals"]) == 0 and run_id in capsys.readouterr().out


def test_a_file_the_owner_allowed_whole_is_read_with_its_marked_pages(env, tmp_path, monkeypatch) -> None:
    """231 (U-A3; the owner's decision of 2026-10-27): the two real documents marked internal may be read whole. By
    their fingerprint, and only theirs, a run keeps no marked page out; any other file keeps the markings."""
    import hashlib

    from jav.core import cfg
    from jav.documents.synthetic_pdf import write_unicode_pdf_pages

    rules = cfg.load("rule_proposals")
    assert rule_proposal_runs.markers("0" * 64) == rules["skip_page_markers"]
    assert {e["file"] for e in rules["marked_allowed"]} == {"AHE-43500_8_VABF_2026_mod_FINAL.pdf",
                                                             "AHE_11888_1_BETLOP_KBF_UT_ZAR_FINAL_MSz.pdf"}
    assert all(rule_proposal_runs.markers(e["sha256"]) == [] for e in rules["marked_allowed"])

    rows = product_sets.document_pages(SET, "inv_general_conditions")
    marked = write_unicode_pdf_pages(tmp_path / "marked.pdf", [rows[0], [*rows[1], "Internal"], *rows[2:]])
    assert _run(marked)["skipped"] == {2: "Internal"}
    sha = hashlib.sha256(marked.read_bytes()).hexdigest()
    real_load = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: {**real_load(name), "marked_allowed": [{"sha256": sha}]}
                        if name == "rule_proposals" else real_load(name))
    assert _run(marked)["skipped"] == {}


def test_a_finished_run_is_checked_again_from_its_answers_without_asking_again(env) -> None:
    """231 (U-A3): the code that turns an answer into a rule and checks it improved after a paid round; the run's
    undecided proposals are checked again from the answers it keeps, against the pages it read, with no model asked.
    A decided proposal stays as it was; a run is checked only against a version of its own document."""
    import json

    run = _run(env["inv_general_conditions"])
    first, second = run["proposals"][0], run["proposals"][1]
    with store.connect() as c:  # as an older code left them: the clause as printed with a lettered point, and blocked
        record = json.loads(c.execute("SELECT record FROM rule_proposals WHERE id=?", (first["id"],)).fetchone()[0])
        clause = record["clause"]
        record["clause"] = f"{clause}.b)"
        c.execute("UPDATE rule_proposals SET record=?, rule=NULL, findings=? WHERE id=?",
                  (json.dumps(record), json.dumps([{"code": "citation_clause", "severity": "blocking", "text": {"text": "x"}}]), first["id"]))
    rule_proposal_runs.reject(second["id"], "not this one", actor=ANNA, expected_state=0)
    again = rule_proposal_runs.recheck(run["run_id"])
    by_id = {p["id"]: p for p in again["proposals"]}
    assert by_id[first["id"]]["readiness"] != "blocked" and by_id[first["id"]]["rule"]["source"]["clause"] == clause
    assert by_id[second["id"]]["state"] == "rejected"
    with pytest.raises(rule_proposal_runs.ProposalError):
        rule_proposal_runs.recheck(run["run_id"], document_ref="inv_burglary_conditions@1")
