"""The pinned JEV version and the provider's moving name (200, decision of 2026-10-22).

Plain-language summary: the system asks JEV by a concrete version (`configs/models.json` `jev.model`, e.g.
`jev-1.14.0`), so its answers, and the cached answers they are keyed by, do not change by themselves. The provider's
moving name (`jev.watch_alias`, `jev-latest`) is only looked at: the daily backup resolves it once (one tiny probe, as
the adapter always did for an alias; `runs/cache/_model_versions.json`), and the start-up check and the System page
say when it points to a newer version than the pinned one. Switching is a decision with a measurement (DECISIONS 200):
on 2026-10-22 the moving name went from jev-1.13.0 to jev-1.14.0 without notice, and every golden set had to be
measured again.

Layer: business module over the JEV adapter (`jav.adapters.jev`), which keeps the resolution file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jav.adapters.jev import _CONCRETE_MODEL, MODEL_VERSIONS_FILE, JevAdapter
from jav.config import CACHE_DIR, JEV_MODEL, JEV_WATCH_ALIAS

WATCH_ALIAS = JEV_WATCH_ALIAS
STALE_DAYS = 3  # the daily backup looks once a day; three days without a look is said


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
    return {"pinned": pinned, "watch_alias": WATCH_ALIAS, "latest": latest, "checked_at": checked,
            "newer": (latest != pinned) if latest and concrete else None,
            "stale": age_days is not None and age_days > STALE_DAYS, "age_days": age_days}


def refresh(*, adapter: JevAdapter | None = None, pinned: str = JEV_MODEL) -> dict[str, Any]:
    """The daily look: resolves the moving name (a probe only when its last resolution is older than the adapter's
    alias TTL), then returns `status`. A failure propagates; the daily backup logs it and goes on."""
    adapter = adapter or JevAdapter()
    adapter.resolve_model(WATCH_ALIAS, run_id="jev-version")
    return status(cache_dir=adapter.cache_dir, pinned=pinned)


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
    return True, line
