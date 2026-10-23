"""153 (review C2): the data guard covers the bank statement exports read since 136-141.

The review of 2026-10-13 found that a real bank export copied into the tree (a CSV, a camt.053 XML or a CIB text file,
or anything under `data/`, an input root) passed the guard, and that a full card number in a file's text did too. The
paths and file types are now blocked (`requirements.txt` allowed), and a payment card number is a value kind; the
schemes' published test number stays allowed. Synthetic values only.
"""

from jav.devtools import data_guard


def _guard() -> data_guard.Guard:
    return data_guard.Guard(data_guard.load_config(), env_secrets={})


def test_bank_export_paths_and_types_are_blocked():
    guard = _guard()
    for path in ("data/bank/2026-09.csv", "tests/fixtures/camt053.xml", "tests/fixtures/cib.txt", "exports/mt940.sta",
                 "data/notes.md"):
        assert guard.check_path(path) is not None, path
    assert guard.check_path("requirements.txt") is None


def test_a_card_number_in_a_files_text_is_found():
    guard = _guard()
    card = " ".join(["5555"] * 3 + ["4444"])  # another scheme's test number, built here so this file holds none
    found = guard.scan_line("tests/example.py", 1, f'memo = "card {card} at the shop"')
    assert [f.kind for f in found] == ["card_number"]  # not on the allow list: found
    assert not guard.scan_line("tests/example.py", 1, "card 4111 1111 1111 1111")  # the allowed Visa test number
    assert not guard.scan_line("tests/example.py", 1, "card 123456xxxxxx3456")  # already masked
    assert not guard.scan_line("tests/example.py", 1, "ref 1234567890123456")  # no right check digit
