"""The process core's failure tests with separate worker processes (213; the engine trial's tests of 212, ported).

Plain-language summary: the invented quote case (`tests/process_quote.py`: two checks, a paid pricing step, a person's
approval, a wait for a missing attachment until a deadline, a handover to another system) runs on the process core in
worker processes, and the tests break it on purpose. A worker dies at a named point and a new one carries on (T01,
T08); the same start and events arrive several times, once with other content (T02); an attachment races its deadline
(T03); the receiver takes a handover and its reply is lost (T04); a new definition version comes in under a waiting
case (T06); two workers share one budget (T07). Each test checks that no work is lost and none is done twice. These
are the standing tests of the process core (DECISIONS 212). Synthetic data; no network and no paid call.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from jav.core import calls, store
from jav.core.process import actor as actors
from jav.core.process import engine, outbox
from tests import process_quote as quote
from tests import process_worker

ROOT = Path(__file__).resolve().parents[1]
POLL_S = 0.1
WAIT_S = 30.0
SETTLE_S = 3.0  # how long a test watches for work that should not happen
STOP_WAIT_S = 15.0
SHARED = "invented-shared"
ME = actors.person("Tester")
View = dict[str, Any]


class Driver:
    """The test's hands: starts cases and sends events in the test's process, runs workers as separate processes."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._workers: dict[subprocess.Popen[bytes], str] = {}

    def start(self, case_id: str, request: dict[str, Any], version: int = 1) -> str:
        return engine.start(case_id, quote.VERSIONS[version], request, ME)

    def send(self, case_id: str, event_id: str, kind: str, payload: dict[str, Any]) -> str:
        return engine.send_event(case_id, event_id, kind, payload, ME)

    def view(self, case_id: str) -> View:
        return engine.state(case_id)

    def cancel(self, case_id: str) -> str:
        return engine.cancel(case_id, ME)

    def settle_handover(self, case_id: str, outcome: str) -> str:
        return outbox.settle(quote.handover_id(case_id), outcome, ME)

    def spawn_worker(self, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
        base = {k: v for k, v in os.environ.items() if not k.upper().startswith("PROCESS_")}
        name = f"w{len(self._workers) + 1}"
        with open(self.folder / f"worker-{name}.log", "ab") as out:
            p = subprocess.Popen([sys.executable, "-m", "tests.process_worker", "--dir", str(self.folder), "--name", name],
                                 cwd=ROOT, env={**base, **(env or {})}, stdout=out, stderr=subprocess.STDOUT)
        self._workers[p] = name
        return p

    def stop_worker(self, p: subprocess.Popen[bytes]) -> int | None:
        if p.poll() is None:
            process_worker.stop_file(self.folder, self._workers[p]).touch()
            try:
                p.wait(timeout=STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        return p.returncode

    def close(self) -> None:
        for p in self._workers:
            self.stop_worker(p)


@pytest.fixture()
def driver(tmp_path: Path) -> Iterator[Driver]:
    d = Driver(tmp_path)
    with store.use_store(tmp_path / quote.STORE_FILE):
        try:
            yield d
        finally:
            d.close()


def request(**changes: Any) -> dict[str, Any]:
    return {"customer": "Example Ltd", "items": [{"sku": "A-1", "qty": 2}], "has_attachment": True, "deadline_s": 3.0,
            **changes}


def wait_for(check: Callable[[], Any], what: str, timeout: float = WAIT_S) -> Any:
    end = time.monotonic() + timeout
    while not (value := check()):
        if time.monotonic() > end:
            pytest.fail(f"timed out after {timeout:.0f} s waiting for {what}")
        time.sleep(POLL_S)
    return value


def wait_view(driver: Driver, case_id: str, cond: Callable[[View], bool], what: str, timeout: float = WAIT_S) -> View:
    end = time.monotonic() + timeout
    while not cond(view := driver.view(case_id)):
        if time.monotonic() > end:
            pytest.fail(f"{case_id}: timed out after {timeout:.0f} s waiting for {what}; last view: {view}")
        time.sleep(POLL_S)
    return view


def waiting(step: str, what: str) -> Callable[[View], bool]:
    return lambda view: view["steps"][step]["waiting_for"] == what


def closed(view: View) -> bool:
    return view["status"] == "closed"


def rows(view: View, kind: str, step: str | None = None, **detail: Any) -> list[dict[str, Any]]:
    return [h for h in view["history"] if h["kind"] == kind and (step is None or h["step_id"] == step)
            and all(h["detail"].get(k) == v for k, v in detail.items())]


def business(view: View) -> View:
    """The case as the application keeps it, without who holds it now."""
    return {k: v for k, v in view.items() if k != "claimed_by"}


def approve(driver: Driver, case_id: str, event_id: str, decision: str = "approve") -> str:
    view = wait_view(driver, case_id, waiting("approval", "approval"), "the approval wait")
    version = view["steps"]["pricing"]["result_version"]
    return driver.send(case_id, event_id, "approval", {"decision": decision, "result_version": version})


def crash_env(tmp_path: Path, point: str) -> dict[str, str]:
    return {quote.CRASH_ENV: point, quote.CRASH_MARK_ENV: str(tmp_path / f"crash-{point}.mark")}


def assert_crashed(p: subprocess.Popen[bytes], tmp_path: Path, point: str) -> None:
    assert p.wait(timeout=WAIT_S) == quote.CRASH_EXIT
    assert (tmp_path / f"crash-{point}.mark").read_text(encoding="utf-8") == point


def provider_calls(tmp_path: Path, case_id: str | None = None) -> int:
    return quote.physical_calls(tmp_path, "provider", case_id)


def receiver_calls(tmp_path: Path, handover: str | None = None) -> int:
    return quote.physical_calls(tmp_path, "receiver", handover)


def deadline_of(view: View) -> float:
    return float(next(t["due_at"] for t in view["timers"] if t["name"] == "deadline"))


# --- T01: a worker dies; a new one carries on ------------------------------------------------------------------------


def test_t01_crash_before_the_approval_wait(driver: Driver, tmp_path: Path) -> None:
    p = driver.spawn_worker(crash_env(tmp_path, "before_approval_wait"))
    assert driver.start("q1", request()) == "started"
    assert_crashed(p, tmp_path, "before_approval_wait")
    view = driver.view("q1")
    assert view["steps"]["pricing"]["state"] == "done" and view["steps"]["approval"]["waiting_for"] is None
    driver.spawn_worker()
    wait_view(driver, "q1", waiting("approval", "approval"), "the approval wait after the restart")
    assert approve(driver, "q1", "q1-approve") == "accepted"
    view = wait_view(driver, "q1", closed, "the case to close")
    assert view["outcome"] == "done"
    assert len(rows(view, "step_done", "pricing")) == 1 and len(rows(view, "waiting", "approval")) == 1
    assert provider_calls(tmp_path) == 1 and receiver_calls(tmp_path) == 1


def test_t01_crash_while_waiting_for_the_attachment(driver: Driver, tmp_path: Path) -> None:
    p = driver.spawn_worker(crash_env(tmp_path, "waiting_attachment"))
    driver.start("q2", request(has_attachment=False, deadline_s=4.0))
    assert approve(driver, "q2", "q2-approve") == "accepted"
    assert_crashed(p, tmp_path, "waiting_attachment")
    view = driver.view("q2")
    assert view["steps"]["attachment"]["waiting_for"] == "attachment"
    deadline = deadline_of(view)
    driver.spawn_worker()  # nothing arrives: only the deadline, which must have survived the crash, closes the case
    view = wait_view(driver, "q2", closed, "the deadline to close the case", timeout=deadline - time.time() + WAIT_S)
    assert view["outcome"] == "expired"
    assert rows(view, "closed", outcome="expired")[0]["at"] >= deadline
    assert receiver_calls(tmp_path) == 0


def test_t01_crash_after_the_handover_was_sent(driver: Driver, tmp_path: Path) -> None:
    p = driver.spawn_worker(crash_env(tmp_path, "after_handover_sent"))
    driver.start("q3", request())
    assert approve(driver, "q3", "q3-approve") == "accepted"
    assert_crashed(p, tmp_path, "after_handover_sent")
    assert driver.view("q3")["handovers"][0]["status"] == "sent" and receiver_calls(tmp_path) == 1
    driver.spawn_worker()
    view = wait_view(driver, "q3", waiting("handover", outbox.SETTLEMENT), "the unanswered handover to wait for a person")
    assert view["handovers"][0]["status"] == "uncertain" and receiver_calls(tmp_path) == 1
    assert driver.settle_handover("q3", "acknowledged") == "acknowledged"
    view = wait_view(driver, "q3", closed, "the case to close")
    assert view["outcome"] == "done" and receiver_calls(tmp_path) == 1


# --- T02: repeats are one transition; other content under the same id is a conflict ----------------------------------


def test_t02_repeated_and_conflicting_events(driver: Driver, tmp_path: Path) -> None:
    driver.spawn_worker()
    assert [driver.start("q4", request(has_attachment=False, deadline_s=60.0)) for _ in range(3)] == [
        "started", "exists", "exists"]
    with pytest.raises(engine.cases.CaseConflict):
        driver.start("q4", request(customer="Other Ltd"))
    view = wait_view(driver, "q4", waiting("approval", "approval"), "the approval wait")
    version = view["steps"]["pricing"]["result_version"]
    assert driver.send("q4", "q4-stale", "approval", {"decision": "approve", "result_version": version + 1}) == "accepted"
    view = wait_view(driver, "q4", lambda v: v["events"]["q4-stale"]["status"] == "refused", "the stale approval's refusal")
    assert view["steps"]["approval"]["waiting_for"] == "approval"
    ok = {"decision": "approve", "result_version": version}
    assert [driver.send("q4", "q4-approve", "approval", ok) for _ in range(3)] == ["accepted", "duplicate", "duplicate"]
    before = business(wait_view(driver, "q4", waiting("attachment", "attachment"), "the attachment wait"))
    assert driver.send("q4", "q4-approve", "approval", {**ok, "decision": "reject"}) == "conflict"
    after = business(driver.view("q4"))
    assert after["events"]["q4-approve"]["conflicts"] == 1
    after["events"]["q4-approve"]["conflicts"] = 0
    assert after == before
    attachment = {"name": "drawing.pdf"}
    assert [driver.send("q4", "q4-attachment", "attachment", attachment) for _ in range(3)] == [
        "accepted", "duplicate", "duplicate"]
    assert driver.send("q4", "q4-attachment", "attachment", {"name": "other.pdf"}) == "conflict"
    view = wait_view(driver, "q4", closed, "the case to close")
    assert view["outcome"] == "done"
    assert len(rows(view, "started")) == 1 and len(rows(view, "event_refused")) == 1
    assert len(rows(view, "event_applied", "approval")) == 1 and len(rows(view, "event_applied", "attachment")) == 1
    assert len(rows(view, "handover_acknowledged")) == 1 and len(rows(view, "closed")) == 1
    assert provider_calls(tmp_path, "q4") == 1 and receiver_calls(tmp_path) == 1

    driver.start("q5", request())  # a rejection closes the case without a handover
    assert approve(driver, "q5", "q5-reject", "reject") == "accepted"
    view = wait_view(driver, "q5", closed, "the rejected case to close")
    assert view["outcome"] == "rejected" and view["handovers"] == []

    driver.start("q6", request())  # a cancelled case keeps a later approval, ignored
    wait_view(driver, "q6", waiting("approval", "approval"), "the approval wait")
    assert driver.cancel("q6") == "cancelled"
    assert driver.send("q6", "q6-approve", "approval", {"decision": "approve", "result_version": 1}) == "accepted"
    view = driver.view("q6")
    assert view["outcome"] == "cancelled" and view["events"]["q6-approve"]["status"] == "ignored"
    assert receiver_calls(tmp_path) == 1


# --- T03: an event races its deadline; a late deadline changes nothing -----------------------------------------------


def test_t03_attachment_and_deadline_race(driver: Driver, tmp_path: Path) -> None:
    driver.spawn_worker()
    cases = ("q7", "q8")
    for case_id in cases:
        driver.start(case_id, request(has_attachment=False, deadline_s=3.0))
    for case_id in cases:
        assert approve(driver, case_id, f"{case_id}-approve") == "accepted"
    deadline = {c: deadline_of(wait_view(driver, c, waiting("attachment", "attachment"), "the attachment wait"))
                for c in cases}
    assert driver.send("q8", "q8-attachment", "attachment", {"name": "early.pdf"}) == "accepted"  # well before
    wait_for(lambda: time.time() >= deadline["q7"], "q7's deadline")
    assert driver.send("q7", "q7-attachment", "attachment", {"name": "on-the-dot.pdf"}) == "accepted"  # at it
    final = {c: wait_view(driver, c, closed, "the case to close") for c in cases}
    view = final["q7"]
    winners = rows(view, "event_applied", "attachment") + rows(view, "closed", outcome="expired")
    assert len(winners) == 1, f"exactly one transition wins: {view['history']}"
    if winners[0]["kind"] == "event_applied":
        assert view["outcome"] == "done" and view["events"]["q7-attachment"]["status"] == "applied"
        assert view["handovers"][0]["status"] == "acknowledged"
    else:
        assert view["outcome"] == "expired" and view["events"]["q7-attachment"]["status"] == "ignored"
        assert view["handovers"] == []
    print(f"T03 race winner: {winners[0]['kind']}")
    assert final["q8"]["outcome"] == "done" and not rows(final["q8"], "closed", outcome="expired")
    sent = receiver_calls(tmp_path)
    wait_for(lambda: time.time() >= max(deadline.values()) + SETTLE_S, "both deadlines to pass long ago")
    for case_id in cases:  # a deadline on a closed step starts no work
        assert business(driver.view(case_id)) == business(final[case_id])
    assert receiver_calls(tmp_path) == sent


# --- T04 + T08: the outbox ---------------------------------------------------------------------------------------------


def test_t04_lost_reply_is_uncertain_and_never_sent_again(driver: Driver, tmp_path: Path) -> None:
    quote.set_system(tmp_path, "receiver", "lose_reply", "1")
    p = driver.spawn_worker()
    driver.start("q9", request())
    assert approve(driver, "q9", "q9-approve") == "accepted"
    view = wait_view(driver, "q9", waiting("handover", outbox.SETTLEMENT), "the handover with a lost reply to wait")
    handover = view["handovers"][0]["handover_id"]
    assert view["handovers"][0]["status"] == "uncertain" and receiver_calls(tmp_path, handover) == 1
    driver.stop_worker(p)
    driver.spawn_worker()  # a restart sends nothing again either
    time.sleep(SETTLE_S)
    view = driver.view("q9")
    assert view["handovers"][0]["status"] == "uncertain" and view["steps"]["handover"]["waiting_for"] == outbox.SETTLEMENT
    assert receiver_calls(tmp_path, handover) == 1
    quote.set_system(tmp_path, "receiver", "lose_reply", "0")
    assert driver.settle_handover("q9", "acknowledged") == "acknowledged"
    view = wait_view(driver, "q9", closed, "the settled case to close")
    assert view["outcome"] == "done" and receiver_calls(tmp_path, handover) == 1


def test_t08_handover_recorded_before_a_crash_is_sent_once(driver: Driver, tmp_path: Path) -> None:
    p = driver.spawn_worker(crash_env(tmp_path, "after_case_saved_before_notify"))
    driver.start("q10", request())
    assert approve(driver, "q10", "q10-approve") == "accepted"
    assert_crashed(p, tmp_path, "after_case_saved_before_notify")
    view = driver.view("q10")
    assert view["handovers"][0]["status"] == "recorded" and receiver_calls(tmp_path) == 0
    driver.spawn_worker()
    view = wait_view(driver, "q10", closed, "the recorded handover to be sent after the restart")
    assert view["outcome"] == "done" and view["handovers"][0]["status"] == "acknowledged"
    assert receiver_calls(tmp_path, view["handovers"][0]["handover_id"]) == 1


# --- T06: a new definition version under a waiting case ----------------------------------------------------------------


def test_t06_new_version_under_a_waiting_case(driver: Driver, tmp_path: Path) -> None:
    p = driver.spawn_worker()
    driver.start("q11", request())
    view = wait_view(driver, "q11", waiting("approval", "approval"), "the approval wait under version 1")
    assert view["definition"]["version"] == "1"
    driver.stop_worker(p)
    driver.spawn_worker()  # the code that knows version 2 is in force
    driver.start("q12", request(), version=2)  # a case started now runs the new step
    assert approve(driver, "q11", "q11-approve") == "accepted"
    view = wait_view(driver, "q11", closed, "the old case to finish")
    assert view["outcome"] == "done" and view["definition"]["version"] == "1" and "notify" not in view["steps"]
    assert approve(driver, "q12", "q12-approve") == "accepted"
    view = wait_view(driver, "q12", closed, "the new case to close")
    assert view["outcome"] == "done" and view["definition"]["version"] == "2"
    assert view["steps"]["notify"]["state"] == "done"


# --- T07: two workers, one budget ------------------------------------------------------------------------------------


def _shared_budget() -> None:
    calls.set_budget(SHARED, quote.PROVIDER, Decimal("1.00"))


def test_t07_shared_budget_while_the_first_worker_holds_a_claim(driver: Driver, tmp_path: Path) -> None:
    _shared_budget()
    quote.set_system(tmp_path, "provider", "delay_s", "5.0")
    cases = ("q13", "q14")
    for case_id in cases:
        driver.start(case_id, request(budget_scope=SHARED))
    driver.spawn_worker()
    wait_for(lambda: provider_calls(tmp_path) == 1, "the first worker's pricing call to be in flight")
    driver.spawn_worker()  # starts while the first worker holds its case
    priced_or_blocked = lambda v: v["steps"]["approval"]["waiting_for"] == "approval" or (  # noqa: E731
        v["steps"]["pricing"]["waiting_for"] in ("budget", "pricing_settlement"))
    views = {c: wait_view(driver, c, priced_or_blocked, "the pricing outcome") for c in cases}
    assert not any(rows(v, "waiting", "pricing", **{"for": "pricing_settlement"}) for v in views.values()), \
        "a live claim was taken over"
    priced = next(v for v in views.values() if v["steps"]["approval"]["waiting_for"] == "approval")
    blocked = next(v for v in views.values() if v["steps"]["pricing"]["waiting_for"] == "budget")
    assert rows(priced, "step_done", "pricing")[0]["pid"] != rows(blocked, "waiting", "pricing")[0]["pid"]  # two workers
    assert provider_calls(tmp_path) == 1
    assert calls.budget_usage(SHARED)["committed_usd"] == quote.BILLED_USD  # the one call, at its known cost


def test_t07_shared_budget_after_a_worker_died_in_a_paid_call(driver: Driver, tmp_path: Path) -> None:
    _shared_budget()
    cases = ("q15", "q16")
    for case_id in cases:
        driver.start(case_id, request(budget_scope=SHARED))
    assert_crashed(driver.spawn_worker(crash_env(tmp_path, "pricing_in_flight")), tmp_path, "pricing_in_flight")
    driver.spawn_worker()
    driver.spawn_worker()  # two workers start together after the crash
    views = {c: wait_view(driver, c, lambda v: v["steps"]["pricing"]["waiting_for"] in ("budget", "pricing_settlement"),
                          "the pricing outcome") for c in cases}
    assert sorted(v["steps"]["pricing"]["waiting_for"] for v in views.values()) == ["budget", "pricing_settlement"]
    time.sleep(SETTLE_S)  # several retry rounds: the unknown outcome is not called again, the budget stays short
    assert {c: driver.view(c)["steps"]["pricing"]["waiting_for"] for c in cases} == {
        c: v["steps"]["pricing"]["waiting_for"] for c, v in views.items()}
    assert provider_calls(tmp_path) == 1
    assert calls.budget_usage(SHARED)["committed_usd"] == quote.MAX_COST_USD  # the unknown call's reservation is kept
    uncertain = next(c for c, v in views.items() if v["steps"]["pricing"]["waiting_for"] == "pricing_settlement")
    assert [r["status"] for r in calls.journal(uncertain)] == ["uncertain"]
