"""Shared test setup (065): the tests must not write to the operational log.

The `worker` command (`jav/cli/work_cli.py`) attaches the operational log (`runs/logs/worker.log`) to the root logger; in
the test suite this left false "worker started / processed=1" lines in the real log on every run, and after attaching,
the other tests' logs went there too. While the tests run, the log folder is temporary.
"""

import pytest

from jav.app import registrations
from jav.ai import gpt_choice
from jav.core import applog, calls


@pytest.fixture(autouse=True, scope="session")
def _registrations():
    """173 (plan 170 E2): the tests run with every registration the command line and the service make at start
    (`registrations.load_all`: a package kind's rule, the delete guards, the party references)."""
    registrations.load_all()
    yield


@pytest.fixture(autouse=True, scope="session")
def _no_disk_flush():
    """189: the tests' stores are temporary files, so SQLite need not wait for the disk after a write (`store.tune`).
    Creating a store with its schema took about 0.55 s, mostly that wait, and nearly every test creates one."""
    from jav.core import store

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(store, "SYNCHRONOUS", "OFF")
        yield


@pytest.fixture(autouse=True, scope="session")
def _commit_read_once():
    """203: a service records the repository's commit when it is built (`version.commit_info`: two git calls, about
    75 ms), and the tests build one about 450 times while the commit stays the same. The repository's own commit is read
    once; a look at another folder, and a test that replaces the function, are unaffected."""
    from jav.core import version

    real = version.commit_info
    seen: dict[str, str | bool | None] = {}

    def once(root=None):
        if root is not None:
            return real(root)
        if not seen:
            seen.update(real())
        return dict(seen)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(version, "commit_info", once)
        yield


@pytest.fixture(autouse=True, scope="session")
def _no_ops_log(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(applog, "LOG_DIR", tmp_path_factory.mktemp("logs"))
        yield


@pytest.fixture(autouse=True)
def _no_default_store(tmp_path_factory, monkeypatch):
    """153 (review F1): a test never opens the real store (`store/jav.sqlite`: personal data, used by the running
    service and worker). 38 tests did, through code that reads the default store (the call-site pages' ledger figures, a
    documents table's directions): they ran the schema set-up on it and read its ledger. The default store is now a
    temporary file per test; a test that needs a store names it (`store.use_store`) or uses this empty one."""
    from jav.core import store

    monkeypatch.setattr(store, "STORE_PATH", tmp_path_factory.mktemp("default-store") / "jav.sqlite")


@pytest.fixture(autouse=True)
def _configs_not_frozen():
    """231: a test that runs the long-running processes' start-up (`preload.preload`) freezes the configs (`cfg.freeze`);
    the next test reads the folder as it is again, as a command does. U4a: and without the installation's defaults,
    which that start-up names to the config reader (`rule_defaults.use`)."""
    yield
    from jav.core import cfg

    if cfg.frozen():
        cfg.unfreeze()
    cfg.use_defaults(None)


@pytest.fixture(autouse=True)
def _no_real_ocr_cache(tmp_path_factory, monkeypatch):
    """160 (review T-1): a test never reads or writes the real OCR cache (`runs/ocr/`: recognised text of real
    documents). Two tests lived from it, so they failed on a clean copy and added files to it here. The cache is an
    empty temporary folder per test."""
    from jav.documents import ocr

    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path_factory.mktemp("ocr-cache"))


@pytest.fixture(autouse=True)
def _no_live_gpt_choice():
    """089: a test never sends a GPT choice question (type or email intent without JEV) to OpenAI, which would be a paid
    call; a test that needs an answer installs its own stand-in with `gpt_choice.use_agent_factory`."""

    def refuse(output_model, instructions):
        raise AssertionError("a test tried a live GPT call (jav/ai/gpt_choice.py); install a stand-in with use_agent_factory")

    with gpt_choice.use_agent_factory(refuse):
        yield


