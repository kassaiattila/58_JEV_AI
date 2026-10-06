"""120: the native facts table reads without the citation JSON, and its machine states have labels."""
from jav import datasets, export, store
from jav.tablequery import Query
from tests.test_native_review_api_109 import published_run


def test_source_text_names_the_quote_and_a_short_place():
    cell = {"quote": "12 500 Ft", "locator": {"kind": "cell", "sheet": "Sheet1", "cell": "B4"}}
    page = {"quote": "Minta   Kft.", "locator": {"kind": "pdf", "page": 2}}
    block = {"quote": "x" * 100, "locator": {"kind": "word", "block_index": 11}}
    text = {"quote": "0012", "locator": {"kind": "text", "start": 0, "end": 30}, "quote_span": {"start": 10, "end": 14}}
    lines = export._source_text([cell, page, block, text]).split("\n")
    assert lines[0] == "12 500 Ft [Sheet1!B4]" and lines[1] == "Minta Kft. [p. 2]"
    assert lines[2].endswith("\u2026 [\u00b6 12]") and len(lines[2].split(" [")[0]) == 80
    assert lines[3] == "0012 [10\u201314]"


def test_native_table_shows_the_source_and_labels_the_states(tmp_path):
    with store.use_store(tmp_path / "view.sqlite"):
        rid, _item, _publication, _cite = published_run(tmp_path)
        page = datasets.query("native_facts", {"run_id": rid}, Query())
        columns = {c["key"]: c for c in page["columns"]}
        assert not columns["source"].get("hidden") and columns["source_citations"].get("hidden")
        assert columns["correctness"].get("hidden")
        assert columns["machine_state"]["labels"]["stated"] and columns["reading_status"]["labels"]["partial"]
        row = page["rows"][0]
        assert row["source"].startswith(row["effective_value"]) and "[" in row["source"]
