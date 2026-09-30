"""K5.3 mérés (058, döntés 2026-09-28: részkeret 0,30 USD OpenAI + 0,10 USD JEV): feladatjavaslat a két valódi
postafiók 47 levelén.

- **A:** a valódi futási út: levél-recept `tasks=propose` (archiválandó levél kihagyva), próba mód, a feldolgozón át, a
  hívásnaplóval és a futás keretével; a szándék a korábbi JEV-válaszból (`jev_cache=reuse`).
- **B:** ugyanaz újrafuttatva (ismételhetőség: a GPT-válasznak nincs gyorsítótára).
- **C:** mind a 47 levél, kihagyás nélkül, közvetlen hívással: a kihagyási szabály nélkül ad-e a GPT teendőt hírlevélre /
  értesítésre (a régi utasítás „action necessity gate”-je). Kemény plafon: 0,20 USD (a ledgerből, hívás előtt ellenőrizve).

Nincs etalon: a számok a javaslatok és a kapu viselkedését írják le, nem pontosságot. Kimenet: `runs/20260928_k53/`.
Futtatás (tiszta munkafán, a feldolgozó leállítva): `python -m jav.experiments.k53_task_proposals`.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav import corrections, email_tasks, store, work
from jav.config import OLD_PROJECT_ROOT, PROJECT_ROOT
from jav.emails import body_coverage, load_message_dir
from jav.runtime import worker

OUT = PROJECT_ROOT / "runs" / "20260928_k53"
CAP_C_USD = Decimal("0.20")
PER_CALL_GUARD_USD = Decimal("0.04")  # egy hívás legrosszabb esete (17 000 karakteres levél, 3 próbálkozás) felülről


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def mail_paths() -> list[Path]:
    """A postafiók-csomagok levelei (message.json), egyszer."""
    seen: dict[str, Path] = {}
    for wp in work.list_workpackages(include_archived=True):
        if wp["source_kind"] != "mailbox":
            continue
        for i in work.get(wp["id"])["items"]:
            if i["kind"] == "email":
                seen.setdefault(i["sha256"], Path(i["source_path"]))
    return sorted(seen.values())


def _ledger_cost(prefix: str) -> Decimal:
    with store.connect() as c:
        row = c.execute("SELECT COALESCE(SUM(cost_usd), 0) s FROM ledger WHERE run_id LIKE ? AND provider='openai'", (prefix + "%",)).fetchone()
    return Decimal(str(row["s"]))


def _item_rows(variant: str, run_id: str) -> list[dict[str, Any]]:
    out = []
    for i in work.get_run(run_id)["input"]["items"]:
        res = corrections.item_result(run_id, i["item_id"])
        email = res["email"]
        tv = email.get("tasks") or {}
        out.append({"variant": variant, "run_id": run_id, "item_id": i["item_id"], "subject": email["subject"],
                    "intent": (email.get("result") or {}).get("intent"), "route": (email.get("result") or {}).get("next_flow"),
                    "status": tv.get("status"), "reason": tv.get("reason"), "error": tv.get("error"),
                    "tasks": [{k: t[k] for k in ("action", "title", "due_date", "assignee_hint", "evidence")} for t in tv.get("tasks") or []],
                    "rejected": tv.get("rejected") or []})
    return out


def run_ab(paths: list[Path]) -> tuple[str, str, list[dict[str, Any]]]:
    wp = work.create_workpackage(name="K5.3 mérés — 47 valódi levél (feladatjavaslat)", source_kind="manual", source_ref=None)
    wp = work.add_items(wp["id"], paths, kind="email", expected_revision=0)
    work.assign_recipe(wp["id"], "email-intent", params={"tasks": "propose"}, expected_revision=0, actor="K5.3 mérés",
                       note="058 K5.3 mérés (részkeret 0,30 + 0,10 USD)")
    ready = work.readiness(wp["id"], verify=True)
    run_a = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"], actor="K5.3 mérés")["run_id"]
    worker.run_worker(once=True)
    ready = work.readiness(wp["id"], verify=True)
    run_b = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"], actor="K5.3 mérés",
                           rerun_of=run_a)["run_id"]
    worker.run_worker(once=True)
    return run_a, run_b, _item_rows("A", run_a) + _item_rows("B", run_b)


def run_c(paths: list[Path], stamp: str) -> list[dict[str, Any]]:
    prefix = f"k53-c-{stamp}:"
    out = []
    for p in paths:
        spent = _ledger_cost(prefix)
        if spent + PER_CALL_GUARD_USD > CAP_C_USD:
            out.append({"variant": "C", "subject": None, "status": "not_run_budget", "spent_usd": str(spent)})
            break
        msg = load_message_dir(p.parent)
        with store.connect() as c:
            row = c.execute("SELECT intent, intent_conf, next_flow FROM emails WHERE message_id=?", (msg.message_id,)).fetchone()
        hint = {"intent_key": row["intent"], "confidence": round(row["intent_conf"] or 0, 3)} if row and row["intent"] else None
        snap = email_tasks.snapshot(message_id=msg.message_id, subject=msg.subject, body=msg.body, body_status=body_coverage(msg)["status"],
                                    attachments=[a.model_dump(exclude={"path"}) for a in msg.attachments])
        try:
            raw = email_tasks.extract(snap, intent_hint=hint, run_id=prefix + msg.message_id[:40])
            tasks, rejected = email_tasks.gate(snap, raw)
            status, err = "proposed", None
        except Exception as exc:  # noqa: BLE001 - a mérés folytatódik, a hiba rögzítve
            tasks, rejected, status, err = [], [], "error", type(exc).__name__
        out.append({"variant": "C", "run_id": prefix + msg.message_id[:40], "subject": msg.subject, "intent": row["intent"] if row else None,
                    "route": row["next_flow"] if row else None, "status": status, "error": err,
                    "tasks": [{k: t[k] for k in ("action", "title", "due_date", "assignee_hint", "evidence")} for t in tasks],
                    "rejected": rejected})
    return out


OLD_GOLDEN = OLD_PROJECT_ROOT / "flows" / "email-actions-bare" / "golden" / "manifest.json"  # csak olvasva (mesterséges)


def run_golden(stamp: str, repeats: int = 2) -> list[dict[str, Any]]:
    """A régi projekt 7 mesterséges etalon-esete (elvárt teendők: akció, határidő, felelős), `repeats` ismétléssel. A régi
    bemenet a mi pillanatképünkbe képezve (tárgy, szöveg, csatolmány-típus; a hiányos / ismeretlen szöveg = részleges)."""
    cases = json.loads(OLD_GOLDEN.read_text(encoding="utf-8"))["cases"]
    out = []
    for rep in range(repeats):
        for case in cases:
            msg = case["input"]["input_snapshot"]["messages"][0]
            snap = email_tasks.snapshot(message_id=msg["id"], subject=msg["subject"], body=msg["body"],
                                        body_status="full" if msg["body_completeness"] == "complete" else "capped",
                                        attachments=[{"filename": a.get("id"), "doc_type": a.get("doc_type")} for a in msg["attachments"]])
            expected = case["expected"]["messages"][0]
            hint = {"intent_key": expected["intent_key"], "confidence": 0.9} if expected["intent_key"] else None
            run_id = f"k53-g-{stamp}:{rep}:{case['id']}"
            try:
                raw = email_tasks.extract(snap, intent_hint=hint, run_id=run_id)
                tasks, rejected = email_tasks.gate(snap, raw)
                status = "proposed"
            except Exception as exc:  # noqa: BLE001
                tasks, rejected, status = [], [{"code": type(exc).__name__}], "error"
            got = sorted([t["action"], t["due_date"], t["assignee_hint"]] for t in tasks)
            want = sorted(expected["tasks"])
            out.append({"variant": "G", "repeat": rep, "case": case["id"], "status": status, "match": got == want, "got": got, "want": want,
                        "titles": [t["title"] for t in tasks], "rejected": rejected, "run_id": run_id})
    return out


def main_golden() -> None:
    if _git("status", "--porcelain"):
        raise SystemExit("a munkafa nem tiszta: élő mérés csak tiszta munkafán indulhat")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    rows = run_golden(stamp)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stamp}_golden.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    summary = {"commit": _git("rev-parse", "--short", "HEAD"), "cases": len(rows), "match": sum(r["match"] for r in rows),
               "openai_cost_usd": str(_ledger_cost(f"k53-g-{stamp}:")), "jsonl": f"runs/20260928_k53/{stamp}_golden.jsonl"}
    (OUT / f"{stamp}_golden_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    if _git("status", "--porcelain"):
        raise SystemExit("a munkafa nem tiszta: élő mérés csak tiszta munkafán indulhat")
    commit = _git("rev-parse", "--short", "HEAD")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)
    paths = mail_paths()
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_a, run_b, ab = run_ab(paths)
    c = run_c(paths, stamp)
    rows = ab + c
    (OUT / f"{stamp}_task_proposals.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    cost = {"A+B": str(_ledger_cost(run_a) + _ledger_cost(run_b)), "C": str(_ledger_cost(f"k53-c-{stamp}:"))}
    summary = {"commit": commit, "started_at": t0, "messages": len(paths), "run_a": run_a, "run_b": run_b, "openai_cost_usd": cost,
               "jsonl": f"runs/20260928_k53/{stamp}_task_proposals.jsonl"}
    (OUT / f"{stamp}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    import sys

    main_golden() if "--golden" in sys.argv else main()
