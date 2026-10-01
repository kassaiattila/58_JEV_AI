"""S path: JEV chooses from the candidates found by code (Choice), and code normalises. Question set: the type pack's
`select_callsite` (`configs/callsites/select.json` for the Hungarian, `select_foreign.json` for the foreign invoice).

Batched requests per invoice (the call site's `requests` block: `parties`, `header`, `money`), each with a state focused
on its family: JEV gets only the lines that hold the family's candidates (± 1 line), because irrelevant context
distracts it. Within one request the questions are independent and run in parallel.

Language: the instructions and criterion descriptions are in English (in the JSON); the state and the Choice option
keys are the verbatim/normalised source value (code copies the chosen value).

Call-site object (`SelectSite`): the question set of one type pack + its `config_hash`. The module-level names
(GLOSSARY, INSTRUCTIONS, build_choice, select_fields, picks_to_invoice, ...) point to the Hungarian invoice call site
(compatibility); for other types use `site_for(pack)`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from typing import Any

from typesafe_sdk import Choice, Noul

from jav import cfg
from jav.adapters.jev import JevAdapter
from jav.candidates import MAX_OPTIONS, candidate_lines, find_currencies, payment_method_lines
from jav.candidates import TOTAL_LINE_RE as _TOTAL_LINE_RE
from jav.dates import read_date
from jav.jev_budget import ask_within_budget
from jav.models import Candidate, FieldPick, InvoiceHU, JevCall, LineLayout
from jav.numbers import is_whole_token
from jav.policy import NONE_LABEL, presence_probe_fields
from jav.typepack import CANDIDATE_KIND_OF, TypePack
from jav.typepack import get as get_pack

PRESENCE_SUFFIX = "__present"  # question id of the presence Noul: <field>__present
_DEFAULT_DOCUMENT = "Hungarian supplier invoice, selected lines (Lnn = line number)"


def _what(field: str) -> str:
    return field.replace("_", " ")


class SelectSite:
    """S-path call site of a type pack: question set from the JSON; `config_hash` = call site + pack hash."""

    def __init__(self, pack: TypePack) -> None:
        self.pack = pack
        self.callsite = pack.select_callsite
        cfg_data = cfg.load(f"callsite:{self.callsite}")
        # 067 (066 Á18): the pack's identity (type JSON + instruction + schema) is included for the default pack too
        self.config_hash = cfg.combine(cfg.config_hash(f"callsite:{self.callsite}"), pack.config_hash)
        self.glossary: str = cfg_data["glossary"]
        self.none_desc: str = cfg_data["none_description"]
        self.document: str = cfg_data.get("document", _DEFAULT_DOCUMENT)
        self.field_kind: dict[str, str] = dict(cfg_data["field_kind"])
        self.instructions: dict[str, str] = dict(cfg_data["instructions"])
        self.presence_template: str = cfg_data["presence_template"]
        self.presence_what: dict[str, str] = dict(cfg_data["presence_what"])
        self.extra: dict[str, dict[str, Any]] = dict(cfg_data["extra_questions"])
        # maximum length (chars) of the option description's context: for requests with many candidates and OCR text,
        # because of the token limit (None = full)
        self.option_context_max: int | None = cfg_data.get("option_context_max")
        # request size budget (chars), None = no budget
        self.request_char_budget: int | None = cfg_data.get("request_char_budget")
        self.requests: dict[str, dict[str, Any]] = {rid: dict(r) for rid, r in cfg_data["requests"].items()}
        self.request_order: tuple[str, ...] = tuple(self.requests)
        # the request an extra question belongs to (default: the money request; select.json v1.1.2 has no `request` key)
        money_rid = next((rid for rid in self.requests if rid.endswith("money")), self.request_order[-1])
        self.extra_request: dict[str, str] = {key: q.get("request", money_rid) for key, q in self.extra.items()}
        # an extra question that fills a pack field (currency, payment_method, reading_method...) is asked only if the
        # field is in the pack; an extra question marked `field: false` (not a field, only a signal) always goes
        self.extra_fields_known: set[str] = {key for key, q in self.extra.items() if q.get("field", True)}

    # --- question builders ---------------------------------------------------------------

    def build_choice(self, field: str, cands: list[Candidate]) -> Choice:
        criteria: dict[str, str | None] = {}
        for c in cands[:MAX_OPTIONS]:
            context = c.context if self.option_context_max is None else c.context[: self.option_context_max]
            desc = f"printed as '{c.raw}' at {context}"
            if c.ambiguous and c.kind != "date":  # 084: a date's to-do comes from code; the option text stays as it was
                desc += " (separator ambiguous)"
            criteria[c.label] = desc
        criteria[NONE_LABEL] = self.none_desc.format(what=_what(field))
        return Choice(instructions=f"{self.glossary}\n\n{self.instructions[field]}", criteria=criteria)

    def build_presence(self, field: str) -> Noul:
        """Presence Noul next to the field's Choice ("is it on the document at all"), so that the model does not
        confidently pick a wrong value when the field is not on the document (docs: function_calling / semantic_find
        pattern). Runs in the same request."""
        return Noul(instructions=f"{self.glossary}\n\n{self.presence_template.format(what=self.presence_what[field])}")

    def build_extra(self, key: str) -> Choice:
        q = self.extra[key]
        return Choice(instructions=f"{self.glossary}\n\n{q['instructions']}", criteria=dict(q["criteria"]))

    # --- requests -----------------------------------------------------------------------

    def _lines_for(self, request_id: str, lines: list[LineLayout], cands: dict[str, list[Candidate]]) -> set[int]:
        r = self.requests[request_id]
        idx = candidate_lines(lines, cands, list(r["kinds"]), margin=1)
        extra_lines = r.get("extra_lines")
        base = request_id.split("_")[-1]  # parties / header / money (without the foreign_ prefix)
        if extra_lines is None and base == "parties":
            extra_lines = {"top_fraction": 0.45}  # select.json v1.1.2 behaviour: the top 45% (the parties block)
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
        """Request size budget (call site `request_char_budget`, in chars; `budget` overrides it with the tighter budget
        of the single retry, `jav/jev_budget.py`) against JEV's request token limit (max_tokens_exceeded). When it is
        exceeded, step by step: (1) the state holds only the candidate lines of the asked fields (no margin, no top
        block), (2) the option context is shorter (80 chars), (3) the number of options per question is cut: candidates
        on total lines first, then in DOCUMENT ORDER (the candidate bucket's order is not that: names with a legal form
        come before the private person's name in the top block, and on the 9-page batch the cap of 40 cut off exactly
        the customer's name - handoff 015). The reduction shows in the raw run (`JevCall.state_chars`); the questions
        and the `none` option do not change."""
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
        # one call site can serve several packs (utility round): only this pack's fields
        fields = [f for f in self.requests[request_id]["fields"] if f in self.pack.fields]
        questions: dict[str, Choice | Noul] = {}
        probe = presence_probe_fields(self.pack)
        no_cands: list[str] = []
        for field in fields:
            items = cands.get(self.field_kind[field], [])
            if not items:
                picks[field] = FieldPick(field=field, label=None, confidence=None, n_options=0, request_id=request_id,
                                         n_candidates=0)
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
        # 069 (Á11): presence question for a field without candidates, but only in a request that goes out anyway (no
        # new call needed). JEV sees the request's lines; if the field's line is not among them, a "not present" answer
        # opens no to-do (the earlier behaviour).
        for field in no_cands:
            questions[field + PRESENCE_SUFFIX] = self.build_presence(field)

        # a call site shared by several packs (extends): the pack's own document description goes after the call
        # site's (unchanged for the other packs)
        document = f"{self.document} {self.pack.document}" if self.pack.extends else self.document
        full_state = {"document": document, "lines": _state_lines(lines, idx)}
        full_questions = questions

        def fit(budget: int | None) -> tuple[dict[str, Any], dict[str, Choice | Noul]]:
            return self._fit_budget(request_id, full_state, full_questions, lines, cands, fields, budget=budget)

        # on a token error, retry once with a tighter budget (jav/jev_budget.py); read back the questions actually sent
        result, _, questions = ask_within_budget(
            jev, request_id, fit, self.request_char_budget, self._size, run_id=run_id, use_cache=use_cache, config_hash=self.config_hash
        )
        response = result.response
        calls.append(result.call)
        for qid, q in questions.items():
            if not isinstance(q, Choice):
                continue  # the presence Nouls are read under their field
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
            # 076: distinct labels, as the options are (the Choice is keyed by label)
            n_found = len({c.label for c in cands.get(self.field_kind[qid], [])}) if qid in self.field_kind else None
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
                n_candidates=n_found,
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

    # --- normalisation ----------------------------------------------------------------------

    def picks_to_invoice(self, picks: dict[str, FieldPick], cands: dict[str, list[Candidate]],
                         lines: list[LineLayout] | None = None) -> tuple[InvoiceHU, list[str]]:
        """Label -> typed value by the pack's field kinds. `none` -> None. Consistency reasons from code (not JEV).
        081: an amount or a quantity whose printed number is flagged gets a to-do; with the document's `lines`, so does
        one whose printed form on its line is only a piece of a longer number (`money:token_cut`, the safety net
        behind the whole-number matching)."""
        by_no = {ln.no: ln.text for ln in lines or []}
        reasons: list[str] = []
        values: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        own = set(InvoiceHU.model_fields) - {"extra", "line_items"}
        for field, kind in self.pack.fields.items():
            if kind == "list":
                continue  # 053: the S path does not read itemised lists (line items go the G path)
            p = picks.get(field)
            label = p.label if p else None
            value: Any = label
            if label is not None and kind in ("money", "number"):
                cand = next((c for c in cands.get("money" if kind == "money" else "quantity", []) if c.label == label), None)
                if cand is not None and cand.ambiguous:
                    reasons.append(f"money:separator_ambiguous:{field}:{cand.raw!r}")
                if cand is not None and cand.line_no in by_no and not is_whole_token(cand.raw, by_no[cand.line_no]):
                    reasons.append(f"money:token_cut:{field}:{cand.raw!r}")
                value = Decimal(label)  # number: the number finder's normalised label (quantity: kWh, m3, MJ)
            elif label is not None and kind == "date":
                value = read_date(label).value  # the candidate's label is the reader's ISO date
                cand = next((c for c in cands.get("date", []) if c.label == label), None)
                if cand is not None and cand.ambiguous:  # 084: the day and the month can be read two ways
                    reasons.append(f"date:order_ambiguous:{field}:{cand.raw!r}")
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
    """The field's effective confidence = the weaker of the Choice and the presence verdict: P(present) for a chosen
    value, P(not present) for `none`. Without a presence verdict, the Choice confidence; without candidates (no Choice),
    None."""
    if pick.confidence is None:
        return None
    if pick.present_p is None:
        return round(pick.confidence, 4)
    agree = pick.present_p if pick.label is not None else 1.0 - pick.present_p
    return round(min(pick.confidence, agree), 4)


def record_conf(picks: dict[str, FieldPick]) -> float | None:
    """Record confidence = the weakest JEV verdict among the fields (fields without candidates are not verdicts)."""
    vals = [c for c in (effective_conf(p) for p in picks.values() if p.n_options > 0) if c is not None]
    return min(vals) if vals else None


def field_confidence(picks: dict[str, FieldPick]) -> dict[str, float | None]:
    """069 (Á11): the field confidence that is stored and shown in the interface: the effective confidence (computed
    together with the presence verdict); None for a field without candidates ("no estimate"; formerly 1.0 =
    "Confident")."""
    return {f: effective_conf(p) for f, p in picks.items()}


# --- compatible module-level names: the Hungarian invoice call site ---------------------------------------------

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
    """State: `{"document": <the pack's document description>, "lines": ["Lnn: <line>", ...]}`: the candidate lines of
    the request's family (± 1); for the parties request also the top 45% of the document (and the bottom lines if the
    pack says so), for the money request the payment-method lines."""
    return _DEFAULT._select_request(*args, **kwargs)


def select_fields(
    jev: JevAdapter, lines: list[LineLayout], cands: dict[str, list[Candidate]], *, run_id: str = "adhoc", use_cache: bool = True, pack: TypePack | None = None
) -> tuple[dict[str, FieldPick], list[JevCall]]:
    site = _DEFAULT if pack is None else site_for(pack.key)
    return site.select_fields(jev, lines, cands, run_id=run_id, use_cache=use_cache)


def picks_to_invoice(picks: dict[str, FieldPick], cands: dict[str, list[Candidate]], pack: TypePack | None = None,
                     lines: list[LineLayout] | None = None) -> tuple[InvoiceHU, list[str]]:
    site = _DEFAULT if pack is None else site_for(pack.key)
    return site.picks_to_invoice(picks, cands, lines)


__all__ = ["GLOSSARY", "PRESENCE_WHAT", "SelectSite", "site_for", "build_choice", "build_presence", "effective_conf", "record_conf", "field_confidence",
           "picks_to_invoice", "select_fields", "find_currencies", "CANDIDATE_KIND_OF"]
