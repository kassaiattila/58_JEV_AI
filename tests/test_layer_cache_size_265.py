"""265 (code review AI-11): the word layers kept in memory are bounded by their words, not only by their count.

A loaded word layer is kept (it never changes), up to 256 of them; 256 long scanned documents could hold hundreds of
megabytes. The kept layers are now also bounded by their words in total; the newest one stays even alone over the
bound. Invented layers; no AI.
"""

from __future__ import annotations

from jav.documents import source_layer


def test_the_layers_kept_stay_under_the_words_bound(tmp_path, monkeypatch) -> None:
    from jav.core import store

    monkeypatch.setattr(source_layer, "_LOADED_MAX_WORDS", 5)
    monkeypatch.setattr(source_layer, "_loaded", type(source_layer._loaded)())
    monkeypatch.setattr(source_layer, "_loaded_words", 0)
    words = [{"text": f"w{i}", "page": 1, "x0": 0, "x1": 1, "top": 0, "bottom": 1} for i in range(3)]
    with store.use_store(tmp_path / "l.sqlite"):
        ids = []
        for n in range(3):
            layer = source_layer.build(f"doc{n}", [words], [(595.0, 842.0)], text_source="pdf", engine="pdfplumber")
            ids.append(source_layer.save(layer))
            source_layer.load(ids[-1])
        assert len(source_layer._loaded) == 1 and source_layer._loaded_words == 3
        assert source_layer.load(ids[0]) is not None  # read again from the store
