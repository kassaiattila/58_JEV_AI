"""231 (stage D, D-e1): the insurance application's detection type and its three type packs.

A business's request for insurance cover is a detection type of its own (the owner's decision of 2026-10-26: a new
main type), in the request family, with three type packs of the G path under it: the quote request form, the property
schedule of one site and the claims history statement. Keywords tell the three apart; each names its files; each one's
verification asks no invoice question and asks its lists about missing and extra rows; an invented PDF of each is
extracted and checked, by JEV (a stand-in) and, without JEV, by the code's own source check. Invented documents and
stand-in clients only; no paid call.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from typesafe_sdk import Noul

from jav.ai import detect_detail, doc_types, extract_llm, typepack
from jav.ai import jev as jev_mod
from jav.ai.jev_verify import site_for
from jav.ai.models import JevCall
from jav.app import naming
from jav.core import store
from jav.documents.synthetic_pdf import write_unicode_pdf
from jav.flows import flow
from tests.test_no_jev_085 import _FakeAgent

BROAD = "insurance_application"
PACKS = ("claims_history", "insurance_request", "property_schedule")

REQUEST = ["BIZTOSÍTÁSI AJÁNLATKÉRŐ LAP", "Vállalkozói vagyonbiztosítás", "Szerződő: Minta Kereskedő Kft.",
           "Adószám: 12345676-2-41", "Fő tevékenység (TEÁOR): 4719", "Kapcsolattartó: Minta Anna, anna@minta.hu",
           "Kockázatviselés kezdete: 2027. január 1.", "Díjfizetés: éves",
           "Kért fedezetek:   [X] vagyonbiztosítás   [X] betöréses lopás   [ ] üzemszünet",
           "Telephelyek:", "1.   1111 Budapest, Minta utca 1.   Magyarország"]
REQUEST_OUT = {"policyholder_name": "Minta Kereskedő Kft.", "policyholder_tax_number": "12345676-2-41", "activity_code": "4719",
               "contact_name": "Minta Anna", "contact_email": "anna@minta.hu", "cover_start": "2027-01-01",
               "payment_frequency": "éves", "accounting_method": None, "interruption_sum_insured": None, "currency": None,
               "requested_covers": [{"cover": "vagyonbiztosítás"}, {"cover": "betöréses lopás"}],
               "sites": [{"site_no": "1", "address": "1111 Budapest, Minta utca 1.", "country": "Magyarország"}]}
SCHEDULE = ["VAGYONADATLAP", "Szerződő: Minta Kereskedő Kft.", "Telephely száma: 1", "Telephely címe: 1111 Budapest, Minta utca 1.",
            "Alapterület: 450 m²", "Árvízi zóna: alacsony", "Távfelügyeletes riasztó: igen", "Túlfeszültség-védelem: T2+T3",
            "Pinceszinti tárolás: nem", "Védelmi szint: 3",
            "Vagyoncsoport   Biztosítási összeg   Értékelés   Avultság",
            "épület   80 000 000 Ft   új érték   10%", "készlet   12 000 000 Ft   új érték   0%"]
SCHEDULE_OUT = {"policyholder_name": "Minta Kereskedő Kft.", "site_no": "1", "site_address": "1111 Budapest, Minta utca 1.",
                "floor_area": "450", "flood_zone": "alacsony", "alarm_remote": "igen", "surge_protection": "T2+T3",
                "basement_storage": "nem", "protection_class": "3", "currency": "HUF",
                "asset_groups": [{"asset_group": "épület", "sum_insured": "80000000", "valuation": "új érték", "wear": 10},
                                 {"asset_group": "készlet", "sum_insured": "12000000", "valuation": "új érték", "wear": 0}]}
STATEMENT = ["KÁRELŐZMÉNY-NYILATKOZAT", "Nyilatkozattevő: Minta Kereskedő Kft., adószám: 12345676-2-41",
             "Vizsgált időszak: 2021. január 1. – 2025. december 31.",
             "Káresemény napja   Kár oka   Kifizetett kárösszeg", "2023. március 4.   csőtörés   350 000 Ft",
             "Károk száma összesen: 1", "Kifizetett kárösszeg összesen: 350 000 Ft"]
STATEMENT_OUT = {"policyholder_name": "Minta Kereskedő Kft.", "policyholder_tax_number": "12345676-2-41",
                 "period_start": "2021-01-01", "period_end": "2025-12-31", "claims_count": "1", "claims_paid_total": "350000",
                 "currency": "HUF", "claims": [{"claim_date": "2023-03-04", "cause": "csőtörés", "paid": "350000"}]}
DOCS = {"request": ("insurance_request", REQUEST, REQUEST_OUT), "schedule": ("property_schedule", SCHEDULE, SCHEDULE_OUT),
        "statement": ("claims_history", STATEMENT, STATEMENT_OUT)}


# --- the registrations ----------------------------------------------------------------------------------------------


def test_the_detection_type_is_in_the_request_family_and_its_neighbours_name_it() -> None:
    t = doc_types.BY_KEY[BROAD]
    assert t.parent == "request_like"
    assert f"({BROAD})" in doc_types.BY_KEY["other"].not_for and f"({BROAD})" in doc_types.BY_KEY["quote_request"].not_for
    assert "(other)" in t.not_for  # a claim notification stays where it was
    assert detect_detail.candidates(BROAD) == list(PACKS)


@pytest.mark.parametrize("key", PACKS)
def test_each_pack_reads_a_pdf_on_the_g_path_and_names_its_files(key: str) -> None:
    pack = typepack.get(key)
    assert pack.arms == ("G",) and pack.default_arm == "G" and pack.inputs == ("pdf",) and pack.parent == BROAD
    assert key in typepack.extractable_keys()
    assert naming.rules().types[key].token


@pytest.mark.parametrize("which", sorted(DOCS))
def test_the_keywords_tell_the_three_apart(which: str) -> None:
    key, lines, _out = DOCS[which]
    result = detect_detail.resolve(BROAD, "\n".join(lines), jev=None, run_id="t")
    assert (result.key, result.method) == (key, "anchors")


def test_the_file_names() -> None:
    def name(key: str, values: dict) -> str:
        return naming.name_for(key, values, dict(typepack.get(key).fields), original="x.pdf", rules=naming.rules()).stem

    holder = {"policyholder_name": "Minta Kereskedő Kft."}
    assert name("insurance_request", {**holder, "cover_start": date(2027, 1, 1)}) == "2027-01-01_BIZT_AJANLATKERO_Minta-Kereskedo-Kft"
    assert name("property_schedule", {**holder, "site_no": "1"}) == "VAGYONADATLAP_Minta-Kereskedo-Kft_1"
    assert name("claims_history", {**holder, "period_end": date(2025, 12, 31)}) == "2025-12-31_KARELOZMENY_Minta-Kereskedo-Kft"


@pytest.mark.parametrize("key", PACKS)
def test_the_verification_asks_no_invoice_question_and_asks_each_list(key: str) -> None:
    site = site_for(key)
    assert site.document_nouls == () and site.list_nouls == ("missing_rows", "extra_rows")
    questions = site.build_questions({f: None for f in typepack.get(key).header_fields}, {})
    assert not set(site_for("invoice_hu").document_nouls) & set(questions)
    assert {f"{lf}__{n}" for lf in typepack.get(key).list_fields for n in ("missing_rows", "extra_rows")} <= set(questions)
    texts = " ".join(str(q.instructions) for q in questions.values()).casefold()
    assert "invoice" not in texts and "supplier" not in texts


# --- the extraction of an invented document ---------------------------------------------------------------------------


class _Jev:
    def __init__(self) -> None:
        self.questions: dict = {}

    def ask(self, request_id, state, questions, **_kw):
        self.questions = questions
        nouls = {q: SimpleNamespace(noul=0.03) for q, v in questions.items() if isinstance(v, Noul)}
        return SimpleNamespace(response=SimpleNamespace(nouls=nouls, model="jev-test"),
                               call=JevCall(request_id=request_id, n_questions=len(questions), state_chars=0))


def _run(tmp_path: Path, which: str, *, jev: bool, adapter=None):
    key, lines, out = DOCS[which]
    pdf = write_unicode_pdf(tmp_path / f"{which}.pdf", lines)
    with store.use_store(tmp_path / "packs.sqlite"), extract_llm.use_agent_factory(lambda pack: _FakeAgent(pack, out)), \
            jev_mod.use_adapter(adapter or _NoJev()):
        app = flow.build_app(str(pdf), f"c-{which}", "G", tracker=False, doc_type=key, jev=jev)
        action, _, state = app.run(halt_after=flow.TERMINALS)
    return action.name, state.data


class _NoJev:
    def ask(self, *_a, **_k):
        raise AssertionError("JEV was asked on the path without JEV")


@pytest.mark.parametrize("which", sorted(DOCS))
def test_an_invented_document_is_extracted_and_checked_by_jev(tmp_path, which: str) -> None:
    jev = _Jev()
    terminal, state = _run(tmp_path, which, jev=True, adapter=jev)
    key = DOCS[which][0]
    assert all(c.ok for c in state.validation), [c for c in state.validation if not c.ok]
    assert {f"{lf}__missing_rows" for lf in typepack.get(key).list_fields} <= set(jev.questions)
    assert terminal == "done" and state.review_reasons == [], state.review_reasons


def _without_jev(tmp_path: Path, which: str) -> None:
    _terminal, state = _run(tmp_path, which, jev=False)
    assert state.verdicts.source == "code"
    assert state.verdicts.unsupported == [], state.verdicts.unsupported  # every value is printed on the document
    assert all(c.ok for c in state.validation)


def test_without_jev_the_code_checks_the_request(tmp_path) -> None:
    _without_jev(tmp_path, "request")


def test_without_jev_the_code_checks_the_schedule(tmp_path) -> None:
    _without_jev(tmp_path, "schedule")


def test_without_jev_the_code_checks_the_statement(tmp_path) -> None:
    _without_jev(tmp_path, "statement")
