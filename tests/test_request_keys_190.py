"""190 (plan 189 A2a): characterisation of every existing type pack's G-path requests before the quote request's core.

The quote request (A2) makes the extraction core general: an email's text as a document, general list fields, and
verification questions named by the pack. Each of these is a switch of the type pack whose default is today's
behaviour, so the requests of every existing pack must stay bit for bit the same; otherwise every golden set would
need a paid re-measurement. These tests pin, for every pack with a G path, the fingerprint of its GPT extraction
request (the reuse key of an earlier answer: instructions, the answer's schema, the settings and the source text) and
of its JEV verification request (the JEV cache key: the state and the questions), on a synthetic document built from
the pack's own fields.

Pinned on `952c2b5` (v1.28.1 + 189); the quote request's pack (190, A2e) when it was added. 197: the taught ticket candidate
(plan 197 K2b) when it was made. 231 (D-e1): the insurance application's three packs when they were added. A deliberate change to a pack, its prompt, its schema or its verification call
site changes its fingerprint too, and needs that pack's paid golden run anyway. Synthetic values only; no model call.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from typesafe_sdk import Noul

from jav.ai import extract_llm, typepack
from jav.ai.jev import request_hash
from jav.ai.jev_verify import site_for
from jav.documents.layout import LineLayout
from jav.core import calls

SAMPLE = {  # a printable synthetic value per field kind
    "name": "Minta Kereskedo Kft.", "tax_id": "12345676-2-41", "date": "2026-03-04", "money": "12700",
    "iban": "HU42117730161111101800000000", "currency": "HUF", "country": "HU", "invoice_number": "MINTA-2026-001",
    "address": "1111 Budapest, Minta utca 1.", "text": "minta szoveg", "number": "42", "boolean": True,
}

G_PACKS = sorted(k for k in typepack.keys() if "G" in typepack.get(k).arms)

# the first 16 hexadecimal digits of each request's fingerprint on `952c2b5`
GPT_KEYS = {
    "altalanos_szerzodesi_feltetelek": "e9bd2b0f4dee424c", "belepo_jegy": "d16cc14923fe14d8",
    "belepo_jegy_taught": "b0d2b8ee2c2ee5f8",  # 197 (plan 197 K2b): the taught candidate, when it was made
    "certificate": "daf2c5cad78a84c2", "csapatmenedzser_utasitas": "6e26cf8577171283",
    "csatorna_szamla": "1433e992cc9866fa", "foldgaz_szamla": "ea19eccc8c6e98fe", "id_document": "70329e3284675e30",
    "insurance_claim_form": "3793871b03708dfc", "invoice_foreign": "ff38e123caafdafa",
    "invoice_hu": "d53be29307d2ff77", "invoice_out": "8c1d13b30d2c7bf2", "meeting_minutes": "9231eabac32c2610",
    "meghivo": "83d46f135afc8a75", "mohu_szamla": "efa9e4b65850aa33", "nav_certificate": "760149090e6e1860",
    "nav_receipt": "a94a5a56bfa91bff", "nav_tax_return": "de4a4dd4bdb38881", "proforma_invoice": "b806c7f7d833181d",
    "statement_cib": "e363a04424b0cbfc", "statement_erste": "a1945247a3e0a671", "terkep_adat": "239ce7fc9be46b0d",
    "villamos_energia_szamla": "4d5873be63e21fb7", "viz_szamla": "7010f2c0cb3c2db5",
    "vizmuvek_szamla": "8b607daa57d74606",
    "quote_request": "026aa29aa98ab0be",  # 190 (A2e): the new pack, pinned when it was added
    # 231 (stage D, D-e1): the insurance application's packs, pinned when they were added
    # 231 (U-A0): the property schedule reads every asset group row, an unlisted one too (a new request on purpose);
    # (U-A6) the request's chosen deductible, term and waiting days, the schedule's protection class and flood zone as printed; (U-A7) the protection the real product's rules ask for
    "insurance_request": "d174d082a62a82d4", "property_schedule": "110489c9c73fd3d9", "claims_history": "1f6311eee41aebbd",
}
JEV_KEYS = {
    "altalanos_szerzodesi_feltetelek": "4be1a38d837ebe3d", "belepo_jegy": "f4973f0d2a07bc02",
    "belepo_jegy_taught": "b8e8ec743fae4499",  # 197: the taught candidate, when it was made
    "certificate": "588ca07d0de9fd7e", "csapatmenedzser_utasitas": "8de8f0792574066c",
    "csatorna_szamla": "bd9a7cb201456622", "foldgaz_szamla": "bf681f047acf48c2", "id_document": "f3629687b5ff18d4",
    "insurance_claim_form": "212a7e23eb536504", "invoice_foreign": "2277972c0f5a0c0b",
    "invoice_hu": "9dadd7d2de6aa5b1", "invoice_out": "2c153ae26424ac44", "meeting_minutes": "abfdd9a01086529f",
    "meghivo": "af6b3f969087a48e", "mohu_szamla": "b3898fb450131f03", "nav_certificate": "cc55618d3cffb01b",
    "nav_receipt": "5173d94d7155493c", "nav_tax_return": "3a98645a4cb21423", "proforma_invoice": "9dadd7d2de6aa5b1",
    "statement_cib": "38f3b0b861300f46", "statement_erste": "1f36e67ef8c2e4d5", "terkep_adat": "bcbde1504beb0e8b",
    "villamos_energia_szamla": "0312741c5dfc7789", "viz_szamla": "e499cb4d9a7dba73",
    "vizmuvek_szamla": "40a4b0f87655833c",
    "quote_request": "c3cb7a88278eca49",  # 190 (A2e)
    "insurance_request": "096c5ca1871c1f4a", "property_schedule": "9c7d3b480742458b", "claims_history": "7a7e2ad253fecb3c",  # D-e1
    # (U-A6: the request's three new fields' meanings; U-A7: the protection fields')
    # 231 (stage F, F1): a document-level question is asked only of a pack that has the fields it reads; the
    # 22 packs without the parties or the line items were re-pinned then (the Hungarian invoice's, the proforma's,
    # the outgoing invoice's, the quote request's and the insurance packs' keys stayed the same)
}


def _row(kinds: dict[str, str]) -> Any:
    """One list row from the pack's item description (`{"*": kind}`: a plain value)."""
    if "*" in kinds:
        return SAMPLE.get(kinds["*"], "minta")
    return {sub: SAMPLE.get(kind, "minta") for sub, kind in kinds.items()}


