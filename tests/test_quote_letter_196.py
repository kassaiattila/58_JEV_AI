"""196 (plan F-Word-output W3, DECISIONS 196): the reply letter to a quote request.

The owner's decisions of 2026-10-22: a draft Outlook opens as an unsent message, the Word quote attached; GPT writes a
few sentences fitted to the request, never a number; a person accepts it; the system never sends it. The code checks
GPT's paragraph and writes every number of the frame. Synthetic requests, a stand-in JEV, match and GPT; no paid call.
"""

from __future__ import annotations

import email
from email import policy
from pathlib import Path
from types import SimpleNamespace

import pytest

from jav.app import work
from jav.domains.quotes import quote_draft, quote_letter
from jav.runtime import worker
from tests import test_quote_draft_192 as q192

env = q192.env
quote = q192.quote


class _Agent:
    """A GPT stand-in answering every prompt with `paragraph`; the prompts it was sent are kept."""

    def __init__(self, paragraph: str):
        self.paragraph, self.prompts = paragraph, []

    def run_sync(self, prompt, **_kw):
        self.prompts.append(prompt)
        return SimpleNamespace(output=quote_letter.Paragraph(paragraph=self.paragraph),
                               usage=SimpleNamespace(input_tokens=700, output_tokens=60),
                               response=SimpleNamespace(model_name="gpt-5.4-mini"))


def _approved(wp_id: str, *, language: str | None = None) -> int:
    v = q192._done(wp_id)
    if language:
        v = quote_draft.save(wp_id, q192._sent(v, language=language), actor="anna", expected_state=v["state"])
    return quote_draft.approve(wp_id, fingerprint=v["fingerprint"], actor="anna")["version"]


# --- the code's check and the frame ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "problems"), [
    ("Köszönjük megkeresését; mellékelten küldjük az irodai eszközökre szóló ajánlatunkat.", []),
    ("A 3 monitor ára mellékelve.", ["number"]),
    ("Részletek: www.pelda.hu", ["link"]),
    ("Írjon az ajanlat@pelda.hu címre.", ["email"]),
    ("Ajánlatunk {{gross_total}} forint.", ["marker"]),
    ("", ["empty"]),
    ("szó " * 300, ["too_long"]),
])
def test_the_code_refuses_a_number_a_link_an_address_a_marker_or_a_long_paragraph(text, problems):
    assert quote_letter.check_paragraph(text) == problems


def test_the_frame_greets_by_name_writes_the_totals_by_code_and_closes():
    content = {"header": {"contact_name": "Minta Anna", "customer_name": "Példa Kft."}, "language": "hu", "currency": "HUF",
               "vat_percent": "27", "lines": [{"net": "164700"}], "totals": {"net": "164700", "vat": "44469", "gross": "209169"},
               "request": {"title": "Ajánlatkérés monitorokra"}}
    body = quote_letter.compose(content, package="Office", n=1, paragraph=None)
    assert body.startswith("Tisztelt Minta Anna!\n\nKöszönjük ajánlatkérését")
    assert "bruttó végösszege 209 169 Ft (nettó 164 700 Ft + ÁFA)" in body and body.endswith("Üdvözlettel:\n")
    assert body.count("mellékelten küldjük") == 1  # W4: said once, by the paragraph, not again by the totals line
    assert quote_letter.subject(content) == "Re: Ajánlatkérés monitorokra"
    english = {**content, "language": "en", "header": {}, "request": {"title": "RE: monitors"}}
    body = quote_letter.compose(english, package="Office", n=1, paragraph="Thank you for asking us.")
    assert body.startswith("Dear Sir or Madam,\n\nThank you for asking us.\n\nThe total of our quotation is 209,169 HUF gross")
    assert quote_letter.subject(english) == "RE: monitors"
    assert quote_letter.subject({**content, "request": {}}) == "Árajánlat"


# --- the letter of an approved version --------------------------------------------------------------------------------


def test_without_an_approved_version_there_is_no_letter(quote):
    assert quote_letter.view(quote["wp"])["version"] is None
    with pytest.raises(quote_letter.LetterError, match="approved"):
        quote_letter.request(quote["wp"], actor="anna")