@pytest.fixture(autouse=True)
def _no_live_mailbox(monkeypatch):
    """231 (C3d): a test never runs the Outlook bridge (`scripts/outlook_bridge.ps1` through PowerShell: a real mailbox
    of the machine). A test that downloads passes its own runner (the tests' `FakeBridge`); one that would reach the
    default runner fails instead."""
    from jav.domains.email import mailbox_bridge  # 231 (C3h): where the bridge is called

    def refuse(argv, timeout):
        raise AssertionError("a test tried to run the Outlook bridge (jav/domains/email/mailbox_bridge.py); pass a runner")

    monkeypatch.setattr(mailbox_bridge, "_subprocess_runner", refuse)


@pytest.fixture(autouse=True)
def _no_live_quote_letter():
    """196: a test never asks OpenAI for a reply letter's paragraph (a paid call); a test that needs one installs its
    own stand-in with `quote_letter.use_agent_factory`."""
    from jav.domains.quotes import quote_letter

    def refuse(output_model, instructions):
        raise AssertionError("a test tried a live GPT call (jav/domains/quotes/quote_letter.py); install a stand-in with use_agent_factory")

    with quote_letter.use_agent_factory(refuse):
        yield


@pytest.fixture(autouse=True)
def _no_jev_question_without_jev(request, monkeypatch):
    """160 (plan F-csak-gpt, L4): a JEV question asked in processing without JEV fails the test. In production it is
    refused and becomes the `jev_unavailable:disabled` to-do, which a test could overlook; a test of the refusal
    itself is marked `jev_refusal`."""
    if request.node.get_closest_marker("jev_refusal"):
        return
    from jav.ai import jev

    def fail(request_id):
        pytest.fail(f"a JEV question ({request_id}) was asked in processing without JEV")

    monkeypatch.setattr(jev, "_refuse", fail)


@pytest.fixture(autouse=True)
def _no_live_connectors():
    """130: a test never asks the MNB rate service; 231 (C2a): nor any other external service through its connector. A
    test that needs an answer installs its own stand-in with `connectors.use_transport` (`fx.use_transport`)."""
    from jav.core import connectors

    def refuse(url, body, headers, timeout):
        raise AssertionError(f"a test tried a live question to an external service ({url}, jav/core/connectors.py);"
                             " install a stand-in with use_transport")

    with connectors.use_transport(refuse):
        yield


@pytest.fixture(autouse=True)
def _no_provider_keys(monkeypatch):
    """120: no test reaches a paid provider. The keys are read when a call is built (`jav/core/config.py`), so without them
    an unpatched OpenAI or JEV call fails with `MissingAPIKeyError` (JEV: `missing_key`) instead of spending. A debug
    run that left the native GPT extraction and JEV support unpatched made three small live calls before this guard."""
    from jav.core.config import API_KEY_ENV_VARS, AZURE_DI_ENV_VARS, OPENAI_KEY_ENV_VAR

    for name in (*API_KEY_ENV_VARS, OPENAI_KEY_ENV_VAR, *AZURE_DI_ENV_VARS):  # 121: Azure is called directly too
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _registered_todo_kinds(monkeypatch):
    """177 (plan 170 E6; the owner's decision of 2026-10-19: the tests watch it, the store does not): every to-do a
    processing step raises in a test is of a kind registered in `configs/todo_kinds.json`, so that the interface's
    label test covers it. A reason a test writes itself (synthetic) is the test's own and is not checked."""
    import sys

    from jav.core import store, todo_kinds

    real = store.review_enqueue
    found: dict[str, str] = {}

    def recording(**kwargs):
        caller = sys._getframe(1).f_globals.get("__name__", "")
        if not caller.startswith("tests"):
            found.update(todo_kinds.unregistered(list(kwargs.get("reasons") or [])))
        return real(**kwargs)

    monkeypatch.setattr(store, "review_enqueue", recording)
    yield
    if found:
        pytest.fail(f"to-dos of unregistered kinds (configs/todo_kinds.json): {sorted(found.values())}")


@pytest.fixture(autouse=True)
def _release_call_holders():
    """092: the holder locks a test's reservations took are let go after it, so that no lock file stays open in a
    temporary folder and no test inherits another's holder."""
    yield
    calls.release_all_holders()
