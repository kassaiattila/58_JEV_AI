"""231 (stage U, U-A2; the owner's decisions of 2026-10-27): a real product's source: its documents' files by
fingerprint and its frame.

The real corporate property source loads: six documents of the kinds the registry knows, a product on the real fact
catalogue whose modules each require a module of the product. A source is read from a folder by code and installed as
drafts the machine makes (documents first, then the product naming them, with no rule and no tariff yet); the same
again changes nothing; a file missing or of another version refuses the whole source before anything is written. The
files here are the invented insurer's documents written as PDFs. No AI call.
"""

from __future__ import annotations

import hashlib

import pytest

from jav.app import facts, product_rules, product_sets, product_sources
from jav.core import store

SET = product_sets.load()


def test_the_real_source_loads_on_the_real_catalogue() -> None:
    source = product_sources.load("allianz_property")
    assert len(source.documents) == 6 and {d.kind for d in source.documents.values()} <= {"general", "special", "supplementary"}
    assert facts.catalogue(source.product.catalogue).facts
    codes = {m.code for m in source.product.modules}
    assert all(set(m.requires) <= codes for m in source.product.modules)
    assert [m.code for m in source.product.modules if m.kind == "base"] == ["property_ar"]


def _source(folder) -> product_sources.ProductSource:
    written = product_sets.write_documents(SET, folder)
    product = next(iter(SET.products.values()))
    return product_sources.ProductSource(
        issuer=SET.issuer,
        documents={ident: product_sources.SourceDocument(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                                          kind=SET.documents[ident].content.kind, title=SET.documents[ident].content.title)
                   for ident, path in written.items()},
        product=product_sources.SourceProduct(id="trial_product", name=product.name, catalogue=product.catalogue,
                                              modules=product.modules))


def test_a_source_installs_its_documents_and_product_as_the_machine_s_drafts(tmp_path) -> None:
    source = _source(tmp_path / "files")
    # the invented documents print no day in force after "hatályos": it is given as the registry has it
    read = {ident: product_sources.condition_import.read(tmp_path / "files" / d.file, kind=d.kind, title=d.title,
                                                         valid_from=SET.documents[ident].content.valid_from)
            for ident, d in source.documents.items()}
    with store.use_store(tmp_path / "registry.sqlite"):
        refs = product_sources.install(source, read)
        assert refs[-1] == "product:trial_product@1" and len(refs) == len(source.documents) + 1
        assert product_sources.install(source, read) == refs
        product = product_rules.get("product", "trial_product", 1)
        assert product["state"] == "draft" and product["made_by_id"] == product_sources.MACHINE.id
        assert product["content"]["rules"] == [] and product["content"]["tariff"] is None
        assert product["content"]["documents"] == [r.removeprefix("document:") for r in refs[:-1]]


def test_a_missing_or_changed_file_refuses_the_source(tmp_path) -> None:
    source = _source(tmp_path / "files")
    first = next(iter(source.documents.values()))
    (tmp_path / "files" / first.file).write_bytes(b"%PDF-1.4 another version")
    second = list(source.documents.values())[1]
    (tmp_path / "files" / second.file).unlink()
    with pytest.raises(product_sources.SourceRefused) as refused:
        product_sources.read(source, tmp_path / "files")
    assert "another version" in str(refused.value) and "no file" in str(refused.value)


def test_a_code_text_recognition_misread_is_the_product_s_code() -> None:
    """U-A3: the all risks conditions were read by text recognition, which printed I29 as "129", IHA as "JHA", IKO as
    "TKO" and J25 as "S25"; a section's code is the product's (or the source's other codes) that differs only in such
    letters, when exactly one does."""
    from jav.app.product_rules import Section

    codes = ("I29", "IHA", "IKO", "I05", "J25", "VIL")
    got = product_sources.known_codes([Section(clause=c, page=1) for c in ("129 1", "JHA 2", "TKO 3", "105 1", "S25 4", "VIL 1", "2.1")],
                                      codes)
    assert [s.clause for s in got] == ["I29 1", "IHA 2", "IKO 3", "I05 1", "J25 4", "VIL 1", "2.1"]
