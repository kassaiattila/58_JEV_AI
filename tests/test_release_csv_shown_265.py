"""265 (code review APPW-09): a released version's CSV downloads are stored as a download shows them.

A run's CSV download shows its fixed headers and the data points' marks in the request's language (231 D4, the
download language rule of 2026-10-29), but a released version stored its CSVs from the raw tables: English sources
and the "igen" code, frozen for good. Now the release stores them through the same shown table. Synthetic PDFs, a fake
JEV client, no paid calls.
"""

import csv
import io

from jav.app import export
from jav.core import display
from tests import test_flexible_package_160c as fp
from tests.test_flexible_package_160c import _assign, _package
from tests.test_package_release_171 import _live, _release

env = fp.env  # the 160-C fixture: a store of its own, two synthetic invoices, a fake JEV client


def _head(content: bytes) -> list[str]:
    return next(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))


def test_a_released_version_s_csvs_carry_the_shown_headers(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    _live(c, wp["id"])
    assert _release(c, wp["id"]).status_code == 200
    documents = _head(c.get(f"/api/workpackages/{wp['id']}/versions/1/files/documents.csv").content)
    fixed = export.document_head()
    with display.use("hu"):
        shown = [display.text(h) for h in fixed]
    assert documents[:len(fixed)] == shown and shown != fixed
    datapoints = _head(c.get(f"/api/workpackages/{wp['id']}/versions/1/files/datapoints.csv").content)
    with display.use("hu"):
        assert datapoints == export.shown_table("datapoints", export.TABLES["datapoints"]([])[0], [])[0]
