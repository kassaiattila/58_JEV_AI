"""Bounded artificial failure cases for new readers, not production data."""
from io import BytesIO
import os
import zipfile

import pytest

from jav.readers.limits import DEFAULT_LIMITS
from jav.readers.pipeline import read_files

pytest.importorskip("docx", reason="Native reader dependencies await integration")
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object reader boundary")


def package(members, *, compression=zipfile.ZIP_STORED):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return output.getvalue()


CASES = [
    ("absolute", "test.docx", lambda: package([("/outside.xml", "<root/>")]), "excluded", {}),
    ("drive", "test.docx", lambda: package([("C:/outside.xml", "<root/>")]), "excluded", {}),
    ("backslash", "test.docx", lambda: package([("word/document.xml", "<root/>")]).replace(
        b"word/document.xml", b"word\\document.xml"), "excluded", {}),
    ("parent", "test.xlsx", lambda: package([("../outside.xml", "<root/>")]), "excluded", {}),
    ("macro", "test.xlsx", lambda: package([("xl/vbaProject.bin", b"synthetic")]), "excluded", {}),
    ("embedded-object", "test.docx", lambda: package([("word/embeddings/object.bin", b"synthetic")]), "excluded", {}),
    ("external", "test.docx", lambda: package([("word/_rels/document.xml.rels",
        '<Relationships><Relationship TargetMode="External" Target="https://example.invalid/never-fetch"/></Relationships>')]), "excluded", {}),
    ("entity", "test.xml", lambda: b'<!DOCTYPE root [<!ENTITY payload "untrusted">]><root>&payload;</root>', "corrupt", {}),
    ("zip-entity", "test.docx", lambda: package([("word/document.xml",
        '<!DOCTYPE root [<!ENTITY payload "untrusted">]><root>&payload;</root>')]), "corrupt", {}),
    ("zip-expansion", "test.docx", lambda: package([("word/document.xml", "<root>" + "x" * 50000 + "</root>")],
        compression=zipfile.ZIP_DEFLATED), "resource_limited", {"expansion_ratio": 10}),
    ("entry-count", "test.docx", lambda: package([("a.xml", "<root/>"), ("b.xml", "<root/>")]),
        "resource_limited", {"archive_entries": 1}),
    ("duplicate-json", "test.json", lambda: b'{"code":"first","code":"second"}', "corrupt", {}),
    ("nonfinite-json", "test.json", lambda: b'{"amount":NaN}', "corrupt", {}),
    ("invalid-encoding", "test.txt", lambda: b'\xff\xfe\x80', "corrupt", {}),
    ("wrong-extension", "test.xlsx", lambda: b"not a workbook", "unsupported", {}),
    ("empty-input", "test.txt", lambda: b"", "corrupt", {}),
]


@pytest.mark.parametrize("label,name,make,status,changes", CASES, ids=[case[0] for case in CASES])
def test_hostile_input_is_visible_and_never_claims_complete(tmp_path, label, name, make, status, changes):
    path = tmp_path / name
    path.write_bytes(make())
    delivery = read_files([path], limits=DEFAULT_LIMITS.model_copy(update=changes))
    result = delivery.bundle.results[0]
    assert result.status == status
    assert result.issues
    assert not result.elements
    assert delivery.bundle.manifest.occurrences[0].object_sha256 is not None
