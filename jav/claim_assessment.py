"""Kísérleti állításvizsgálat: szerep/állapot külön, a forrás és a helyesség nem azonos."""
from __future__ import annotations

import json
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jav.config import PROJECT_ROOT
from jav.document_learning import digest
from jav.learning_runtime import canonical_hash


def load_config():
    return json.loads((PROJECT_ROOT / 'configs/experiments/claim_assessment.json').read_text(encoding='utf-8'))


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: str = Field(min_length=1, max_length=300)
    value: str = Field(min_length=1, max_length=300)
    unit: str | None = Field(default=None, max_length=40)
    entity: str | None = Field(default=None, max_length=200)


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=100)
    text: str
    sha256: str
    status: str = Field(min_length=1, max_length=80)


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str
    start: int = Field(ge=0, strict=True)
    quote: str = Field(min_length=1)


class ClaimCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: str = Field(min_length=1, max_length=100)
    sources: list[Source] = Field(min_length=1, max_length=100)
    target: Target
    evidence: list[Evidence] = Field(min_length=1, max_length=100)
    source_complete: bool = False


class Assessment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role_match: Literal['matches', 'mismatches', 'unknown']
    assertion_status: Literal['current', 'superseded', 'disputed', 'unknown']


def compare_assessments(packet, openai, jev, review):
    openai = Assessment.model_validate(openai).model_dump()
    jev = Assessment.model_validate(jev).model_dump()
    reasons = list(packet['coverage']['review_reasons']) + ['human_quality_review_required']
    if openai != jev:
        reasons.append('model_disagreement')
    for provider, answer in [('openai', openai), ('jev', jev)]:
        if answer['role_match'] != 'matches' and answer['assertion_status'] != 'unknown':
            reasons.append('inconsistent_attribution_status:' + provider)
    return {'schema_version': '1.0.0', 'status': 'candidate_only', 'activation_allowed': False,
            'correctness': 'not_established', 'needs_review': True, 'gold_label': None,
            'claim_id': packet['claim_id'], 'packet': packet, 'openai': openai, 'jev': jev,
            'jev_review': review, 'agreement': openai == jev, 'review_reasons': reasons}


def prepare_packet(case, config):
    case = ClaimCase.model_validate(case)
    sources = {s.id: s for s in case.sources}
    if len(sources) != len(case.sources):
        raise ValueError('duplicate source IDs')
    if sum(len(s.text) for s in case.sources) > config['max_source_chars']:
        raise ValueError('source character limit')
    for s in case.sources:
        if digest(s.text) != s.sha256:
            raise ValueError('source hash mismatch')
    if sum(len(e.quote) for e in case.evidence) > config['max_evidence_chars']:
        raise ValueError('evidence character limit')
    evidence, covered = [], {sid: [] for sid in sources}
    for e in case.evidence:
        s = sources.get(e.source_id)
        end = e.start + len(e.quote)
        if s is None or s.status != 'read' or s.text[e.start:end] != e.quote:
            raise ValueError('invalid evidence')
        evidence.append(e.model_dump() | {'end': end, 'source_sha256': s.sha256})
        covered[s.id].append((e.start, end))
    covered_chars = 0
    for spans in covered.values():
        right = 0
        for start, end in sorted(spans):
            covered_chars += max(0, end - max(right, start))
            right = max(right, end)
    source_chars = sum(len(s.text) for s in case.sources)
    reasons = ['unread_source:' + s.id for s in case.sources if s.status != 'read']
    if not case.source_complete:
        reasons.append('upstream_completeness_unknown')
    if covered_chars != source_chars:
        reasons.append('source_excerpts_only')
    identity = {'target': case.target.model_dump(), 'sources': {sid: s.sha256 for sid, s in sources.items()},
                'evidence': evidence}
    return {'claim_id': canonical_hash(identity), 'target': case.target.model_dump(), 'evidence': evidence,
            'coverage': {'source_chars': source_chars, 'covered_chars': covered_chars,
                         'all_available_text_included': covered_chars == source_chars,
                         'source_complete_declared': case.source_complete,
                         'source_status': {sid: s.status for sid, s in sources.items()},
                         'review_reasons': reasons, 'extraction_completeness': 'not_established'}}


def assess_openai(packet, *, model, config, run_id):
    """A meglévő Pydantic AI-javaslattevő mintája, egy strukturált értelmezésre."""
    from pydantic_ai import Agent
    from pydantic_ai.usage import UsageLimits
    from jav import store
    from jav.config import OPENAI_USD_PER_MTOK
    instructions = config['instructions'] + '\n' + json.dumps({
        'role_match': config['role_criteria'], 'assertion_status': config['status_criteria']}, ensure_ascii=False)
    agent = Agent(model, output_type=Assessment, instructions=instructions, retries=0,
                  model_settings=config['model_settings'])
    provider = model.split(':', 1)[0] if isinstance(model, str) else getattr(model, 'system', 'unknown')
    requested = model.split(':', 1)[-1] if isinstance(model, str) else getattr(model, 'model_name', '')
    started = time.perf_counter()
    try:
        result = agent.run_sync(json.dumps(packet, ensure_ascii=False), usage_limits=UsageLimits(request_limit=1))
    except Exception as exc:
        store.ledger_add(run_id=run_id, step='claim_openai', provider=provider, model=str(requested),
                         input_tokens=None, output_tokens=None, cost_usd=None,
                         seconds=time.perf_counter()-started, config_hash=canonical_hash(config),
                         error=type(exc).__name__)
        raise
    usage = result.usage() if callable(result.usage) else result.usage
    actual = result.response.model_name
    price_key = actual
    if actual not in OPENAI_USD_PER_MTOK and re.fullmatch(re.escape(requested) + r'-\d{4}-\d{2}-\d{2}', actual):
        price_key = requested
    price = OPENAI_USD_PER_MTOK.get(price_key) if provider == 'openai' else None
    cost = (round((usage.input_tokens*price[0] + usage.output_tokens*price[1])/1_000_000, 6)
            if price else 0. if provider == 'test' else None)
    seconds = time.perf_counter()-started
    store.ledger_add(run_id=run_id, step='claim_openai', provider=provider, model=actual,
                     input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=cost,
                     seconds=seconds, config_hash=canonical_hash(config))
    return {'assessment': result.output.model_dump(), 'model': actual, 'cost_usd': cost,
            'seconds': seconds, 'input_tokens': usage.input_tokens, 'output_tokens': usage.output_tokens,
            'price_model': price_key if price else None, 'messages': json.loads(result.all_messages_json())}


