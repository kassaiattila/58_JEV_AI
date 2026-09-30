"""G-kar, 2. lépés: a generatív kivonat mezőnkénti ellenőrzése Jev Noul-okkal (SDE-cascade minta).

Munkamegosztás:
- A hallucináció-ellenőrzés KÓDBAN történik (`find_evidence`): egy érték, amelynek nincs forrás-sora, `unsupported`.
  Nem kérünk Jevtől fuzzy string-illesztést.
- Jev azt ítéli meg, amihez szemantikai megértés kell: rossz mezőhöz rendelt érték (`off_target`), csonka érték
  (`incomplete`), tévesen üresen hagyott mező (`absence_wrong`), felcserélt felek, hiányzó/többlet tételsorok.
- Minden Noul EGY kérésben megy (fan-out); a nyers P(igen) értékek változatlanul kerülnek a `JevVerdicts`-be.

Hívási-hely objektum (`VerifySite`): a típus-csomag `verify_callsite`-ja (`verify.json` a magyar, `verify_foreign.json` a
külföldi számlához; az utóbbi `inherits` kulccsal örökli a Noul-kérdéseket, csak a mező-leírásai sajátok). A modul-szintű
nevek (FIELD_SPECS, build_questions, verify, ...) a magyar számla hívási helyére mutatnak (kompatibilitás).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from typesafe_sdk import Noul

from jav import cfg
from jav.adapters.jev import JevAdapter
from jav.candidates import find_all, profile_of
from jav.jev_budget import ask_within_budget, line_numbers
from jav.models import (
    Candidate,
    DATE_NUMERIC_RE,
    DATE_TEXT_RE,
    INTL_DATE_RES,
    JevCall,
    JevVerdicts,
    LineLayout,
    money_label,
    normalize_date,
    parse_money,
)
from jav.typepack import TypePack, get as get_pack

# Országkód -> a dokumentumon nyomtatható nevek / jelek (a `country` fajta evidenciája: a kód nem a kódot, a jeleit keresi)
COUNTRY_HINTS: dict[str, tuple[str, ...]] = {
    "IE": ("ireland", "írország", "irland", "dublin", "ie8"), "US": ("usa", "united states", "u.s.a", " ca ", " ny ", " tx ", " wa "),
    "GB": ("united kingdom", "england", "london", "egyesült királyság"), "DE": ("germany", "deutschland", "németország", "gmbh"),
    "AT": ("austria", "österreich", "ausztria"), "NL": ("netherlands", "nederland", "hollandia", "b.v."), "PL": ("poland", "polska", "lengyelország", "nip"),
    "CZ": ("czech", "česk", "csehország", "praha", "a.s."), "SK": ("slovak", "slovensko", "szlovákia"), "TR": ("türkiye", "turkey", "törökország", "vergi", "vkn"),
    "EG": ("egypt", "cairo", "egyiptom"), "AU": ("australia", "ausztrália", "pty ltd", "abn"), "CH": ("switzerland", "schweiz", "svájc", "che-"),
    "FR": ("france", "franciaország"), "IT": ("italy", "italia", "olaszország"), "ES": ("spain", "españa", "spanyolország"), "HU": ("hungary", "magyarország"),
    "CA": ("canada", "kanada"), "IN": ("india",), "IL": ("israel", "izrael"), "AE": ("dubai", "united arab emirates"), "SG": ("singapore",),
    "SE": ("sweden", "sverige"), "DK": ("denmark", "danmark"), "FI": ("finland", "suomi"), "NO": ("norway", "norge"), "BE": ("belgium", "belgique", "belgië"),
    "LU": ("luxembourg",), "PT": ("portugal",), "RO": ("romania", "românia"), "UA": ("ukraine", "ukrajna"), "RS": ("serbia", "srbija"),
}
CURRENCY_EVIDENCE_RE: dict[str, str] = {
    "HUF": r"(?i)\bHUF\b|\bFt\b|\bforint\b", "EUR": r"(?i)\bEUR\b|€", "USD": r"(?i)\bUSD\b|\$", "GBP": r"(?i)\bGBP\b|£",
    "TRY": r"(?i)\bTRY\b|\bTL\b|₺", "PLN": r"(?i)\bPLN\b|zł", "CZK": r"(?i)\bCZK\b|Kč", "CHF": r"(?i)\bCHF\b", "AUD": r"(?i)\bAUD\b|A\$", "CAD": r"(?i)\bCAD\b|C\$",
}


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


_PUNCT = re.compile(r"[.,;:]")


_OCR_CONFUSIONS = str.maketrans({"l": "1", "i": "1", "|": "1", "o": "0"})


def _ocr_fold(folded: str) -> str:
    """A már összehajtott (kisbetűs) szöveg OCR-tévesztés-független alakja: l / i / | -> 1, o -> 0."""
    return folded.translate(_OCR_CONFUSIONS)


def _fold(s: str) -> str:
    """Kis/nagybetű-, whitespace- és írásjel-független ("1141, Budapest" == "1141 Budapest,")."""
    return " ".join(_PUNCT.sub(" ", s).split()).casefold()


CANDIDATE_KIND = {"name": "name", "address": "address", "iban": "iban"}  # mező-fajta -> jelölt-fajta (többsoros értékekhez)


def _candidate_hits(kind: str, value: str, cands: dict[str, list[Candidate]] | None) -> list[str]:
    """Többsoros / sortörött értékek: a jelöltkeresők már oszlop-tudatosan összefűzték őket."""
    ckind = CANDIDATE_KIND.get(kind)
    if not cands or not ckind:
        return []
    if ckind == "iban":
        target = _digits(value)
        return [c.context for c in cands.get(ckind, []) if target and _digits(c.label) == target]
    target = _fold(value)
    return [c.context for c in cands.get(ckind, []) if target and _fold(c.label) == target]


def find_evidence(
    field: str, value: str, lines: list[LineLayout], cands: dict[str, list[Candidate]] | None = None, kind: str | None = None, *, intl: bool = False
) -> list[str]:
    """Determinisztikus, toleráns illesztés: mely sorokon szerepel a kivonatolt érték. A `kind` a típus-csomag mező-fajtája
    (alap: a magyar számla mezőiből következtetve)."""
    if kind is None:
        kind = get_pack("invoice_hu").kind(field)
    hits: list[str] = _candidate_hits(kind, value, cands)
    if hits:
        return hits[:4]
    if kind in ("money", "number"):  # mennyiség (kWh, m3): ugyanaz a szám-illesztés, mint a pénzé
        targets: set[str] = set()
        try:
            targets.add(money_label(Decimal(value)))
        except (InvalidOperation, ValueError):
            pass
        raw = parse_money(value, intl=intl).value  # 054: a nyers „1.153” úgy, ahogy a rekord is érti (magyar ezres pont)
        if raw is not None:
            targets.add(money_label(raw))
        if not targets:
            return hits
        target = next(iter(targets)) if len(targets) == 1 else None
        prof = profile_of("intl" if intl else "hu")
        digits = re.sub(r"\D", "", value)
        exact: list[str] = []  # 054: a számjegyek is egyeznek („1,0000” ↔ „1.0000”, nem az „1.” sorszám) - ezek előre
        for ln in lines:
            # ugyanaz a tokenizálás, mint a jelöltkeresőben (cellahatáron nem folyik át)
            for m in prof.money_re.finditer(ln.text):
                parsed = parse_money(m.group(1), intl=intl)
                if parsed.value is not None and money_label(parsed.value) in targets:
                    (exact if re.sub(r"\D", "", m.group(1)) == digits else hits).append(f"L{ln.no:02d}: {ln.text}")
                    break
        if len(digits) >= 2:  # a pénz-tokenizáló a „1.0000”-t ezres pontnak veszi; a számjegy-pontos token is bizonyíték
            for ln in lines:
                row = f"L{ln.no:02d}: {ln.text}"
                if row not in exact and any(re.sub(r"\D", "", t) == digits for t in re.findall(r"\d(?:[\d.,]*\d)?", ln.text)):
                    exact.append(row)
        hits = exact + [h for h in hits if h not in exact]
        if not hits and target == "0" and intl and any(re.search(r"(?i)reverse\s*charge|fordított\s*áfa", ln.text) for ln in lines):
            hits = [f"L{ln.no:02d}: {ln.text}" for ln in lines if re.search(r"(?i)reverse\s*charge|fordított\s*áfa", ln.text)]
    elif kind == "date":
        target = normalize_date(value, intl=True)
        if target is None:
            return hits
        res = (DATE_NUMERIC_RE, DATE_TEXT_RE) + (INTL_DATE_RES if intl else ())
        for ln in lines:
            if any(normalize_date(m.group(0), intl=intl) == target for rx in res for m in rx.finditer(ln.text)):
                hits.append(f"L{ln.no:02d}: {ln.text}")
    elif kind in ("tax_id", "iban"):
        target = _digits(value)
        if not target:
            return hits
        for ln in lines:
            if target in _digits(ln.text) and (len(target) >= 6 or value.casefold() in ln.text.casefold()):
                hits.append(f"L{ln.no:02d}: {ln.text}")
        if not hits and re.search(r"[A-Z]", value):  # betűs azonosító (IE8256796U): a teljes token, kis/nagybetű-független
            hits = [f"L{ln.no:02d}: {ln.text}" for ln in lines if value.replace(" ", "").casefold() in ln.text.replace(" ", "").casefold()]
    elif kind == "currency":
        rx = CURRENCY_EVIDENCE_RE.get(value.upper())
        if rx:
            hits = [f"L{ln.no:02d}: {ln.text}" for ln in lines if re.search(rx, ln.text)]
    elif kind == "country":
        # következtetett mező: a bizonyíték az ország neve / jele a dokumentumon (bármely nyelven), vagy az adószám-előtag
        code = value.upper()
        needles = tuple(h for h in COUNTRY_HINTS.get(code, ())) + (f" {code.lower()} ",)
        for ln in lines:
            low = f" {ln.text.casefold()} "
            if any(n in low for n in needles) or re.search(rf"\b{code}\d{{7,12}}", ln.text):
                hits.append(f"L{ln.no:02d}: {ln.text}")
    else:
        target = _fold(value)
        if not target:
            return hits
        joined = [(ln, _fold(ln.text)) for ln in lines]
        for ln, folded in joined:
            if target in folded:
                hits.append(f"L{ln.no:02d}: {ln.text}")
        if not hits:
            # többsoros érték (pl. két sorba tört cégnév): egymás utáni sorpárok/hármasok
            for i in range(len(joined)):
                for span in (2, 3):
                    chunk = " ".join(f for _, f in joined[i : i + span])
                    if target in chunk:
                        hits.extend(f"L{ln.no:02d}: {ln.text}" for ln, _ in joined[i : i + span])
                        break
                if hits:
                    break
        if not hits:
            # 054: OCR-tévesztések (kis L / nagy I / függőleges vonal az 1-es helyett, O a 0 helyett) - mindkét oldalon
            ocr_target = _ocr_fold(target)
            hits = [f"L{ln.no:02d}: {ln.text}" for ln, folded in joined if ocr_target in _ocr_fold(folded)]
        if not hits and kind == "address":
            # cím: vesszős / többsoros tördelés - a részek külön sorokon; elfogadva, ha a részek legalább fele megvan valahol
            parts = [_fold(p) for p in re.split(r"[,;]", value) if len(_fold(p)) >= 4]
            found = [p for p in parts if any(p in folded for _, folded in joined)]
            if parts and len(found) * 2 >= len(parts):
                hits = [f"L{ln.no:02d}: {ln.text}" for ln, folded in joined if any(p in folded for p in found)]
    return hits[:4]


def _as_dict(llm: BaseModel | dict[str, Any]) -> dict[str, Any]:
    return llm if isinstance(llm, dict) else llm.model_dump()


class VerifySite:
    """Egy típus-csomag G-kar ellenőrző hívási helye: mező-leírások + Noul-kérdések (örökölhetők), `config_hash`."""

    def __init__(self, pack: TypePack) -> None:
        from jav.jev_select import site_for as select_site_for

        self.pack = pack
        self.callsite = pack.verify_callsite
        data = dict(cfg.load(f"callsite:{self.callsite}"))
        # a glosszár a select-hívási helyből jön; S-kar nélküli csomagnál (047) a saját hívási helyéből
        names = [f"callsite:{self.callsite}"] + ([f"callsite:{pack.select_callsite}"] if pack.select_callsite else [])
        parent = data.get("inherits")
        if parent:
            base = cfg.load(f"callsite:{parent}")
            data = {**{k: v for k, v in base.items() if k != "meta"}, **data}
            names.append(f"callsite:{parent}")
        self.hash_names = tuple(names)
        # 067 (066 Á18): a csomag azonosítója (típus-JSON + utasítás + séma) az alapcsomagnál is benne van
        self.config_hash = cfg.combine(cfg.config_hash(*names), pack.config_hash)
        self.request_id: str = data.get("request_id", "verify")
        self.document: str = data.get("document", "Hungarian supplier invoice")
        self.glossary: str = data["glossary"] if not pack.select_callsite else select_site_for(pack.key).glossary
        self.field_specs: dict[str, str] = dict(data["field_specs"])
        self.incomplete_fields = tuple(data["incomplete_fields"])
        self.wrong_kind_fields = tuple(data["wrong_kind_fields"])
        self.nouls: dict[str, dict[str, str]] = data["nouls"]
        self.intl = pack.candidate_profile != "hu"
        # a glosszár egyszer, a state-ben (nem minden Noul instrukciójában): sok mezős csomagnál (közmű: ~30 mező × 3 kérdés) a
        # kérés különben túllépi a Jev token-korlátját (max_tokens_exceeded); a magyar / külföldi számlánál változatlan (false)
        self.glossary_in_state: bool = bool(data.get("glossary_in_state", False))
        self.request_char_budget: int | None = data.get("request_char_budget")  # kérés-méret keret (karakter), None = nincs

    def _noul(self, name: str, **data: object) -> Noul:
        """Strukturált Noul-instrukció (sde_cascade minta, v1.1.0): egy objektum, amelyben a kérdés szövege (`question`)
        mellett a kód által épített adat áll (`field_spec`, `extracted_field`, `printed_on`), nem egy f-stringbe ragasztva."""
        t = self.nouls[name]
        glossary = {"glossary": "see state.glossary"} if self.glossary_in_state else {"glossary": self.glossary}
        instructions = {**glossary, **data, "question": t["question"]}
        return Noul(instructions=instructions, criteria={"true": t["true"], "false": t["false"]})

    def _field_spec(self, field: str) -> dict[str, str]:
        return {"name": field, "meaning": self.field_specs[field]}

    @staticmethod
    def _size(state: dict[str, Any], questions: dict[str, Noul]) -> int:
        return len(json.dumps(state, ensure_ascii=False)) + sum(len(json.dumps(q.instructions, ensure_ascii=False, default=str)) for q in questions.values())

    def _fit_budget(
        self, state: dict[str, Any], questions: dict[str, Noul], lines: list[LineLayout], evidence: dict[str, list[str]], budget: int | None
    ) -> dict[str, Any]:
        """Kérés-méret keret az ellenőrző kérésre (hívási hely `request_char_budget`, karakter; `jav/jev_budget.py`): a teljes
        dokumentum sorai csak kontextus - a Noul-ok a `printed_on` evidencia-sorokból ítélnek. Túllépésnél (1) a
        `source_lines` csak az evidencia-sorok ± 1 (a 9 oldalas Díjbeszedő-köteg: max_tokens_exceeded a teljes szöveggel),
        (2) ha az sem fér, a `source_lines` elmarad. A kérdések nem változnak."""
        if budget is None:
            budget = self.request_char_budget
        if budget is None or self._size(state, questions) <= budget:
            return state
        keep = line_numbers(evidence)
        keep = {n + d for n in keep for d in (-1, 0, 1)}
        state = {**state, "source_lines": [f"L{ln.no:02d}: {ln.text}" for ln in lines if ln.no in keep]}
        if self._size(state, questions) <= budget:
            return state
        return {k: v for k, v in state.items() if k != "source_lines"}

    def build_questions(self, llm: BaseModel | dict[str, Any], evidence: dict[str, list[str]]) -> dict[str, Noul]:
        """Mezőnkénti Noul-ok: `field_spec` + `extracted_field` (nyers érték) + `printed_on` (evidencia-sorok) + `question`."""
        d = _as_dict(llm)
        q: dict[str, Noul] = {}
        for field in self.pack.header_fields:
            value = d.get(field)
            if value is None:
                q[f"{field}__absence_wrong"] = self._noul("absence_wrong", field_spec=self._field_spec(field), extracted_field=None)
                continue
            if not evidence.get(field):
                continue  # nincs evidencia -> `unsupported`, kód döntötte, Jevet nem kérdezzük
            data = {"field_spec": self._field_spec(field), "extracted_field": value, "printed_on": list(evidence[field])}
            q[f"{field}__off_target"] = self._noul("off_target", **data)
            if field in self.wrong_kind_fields:
                q[f"{field}__wrong_kind"] = self._noul("wrong_kind", **data)
            if field in self.incomplete_fields:
                q[f"{field}__incomplete"] = self._noul("incomplete", **data)
        for name in ("parties_swapped", "line_items_missing_rows", "line_items_extra_rows"):
            q[name] = self._noul(name)
        return q

    def verify(
        self, jev: JevAdapter, lines: list[LineLayout], llm: BaseModel | dict[str, Any], *, run_id: str = "adhoc", use_cache: bool = True
    ) -> tuple[JevVerdicts, JevCall]:
        d = _as_dict(llm)
        evidence: dict[str, list[str]] = {}
        unsupported: list[str] = []
        cands = find_all(lines, self.pack.candidate_profile, text_labels=self.pack.text_labels)
        for field in self.pack.header_fields:
            value = d.get(field)
            if value is None:
                continue
            hits = find_evidence(field, str(value), lines, cands, kind=self.pack.kind(field), intl=self.intl)
            if hits:
                evidence[field] = hits
            else:
                unsupported.append(field)

        questions = self.build_questions(d, evidence)
        full_state = {
            "document": f"{self.document} {self.pack.document}" if self.pack.extends else self.document,
            **({"glossary": self.glossary} if self.glossary_in_state else {}),
            "source_lines": [f"L{ln.no:02d}: {ln.text}" for ln in lines],
            "extraction": d,
            "evidence": evidence,
        }

        def fit(budget: int | None) -> tuple[dict[str, Any], dict[str, Noul]]:
            return self._fit_budget(full_state, questions, lines, evidence, budget), questions

        result, _, _ = ask_within_budget(
            jev, self.request_id, fit, self.request_char_budget, self._size, run_id=run_id, use_cache=use_cache, config_hash=self.config_hash
        )
        response = result.response

        flags: dict[str, dict[str, float]] = {}
        doc_flags: dict[str, float] = {}
        for qid in questions:
            p = float(response.nouls[qid].noul)
            if "__" in qid:
                field, flag = qid.split("__", 1)
                flags.setdefault(field, {})[flag] = p
            else:
                doc_flags[qid] = p
        verdicts = JevVerdicts(flags=flags, doc_flags=doc_flags, unsupported=unsupported, model=getattr(response, "model", None))
        return verdicts, result.call


@lru_cache(maxsize=None)
def site_for(pack_key: str) -> VerifySite:
    return VerifySite(get_pack(pack_key))


# --- kompatibilis modul-szintű nevek: a magyar számla hívási helye ----------------------------------------------

_DEFAULT = site_for("invoice_hu")
CONFIG_HASH = _DEFAULT.config_hash
FIELD_SPECS: dict[str, str] = _DEFAULT.field_specs
INCOMPLETE_FIELDS = _DEFAULT.incomplete_fields
WRONG_KIND_FIELDS = _DEFAULT.wrong_kind_fields


def build_questions(llm: BaseModel | dict[str, Any], evidence: dict[str, list[str]], pack: TypePack | None = None) -> dict[str, Noul]:
    site = _DEFAULT if pack is None else site_for(pack.key)
    return site.build_questions(llm, evidence)


def verify(
    jev: JevAdapter, lines: list[LineLayout], llm: BaseModel | dict[str, Any], *, run_id: str = "adhoc", use_cache: bool = True, pack: TypePack | None = None
) -> tuple[JevVerdicts, JevCall]:
    """State: `{"document", "source_lines": ["Lnn: <sor>", ...], "extraction": <a kivonat szótárként>, "evidence": {mező: [sorok]}}`
    - a teljes dokumentum, mert az ellenőrző kérdések bármely mezőre hivatkozhatnak."""
    site = _DEFAULT if pack is None else site_for(pack.key)
    return site.verify(jev, lines, llm, run_id=run_id, use_cache=use_cache)
