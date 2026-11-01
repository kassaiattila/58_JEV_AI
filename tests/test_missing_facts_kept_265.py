"""265 (code review APPR-11): the facts a premium misses are computed once per evaluation and tariff version.

The missing-facts step asked every five seconds which facts the premium still misses, about 170 000 times in ten
days, each time reading the evaluation, the checked input and the tariff. An evaluation version and a tariff version
never change, so the answer is now kept per both (and per store); a tariff named without a version is computed each
time. The computation itself is a stand-in here; no AI.
"""

from __future__ import annotations

from jav.app import evaluation_steps


def test_the_answer_is_kept_per_version(monkeypatch, tmp_path) -> None:
    from jav.core import store

    calls = []
    monkeypatch.setattr(evaluation_steps, "_MISSING_KEPT", {})
    monkeypatch.setattr(evaluation_steps, "_tariff_missing",
                        lambda *a: calls.append(a) or [{"unit_id": "u-1", "fact": "sum_insured", "title": "Sum"}])
    with store.use_store(tmp_path / "m.sqlite"):
        first = evaluation_steps.tariff_missing("wp-1", "evaluate", 2, "invented_tariff@1")
        first[0]["fact"] = "changed by a caller"
        again = evaluation_steps.tariff_missing("wp-1", "evaluate", 2, "invented_tariff@1")
        assert again == [{"unit_id": "u-1", "fact": "sum_insured", "title": "Sum"}] and len(calls) == 1
        evaluation_steps.tariff_missing("wp-1", "evaluate", 3, "invented_tariff@1")  # another evaluation version
        evaluation_steps.tariff_missing("wp-1", "evaluate", 2, "invented_tariff")  # no version: computed each time
        evaluation_steps.tariff_missing("wp-1", "evaluate", 2, "invented_tariff")
    assert len(calls) == 4
