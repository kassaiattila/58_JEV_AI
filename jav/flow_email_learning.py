"""Opt-in M3: baseline measurement → source scan → intent → learning candidate."""
from burr.core import ApplicationBuilder, action
from jav import store

TERMINALS=['done']

@action(reads=['run_id'],writes=['baseline'])
def baseline(state,service):
    return state.update(baseline=service.classify_baseline_jev(run_id=state['run_id']))

@action(reads=['run_id'],writes=['searches'])
def scan(state,service):
    return state.update(searches=service.scan_jev(run_id=state['run_id']))

@action(reads=['run_id','searches'],writes=['result'])
def classify(state,service):
    return state.update(result=service.classify_evidence(state['searches'],run_id=state['run_id']))

@action(reads=['run_id','baseline','result'],writes=['candidate'])
def collect(state,service):
    candidate=service.candidate(state['baseline'],state['result'])
    store.save_artifact('email_learning_candidate',state['run_id'],candidate)
    return state.update(candidate=candidate)

@action(reads=[],writes=[])
def done(state):
    return state

CONTRACT=dict(name='email_learning',phases=['baseline','scan','classify','collect','terminal'],
    steps=[('baseline','baseline'),('scan','scan'),('classify','classify'),('collect','collect'),('done','terminal')],
    edges=[('baseline','scan'),('scan','classify'),('classify','collect'),('collect','done')],
    step_meta={
        'baseline':dict(kind='jev',note='Változatlan M3-kérdések az új mintán; saját válasznapló.'),
        'scan':dict(kind='jev',note='Minden olvasható forrás minden része; pontos helyek és nyers relevancia.'),
        'classify':dict(kind='jev',note='Szándék eredeti törzs- és csatolmányrészletekből; nincs típusaktiválás.'),
        'collect':dict(kind='store',note='Jelölt, eltérések, forráshiány, ellenőrzési okok; még nem etalon.'),
        'done':dict(kind='terminal',note='Tartós kísérleti eredmény; kézi címkézés külön parancs.')},
    terminals=TERMINALS,doc_note='Opt-in M3-próba: jav.email_learning_runtime; üzemi út és küszöbök változatlanok.')

def builder(service=None):
    return ApplicationBuilder().with_actions(baseline.bind(service=service),scan.bind(service=service),
        classify.bind(service=service),collect.bind(service=service),done).with_transitions(*CONTRACT['edges'])

def build_app():
    return builder().with_state(run_id='lint').with_entrypoint('baseline').build()