def assess_jev(packet, ask, config):
    from typesafe_sdk import Choice
    questions = {
        'role_match': Choice(instructions=config['instructions'] + ' ' + config['role_question'],
                             criteria=config['role_criteria']),
        'assertion_status': Choice(instructions=config['instructions'] + ' ' + config['status_question'],
                                  criteria=config['status_criteria'])}
    response = ask('claim_independent', packet, questions)
    assessment = Assessment(role_match=response.choices['role_match'].choice,
                            assertion_status=response.choices['assertion_status'].choice)
    return {'assessment': assessment.model_dump(), 'response': response.model_dump(mode='json')}


def review_proposal(packet, proposal, ask, config):
    from typesafe_sdk import Noul
    proposal = Assessment.model_validate(proposal).model_dump()
    state = {'source_packet': packet, 'proposal': proposal,
             'definitions': {'role_match': config['role_criteria'], 'assertion_status': config['status_criteria']}}
    questions = {'proposal_supported': Noul(instructions=config['instructions'] + ' ' + config['review_question'])}
    dimensions = config.get('review_dimensions', {})
    if 'proposal_supported' in dimensions:
        raise ValueError('review dimension cannot replace overall question')
    questions.update({name: Noul(instructions=config['instructions'] + ' ' + question)
                      for name, question in dimensions.items()})
    response = ask('claim_review', state, questions)
    result = {'noul': response.nouls['proposal_supported'].noul, 'response': response.model_dump(mode='json')}
    if dimensions:
        result['dimension_nouls'] = {name: response.nouls[name].noul for name in dimensions}
    return result


def run_assessment(*, case, directory, run_id, model, adapter, config, fault=None):
    """Saját változatlan válasznapló, hívás előtti jelző és egyetlen helyi munkás.

    Ez fájlos kísérleti vizsgálat; nem új üzemi Burr-gráf és nem aktiválási kapu.
    """
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    from jav import store
    from jav.learning_runtime import code_hash
    packet = prepare_packet(case, config)
    if not run_id or not re.fullmatch(r'jev-\d+\.\d+\.\d+', adapter.model):
        raise ValueError('run ID and concrete JEV model required')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model_name = model if isinstance(model, str) else getattr(model, 'model_name', None)
    identity = {'case': ClaimCase.model_validate(case).model_dump(), 'config': config,
                'generator': str(model_name), 'provider': getattr(model, 'system', None),
                'jev_model': adapter.model, 'code_sha256': code_hash()}
    with closing(sqlite3.connect(directory/'worker.sqlite', timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with store.use_store(directory/'business.sqlite'), adapter.no_cache_write():
            store.save_artifact('claim_identity', run_id, identity)
            saved = store.load_artifact('claim_result', run_id)
            if saved is not None:
                return saved

            def stage(name, execute):
                key = run_id + ':' + name
                saved = store.load_artifact('claim_stage', key)
                if saved is not None:
                    return saved
                if store.load_artifact('claim_started', key) is not None:
                    raise RuntimeError('unresolved external call: ' + name)
                store.save_artifact('claim_started', key, {'identity_sha256': canonical_hash(identity)})
                value = execute()
                if fault:
                    fault('before_save:' + name)
                store.save_artifact('claim_stage', key, value)
                if fault:
                    fault('after_' + name)
                return value

            def ask(step, state, questions):
                result = adapter.ask(step, state, questions, run_id=run_id, use_cache=False,
                                     config_hash=canonical_hash(config))
                store.save_artifact('claim_exchange', run_id + ':' + step, {
                    'request': {'state': state, 'questions': {k:q.model_dump(mode='json') for k,q in questions.items()}},
                    'response': result.response.model_dump(mode='json'), 'call': result.call.model_dump(mode='json')})
                return result.response

            generated = stage('openai', lambda: assess_openai(packet, model=model, config=config, run_id=run_id))
            independent = stage('independent', lambda: assess_jev(packet, ask, config))
            review = stage('review', lambda: review_proposal(packet, generated['assessment'], ask, config))
            result = compare_assessments(packet, generated['assessment'], independent['assessment'], review)
            result.update(openai_details=generated, jev_details=independent,
                          run_id=run_id, config_hash=canonical_hash(config), code_sha256=identity['code_sha256'])
            store.save_artifact('claim_result', run_id, result)
            return result
