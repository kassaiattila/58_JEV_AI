"""265 (code review SEC-10): a list request takes no field it does not know, and a column name has a bound.

The models of the shared list request accepted any unknown field and a column name of any length. Now they refuse an
unknown field (422 at the service) and a column name over 80 characters.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jav.app.tablequery import Filter, Query, Sort


def test_an_unknown_field_is_refused() -> None:
    for model, data in ((Query, {"limit": 10, "everything": True}), (Filter, {"col": "a", "op": "eq", "x": 1}),
                        (Sort, {"col": "a", "up": True})):
        with pytest.raises(ValidationError, match="Extra inputs"):
            model.model_validate(data)


def test_a_column_name_has_a_bound() -> None:
    with pytest.raises(ValidationError):
        Filter(col="c" * 81, op="eq", value="x")
    assert Query.model_validate({"filters": [{"col": "status", "op": "in", "value": ["a"]}], "sort": [{"col": "id"}]})
