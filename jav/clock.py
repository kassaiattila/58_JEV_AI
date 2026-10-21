"""The one clock of the shared code and the domains (194, plan G-tidy R2).

Plain-language summary: every record of when something happened is written in UTC, to the second, in one form
(`2026-10-21T18:09:02+00:00`). Each module used to carry its own two-line helper for it; now they all read this one.
A module keeps its own `_now` name for it (`from jav.clock import utc_stamp as _now`), so a test can still stop the
clock of that one module. Names a person reads beside the machine's own clock (the backup's folders and times, the
files of a measurement) stay in local time; so does the email receiver's download time, which this step leaves as
it was.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """The current moment, in UTC."""
    return datetime.now(timezone.utc)


def utc_stamp() -> str:
    """The current moment in UTC as an ISO text to the second: the form every stored time uses."""
    return utc_now().isoformat(timespec="seconds")


__all__ = ["utc_now", "utc_stamp"]
