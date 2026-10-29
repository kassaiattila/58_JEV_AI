"""231 (stage F, F2a; the owner's decisions of 2026-10-29): the S path's requests and the code's candidates, pinned.

The candidate finder's patterns move out of the code into a rule file (F2). That move must change no candidate and no
request: otherwise every S path golden set would need a paid re-measurement. These tests pin, for every pack with an
S path, the fingerprint of the JEV requests its selection sends (the JEV cache keys: the state with the candidate
options and the questions), and for every candidate profile the candidates the finders offer, on synthetic documents
written into a PDF and read back as a work run reads them: the synthetic golden cases (configs/golden_synthetic.json)
and an invented utility bill. Pinned on `2cb7b31`, before the move; the terms and conditions' S path and its `terms`
profile (F2c) on an invented web shop's terms when they were added. Synthetic values only; no model call.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from typesafe_sdk import Choice, Noul

from jav.ai import typepack
from jav.ai.candidates import PROFILES, find_all
from jav.ai.jev import request_hash
from jav.ai.jev_select import find_candidates, s_path_profile, site_for
from jav.ai.policy import NONE_LABEL
from jav.core import cfg
from jav.documents.pdf import read_pdf
from jav.documents.synthetic_pdf import write_unicode_pdf

UTILITY_BILL = [  # an invented water bill, its labels as a utility bill prints them
    "VÍZDÍJ SZÁMLA",
    "Szolgáltató neve: Minta Vízmű Zrt.   Felhasználó neve: Példa Lakó",
    "Székhely címe: 1111 Budapest, Teszt utca 1.   Felhasználási hely: 2222 Mintaváros, Próba út 2.",
    "Adószám: 12121216-2-42",
    "Számla sorszáma: VZ-2026-000123",
    "Számla kelte: 2026.03.10.   Fizetési határidő: 2026.03.25.",
    "Elszámolási időszak: 2026.02.01. - 2026.02.28.",
    "Fizetési mód: átutalás   Bankszámla: HU42 1177 3016 1111 1018 0000 0000",
    "Megnevezés   Mennyiség   Egységár   Nettó   Áfa   Bruttó",
    "Vízdíj   12,5 m3   350,00 Ft   4 375 Ft   27%   5 556 Ft",
    "Csatornadíj   12,5 m3   410,00 Ft   5 125 Ft   27%   6 509 Ft",
    "Nettó összesen: 9 500 Ft",
    "Áfa összesen: 2 565 Ft",
    "Fizetendő összeg: 12 065 Ft",
    "Mérőállás: 1234,5 m3   Korrekciós tényező: 1,0000",
]

TERMS = [  # invented general terms and conditions of a web shop (231, F2c: the `terms` profile)
    "Általános Szerződési Feltételek",
    "Fogyasztók részére",
    "Hatályos: 2026. március 1-től",
    "Cégnév: Minta Webáruház Korlátolt Felelősségű Társaság",
    "Székhely: 1111 Budapest, Teszt utca 1.   Adószám: 12121216-2-42",
    "1. A jelen Általános Szerződési Feltételek a Minta Webáruház és a Vevő jogait és kötelezettségeit tartalmazzák.",
    "2. Az Eladó a megrendelést három munkanapon belül teljesíti.",
    "1/3 oldal",
]

S_PACKS = sorted(k for k in typepack.keys() if "S" in typepack.get(k).arms)

# the first 16 hexadecimal digits of each fingerprint on `2cb7b31`
SELECT_KEYS = {
    "altalanos_szerzodesi_feltetelek": "6d592cf7ba6ae7d8",  # F2c, when it was added
    "csatorna_szamla": "b61926e4f8293edc", "foldgaz_szamla": "2deddea27efb0824", "invoice_foreign": "252275f3a774ca10",
    "invoice_hu": "58a7d4ce2f773677", "invoice_out": "0ced44c4d2788876", "mohu_szamla": "eb50cff9474b13bd",
    "proforma_invoice": "58a7d4ce2f773677", "villamos_energia_szamla": "22beb4e9d412b5a5", "viz_szamla": "aecf7385ca096b74",
    "vizmuvek_szamla": "909132b3c4bcd0e8",
}
CANDIDATE_KEYS = {"hu": "de00dc6e2e01f24e", "intl": "b441ff11b81ae63b", "utility": "32dbb3ae9982887e",
                  "terms": "b885976a365233ec"}  # F2c, when it was added


def _documents() -> dict[str, list[list[str]]]:
    """The synthetic documents per profile: the golden cases of the packs reading with it, the utility bill."""
    cases = cfg.load("golden_synthetic")["cases"]
    by_profile: dict[str, list[list[str]]] = {name: [] for name in PROFILES}
    for case in cases:
        by_profile[typepack.get(case["type_key"]).candidate_profile].append(list(case["rows"]))
    by_profile["utility"].append(UTILITY_BILL)
    by_profile["terms"].append(TERMS)
    return by_profile


@lru_cache(maxsize=None)
def _layouts(profile: str, folder: str) -> tuple:
    return tuple(read_pdf(write_unicode_pdf(Path(folder) / f"{profile}_{i}.pdf", rows)).layout
                 for i, rows in enumerate(_documents()[profile]))


class _Jev:
    """A JEV stand-in that keeps what it was asked and answers every Choice with none and every Noul with 0.5."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def ask(self, request_id, state, questions, **_kw):
        self.sent.append((request_id, request_hash("jev-test-model", state, questions)))
        choices = {q: SimpleNamespace(choice=NONE_LABEL, confidence=0.5, probabilities={NONE_LABEL: 0.5})
                   for q, v in questions.items() if isinstance(v, Choice)}
        nouls = {q: SimpleNamespace(noul=0.5) for q, v in questions.items() if isinstance(v, Noul)}
        return SimpleNamespace(response=SimpleNamespace(choices=choices, nouls=nouls, model="jev-test"),
                               call=SimpleNamespace(request_id=request_id, cached=False))


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def select_key(key: str, folder: str) -> str:
    pack = typepack.get(key)
    jev = _Jev()
    for layout in _layouts(s_path_profile(pack), folder):  # 231 (F2c): the S path's own profile and candidates
        site_for(key).select_fields(jev, layout, find_candidates(layout, pack), run_id="select-keys-231")
    return _digest(jev.sent)


def candidate_key(profile: str, folder: str) -> str:
    found = []
    for layout in _layouts(profile, folder):
        cands = find_all(layout, profile)
        found.append({kind: [c.model_dump() if hasattr(c, "model_dump") else vars(c) for c in items]
                      for kind, items in sorted(cands.items())})
    return _digest(found)


@pytest.fixture(scope="module")
def folder(tmp_path_factory) -> str:
    return str(tmp_path_factory.mktemp("select_keys"))


def test_every_s_path_pack_and_every_profile_is_pinned():
    assert sorted(SELECT_KEYS) == S_PACKS
    assert sorted(CANDIDATE_KEYS) == sorted(PROFILES)


@pytest.mark.parametrize("key", S_PACKS)
def test_the_s_path_requests_are_unchanged(key, folder):
    assert select_key(key, folder) == SELECT_KEYS[key]


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_the_candidates_are_unchanged(profile, folder):
    assert candidate_key(profile, folder) == CANDIDATE_KEYS[profile]