def test_gpts_paragraph_is_asked_by_the_worker_under_its_cap_and_used_when_it_passes(quote):
    wp_id = quote["wp"]
    n = _approved(wp_id)
    before = quote_letter.view(wp_id)
    assert before["version"] == n and before["state"] is None and before["cap"] == {"openai": "0.02"}
    assert "Köszönjük ajánlatkérését" in before["body"]  # the frame's own paragraph before GPT is asked
    agent = _Agent("Köszönjük megkeresését. Mellékelten küldjük az irodai eszközökre és a kávéfőzőre szóló ajánlatunkat.")
    with quote_letter.use_agent_factory(lambda model, instructions: agent):
        assert quote_letter.request(wp_id, actor="anna")["state"] == "queued"
        worker.run_worker(once=True)
    after = quote_letter.view(wp_id)
    assert after["state"] == "done" and after["problems"] == []
    assert "Mellékelten küldjük az irodai eszközökre" in after["body"] and "Köszönjük ajánlatkérését" not in after["body"]
    assert after["usage"]["providers"]["openai"]["limit_usd"] == "0.02"  # the call went through the letter's budget
    sent = agent.prompts[0]
    assert '"language": "Hungarian"' in sent and "54900" not in sent and "1228979" not in sent  # no price goes to GPT
    assert after["to"] and after["subject"].startswith("Re: ")


def test_a_paragraph_with_a_number_is_not_used_and_the_frame_stays(quote):
    wp_id = quote["wp"]
    _approved(wp_id)
    with quote_letter.use_agent_factory(lambda model, instructions: _Agent("A 3 monitor és a 2 laptop ára mellékelve.")):
        quote_letter.request(wp_id, actor="anna")
        worker.run_worker(once=True)
    v = quote_letter.view(wp_id)
    assert v["state"] == "done" and v["problems"] == ["number"]
    assert "A 3 monitor" not in v["body"] and "Köszönjük ajánlatkérését" in v["body"]


def test_a_failed_call_shows_on_the_letter_and_the_frame_stays(quote):
    wp_id = quote["wp"]
    _approved(wp_id)

    class _Broken:
        def run_sync(self, *_a, **_k):
            raise RuntimeError("synthetic outage")

    with quote_letter.use_agent_factory(lambda model, instructions: _Broken()):
        quote_letter.request(wp_id, actor="anna")
        worker.run_worker(once=True)
    v = quote_letter.view(wp_id)
    assert v["state"] == "failed" and "synthetic outage" in v["error"] and "Köszönjük ajánlatkérését" in v["body"]


def test_the_letter_file_needs_an_accepted_body_and_carries_the_word_quote(quote):
    wp_id = quote["wp"]
    n = _approved(wp_id, language="en")
    with pytest.raises(quote_letter.LetterNotReady):
        quote_letter.eml(wp_id, n)
    v = quote_letter.view(wp_id)
    assert v["body"].startswith("Dear ")
    with pytest.raises(quote_letter.LetterError, match="no text"):
        quote_letter.accept(wp_id, "  ", actor="anna", expected_state=v["decision_state"])
    accepted = quote_letter.accept(wp_id, v["body"] + "\nAnna Minta\n", actor="anna", expected_state=v["decision_state"])
    assert accepted["accepted"]["by"] == "anna" and accepted["body"].endswith("Anna Minta\n")
    with pytest.raises(work.RevisionConflict):
        quote_letter.accept(wp_id, "Other text", actor="bela", expected_state=v["decision_state"])
    data, name = quote_letter.eml(wp_id, n)
    assert name == f"reply-Office-v{n}.eml"
    msg = email.message_from_bytes(data, policy=policy.default)
    assert msg["X-Unsent"] == "1" and msg["Subject"].startswith("Re: ") and msg["To"]
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert body.startswith("Dear ") and "Anna Minta" in body
    attachment = next(msg.iter_attachments())
    assert attachment.get_filename() == f"quotation-Office-v{n}.docx"
    assert attachment.get_content() == quote_draft.version_docx(wp_id, n)[0]
    assert [e["action"] for e in work.workpackage_events(wp_id) if e["action"] == "quote_letter_accept"] == ["quote_letter_accept"]


def test_a_reopened_quote_has_no_letter_until_it_is_approved_again(quote):
    wp_id = quote["wp"]
    _approved(wp_id)
    v = quote_letter.view(wp_id)
    quote_letter.accept(wp_id, v["body"], actor="anna", expected_state=v["decision_state"])
    quote_draft.reopen(wp_id, note="New quantities", actor="anna")
    assert quote_letter.view(wp_id)["version"] is None
    quote_letter.eml(wp_id, 1)  # the earlier version's accepted letter stays


