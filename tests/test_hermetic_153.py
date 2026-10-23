"""153 (review F1): the test suite never opens the real store.

The review of 2026-10-13 found 38 tests opening `store/jav.sqlite` (the call-site pages' ledger figures, a documents
table's directions), so they ran the schema set-up on the store the service and the worker use and read its ledger.
The shared fixture points the default store at a temporary file for every test.
"""

from jav.core import config, store


def test_the_default_store_is_a_temporary_file():
    assert store.STORE_PATH != config.STORE_PATH
    assert config.STORE_PATH not in store.STORE_PATH.parents
    with store.connect() as c:
        c.execute("SELECT 1")
    assert store.STORE_PATH.exists()
