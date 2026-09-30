"""Típusfüggetlen, forrásos adatpontok: javaslat és ellenőrzés külön állapot."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jav import store
from jav.config import PROJECT_ROOT
from jav.grounded_claims import GroundedClaim, verify_claim


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_config() -> dict:
    directory = PROJECT_ROOT / "configs/experiments"
    config = json.loads((directory / "document_learning.json").read_text(encoding="utf-8"))
    config["claims"] = json.loads((directory / "grounded_structure.json").read_text(encoding="utf-8"))["claims"]
    return config


class PointProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=200)
    raw_value: str = Field(min_length=1, max_length=300)
    unit: str | None = Field(default=None, max_length=40)
    entity_id: str | None = Field(default=None, max_length=80)
    quote: str = Field(min_length=1, max_length=4000)
    start: int | None = Field(default=None, ge=0)
    context_quote: str | None = Field(default=None, min_length=1, max_length=8000)


class ProposalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    doc_kind_guess: str | None = Field(default=None, max_length=150)
    method: str = Field(default="imported_proposals", min_length=1, max_length=100)
    points: list[PointProposal] = Field(max_length=64)
    generation: dict | None = None
    omitted_candidates: int = Field(default=0, ge=0)


class GeneratedPoints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_kind_guess: str | None = Field(default=None, max_length=150)
    points: list[PointProposal] = Field(max_length=64)


def resolve_literal_spans(text: str, batch: ProposalBatch) -> tuple[ProposalBatch, list[dict]]:
    """Opt-in javítás: egyetlen szó szerinti idézet hibás modellpozícióját helyreállítja.

    Szöveg, érték és szerep nem változhat; ismétlődő vagy módosított idézetet
    nem oldunk fel találgatással. Az eredeti javaslat és a változáslista megőrzendő.
    """
    if digest(text)!=batch.source_sha256:
        raise ValueError('proposal source mismatch')
    points=[]
    changes=[]
    for index,point in enumerate(batch.points):
        start=point.start
        if start is not None and text[start:start+len(point.quote)]!=point.quote:
            found=text.find(point.quote)
            if found>=0 and text.find(point.quote,found+1)<0:
                changes.append({'point_index':index,'old_start':start,'new_start':found,'reason':'unique_exact_quote'})
                point=point.model_copy(update={'start':found})
        points.append(point)
    return batch.model_copy(update={'points':points}),changes


def contextual_position(text: str, point: PointProposal) -> tuple[int | None, str | None]:
    """Egyedi szó szerinti környezet és azon belül egyedi idézet; nincs első-találat döntés."""
    context = point.context_quote
    if context is None:
        first = text.find(point.quote)
        if first >= 0 and text.find(point.quote, first + 1) >= 0:
            return None, 'ambiguous_quote'
        return (first, None) if first >= 0 else (None, 'invalid_quote')
    outer = text.find(context)
    inner = context.find(point.quote)
    if outer < 0 or inner < 0:
        return None, 'invalid_context'
    if text.find(context, outer + 1) >= 0 or context.find(point.quote, inner + 1) >= 0:
        return None, 'ambiguous_quote'
    return outer + inner, None


def resolve_context_spans(text: str, batch: ProposalBatch, *, expand_exact_context=False,
                          context_ranges=None) -> tuple[ProposalBatch, list[dict]]:
    if digest(text) != batch.source_sha256:
        raise ValueError('proposal source mismatch')
    points, changes = [], []
    for index, point in enumerate(batch.points):
        if expand_exact_context and point.context_quote is not None:
            context=point.context_quote
            left=text.find(context)
            quote_start=text.find(point.quote)
            if (left>=0 and quote_start>=0 and point.quote not in context
                    and text.find(context,left+1)<0 and text.find(point.quote,quote_start+1)<0):
                begin,end=min(left,quote_start),max(left+len(context),quote_start+len(point.quote))
                ranges=context_ranges if context_ranges is not None else [(0,len(text))]
                if end-begin<=8000 and any(a<=begin<end<=b for a,b in ranges):
                    expanded=text[begin:end]
                    candidate=point.model_copy(update={'context_quote':expanded})
                    if contextual_position(text,candidate)[1] is None:
                        changes.append(dict(point_index=index,old_context=context,new_context=expanded,
                                            reason='expanded_exact_context'))
                        point=candidate
        start, error = contextual_position(text, point)
        if error is None and start != point.start:
            changes.append(dict(point_index=index, old_start=point.start, new_start=start,
                                reason='unique_exact_context' if point.context_quote else 'unique_exact_quote'))
            point = point.model_copy(update={'start': start})
        points.append(point)
    return batch.model_copy(update={'points': points}), changes


def propose(text: str, *, model, config: dict, run_id: str = "adhoc") -> ProposalBatch:
    """Explicit modellfüggőség; nincs automatikus szolgáltatóválasztás vagy adatküldés."""
    from pydantic_ai import Agent
    from pydantic_ai.usage import UsageLimits
    if not text.strip() or len(text) > config["max_text_chars"]:
        raise ValueError("source empty or exceeds explicit context limit")
    agent = Agent(model,output_type=GeneratedPoints,instructions=config["proposal_instructions"],retries=0,
                  model_settings=config.get("proposal_model_settings"))
    started = time.perf_counter()
    provider = model.split(":",1)[0] if isinstance(model,str) else getattr(model,"system","unknown")
    config_hash = digest(json.dumps(config,sort_keys=True,ensure_ascii=False))
    try:
        result = agent.run_sync(text,usage_limits=UsageLimits(request_limit=config["proposal_request_limit"]))
    except Exception as exc:
        store.ledger_add(run_id=run_id,step="generic_propose",provider=provider,model=str(getattr(model,"model_name",model)),
                         input_tokens=None,output_tokens=None,cost_usd=None,seconds=time.perf_counter()-started,
                         config_hash=config_hash,error=type(exc).__name__)
        raise
    usage = result.usage() if callable(result.usage) else result.usage
    from jav.config import OPENAI_USD_PER_MTOK
    price_key = result.response.model_name
    requested = model.split(":",1)[-1] if isinstance(model,str) else str(getattr(model,"model_name",""))
    if (price_key not in OPENAI_USD_PER_MTOK and requested in OPENAI_USD_PER_MTOK
            and re.fullmatch(re.escape(requested)+r"-\d{4}-\d{2}-\d{2}",price_key)):
        price_key = requested
    price = OPENAI_USD_PER_MTOK.get(price_key) if provider == "openai" else None
    cost = (round(((usage.input_tokens or 0)*price[0]+(usage.output_tokens or 0)*price[1])/1_000_000,6)
            if price else 0.0 if provider == "test" else None)
    store.ledger_add(run_id=run_id,step="generic_propose",provider=provider,model=result.response.model_name,
                     input_tokens=usage.input_tokens,output_tokens=usage.output_tokens,cost_usd=cost,
                     seconds=time.perf_counter()-started,config_hash=config_hash)
    if len(result.output.points) > config["max_points"]:
        raise ValueError("proposal count exceeds configured limit")
    return ProposalBatch(source_sha256=digest(text),doc_kind_guess=result.output.doc_kind_guess,
        method="pydantic_ai",points=result.output.points,generation={
            "model":result.response.model_name,"input_tokens":usage.input_tokens,"output_tokens":usage.output_tokens,
            "messages":json.loads(result.all_messages_json()),
            "config_hash":config_hash,"cost_usd":cost,"price_model":price_key if price else None})


def propose_labels(text: str, config: dict) -> ProposalBatch:
    """Helyi alapmódszer címke: érték sorokra; nem általános szemantikai kivonatoló."""
    if not text.strip() or len(text) > config["max_text_chars"]:
        raise ValueError("source empty or exceeds explicit context limit")
    pattern = re.compile(config["label_pattern"])
    points, offset = [], 0
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        match = pattern.fullmatch(line)
        if match:
            points.append(PointProposal(name=f"field_{len(points)+1:04d}",role=match["label"].strip(),
                                        raw_value=match["value"].strip(),quote=line,start=offset))
        offset += len(raw)
    limit = config["max_points"]
    return ProposalBatch(source_sha256=digest(text),method="labelled_lines",points=points[:limit],
                         omitted_candidates=max(0,len(points)-limit))


class CheckedPoint(BaseModel):
    proposal: PointProposal
    start: int | None = None
    end: int | None = None
    verification: dict


class GenericResult(BaseModel):
    source_sha256: str
    config_hash: str
    method: str
    doc_kind_guess: str | None
    type_status: Literal["unknown", "unconfirmed_guess"]
    completeness: Literal["not_established"] = "not_established"
    generation: dict | None = None
    omitted_candidates: int = 0
    points: list[CheckedPoint]


def check_proposals(text: str, proposals: ProposalBatch, ask, config: dict) -> GenericResult:
    if digest(text) != proposals.source_sha256:
        raise ValueError("proposal source mismatch")
    if not text.strip() or len(text) > min(config["max_text_chars"], config["claims"]["max_context_chars"]):
        raise ValueError("source empty or exceeds explicit context limit")
    if len(proposals.points) > config["max_points"]:
        raise ValueError("proposal count exceeds configured limit")
    points = []
    unavailable = False
    for point in proposals.points:
        pattern = config.get('field_patterns', {}).get(point.name)
        if pattern is not None and re.fullmatch(pattern, point.raw_value) is None:
            points.append(CheckedPoint(proposal=point, verification={
                'status':'invalid_value', 'reason':'requested_field_format', 'response':None}))
            continue
        start = point.start
        if config.get('resolve_context_spans', False) or point.context_quote is not None:
            located, error = contextual_position(text, point)
            if error is not None or (start is not None and start != located):
                points.append(CheckedPoint(proposal=point, verification={
                    'status': error or 'invalid_context', 'response': None}))
                continue
            start = located
        if start is None:
            start = text.find(point.quote)
            if start >= 0 and text.find(point.quote, start + 1) >= 0:
                points.append(CheckedPoint(proposal=point, verification={"status":"ambiguous_quote", "response":None}))
                continue
        if start < 0 or text[start:start + len(point.quote)] != point.quote:
            points.append(CheckedPoint(proposal=point, verification={"status":"invalid_quote", "response":None}))
            continue
        end = start + len(point.quote)
        if unavailable:
            checked = {"status":"not_checked", "reason":"provider_unavailable", "response":None}
        else:
            fact = point.model_dump(include={"name", "role", "raw_value", "unit", "entity_id"})
            statement = config["claim_template"].format(point=json.dumps(fact,ensure_ascii=False))
            if len(statement) > 1000:
                points.append(CheckedPoint(proposal=point,start=start,end=end,
                                          verification={"status":"claim_limit", "response":None}))
                continue
            claim = GroundedClaim(statement=statement,source_sha256=proposals.source_sha256,start=start,end=end,quote=point.quote)
            checked = verify_claim(text, claim, config["claims"], ask)
            unavailable = checked["status"] == "unavailable"
        points.append(CheckedPoint(proposal=point,start=start,end=end,verification=checked))
    return GenericResult(source_sha256=proposals.source_sha256,method=proposals.method,
        config_hash=digest(json.dumps(config,sort_keys=True,ensure_ascii=False)),doc_kind_guess=proposals.doc_kind_guess,
        type_status="unconfirmed_guess" if proposals.doc_kind_guess else "unknown",points=points,
        generation=proposals.generation,omitted_candidates=proposals.omitted_candidates)


def save_result(run_id: str, result: GenericResult) -> None:
    store.save_artifact("generic_extraction",run_id,result.model_dump(mode="json"))


def load_result(run_id: str) -> GenericResult | None:
    value = store.load_artifact("generic_extraction",run_id)
    return GenericResult.model_validate(value) if value is not None else None
