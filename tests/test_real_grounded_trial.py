from jav.models import LineLayout
from jav.experiments.real_grounded_trial import partition_layout
import pytest


def test_budget_reservation_survives_restart_and_refuses_extra_call(tmp_path):
    from jav.experiments.real_grounded_trial import reserve_call
    budget = tmp_path/"budget.sqlite"
    assert reserve_call(budget,already_used=198,maximum=200) == 199
    assert reserve_call(budget,already_used=198,maximum=200) == 200
    with pytest.raises(RuntimeError,match="budget"):
        reserve_call(budget,already_used=198,maximum=200)


def test_oversized_line_is_not_silently_truncated():
    with pytest.raises(ValueError):
        partition_layout([LineLayout(no=1,page=1,text="x"*16001)])


def test_real_page_partitions_preserve_every_source_line_and_page_boundary():
    rows = [LineLayout(no=i+1,page=1 if i<81 else 2,text=f"Line {i}") for i in range(90)]
    chunks = partition_layout(rows)
    assert [len(c) for c in chunks] == [80,1,9]
    assert [r.no for c in chunks for r in c] == list(range(1,91))
    assert all(len({r.page for r in c}) == 1 for c in chunks)
