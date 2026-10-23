"""164 (the owner's decision of 2026-10-17, after the GPT-only check measurement): an outgoing invoice's buyer address
only shows its GPT confidence, as an address does on a Hungarian invoice; it opens no to-do on the G path without JEV.

The measurement: on 43 real outgoing invoices the buyer address opened a to-do on every one, each time on a value that
agreed with the earlier result, since a long text gets a lower token probability as a whole. The setting is the
policy's (`gpt_field_confidence.info_only`, per type pack), so the pack's scoring, the JEV path and the text GPT is sent
stay as they were. The eval report follows it: such a field never counts as a to-do. No paid call.
"""

from __future__ import annotations

from jav.evals import eval_report as er
from jav.ai import policy
from jav.ai.typepack import get as get_pack


def test_the_outgoing_invoices_buyer_address_opens_no_gpt_to_do():
    fields = policy.gpt_review_fields("invoice_out")
    assert "buyer_address" not in fields
    assert {"buyer_name", "buyer_tax_id", "net_total", "invoice_number"} <= set(fields)  # the other accounting fields stay
    assert "buyer_address" in get_pack("invoice_out").strict_scored  # the pack still scores it


def test_other_packs_are_unchanged():
    assert policy.GPT_FIELD_CONFIDENCE["info_only"] == {"invoice_out": ["buyer_address"]}
    pack = get_pack("invoice_hu")
    assert policy.gpt_review_fields("invoice_hu") == [f for f in pack.header_fields
                                                       if f in set(pack.strict_scored) | set(pack.high_stakes)]


def test_the_gpt_extraction_text_does_not_change():
    """The setting is read by the to-do rule only: the instructions and the schema GPT is sent are those of the pack."""
    import json

    from jav.ai.extract_llm import instructions

    pack = get_pack("invoice_out")
    assert "info_only" not in instructions(pack)
    assert "info_only" not in json.dumps(pack.llm_model().model_json_schema())


def test_the_eval_report_counts_such_a_field_as_no_to_do():
    row = {"case_id": "o1", "doc_type": "invoice_out", "flow_label": "invoice_out_G", "arm": "G", "run_no": 1,
           "review_reasons": ["gpt:low_conf:net_total:0.90"], "scores": {"buyer_address": True, "net_total": True},
           "field_confidence": {"buyer_address": 0.60, "net_total": 0.90, "buyer_name": 0.97}}
    js = {j.question: j for j in er._from_invoice_G_gpt(row)}
    assert js["buyer_address"].callsite == "invoice.gpt_field.info" and er.band_of(js["buyer_address"]) == "auto"
    assert js["net_total"].callsite == "invoice.gpt_field" and er.band_of(js["net_total"]) == "human"
    assert er.band_of(js["buyer_name"]) == "human"
