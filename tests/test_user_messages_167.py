"""167 (review 160 U-1): an error a person sees carries its English template and parameters, so the interface shows it
in the chosen language; the filled English text stays the exception's message for the log and the command line. Every
template is a translated interface label (an English source key with a Hungarian translation)."""

from __future__ import annotations

import ast
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav.service import api
from jav.app import work
from jav.core.user_messages import explained, fill, inside, said, said_back, said_fields, said_from

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "ui" / "src" / "i18n"


def test_the_message_is_the_filled_template_and_keeps_its_parts() -> None:
    exc = explained(ValueError, "The amount {{amount}} is over what the line has left ({{left}})", amount="12.50",
                    left=Decimal("3.00"))
    assert str(exc) == "The amount 12.50 is over what the line has left (3.00)"
    assert exc.template == "The amount {{amount}} is over what the line has left ({{left}})"
    assert exc.params == {"amount": "12.50", "left": "3.00"}
    assert isinstance(exc, ValueError)


def test_extra_positional_arguments_reach_the_exception() -> None:
    exc = explained(work.NotReady, "The run has {{n}} open to-dos", [{"code": "open", "message": "x"}], n=3)
    assert str(exc) == "The run has 3 open to-dos"
    assert exc.blockers == [{"code": "open", "message": "x"}]


def test_a_missing_or_unused_parameter_is_a_programming_error() -> None:
    with pytest.raises(KeyError):
        explained(ValueError, "Unknown run {{run}}")
    with pytest.raises(TypeError):
        explained(ValueError, "Unknown run", run="r-1")


def test_a_sentence_keeps_its_template_and_where_it_applies() -> None:
    """231 D-c6: a problem a check lists is a `str` as before, with its template, parameters and where it applies."""
    row = said("row {{row}}", row=2)
    sentence = said("no comparison {{op}}", within=row, op="like")
    assert sentence == "row 2: no comparison like" and (sentence.template, sentence.params) == ("no comparison {{op}}", {"op": "like"})
    outer = inside(said("rule {{ref}}", ref="r@1"), sentence)
    assert outer == "rule r@1: row 2: no comparison like"
    fields = said_fields(outer)
    assert fields["template"] == "no comparison {{op}}" and fields["within"]["template"] == "row {{row}}"
    assert fields["within"]["within"] == {"text": "rule r@1", "template": "rule {{ref}}", "params": {"ref": "r@1"}, "within": None}
    assert said_fields("plain") == {"text": "plain"}
    assert said_from(explained(ValueError, "Unknown run {{run}}", run="r-1"), within=row) == "row 2: Unknown run r-1"


def test_fill_leaves_unknown_braces_alone() -> None:
    assert fill("a {b} {{c}}", {"c": "1"}) == "a {b} 1"


def test_the_service_sends_the_template_and_parameters(tmp_path: Path) -> None:
    app = api.create_app(store_path=tmp_path / "s.sqlite")

    @app.get("/api/_test/explained")
    def boom() -> None:
        raise explained(ValueError, "Unknown package {{id}}", id="wp-1")

    @app.get("/api/_test/plain")
    def plain() -> None:
        raise ValueError("plain text")

    # ahead of the interface's catch-all route
    app.router.routes[:0] = [app.router.routes.pop(), app.router.routes.pop()]
    client = TestClient(app, base_url="http://127.0.0.1")
    r = client.get("/api/_test/explained")
    assert r.status_code == 422
    assert r.json() == {"error": "invalid", "message": "Unknown package wp-1", "template": "Unknown package {{id}}",
                        "params": {"id": "wp-1"}}
    # a message not yet written as a template keeps the old form
    assert "template" not in client.get("/api/_test/plain").json()


def _templates() -> dict[str, str]:
    """Every literal template passed to `explained(...)` (231 D-c6: and to `said(...)`) in the application code, with
    where it is."""
    found: dict[str, str] = {}
    for path in sorted((ROOT / "jav").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(node.func, "id", getattr(node.func, "attr", None)) if isinstance(node, ast.Call) else None
            if name in ("explained", "said"):
                arg = (node.args[1] if len(node.args) > 1 else None) if name == "explained" else (node.args[0] if node.args else None)
                where = f"{path.relative_to(ROOT)}:{node.lineno}"
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), f"{where}: the template must be a literal"
                found[arg.value] = where
    return found


_MARKER = re.compile(r"\{\{[^}]*\}\}")
_SOFTWARE = re.compile(r"Python|UI package|npm|pip\b|vulnerab|dependenc|audit", re.I)
_BATCH = ((re.compile(r"\bwork packages\b"), "document batches"), (re.compile(r"\bwork package\b"), "document batch"),
          (re.compile(r"\bpackage\(s\)"), "batch(es)"), (re.compile(r"\bpackages\b"), "batches"),
          (re.compile(r"\bpackage\b"), "batch"))


def _shown(template: str) -> str:
    """231 (stage U; the owner's decision of 2026-10-28): the English interface shows the source, saying (document)
    batch for a work package; a placeholder keeps its name, and a text about software packages stays as it is."""
    if _SOFTWARE.search(template):
        return template
    parts, markers = _MARKER.split(template), _MARKER.findall(template)
    out = []
    for i, part in enumerate(parts):
        for rule, new in _BATCH:
            part = rule.sub(new, part)
        out.append(part + (markers[i] if i < len(markers) else ""))
    return "".join(out)


def test_every_template_is_a_translated_interface_label() -> None:
    english = json.loads((I18N / "en-native.json").read_text(encoding="utf-8"))
    hungarian = json.loads((I18N / "hu-native.json").read_text(encoding="utf-8"))
    holes = re.compile(r"\{\{\w+\}\}")
    missing = []
    for template, where in _templates().items():
        if english.get(template) != _shown(template) or template not in hungarian:
            missing.append(f"{where}: {template}")
        elif sorted(holes.findall(template)) != sorted(holes.findall(hungarian[template])):
            missing.append(f"{where}: the Hungarian placeholders differ: {template}")
    assert not missing, "\n".join(missing)


def test_a_sentence_names_the_parameters_the_interface_translates() -> None:
    """U-A8: a sentence whose parameters are interface labels too (a fact's title, an asset group's label) names them,
    so the interface translates them with the template; it is kept and read back with them."""
    sentence = said("{{unit}}: the fact {{fact}} is missing", labels=("unit", "fact"), unit="Stock", fact="Payment frequency")
    assert sentence == "Stock: the fact Payment frequency is missing" and sentence.labels == ("unit", "fact")
    fields = said_fields(sentence)
    assert fields["labels"] == ["unit", "fact"] and said_back(fields).labels == ("unit", "fact")
    assert "labels" not in said_fields(said("row {{row}}", row=2))
    with pytest.raises(KeyError):
        said("{{unit}} is missing", labels=("fact",), unit="Stock")  # a label that is no parameter
