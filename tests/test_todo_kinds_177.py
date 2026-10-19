"""177 (plan 170 E6): the to-do kind registry (`configs/todo_kinds.json`, `jav/todo_kinds.py`).

Every kind is listed once with an example that maps back to it; its owners exist; a family covers its whole shape; the
codes the interface's label function names are registered kinds. The label test itself is the interface's
(`ui/src/todoKinds177.test.ts`); that every to-do a step raises is registered is checked for every test
(`tests/conftest.py`). No calls.
"""

from __future__ import annotations

import re
from pathlib import Path

from jav import todo_kinds as tk

ROOT = Path(__file__).resolve().parents[1]


def test_every_kind_once_and_its_example_maps_back_to_it():
    codes = [k.code for k in tk.kinds()]
    assert len(codes) == len(set(codes))
    for k in tk.kinds():
        assert tk.of(k.example) is k, k.code
        assert k.what and k.shape


def test_the_owners_exist():
    for k in tk.kinds():
        for owner in k.owners:
            assert (ROOT / owner).is_file(), (k.code, owner)
    assert {k.code for k in tk.kinds() if not k.owners} == {  # only earlier runs have them
        "reconcile:proposed", "reconcile:amount_only", "parties:same_tax_id", "parties:same_name", "intent:jev_off"}


def test_a_kind_is_read_from_the_first_two_parts():
    assert tk.code_of("pick:low_conf:invoice_number:0.62") == "pick:low_conf"
    assert tk.code_of("no_invoice") == "no_invoice:"
    assert tk.of("no_invoice").code == "no_invoice:"
    assert tk.of("validator:taxid.unrecognized:supplier_tax_id").code == "validator:*"
    assert tk.of("jev_unavailable:disabled").code == "jev_unavailable:*"
    assert tk.of("meter_reading_end:unparseable:'abc'").code == "*:unparseable"
    assert tk.of("pick:second_option:invoice_number:0.04") is None  # its band's uncertain review is off
    assert tk.unregistered(["pick:none:x", "kep:uj:1", "kep:uj:2", "hang:x"]) == {"kep:uj": "kep:uj:1", "hang:x": "hang:x"}


def test_every_code_the_label_function_names_is_registered():
    labels = (ROOT / "ui" / "src" / "labels.ts").read_text(encoding="utf-8")
    body = labels[labels.index("export function reasonText"):labels.index("export function usd")]
    named = set(re.findall(r'case "([a-z_]+:[a-z_]*)":', body))
    assert len(named) > 60
    assert sorted(code for code in named if tk.of(code) is None) == []
