import pytest


def test_shared_trial_budget_stops_both_providers_and_counts_attempts(tmp_path):
    from jav.experiments.long_document_trial import TrialBudget
    budget = TrialBudget(tmp_path, limits={'openai': (1, 6), 'jev': (12, 2)})
    budget.reserve('openai')
    with pytest.raises(RuntimeError):
        budget.reserve('jev')
    assert budget.usage()['openai']['reserved'] == 1
    assert budget.usage()['jev']['reserved'] == 0
