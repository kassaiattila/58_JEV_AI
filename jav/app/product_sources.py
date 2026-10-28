"""Where a real product comes from: its condition documents' files and its frame (231, stage U, U-A2; the owner's
decisions of 2026-10-27).

Plain-language summary: a real product is built from its insurer's published condition documents. A product source
(`configs/product_source_<name>.json`) names each document by its file name and SHA-256 fingerprint (so only these very
versions are read), with its kind and title as printed, and the product's frame: its name, the fact catalogue its rules
read, and its cover modules. The files stay on the machine they are on: given the folder they are in, each one is read
by code (`condition_import`), and the machine adds each document and the product as drafts; the product names its
documents but no rule and no tariff yet, as the rules come from proposals a person decides on. A person makes each one
active (the owner's decision: the system assembles the product, a person makes it active). A file that is missing or is
another version refuses the whole source before anything is written.

- `load(name)`: the source; `read(source, folder)`: each document read (`SourceRefused`: a file missing or changed, or
  one that could not be read); `install(source, read_documents)`: the documents' and the product's references.
- U-A4 `assemble(source)`: once a person decided on the rules proposed from its documents, the product's next version
  as the machine drafts it: the latest version of each document, every rule a person accepted or corrected, the tariff
  the source names; its reference (the same content as the latest version: that one).

Layer: application; it names no insurer and no product (the source is data).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from jav.app import condition_import, product_rules
from jav.app.product_rules import Module, Product, Section
from jav.core import cfg, identity
from jav.core.user_messages import explained

__all__ = ["MACHINE", "ProductSource", "SourceRefused", "assemble", "install", "known_codes", "load", "read"]

MACHINE = identity.machine("product assembly")
PREFIX = "product_source_"


class SourceRefused(ValueError):
    """A source whose files are not all there as named: nothing is written."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceDocument(_Model):
    file: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: condition_import.Kind
    title: str = Field(min_length=1)


class SourceProduct(_Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    catalogue: str = Field(min_length=1)
    modules: tuple[Module, ...] = Field(min_length=1)
    tariff: str | None = None  # U-A4: the tariff the assembled product is priced by (an example until a live one is given)


class ProductSource(_Model):
    issuer: str
    documents: dict[str, SourceDocument] = Field(min_length=1)
    product: SourceProduct
    codes: tuple[str, ...] = ()  # U-A3: the clause codes the documents print besides the modules' (I16, J25, …)


# U-A3: the letters and digits text recognition takes for one another in an extension's code ("129" for "I29")
_LOOKALIKE = {"1": "I", "I": "1", "0": "O", "O": "0", "J": "I", "T": "I", "S": "J", "5": "S", "8": "B", "B": "8"}


def _alike(read: str, code: str) -> bool:
    return len(read) == len(code) and all(a == b or _LOOKALIKE.get(a) == b for a, b in zip(read, code))


def known_codes(sections: tuple[Section, ...] | list[Section], codes: tuple[str, ...] | list[str]) -> list[Section]:
    """U-A3: each section named with a code (`"129 1"`) whose code is none of `codes` but looks like exactly one of them
    as text recognition misreads letters ("129" is "I29", "JHA" is "IHA", "TKO" is "IKO", "S25" is "J25"), named with
    that one; any other section as it is."""
    out = []
    for s in sections:
        head, _, rest = s.clause.partition(" ")
        if rest and head not in codes and len(alike := [c for c in codes if _alike(head, c)]) == 1:
            s = s.model_copy(update={"clause": f"{alike[0]} {rest}"})
        out.append(s)
    return out


def load(name: str) -> ProductSource:
    return ProductSource.model_validate({k: v for k, v in cfg.load(PREFIX + name).items() if k != "meta"})


def read(source: ProductSource, folder: str | Path) -> dict[str, condition_import.Imported]:
    """Every document of the source read from `folder` by code; nothing is written."""
    problems: list[str] = []
    found: dict[str, Path] = {}
    for ident, d in source.documents.items():
        path = Path(folder) / d.file
        if not path.is_file():
            problems.append(f"{ident}: no file {d.file}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != d.sha256:
            problems.append(f"{ident}: {d.file} is another version than the source names")
        else:
            found[ident] = path
    if problems:
        raise explained(SourceRefused, "the product source cannot be read: {{problems}}", problems="; ".join(problems))
    out = {ident: condition_import.read(path, kind=source.documents[ident].kind, title=source.documents[ident].title)
           for ident, path in found.items()}
    codes = tuple(m.code for m in source.product.modules) + source.codes
    out = {ident: replace(got, content=got.content.model_copy(update={"sections": tuple(known_codes(got.content.sections, codes))}))
           for ident, got in out.items()}
    if unread := [f"{ident}: {p}" for ident, got in out.items() for p in got.problems]:
        raise explained(SourceRefused, "the product source cannot be read: {{problems}}", problems="; ".join(unread))
    return out


def install(source: ProductSource, documents: dict[str, condition_import.Imported]) -> list[str]:
    """Each document and then the product, as drafts the machine makes (one already there with the same content is
    kept); their references (`<kind>:<id>@<n>`)."""
    refs = {ident: condition_import.install(ident, documents[ident]) for ident in source.documents}
    p = source.product
    content = Product(name=p.name, catalogue=p.catalogue, modules=p.modules,
                      documents=tuple(refs[ident] for ident in source.documents)).model_dump(mode="json")
    latest = product_rules.latest("product", p.id)
    product = latest["ref"] if latest is not None and latest["content"] == content else \
        product_rules.add("product", p.id, content, actor=MACHINE)["ref"]
    return [f"document:{ref}" for ref in refs.values()] + [f"product:{product}"]


def assemble(source: ProductSource) -> str:
    """U-A4 (the owner's decision of 2026-10-27: the system assembles the product, a person makes it active): the
    product's next version, a draft the machine makes, naming the latest version of each of its documents, the latest
    version of every rule a person accepted or corrected from a proposal of a run on one of them (in the order decided;
    a rejected one never) and the tariff the source names. The same content as the latest version: that one, nothing
    new. A product or document not installed yet: `SourceRefused`."""
    from jav.app import rule_proposal_runs

    p = source.product
    if product_rules.latest("product", p.id) is None:
        raise SourceRefused(f"the product {p.id} is not installed yet: install its source first")
    documents = []
    for ident in source.documents:
        found = product_rules.latest("document", ident)
        if found is None:
            raise SourceRefused(f"the document {ident} is not installed yet: install its source first")
        documents.append(found["ref"])
    rules = [product_rules.latest("rule", ident)["ref"] for ident in rule_proposal_runs.decided_rules(set(source.documents))]
    content = Product(name=p.name, catalogue=p.catalogue, modules=p.modules, documents=tuple(documents), rules=tuple(rules),
                      tariff=p.tariff).model_dump(mode="json")
    latest = product_rules.latest("product", p.id)
    if latest["content"] == content:
        return latest["ref"]
    return product_rules.add("product", p.id, content, actor=MACHINE)["ref"]