def _extraction(pack: typepack.TypePack) -> dict[str, Any]:
    """Every field with a sample of its kind, except every third header field, which is left empty (the questions on
    an empty field differ from those on a printed one)."""
    out: dict[str, Any] = {}
    for i, (field, kind) in enumerate(pack.fields.items()):
        if kind == "list":
            out[field] = [_row(pack.list_fields[field])]
        else:
            out[field] = None if i % 3 == 2 else SAMPLE[kind]
    return out


def _lines(pack: typepack.TypePack, extraction: dict[str, Any]) -> list[LineLayout]:
    """The document: a labelled line per printed header field, then the list rows."""
    texts = [f"{field}:   {value}" for field, value in extraction.items()
             if pack.kind(field) != "list" and value is not None]
    for field in pack.list_fields:
        for row in extraction[field]:
            texts.append("   ".join(str(v) for v in (row.values() if isinstance(row, dict) else [row])))
    return [LineLayout(no=i, page=1, text=t) for i, t in enumerate(texts, 1)]


def _text(lines: list[LineLayout]) -> str:
    return "\n".join(ln.text for ln in lines)


class _Jev:
    """A JEV stand-in that keeps what it was asked and answers every Noul with 0.1."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, dict]] = []

    def ask(self, request_id, state, questions, **_kw):
        self.sent.append((request_id, state, questions))
        nouls = {q: SimpleNamespace(noul=0.1) for q, v in questions.items() if isinstance(v, Noul)}
        return SimpleNamespace(response=SimpleNamespace(nouls=nouls, model="jev-test"),
                               call=SimpleNamespace(request_id=request_id, cached=False))


def gpt_key(key: str, monkeypatch) -> str:
    """The reuse key of the pack's extraction request, as the call log receives it in a work run."""
    pack = typepack.get(key)
    lines = _lines(pack, _extraction(pack))
    seen: dict[str, Any] = {}

    def invoke(**kw):
        seen.update(kw)
        return SimpleNamespace(response=extract_llm.encode_answer({}, None))

    monkeypatch.setattr(extract_llm.calls, "invoke", invoke)
    with extract_llm.use_agent_factory(lambda _pack: None), calls.use_run(budget_scope="request-keys-190"):
        extract_llm.extract_scored(_text(lines), run_id="request-keys-190", pack=pack)
    return seen["request_hash"]


def jev_key(key: str) -> tuple[str, str]:
    """(request id, the JEV cache key) of the pack's verification request; the model name is fixed."""
    pack = typepack.get(key)
    extraction = _extraction(pack)
    jev = _Jev()
    site_for(key).verify(jev, _lines(pack, extraction), extraction, run_id="request-keys-190")
    assert len(jev.sent) == 1, "one request, without trimming"
    request_id, state, questions = jev.sent[0]
    return request_id, request_hash("jev-test-model", state, questions)


def test_every_g_path_pack_is_pinned():
    assert sorted(GPT_KEYS) == G_PACKS
    assert sorted(JEV_KEYS) == G_PACKS


@pytest.mark.parametrize("key", G_PACKS)
def test_the_gpt_extraction_request_is_unchanged(key, monkeypatch):
    assert gpt_key(key, monkeypatch)[:16] == GPT_KEYS[key]


@pytest.mark.parametrize("key", G_PACKS)
def test_the_jev_verification_request_is_unchanged(key):
    request_id, digest = jev_key(key)
    assert request_id == site_for(key).request_id
    assert digest[:16] == JEV_KEYS[key]
