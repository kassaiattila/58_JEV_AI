"""Matter-link proposal: a durable Burr experiment, without writing operational links."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from jav import store
from jav.learning_runtime import canonical_hash

Relation = Literal['none', 'invoice_order', 'invoice_receipt', 'order_receipt',
                   'invoice_payment', 'duplicate', 'correction', 'same_thread', 'same_case', 'other']


class MatterVerdict(BaseModel):
    """Typed version of the output contract of the legacy matter judge."""
    model_config = ConfigDict(extra='forbid')
    linked: bool
    relation: Relation
    missing: list[str]
    confidence: float = Field(ge=0, le=1)
    rationale: str


def combine(gpt, jev, *, minimum=.8, maximum_contradiction=.2):
    """Pre-registered experimental filter, not a calibrated operational acceptance."""
    reasons = []
    if gpt['linked'] != (gpt['relation'] != 'none'):
        reasons.append('gpt_internal_contradiction')
    if jev['selected_probability'] < minimum:
        reasons.append('jev_uncertain_relation')
    if jev['relation'] != 'none':
        if jev['linked_probability'] < minimum:
            reasons.append('jev_insufficient_link_support')
        if jev['contradiction_probability'] > maximum_contradiction:
            reasons.append('jev_contradiction')
    elif jev['linked_probability'] > 1-minimum:
        reasons.append('jev_link_relation_disagreement')
    jev_reasons = [r for r in reasons if r.startswith('jev_')]
    if gpt['relation'] != jev['relation']:
        reasons.append('provider_disagreement')
    return {'gpt_relation': gpt['relation'], 'jev_relation': jev['relation'],
            'jev_guarded_relation': 'review' if jev_reasons else jev['relation'],
            'hybrid_relation': 'review' if reasons else gpt['relation'],
            'review_reasons': reasons, 'candidate_only': True,
            'correctness': 'not_established', 'human_gold': None}


def run_pair(*, directory, run_id, packet, config, gpt, jev, halt_after=None):
    """One worker; a saved provider response is replayed when Burr resumes.

    A call that was started but left without a response is not restarted. The caller pins the exact
    model/prompt identity in the config; the hash of the local code is also part of the lock.
    """
    from burr.core import ApplicationBuilder, State, action
    from jav.runtime.persistence import ClosingSQLitePersister
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    identity = {'packet': packet, 'config': config,
                'source_sha256': canonical_hash(Path(__file__).read_text(encoding='utf-8'))}
    with closing(sqlite3.connect(directory/'worker.sqlite', timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with store.use_store(directory/'business.sqlite'):
            prior = store.load_artifact('matter_identity', run_id)
            if prior is not None and prior != identity:
                raise ValueError('matter identity changed')
            store.save_artifact('matter_identity', run_id, identity)

            def call(name, fn):
                key = run_id + ':' + name
                saved = store.load_artifact('matter_exchange', key)
                if saved is not None:
                    return saved
                if store.load_artifact('matter_started', key) is not None:
                    raise RuntimeError('unresolved external call: '+name)
                store.save_artifact('matter_started', key, {'identity': canonical_hash(identity)})
                result = fn()
                store.save_artifact('matter_exchange', key, result)
                return result

            @action(reads=[], writes=['gpt'])
            def generate(state: State):
                value = call('gpt', gpt)
                return value, state.update(gpt=value)

            @action(reads=[], writes=['jev'])
            def judge(state: State):
                value = call('jev', jev)
                return value, state.update(jev=value)

            @action(reads=['gpt', 'jev'], writes=['result'])
            def compare(state: State):
                value = combine(state['gpt'], state['jev'],
                                minimum=config.get('minimum', .8),
                                maximum_contradiction=config.get('maximum_contradiction', .2))
                return value, state.update(result=value)

            persister = ClosingSQLitePersister.from_values(str(directory/'burr.sqlite'))
            persister.initialize()
            try:
                app = (ApplicationBuilder().with_identifiers(app_id=run_id, partition_key='matter_trial')
                       .with_actions(gpt=generate, jev=judge, compare=compare)
                       .with_transitions(('gpt', 'jev'), ('jev', 'compare'))
                       .initialize_from(persister, resume_at_next_action=True,
                                        default_state={}, default_entrypoint='gpt')
                       .with_state_persister(persister).build())
                if 'result' in app.state:
                    return app.state.get_all()
                _, _, state = app.run(halt_after=halt_after or ['compare'])
                return state.get_all()
            finally:
                persister.cleanup()
