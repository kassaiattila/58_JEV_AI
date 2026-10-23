"""160 (review AI-9): the JEV verification uses the word layer's source search too, as the check without JEV does.

092 taught the code's own source check (the G path without JEV) to look for a value on the word layer when the line
search misses it (an address over several lines of one column, an identifier glued to a label). The JEV path kept the
line search alone, so the same value got a "not supported by the model" to-do there although the box showed where it
is printed. The JEV request itself does not change (the questions come from the line evidence), so no cache key moves.
Synthetic word layer and a fake JEV client, no paid call.
"""

from __future__ import annotations

from jav.core import store
from jav.adapters import jev as jev_mod
from jav.jev_verify import verify
from jav.typepack import get as get_pack
from tests.test_grounding import layer_of
from tests.test_grounding_frames_092 import TWO_COLUMN_HEADER, _line_layout
from tests.test_runtime_worker import FakeClient

LLM = {"supplier_address": "Szeged Fo utca 1. 2. em. 6720 Magyarorszag", "buyer_address": "Sopron Varkerulet 9."}


def test_a_value_found_on_the_word_layer_is_supported_on_the_jev_path_too(tmp_path):
    layer = layer_of(TWO_COLUMN_HEADER)
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "s.sqlite"):
        lines_only, first = verify(adapter, _line_layout(layer), LLM, pack=get_pack("invoice_hu"))
        with_layer, second = verify(adapter, _line_layout(layer), LLM, pack=get_pack("invoice_hu"), layer=layer)
    assert "supplier_address" in lines_only.unsupported  # the line search alone misses it
    assert "supplier_address" not in with_layer.unsupported and "buyer_address" in with_layer.unsupported
    assert second.cached  # the same request: answered from the first one's cache
