"""Kísérleti általános kivonatolás: javaslat → JEV → tartós eredmény."""
from burr.core import ApplicationBuilder, action

from jav import store

TERMINALS = ['done']


@action(reads=['run_id'], writes=['proposals'])
def generate(state, service):
    return state.update(proposals=service.extract(run_id=state['run_id']))


@action(reads=['run_id','proposals'], writes=['result'])
def verify(state, service):
    return state.update(result=service.verify(state['proposals'],run_id=state['run_id']))


@action(reads=['run_id','result'], writes=[])
def save(state):
    store.save_artifact('generic_extraction',state['run_id'],state['result'])
    return state


@action(reads=[], writes=[])
def done(state):
    return state


CONTRACT = {
    'name':'document_learning',
    'phases':['propose','check','persist','terminal'],
    'steps':[('generate','propose'),('verify','check'),('save','persist'),('done','terminal')],
    'edges':[('generate','verify'),('verify','save'),('save','done')],
    'step_meta':{
        'generate':{'kind':'llm','note':'Explicit Pydantic AI modell vagy importált javaslat; saját tartós válasz.'},
        'verify':{'kind':'jev','note':'Forráshű adatpontok; futásonkénti válasznapló, nyers valószínűségekkel.'},
        'save':{'kind':'store','note':'Megváltoztathatatlan eredmény; ismételt azonos írás idempotens.'},
        'done':{'kind':'terminal','note':'Mentve; a dokumentum teljessége továbbra sem bizonyított.'}},
    'terminals':TERMINALS,
    'doc_note':'Kísérleti, UTF-8 szöveges bemenet. A tartós futtató: jav.learning_runtime.run_learning. '
               'Munkakönyvtáranként egy futtató; nincs típusaktiválás vagy automatikus személyesadat-küldés.'}


def builder(service=None):
    return (ApplicationBuilder().with_actions(generate.bind(service=service),verify.bind(service=service),save,done)
            .with_transitions(*CONTRACT['edges']))


def build_app():
    """Mellékhatásmentes gráfpéldány a kontrakt ellenőrzéséhez."""
    return builder().with_state(run_id='lint').with_entrypoint('generate').build()
