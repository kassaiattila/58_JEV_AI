"""156: a name-like column (a name, a file name, a path, an e-mail address) may break inside a long unbroken value.

The interface wraps every other column at spaces only; without this mark one e-mail address or file name widened a
whole result table past the screen (the e-mail table by 327 px at 1440 px).
"""

from jav.datasets import col as _col  # 185: public, a domain's table uses it too


def test_a_name_like_text_column_may_break_anywhere():
    for key in ("name", "file", "filename", "original", "source_path", "sender"):
        assert _col(key, "Label").spec()["wrap"] == "anywhere", key


def test_other_columns_wrap_at_spaces_only():
    assert "wrap" not in _col("subject", "Label").spec()
    assert "wrap" not in _col("file", "Label", "enum").spec()  # a value from a short list is no long name
