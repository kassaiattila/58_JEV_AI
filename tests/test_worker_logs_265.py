"""265 (code review CORE-02): each worker slot writes its own log.

Several workers rotated one `worker.log`; on Windows the rotation of a file another process holds fails and its
entries were lost. The first slot keeps `worker.log`, a further one writes `worker-<n>.log`.
"""

from jav.cli.work_cli import worker_log_name


def test_each_slot_has_its_own_log() -> None:
    assert [worker_log_name(s) for s in (None, 1, 2, 3)] == ["worker", "worker", "worker-2", "worker-3"]
