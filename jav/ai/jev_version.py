"""The pinned JEV version and the provider's moving name (200, decision of 2026-10-22).

Plain-language summary: the system asks JEV by a concrete version (`configs/models.json` `jev.model`, e.g.
`jev-1.14.0`), so its answers, and the cached answers they are keyed by, do not change by themselves. The provider's
moving name (`jev.watch_alias`, `jev-latest`) is only looked at: the daily backup resolves it once (one tiny probe, as
the adapter always did for an alias; `runs/cache/_model_versions.json`), and the start-up check and the System page
say when it points to a newer version than the pinned one. Switching is a decision with a measurement (DECISIONS 200):
on 2026-10-22 the moving name went from jev-1.13.0 to jev-1.14.0 without notice, and every golden set had to be
measured again.

Layer: business module over the JEV adapter (`jav.ai.jev`), which keeps the resolution file.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.ai.jev import _CONCRETE_MODEL, MODEL_VERSIONS_FILE, JevAdapter
from jav.core import cfg, jsonfile
from jav.core.config import CACHE_DIR, JEV_ALIAS_TTL_H, JEV_MODEL, JEV_WATCH_ALIAS, RUNS_DIR

WATCH_ALIAS = JEV_WATCH_ALIAS
STALE_DAYS = 3  # the daily backup looks once a day; three days without a look is said
# 272 (K1a): the outcome of the last daily look, so the start-up check can say a look that could not run
LOOK_PATH = RUNS_DIR / "jev-version-look.json"


class LookFailed(RuntimeError):
    """272 (K1a): the daily look was due but the moving name was not resolved again (the adapter kept its earlier
    resolution: no budget, no key, or JEV unavailable; its warning names the reason)."""


def daily_budget_usd() -> Decimal:
    """272 (K1a, the owner's decision of 2026-11-01): the daily look's own JEV budget, `configs/service.json`
    `backup.jev_version_usd`; 0 turns the look off (it is then said as failed)."""
    return Decimal(str(cfg.load("service").get("backup", {}).get("jev_version_usd", 0)))


def status(*, cache_dir: Path | None = None, pinned: str = JEV_MODEL) -> dict[str, Any]:
    """Where the moving name pointed at its last look, against the pinned version; no call. `newer` is None when there
    has been no look (or the model is not pinned); `stale` when the last look is older than `STALE_DAYS`."""
    path = (cache_dir or CACHE_DIR) / MODEL_VERSIONS_FILE
    try:
        entry = json.loads(path.read_text(encoding="utf-8")).get(WATCH_ALIAS)
    except (OSError, ValueError, AttributeError):  # missing or unreadable: no look, as the adapter reads it
        entry = None
    latest = entry.get("model") if isinstance(entry, dict) else None
    checked = entry.get("resolved_at") if isinstance(entry, dict) else None
    age_days = None
    if checked:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(checked)).total_seconds() / 86400
    concrete = bool(_CONCRETE_MODEL.match(pinned))
    look = jsonfile.read_tolerant(LOOK_PATH)
    failed = look.get("failed_at") if isinstance(look, dict) else None
    return {"pinned": pinned, "watch_alias": WATCH_ALIAS, "latest": latest, "checked_at": checked,
            "newer": (latest != pinned) if latest and concrete else None,
            "stale": age_days is not None and age_days > STALE_DAYS, "age_days": age_days,
            "look_failed_at": failed if isinstance(failed, str) else None}


def refresh(*, adapter: JevAdapter | None = None, pinned: str = JEV_MODEL,
            budget_usd: Decimal | None = None) -> dict[str, Any]:
    """The daily look: resolves the moving name (a probe only when its last resolution is older than the adapter's
    alias TTL), then returns `status`. 272 (K1a): outside a run the probe goes through the call log under its own
    daily budget (`daily_budget_usd`; one scope a day, so a second backup on the same day spends from the same
    limit); a look that was due and did not resolve the name again raises `LookFailed` and is kept for the start-up
    check. Other failures propagate; the daily backup logs them and goes on."""
    from jav.core import calls  # deferred, as in the adapter: the call log builds on the store

    adapter = adapter or JevAdapter()
    before = _resolved_at(adapter.cache_dir)
    due = before is None or datetime.now(timezone.utc) - before >= timedelta(hours=JEV_ALIAS_TTL_H)
    if calls.current() is None:
        limit = daily_budget_usd() if budget_usd is None else budget_usd
        with calls.measurement(f"jev-version-{datetime.now():%Y%m%d}", {"jev": limit}):
            adapter.resolve_model(WATCH_ALIAS, run_id="jev-version")
    else:
        adapter.resolve_model(WATCH_ALIAS, run_id="jev-version")
    if due and _resolved_at(adapter.cache_dir) == before:
        _keep_look(failed=True)
        raise LookFailed(f"{WATCH_ALIAS} was not resolved again; the adapter kept its earlier resolution")
    if due:
        _keep_look(failed=False)
    return status(cache_dir=adapter.cache_dir, pinned=pinned)


def _resolved_at(cache_dir: Path) -> datetime | None:
    checked = status(cache_dir=cache_dir)["checked_at"]
    return datetime.fromisoformat(checked) if checked else None


def _keep_look(*, failed: bool) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jsonfile.write_atomic(LOOK_PATH, {"looked_at": now, "failed_at": now if failed else None})


def verdict(st: dict[str, Any]) -> tuple[bool, str]:
    """(ok, one line) for the start-up check. A newer version is a notice, not a failure: the pinned one still answers."""
    pinned = st["pinned"]
    if not _CONCRETE_MODEL.match(pinned):
        return True, f"not pinned: the model is the moving name {pinned}"
    if not st["latest"]:
        return True, f"{pinned} pinned; {WATCH_ALIAS} not looked up yet"
    when = (st["checked_at"] or "")[:10]
    if st["newer"]:
        line = (f"{pinned} pinned; a newer JEV version is out: {WATCH_ALIAS} is {st['latest']} (checked {when}); "
                "switching is a decision and a measurement")
    else:
        line = f"{pinned} pinned; {WATCH_ALIAS} is the same version (checked {when})"
    if st["stale"]:
        line += f"; not looked up for {int(st['age_days'])} days"
    if st.get("look_failed_at"):
        line += f"; the last daily look failed ({st['look_failed_at'][:10]}: no answer from JEV, see the backup log)"
    return True, line
