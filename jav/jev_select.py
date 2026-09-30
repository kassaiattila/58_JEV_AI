"""S-kar: Jev választ a kód által talált jelöltek közül (Choice), a kód normalizál. Kérdéskészlet: a típus-csomag
`select_callsite`-ja (`configs/callsites/select.json` a magyar, `select_foreign.json` a külföldi számlához).

Kötegelt kérések számlánként (a hívási-hely `requests` blokkja: `parties`, `header`, `money`), családonként fókuszált
state-tel: a Jev-nek csak azok a sorok mennek, ahol az adott család jelöltjei vannak (± 1 sor), mert az irreleváns
kontextus elterel. Egy kérésen belül a kérdések függetlenek és párhuzamosan futnak.

Nyelv: az instrukciók és a kritérium-leírások angolul (a JSON-ban), a state és a Choice-opció kulcsai szó
szerinti/normalizált forrásérték (a kiválasztott értéket kód másolja).

Hívási-hely objektum (`SelectSite`): egy típus-csomaghoz tartozó kérdéskészlet + a hozzá tartozó `config_hash`. A
modul-szintű nevek (GLOSSARY, INSTRUCTIONS, build_choice, select_fields, picks_to_invoice, ...) a magyar számla
hívási helyére mutatnak (kompatibilitás); más típusnál `site_for(pack)`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from typing import Any

from typesafe_sdk import Choice, Noul

from jav import cfg
from jav.adapters.jev import JevAdapter
from jav.candidates import MAX_OPTIONS, TOTAL_LINE_RE as _TOTAL_LINE_RE, candidate_lines, find_currencies, payment_method_lines
from jav.jev_budget import ask_within_budget
from jav.models import Candidate, FieldPick, InvoiceHU, JevCall, LineLayout, normalize_date
from jav.policy import NONE_LABEL, presence_probe_fields
from jav.typepack import CANDIDATE_KIND_OF, TypePack, get as get_pack

PRESENCE_SUFFIX = "__present"  # a jelenlét-Noul kérdés-azonosítója: <mező>__present
_DEFAULT_DOCUMENT = "Hungarian supplier invoice, selected lines (Lnn = line number)"


def _what(field: str) -> str:
    return field.replace("_", " ")


class SelectSite:
    """Egy típus-csomag S-kar hívási helye: a kérdéskészlet a JSON-ból, a `config_hash` a hívási hely + a csomag hash-e."""

    def __init__(self, pack: TypePack) -> None:
        self.pack = pack
        self.callsite = pack.select_callsite
        cfg_data = cfg.load(f"callsite:{self.callsite}")
        # 067 (066 Á18): a csomag azonosítója (típus-JSON + utasítás + séma) az alapcsomagnál is benne van
        self.config_hash = cfg.combine(cfg.config_hash(f"callsite:{self.callsite}"), pack.config_hash)
        self.glossary: str = cfg_data["glossary"]
        self.none_desc: str = cfg_data["none_description"]
        self.document: str = cfg_data.get("document", _DEFAULT_DOCUMENT)
        self.field_kind: dict[str, str] = dict(cfg_data["field_kind"])
        self.instructions: dict[str, str] = dict(cfg_data["instructions"])
        self.presence_template: str = cfg_data["presence_template"]
        self.presence_what: dict[str, str] = dict(cfg_data["presence_what"])
        self.extra: dict[str, dict[str, Any]] = dict(cfg_data["extra_questions"])
        # az opció-leírás kontextusának felső hossza (karakter): sok jelöltű, OCR-szövegű kérésnél a token-korlát miatt (None = teljes)
        self.option_context_max: int | None = cfg_data.get("option_context_max")
        self.request_char_budget: int | None = cfg_data.get("request_char_budget")  # kérés-méret keret (karakter), None = nincs
        self.requests: dict[str, dict[str, Any]] = {rid: dict(r) for rid, r in cfg_data["requests"].items()}
        self.request_order: tuple[str, ...] = tuple(self.requests)
        # melyik kérésbe tartozik egy extra kérdés (alap: a money kérés - a select.json v1.1.2-ben nincs `request` kulcs)
        money_rid = next((rid for rid in self.requests if rid.endswith("money")), self.request_order[-1])
        self.extra_request: dict[str, str] = {key: q.get("request", money_rid) for key, q in self.extra.items()}
        # extra kérdés, amely egy csomag-mezőt tölt (currency, payment_method, reading_method...): csak akkor kérdezzük, ha a mező a csomagban van;
        # a `field: false` jelölésű extra kérdés (nem mező, csak jel) mindig megy
        self.extra_fields_known: set[str] = {key for key, q in self.extra.items() if q.get("field", True)}

    # --- kérdés-építők -------------------------------------------------------------------

    def build_choice(self, field: str, cands: list[Candidate]) -> Choice:
        criteria: dict[str, str | None] = {}
        for c in cands[:MAX_OPTIONS]:
            context = c.context if self.option_context_max is None else c.context[: self.option_context_max]
            desc = f"printed as '{c.raw}' at {context}"
            if c.ambiguous:
                desc += " (separator ambiguous)"
            criteria[c.label] = desc
        criteria[NONE_LABEL] = self.none_desc.format(what=_what(field))
        return Choice(instructions=f"{self.glossary}\n\n{self.instructions[field]}", criteria=criteria)

    def build_presence(self, field: str) -> Noul:
        """Jelenlét-Noul a mező Choice-a mellé: „szerepel-e egyáltalán” - hogy a modell ne válasszon magabiztosan rosszat,
        ha a mező nincs is a dokumentumon (doksi: function_calling / semantic_find minta). Ugyanabban a kérésben fut."""
        return Noul(instructions=f"{self.glossary}\n\n{self.presence_template.format(what=self.presence_what[field])}")

    def build_extra(self, key: str) -> Choice:
        q = self.extra[key]
        return Choice(instructions=f"{self.glossary}\n\n{q['instructions']}", criteria=dict(q["criteria"]))

    # --- kérések ------------------------------------------------------------------------

    def _lines_for(self, request_id: str, lines: list[LineLayout], cands: dict[str, list[Candidate]]) -> set[int]:
        r = self.requests[request_id]
        idx = candidate_lines(lines, cands, list(r["kinds"]), margin=1)
        extra_lines = r.get("extra_lines")
        base = request_id.split("_")[-1]  # parties / header / money (a foreign_ előtag nélkül)
        if extra_lines is None and base == "parties":
            extra_lines = {"top_fraction": 0.45}  # a select.json v1.1.2 viselkedése: a felső 45 % (a felek blokkja)
        if extra_lines:
            if extra_lines.get("top_fraction"):
                idx |= set(range(0, max(1, int(len(lines) * float(extra_lines["top_fraction"])))))
            if extra_lines.get("bottom_lines"):
                idx |= set(range(max(0, len(lines) - int(extra_lines["bottom_lines"])), len(lines)))
        if base == "money":
            idx |= set(payment_method_lines(lines))
        return idx

    @staticmethod
    def _size(state: dict[str, Any], questions: dict[str, Choice | Noul]) -> int:
        n = len(json.dumps(state, ensure_ascii=False))
        for q in questions.values():
            if isinstance(q, Choice):
                n += sum(len(k) + len(v or "") for k, v in q.criteria.items()) + len(q.instructions)
            else:
                n += len(q.instructions) if isinstance(q.instructions, str) else len(json.dumps(q.instructions, ensure_ascii=False))
        return n

    def _fit_budget(
        self,
        request_id: str,
        state: dict[str, Any],
        questions: dict[str, Choice | Noul],
        lines: list[LineLayout],
        cands: dict[str, list[Candidate]],
        fields: list[str],
        budget: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Choice | Noul]]:
        """Kérés-méret keret (hívási hely `request_char_budget`, karakter; `budget` felülírja - az egyszeri újrapróbálás szűkebb
        kerete, `jav/jev_budget.py`): a Jev kérés token-korlátja (max_tokens_exceeded) ellen. Túllépésnél fokozatosan: (1) a
        state csak a kérdezett mezők jelölt-sorai (margó nélkül, felső blokk nélkül), (2) az opció-kontextus rövidebb (80
        karakter), (3) az opciók száma kérdésenként csökkentve: az összesítő-sorok jelöltjei elöl, utána DOKUMENTUM-SORRENDBEN
        (a jelölt-vödör sorrendje nem az: a jogi formás nevek megelőzik a felső blokk magánszemély-nevét, és a 9 oldalas
        kötegnél a 40-es sapka épp az ügyfél nevét vágta le - handoff 015). A csökkentés a nyers futásban látszik
        (`JevCall.state_chars`), a kérdések és a `none` opció nem változnak."""
        if budget is None:
            budget = self.request_char_budget
        if budget is None or self._size(state, questions) <= budget:
            return state, questions
        idx = candidate_lines(lines, cands, [self.field_kind[f] for f in fields if f in self.field_kind], margin=0)
        state = {**state, "lines": _state_lines(lines, idx)}
        if self._size(state, questions) <= budget:
            return state, questions
        for ctx_max, cap in ((80, None), (80, 60), (60, 40), (40, 25)):
            trimmed: dict[str, Choice | Noul] = {}
            for qid, q in questions.items():
                if isinstance(q, Choice) and qid in self.field_kind:
                    items = cands.get(self.field_kind[qid], [])
                    if cap is not None and len(items) > cap:
                        priority = [c for c in items if _TOTAL_LINE_RE.search(lines[c.line_no - 1].text)]
                        rest = sorted((c for c in items if c not in priority), key=lambda c: c.line_no)
                        items = (priority + rest)[:cap]
                    trimmed[qid] = self._build_choice_ctx(qid, items, ctx_max)
                else:
                    trimmed[qid] = q
            questions = trimmed
            if self._size(state, questions) <= budget:
                break
        return state, questions

    def _build_choice_ctx(self, field: str, cands: list[Candidate], ctx_max: int) -> Choice:
        saved = self.option_context_max
        self.option_context_max = ctx_max
        try:
            return self.build_choice(field, cands)
        finally:
            self.option_context_max = saved

    def _select_request(
        self,
        jev: JevAdapter,
        request_id: str,
        lines: list[LineLayout],
        cands: dict[str, list[Candidate]],
        picks: dict[str, FieldPick],
        calls: list[JevCall],
        *,
        run_id: str,
        use_cache: bool,
    ) -> None:
        fields = [f for f in self.requests[request_id]["fields"] if f in self.pack.fields]  # egy hívási hely több csomagot szolgálhat (közmű-kör): csak a csomag mezői
        questions: dict[str, Choice | Noul] = {}
        probe = presence_probe_fields(self.pack)
        no_cands: list[str] = []
        for field in fields:
            items = cands.get(self.field_kind[field], [])
            if not items:
                picks[field] = FieldPick(field=field, label=None, confidence=None, n_options=0, request_id=request_id)
                if field in probe:
                    no_cands.append(field)
                continue
            questions[field] = self.build_choice(field, items)
            questions[field + PRESENCE_SUFFIX] = self.build_presence(field)

        idx = self._lines_for(request_id, lines, cands)
        for key, rid in self.extra_request.items():
            if rid == request_id and (key in self.pack.fields or key not in self.extra_fields_known):
                questions[key] = self.build_extra(key)
        if not questions:
            return
        # 069 (Á11): jelölt nélküli mező jelenlét-kérdése, de csak az amúgy is elmenő kérésben (új hívás nem kell). A JEV
        # a kérés sorait látja; ha a mező sora nincs köztük, a „nincs” válasz nem nyit teendőt (a korábbi viselkedés).
        for field in no_cands:
            questions[field + PRESENCE_SUFFIX] = self.build_presence(field)

        # közös hívási hely több csomaghoz (extends): a csomag saját dokumentum-leírása a hívási helyé mögé kerül (a többi csomagnál változatlan)
        document = f"{self.document} {self.pack.document}" if self.pack.extends else self.document
        full_state = {"document": document, "lines": _state_lines(lines, idx)}
        full_questions = questions

        def fit(budget: int | None) -> tuple[dict[str, Any], dict[str, Choice | Noul]]:
            return self._fit_budget(request_id, full_state, full_questions, lines, cands, fields, budget=budget)

        # token-hibánál egyszer újra, szűkebb kerettel (jav/jev_budget.py); a ténylegesen elküldött kérdéskészletet olvassuk ki
        result, _, questions = ask_within_budget(
            jev, request_id, fit, self.request_char_budget, self._size, run_id=run_id, use_cache=use_cache, config_hash=self.config_hash
        )
        response = result.response
        calls.append(result.call)
        for qid, q in questions.items():
            if not isinstance(q, Choice):
                continue  # a jelenlét-Noulokat a mezőjük alatt olvassuk ki
            ans = response.choices[qid]
            label = None if ans.choice == NONE_LABEL else ans.choice
            raw = None
            line_no = None
            if label is not None and qid in self.field_kind:
                cand = next((c for c in cands.get(self.field_kind[qid], []) if c.label == label), None)
                raw = cand.raw if cand else label
                line_no = cand.line_no if cand else None
            elif label is not None:
                raw = label
            presence = response.nouls.get(qid + PRESENCE_SUFFIX) if qid + PRESENCE_SUFFIX in questions else None
            picks[qid] = FieldPick(
                field=qid,
                label=label,
                raw=raw,
                confidence=float(ans.confidence),
                probabilities={k: float(v) for k, v in dict(ans.probabilities).items()},
                n_options=len(q.criteria) - 1,
                request_id=request_id,
                present_p=None if presence is None else round(float(presence.noul), 4),
                line_no=line_no,
            )
        for field in no_cands:
            presence = response.nouls.get(field + PRESENCE_SUFFIX) if field + PRESENCE_SUFFIX in questions else None
            if presence is not None:
                picks[field] = picks[field].model_copy(update={"present_p": round(float(presence.noul), 4)})

    def select_fields(
        self, jev: JevAdapter, lines: list[LineLayout], cands: dict[str, list[Candidate]], *, run_id: str = "adhoc", use_cache: bool = True
    ) -> tuple[dict[str, FieldPick], list[JevCall]]:
        picks: dict[str, FieldPick] = {}
        calls: list[JevCall] = []
        for request_id in self.request_order:
            self._select_request(jev, request_id, lines, cands, picks, calls, run_id=run_id, use_cache=use_cache)
        return picks, calls

    # --- normalizálás -----------------------------------------------------------------------

    def picks_to_invoice(self, picks: dict[str, FieldPick], cands: dict[str, list[Candidate]]) -> tuple[InvoiceHU, list[str]]:
        """Label -> típusos érték a csomag mező-fajtái szerint. `none` -> None. Kód-oldali konzisztencia-okok (nem Jev)."""
        reasons: list[str] = []
        values: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        own = set(InvoiceHU.model_fields) - {"extra", "line_items"}
        for field, kind in self.pack.fields.items():
            if kind == "list":
                continue  # 053: tételes listát az S-kar nem olvas (a tétel a G-kar útja)
            p = picks.get(field)
            label = p.label if p else None
            value: Any = label
            if label is not None and kind == "money":
                cand = next((c for c in cands.get("money", []) if c.label == label), None)
                if cand is not None and cand.ambiguous:
                    reasons.append(f"money:separator_ambiguous:{field}:{cand.raw!r}")
                value = Decimal(label)
            elif label is not None and kind == "date":
                value = normalize_date(label)
            elif label is not None and kind == "number":
                value = Decimal(label)  # a szám-kereső normalizált címkéje (mennyiség: kWh, m3, MJ)
            elif label is not None and kind in ("currency", "country"):
                value = label.upper()
            if field in own:
                values[field] = value
            else:
                extra[field] = value
        inv = InvoiceHU(**values, extra=extra)
        if inv.supplier_tax_id and inv.supplier_tax_id == inv.buyer_tax_id:
            reasons.append("parties:same_tax_id")
        if inv.supplier_name and inv.supplier_name == inv.buyer_name:
            reasons.append("parties:same_name")
        return inv, reasons


@lru_cache(maxsize=None)
def site_for(pack_key: str) -> SelectSite:
    return SelectSite(get_pack(pack_key))


def _state_lines(lines: list[LineLayout], idx: set[int]) -> list[str]:
    return [f"L{lines[i].no:02d}: {lines[i].text}" for i in sorted(idx)]


def effective_conf(pick: FieldPick) -> float | None:
    """A mező tényleges confidence-e = a Choice és a jelenlét-ítélet gyengébbike: választott érték mellett P(szerepel),
    `none` mellett P(nem szerepel). Jelenlét-ítélet nélkül a Choice confidence; jelölt nélkül (nincs Choice) None."""
    if pick.confidence is None:
        return None
    if pick.present_p is None:
        return round(pick.confidence, 4)
    agree = pick.present_p if pick.label is not None else 1.0 - pick.present_p
    return round(min(pick.confidence, agree), 4)


def record_conf(picks: dict[str, FieldPick]) -> float | None:
    """Rekord-confidence = a leggyengébb Jev-ítélet a mezők közt (a jelölt nélküli mezők nem ítéletek)."""
    vals = [c for c in (effective_conf(p) for p in picks.values() if p.n_options > 0) if c is not None]
    return min(vals) if vals else None


def field_confidence(picks: dict[str, FieldPick]) -> dict[str, float | None]:
    """069 (Á11): a tárolt és a felületen látszó mező-bizonyosság: a tényleges (a jelenlét-ítélettel együtt számolt)
    bizonyosság; jelölt nélküli mezőnél None („nincs becslés”, eddig 1,0 = „Magabiztos”)."""
    return {f: effective_conf(p) for f, p in picks.items()}


# --- kompatibilis modul-szintű nevek: a magyar számla hívási helye ----------------------------------------------

_DEFAULT = site_for("invoice_hu")
CONFIG_HASH = _DEFAULT.config_hash
GLOSSARY: str = _DEFAULT.glossary
FIELD_KIND: dict[str, str] = _DEFAULT.field_kind
INSTRUCTIONS: dict[str, str] = _DEFAULT.instructions
PRESENCE_TEMPLATE: str = _DEFAULT.presence_template
PRESENCE_WHAT: dict[str, str] = _DEFAULT.presence_what
CURRENCY_CRITERIA: dict[str, str] = dict(_DEFAULT.extra["currency"]["criteria"])
CURRENCY_INSTRUCTION: str = _DEFAULT.extra["currency"]["instructions"]
PAYMENT_METHOD_CRITERIA: dict[str, str] = dict(_DEFAULT.extra["payment_method"]["criteria"])
PAYMENT_METHOD_INSTRUCTION: str = _DEFAULT.extra["payment_method"]["instructions"]
REQUEST_FIELDS: dict[str, list[str]] = {rid: list(r["fields"]) for rid, r in _DEFAULT.requests.items()}
REQUEST_KINDS: dict[str, list[str]] = {rid: list(r["kinds"]) for rid, r in _DEFAULT.requests.items()}
REQUEST_ORDER: tuple[str, ...] = _DEFAULT.request_order


def build_choice(field: str, cands: list[Candidate]) -> Choice:
    return _DEFAULT.build_choice(field, cands)


def build_presence(field: str) -> Noul:
    return _DEFAULT.build_presence(field)


def _select_request(*args: Any, **kwargs: Any) -> None:
    """State: `{"document": <a csomag dokumentum-leírása>, "lines": ["Lnn: <sor>", ...]}` - a kérés családjának jelölt-sorai
    (± 1), a felek kérésénél a dokumentum felső 45 %-a (és a csomag szerint az alsó sorok), a pénz-kérésnél a fizetési-mód sorok."""
    return _DEFAULT._select_request(*args, **kwargs)


def select_fields(
    jev: JevAdapter, lines: list[LineLayout], cands: dict[str, list[Candidate]], *, run_id: str = "adhoc", use_cache: bool = True, pack: TypePack | None = None
) -> tuple[dict[str, FieldPick], list[JevCall]]:
    site = _DEFAULT if pack is None else site_for(pack.key)
    return site.select_fields(jev, lines, cands, run_id=run_id, use_cache=use_cache)


def picks_to_invoice(picks: dict[str, FieldPick], cands: dict[str, list[Candidate]], pack: TypePack | None = None) -> tuple[InvoiceHU, list[str]]:
    site = _DEFAULT if pack is None else site_for(pack.key)
    return site.picks_to_invoice(picks, cands)


__all__ = ["GLOSSARY", "PRESENCE_WHAT", "SelectSite", "site_for", "build_choice", "build_presence", "effective_conf", "record_conf", "field_confidence",
           "picks_to_invoice", "select_fields", "find_currencies", "CANDIDATE_KIND_OF"]
