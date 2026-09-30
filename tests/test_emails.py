"""M3 e-mail szándék - offline: szándék-regiszter, törzs-tisztítás, state-építés, next_flow policy, régi golden betöltés."""

import json

from jav import policy
from jav.emails import OLD_INTENT_GOLDEN, Attachment, EmailMessage, clean_body, load_message_dir, load_old_golden, sender_domain
from jav.intent import NOUL_KEYS, build_questions, build_state
from jav.intents import BY_KEY, DOCUMENT_BEARING, INTENT_KEYS, OTHER, choice_criteria


def test_registry_consistent():
    assert OTHER in INTENT_KEYS and len(INTENT_KEYS) == 11
    crit = choice_criteria()
    assert set(crit) == set(INTENT_KEYS)
    assert all(len(v["what"]) > 40 and v["not_for"] for v in crit.values())  # v2: strukturált kritérium
    assert DOCUMENT_BEARING == {"szamlakuldes", "fizetesi_visszaigazolas"}
    assert BY_KEY["szamlakuldes"].display_name == "Számlaküldés"


def test_clean_body_cuts_quoted_reply_and_urls():
    raw = ("Sziasztok!\r\n\r\nItt a hétvégi mezszín.\r\n <https://x.example/logo.png> \r\n\r\nLajos\r\n\r\n"
           "From: TD MGYSZ <td@example.com>\r\nSent: Monday\r\nSubject: régi\r\nEz már idézet.")
    body = clean_body(raw)
    assert body.startswith("Sziasztok!")
    assert "Lajos" in body and "idézet" not in body and "https://" not in body
    assert "\n\n\n" not in body


def test_clean_body_strips_newsletter_preheader_padding():
    raw = "És egy meghívó vasárnapra.\r\n͏ ‌     ͏ ‌     ͏ ‌\r\nTartalom."
    body = clean_body(raw)
    assert body == "És egy meghívó vasárnapra.\n\nTartalom."  # a töltelék-sor üres sorrá válik, a bekezdés-határ megmarad


def test_clean_body_keeps_forwarded_content_when_body_starts_with_header():
    raw = "From: valaki <v@example.com>\r\nSent: ma\r\nSubject: FW\r\n\r\nA továbbított tartalom itt van."
    assert "továbbított tartalom" in clean_body(raw)


def test_build_state_features_and_questions():
    msg = EmailMessage(
        message_id="m1", mailbox="x@example.hu", sender="noreply@billingo.hu", subject="Számlája érkezett",
        body="Önnek elektronikus számlája érkezett.\nA számla végösszege: 9 525 Ft\nFizetési határidő: 2026-06-05\n",
        attachments=[Attachment(filename="peldaweb-2026-3175.pdf")],
    )
    st = build_state(msg)
    f = st["features"]
    assert f["automated_sender"] and not f["reply_or_forward"]
    assert f["mentions_amount"] and f["mentions_due"] and f["invoice_words"] >= 2
    assert st["sender_domain"] == "billingo.hu" and st["attachments"][0]["filename"].endswith(".pdf")
    assert st["body_lines"][0].startswith("L01: ")
    qs = build_questions()
    assert set(qs) == {"intent", *NOUL_KEYS, "urgency"}
    json.dumps(st, ensure_ascii=False)  # a state JSON-szerializálható (cache-kulcs)


def test_sender_domain():
    assert sender_domain("Név <a@B.Example.com>") == "b.example.com"
    assert sender_domain(None) is None and sender_domain("nincs") is None


def test_next_flow_policy():
    pdf_typed = [Attachment(filename="a.pdf", path="a.pdf", doc_type="invoice_hu", type_conf=0.98, status="done")]
    pdf_name_only = [Attachment(filename="a.pdf", status="name_only")]
    assert policy.email_next_flow("szamlakuldes", 0.3, pdf_typed) == "human:low_confidence"
    assert policy.email_next_flow("szamlakuldes", 0.9, pdf_typed) == "m2:invoice_hu"
    assert policy.email_next_flow("szamlakuldes", 0.9, pdf_name_only) == "m1:detect"
    assert policy.email_next_flow("szamlakuldes", 0.9, []) == "human:fetch_document"
    assert policy.email_next_flow("fizetesi_visszaigazolas", 0.9, []) == "archive:payment_proof"
    assert policy.email_next_flow("business_correspondence", 0.9, []) == "human:inbox"
    assert policy.email_next_flow("newsletter_marketing", 0.9, []) == "archive"
    assert policy.email_next_flow("szamlakuldes", 0.9, [Attachment(filename="s.pdf", path="s.pdf", status="needs_ocr")]) == "m2:needs_ocr"


def test_load_message_dir(tmp_path):
    d = tmp_path / "box" / "abc123"
    d.mkdir(parents=True)
    (d / "message.json").write_text(json.dumps({"sender": "a@b.hu", "subject": "T", "body": "szia"}), encoding="utf-8")
    (d / "01_szamla.pdf").write_bytes(b"%PDF-1.4")
    msg = load_message_dir(d)
    assert msg.message_id == "abc123" and msg.mailbox == "box"
    assert [a.filename for a in msg.attachments] == ["01_szamla.pdf"] and msg.attachments[0].path


def test_ingest_server_maps_bridge_payload(tmp_path):
    from jav.ingest_server import host_path, short_hash, write_message

    assert short_hash("x") == "9dd4e461268c8034"  # md5("x")[:16] - a bridge Get-ShortHash-ével azonos
    assert len(short_hash("y")) == 16 and short_hash("x") != short_hash("y")
    assert host_path("/tmp/other") is None and host_path("/data/does/not/exist.pdf") is None
    payload = {
        "batch_id": "b1", "message_id": "ENTRYID-1", "account": "a@example.hu", "from": "noreply@billingo.hu",
        "sender": "Billingo", "to": ["a@example.hu"], "cc": [], "subject": "Számlája érkezett",
        "body_preview": "Önnek elektronikus számlája érkezett.", "received": "2026-06-01T10:00:00",
        "attachments": [{"path": "/data/inbox/email/a_example.hu/abc/01_szamla.pdf", "filename": "szamla.pdf"}],
        "ocr_policy": "auto", "attachments_failed": 0, "n_recognized": 1, "force": False,
    }
    folder, existed = write_message(payload, tmp_path)
    assert not existed and folder == tmp_path / "a_example.hu" / short_hash("ENTRYID-1")
    rec = json.loads((folder / "message.json").read_text(encoding="utf-8"))
    assert rec["sender"] == "noreply@billingo.hu" and rec["sender_name"] == "Billingo" and rec["body"].startswith("Önnek")
    assert rec["attachments"][0]["filename"] == "szamla.pdf" and rec["attachments"][0]["path"] is None  # a host-fájl nincs meg
    _, existed2 = write_message(payload, tmp_path)
    assert existed2  # ismételt POST -> deduped
    msg = load_message_dir(folder)
    assert msg.message_id == short_hash("ENTRYID-1") and msg.mailbox == "a@example.hu" and msg.attachments[0].path is None


def test_old_golden_loads_if_present():
    cases = load_old_golden()
    if not OLD_INTENT_GOLDEN.exists():
        assert cases == []
        return
    assert len(cases) == 96
    assert {c.expected for c in cases} <= set(INTENT_KEYS)
    assert all(c.message.subject or c.message.body for c in cases)