def test_the_service_answers_the_letter(quote, tmp_path):
    from fastapi.testclient import TestClient

    from jav.service.api import create_app

    wp_id = quote["wp"]
    human = {"X-Actor": "teszt.elek"}
    with TestClient(create_app(store_path=Path(tmp_path) / "q.sqlite"), base_url="http://127.0.0.1:8930") as c:
        assert c.post(f"/api/workpackages/{wp_id}/quote/letter/paragraph", headers=human, json={}).status_code == 422
        n = _approved(wp_id)
        page = c.get(f"/api/cases/{wp_id}").json()  # 231 (A3d): the quote is a case's; its approval tab shows the letter
        assert page["tabs"][2]["elements"][0]["data"]["quote"]["letter"]["version"] == n
        letter = c.get(f"/api/workpackages/{wp_id}/quote/letter").json()
        assert c.get(f"/api/workpackages/{wp_id}/quote/versions/{n}/letter.eml").status_code == 422
        ok = c.put(f"/api/workpackages/{wp_id}/quote/letter", headers=human,
                   json={"body": letter["body"], "expected_state": letter["decision_state"]})
        assert ok.status_code == 200 and ok.json()["accepted"]["by"] == "teszt.elek"
        stale = c.put(f"/api/workpackages/{wp_id}/quote/letter", headers=human,
                      json={"body": "x", "expected_state": letter["decision_state"]})
        assert stale.status_code == 409
        got = c.get(f"/api/workpackages/{wp_id}/quote/versions/{n}/letter.eml")
        assert got.status_code == 200 and got.headers["content-type"].startswith("message/rfc822")
        with quote_letter.use_agent_factory(lambda model, instructions: _Agent("Köszönjük megkeresését.")):
            queued = c.post(f"/api/workpackages/{wp_id}/quote/letter/paragraph", headers=human, json={})
        assert queued.status_code == 202 and queued.json()["state"] == "queued"


# --- the golden set (W4) ---------------------------------------------------------------------------------------------


class _ByLanguage:
    """A GPT stand-in writing a clean paragraph in the language the prompt names."""

    def run_sync(self, prompt, **_kw):
        text = ("Thank you for your request; please find our quotation for the office equipment attached."
                if '"language": "English"' in prompt else
                "Köszönjük megkeresését; mellékelten küldjük az irodai eszközökre szóló árajánlatunkat.")
        return SimpleNamespace(output=quote_letter.Paragraph(paragraph=text), usage=SimpleNamespace(input_tokens=600, output_tokens=40),
                               response=SimpleNamespace(model_name="gpt-5.4-mini"))


def test_the_golden_set_is_every_invented_request_with_a_quote_and_the_injection_probe():
    from jav.domains.quotes import invented_golden

    cases = quote_letter.golden_cases(invented_golden.load())
    expected = [c.id for c in invented_golden.load().cases if c.expected.request is not None and c.expected.quote is not None]
    assert [c["id"] for c in cases] == [*expected, "probe_injection_hu"]
    assert {c["language"] for c in cases} == {"hu", "en"}
    assert all(c["lines"] and c["requested"] for c in cases)


def test_the_golden_set_judges_each_paragraph_by_the_codes_check_and_its_language(tmp_path):
    from jav.core import store
    from jav.domains.quotes import invented_golden

    data = invented_golden.load()
    with store.use_store(tmp_path / "g.sqlite"), quote_letter.use_agent_factory(lambda m, i: _ByLanguage()):
        g = quote_letter.golden(data, limits={"openai": quote_letter.Decimal("0.5")}, out_dir=tmp_path)
        assert g["tally"] == {"right": g["cases"]} and g["usage"]["committed_usd"] > 0
        again = quote_letter.golden(data, limits={}, earlier_only=True, out_dir=tmp_path)  # free: the earlier answers
        assert again["tally"] == {"right": g["cases"]}
    with store.use_store(tmp_path / "empty.sqlite"):
        none = quote_letter.golden(data, limits={}, earlier_only=True, out_dir=tmp_path)
    assert none["tally"] == {"failed": g["cases"]}  # without a budget nothing new is asked


def test_the_letter_is_written_with_the_frame_its_process_names(quote, monkeypatch):
    """231 (B0): the letter step's frame (a process pack's resource) reaches the letter: its body, subject and file."""
    from jav.domains.quotes import quote_document

    shipped = quote_document.settings()
    formal = {lang: {**frame, "fallback": "Formal paragraph.", "file": "formal-reply"}
              for lang, frame in shipped["letter"].items()}
    monkeypatch.setattr(quote_document, "settings", lambda: {**shipped, "formal": formal})
    wp_id = quote["wp"]
    _approved(wp_id)
    with pytest.raises(quote_letter.LetterError):
        quote_letter.request(wp_id, actor="anna", frame="nowhere")
    with quote_letter.use_agent_factory(lambda: _Agent("Thank you for asking about 3 monitors.")):  # a number: not used
        quote_letter.request(wp_id, actor="anna", frame="formal")
        worker.run_worker(once=True)
    shown = quote_letter.view(wp_id)
    assert "Formal paragraph." in shown["body"]  # the formal frame's own paragraph stands in for the refused one
    quote_letter.accept(wp_id, shown["body"], actor="anna", expected_state=shown["decision_state"])
    _data, name = quote_letter.eml(wp_id, shown["version"])
    assert name.startswith("formal-reply-")
