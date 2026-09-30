import sqlite3

import pytest

from jav.experiments.long_document_trial import TrialBudget


def test_exhausted_provider_does_not_block_other_provider(tmp_path):
    budget = TrialBudget(tmp_path, {'openai': (1, 1), 'jev': (1, 1)})
    budget.reserve('openai')
    with sqlite3.connect(tmp_path/'business.sqlite') as db:
        db.execute('CREATE TABLE ledger (id INTEGER, provider TEXT, cost_usd REAL, error TEXT, cached INTEGER)')
        db.execute("INSERT INTO ledger VALUES (1,'openai',0.01,NULL,0)")
    with pytest.raises(RuntimeError):
        budget.reserve('openai')
    budget.reserve('jev')
    assert budget.usage()['jev']['reserved'] == 1


def test_unresolved_provider_still_blocks_all_new_calls(tmp_path):
    budget = TrialBudget(tmp_path, {'openai': (1, 1), 'jev': (1, 1)})
    budget.reserve('openai')
    with pytest.raises(RuntimeError):
        budget.reserve('jev')
