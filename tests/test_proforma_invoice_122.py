"""122 (backlog F-pro-forma, the owner's decision of 2026-10-02 'new type: pro forma invoice'): the pro forma invoice
(payment request) is its own type in the invoice family, read like a Hungarian invoice. Offline; no paid calls."""

import json

from jav import cfg, detect_detail, extract_llm, typepack
from jav.config import PROJECT_ROOT, load_prompt
from jav.doc_types import BY_KEY, DOC_TYPE_KEYS


def test_the_pro_forma_invoice_is_a_registered_type_of_the_invoice_family():
    t = BY_KEY["proforma_invoice"]
    assert "proforma_invoice" in DOC_TYPE_KEYS and t.parent == "invoice_like"
    assert "proforma_invoice" in BY_KEY["invoice_hu"].not_for  # the sibling points to it
    assert t.examples and t.required_any


def test_its_pack_is_the_category_itself_and_reads_like_a_hungarian_invoice():
    assert detect_detail.candidates("proforma_invoice") == ["proforma_invoice"]
    pack, invoice = typepack.get("proforma_invoice"), typepack.get("invoice_hu")
    assert pack.parent == "proforma_invoice" and pack.arms == ("S", "G")
    assert pack.fields == invoice.fields and pack.list_fields == invoice.list_fields
    assert (pack.select_callsite, pack.verify_callsite, pack.candidate_profile) == ("select", "verify", "hu")
    assert "fulfillment_date" not in pack.required


def test_the_g_path_instructions_add_the_pro_forma_note_to_the_invoice_prompt():
    pack, invoice = typepack.get("proforma_invoice"), typepack.get("invoice_hu")
    text = extract_llm.instructions(pack)
    assert text.startswith(load_prompt(invoice.prompt_file)) and "pro forma" in text.lower()
    # the existing packs' requests are unchanged (their saved answers stay reusable)
    assert extract_llm.instructions(invoice) == load_prompt(invoice.prompt_file)


def test_naming_labels_and_email_routing_know_the_type():
    assert cfg.load("naming")["types"]["proforma_invoice"]["token"] == "DIJBEKERO"
    label = cfg.load("field_labels")["doc_types"]["proforma_invoice"]  # the Hungarian UI label
    english = json.loads((PROJECT_ROOT / "ui" / "src" / "i18n" / "en-server.json").read_text(encoding="utf-8"))
    assert label != "proforma_invoice" and english[label] == "Pro forma invoice"
    assert "proforma_invoice" in cfg.load("policy")["email"]["m2_types"]


def test_the_capability_catalog_covers_the_new_pack():
    from jav.capability_catalog import build_catalog

    keys = [d["key"] for d in build_catalog()["documents"]]
    assert "proforma_invoice" in keys
