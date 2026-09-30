"""Work package and run commands (040 K1): a thin command-line interface over `jav.work` and `jav.runtime`.

  recipes                                  the recipe catalogue
  wp-create <folder> [--name N]            work package from the PDFs in a folder
  wp-create --files <pdf>... --name N      work package from the given files (possibly from several folders)
  wp-list | wp-show <wp>                   work packages; one package's items, recipe and readiness
  wp-assign <wp> <recipe> [--arm S|G] [--doc-type T] [--note N]   assign a recipe (to the current revision)
  run-start <wp> [--mode shadow|apply]     start a run with the input pinned by the current readiness check (idempotent)
  run-list [<wp>] | run-show <run>         runs; one run's items, work queue, cost and to-dos
  run-cancel <run> | run-approve <run> --actor A
  run-names <run> [--zip F | --to-output]  content-based names of the run's documents; the copies into a ZIP or the
                                           output folder (078; the originals are only read)
  worker [--once] [--max-jobs N]           worker: runs the work-queue items (one instance at a time, with a lock)
  worker-status | worker-stop              is a worker running; request a clean stop (after the current item)
  serve [--port P]                         local service (040 K2, 127.0.0.1 only; endpoint list: /api/openapi.json)
  calls-uncertain | calls-resolve <id> [--cost USD] --note N   paid calls with an uncertain outcome; manual resolution
                                                               (066 Á30)

The commands call the same business operations as the UI; the rules (revision conflict, readiness, approval) live in
`jav.work`, not here. `--json` gives machine-readable output.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any


def _out(args: argparse.Namespace, data: Any, text: str) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str) if getattr(args, "json", False) else text)
    return 0


def _usd(v: Decimal | str | None) -> str:
    return "-" if v is None else f"{Decimal(v):.6f} USD"


def cmd_recipes(args):
    from jav import work_views
    rows = work_views.recipe_catalog()
    text = "\n".join(f"- {r['id']} v{r['version']}: {r['title']} — {r['description']}" for r in rows)
    return _out(args, rows, text)


def cmd_wp_create(args):
    from jav import work
    if (args.folder is None) == (not args.files):
        print("Adj meg vagy egy mappát, vagy --files fájlokat (a kettő együtt nem).")
        return 2
    if args.files and not args.name:
        print("Fájlokból készülő munkacsomaghoz --name kell.")
        return 2
    wp = (work.create_from_files([Path(f) for f in args.files], name=args.name) if args.files
          else work.create_from_folder(Path(args.folder), name=args.name))
    return _out(args, wp, f"Munkacsomag: {wp['id']} „{wp['name']}”, {len(wp['items'])} tétel (verzió {wp['revision']})")


def cmd_wp_list(args):
    from jav import work_views
    rows = work_views.workpackage_list()
    lines = [f"{r['id']}  {r['name']}  tétel: {r['items']}  recept: {r['recipe_id'] or '-'}  utolsó futás: {r['last_run_id'] or '-'}"
             f"  nyitott teendő: {r['open_reasons']}" for r in rows]
    return _out(args, rows, "\n".join(lines) or "Nincs munkacsomag.")


def cmd_wp_show(args):
    from jav import work_views
    view = work_views.workpackage_view(args.wp)
    wp, ready = view["workpackage"], view["readiness"]
    a = wp["assignment"]
    lines = [f"{wp['id']}  „{wp['name']}”  forrás: {wp['source_kind']} {wp['source_ref'] or ''}  verzió: {wp['revision']}",
             f"Recept: {a['recipe_id']} v{a['recipe_version']} {a['params']} (hozzárendelés {a['revision']})" if a else "Recept: nincs",
             f"Tételek ({len(wp['items'])}):"]
    lines += [f"  - {Path(i['source_path']).name}  {i['item_id'][:12]}" for i in wp["items"]]
    lines.append("Készenlét: " + ("indítható" if ready["ready"] else "NEM indítható"))
    lines += [f"  akadály: {b['message']}" for b in ready["blockers"]]
    lines += [f"  figyelmeztetés: {w['message']}" for w in ready["warnings"]]
    if ready["budget"]:
        lines.append("  keret: " + ", ".join(f"{p} {_usd(v)}" for p, v in ready["budget"].items()))
    return _out(args, view, "\n".join(lines))


def cmd_wp_assign(args):
    from jav import work
    current = work.current_assignment(args.wp)
    params = {k: v for k, v in {"arm": args.arm, "doc_type": args.doc_type, "jev_cache": args.jev_cache}.items() if v is not None}
    a = work.assign_recipe(args.wp, args.recipe, params=params, expected_revision=current["revision"] if current else 0,
                           actor=args.actor, note=args.note)
    return _out(args, a, f"Hozzárendelve: {a['recipe_id']} {a['params']} (hozzárendelés {a['revision']})")


def cmd_run_start(args):
    from jav import work
    ready = work.readiness(args.wp)
    if not ready["ready"]:
        print("Nem indítható:\n" + "\n".join(f"  - {b['message']}" for b in ready["blockers"]))
        return 2
    res = work.start_run(args.wp, mode=args.mode, expected_assignment_revision=ready["assignment_revision"],
                         input_hash=ready["input_hash"], actor=args.actor)
    note = "(már létezett, ugyanaz a futás)" if res["deduped"] else "(új; a feldolgozó futtatja: python -m jav.cli worker)"
    return _out(args, res, f"Futás: {res['run_id']} {note}")


def cmd_run_list(args):
    from jav import work_views
    runs = work_views.run_list(args.wp)
    lines = [f"{r['run_id']}  {r['workpackage_id']}  {r['recipe_id']}  mód: {r['mode']}  állapot: {r['status']}"
             f"  jóváhagyás: {r['approval'] or '-'}  feladatok: {r['jobs']}" for r in runs]
    return _out(args, runs, "\n".join(lines) or "Nincs futás.")


def cmd_run_show(args):
    from jav import work_views
    view = work_views.run_view(args.run)
    run, usage = view["run"], view["budget"]
    lines = [f"{run['run_id']}  {run['recipe_id']} v{run['recipe_version']} {run['params']}  mód: {run['mode']}  állapot: {run['status']}",
             f"Munkacsomag: {run['workpackage_id']} (verzió {run['input']['workpackage_revision']})  feladatok: {run['jobs']}",
             "Keret: " + (", ".join(f"{p}: {_usd(v['committed_usd'])} / {_usd(v['limit_usd'])}" for p, v in usage["providers"].items()) or "-")]
    names = {i["item_id"]: Path(i["source_path"]).name for i in run["input"]["items"]}
    for i in run["items"]:
        reasons = [r["reason"] for r in view["open_reasons"].get(i["item_id"], [])]
        earlier = len(view["earlier_open_reasons"].get(i["item_id"], []))
        lines.append(f"  - {names.get(i['item_id'], i['item_id'][:12])}: {i['status']} / {i['final_status'] or '-'}"
                     + (f"  hiba: {i['error']}" if i["error"] else "") + (f"  teendő: {', '.join(reasons)}" if reasons else "")
                     + (f"  (korábbi nyitott teendő az iraton: {earlier})" if earlier else ""))
    waiting = [n for k, n in names.items() if k not in {i["item_id"] for i in run["items"]}]
    lines += [f"  - {n}: még nem futott" for n in waiting]
    if run["approval"]:
        lines.append(f"Jóváhagyta: {run['approved_by']} ({run['approved_at']})")
    return _out(args, view, "\n".join(lines))


def cmd_run_cancel(args):
    from jav import work
    res = work.cancel_run(args.run)
    return _out(args, res, f"Leállítás: {res or 'nincs futó vagy sorban álló tétel'}")


def cmd_run_approve(args):
    from jav import work
    run = work.approve_run(args.run, actor=args.actor)
    return _out(args, run, f"Jóváhagyva: {run['run_id']} ({run['approved_by']})")


def cmd_run_names(args):
    """078: the content-based names of the run's documents; with `--zip` or `--to-output` also the copies."""
    from jav import app_settings, naming
    if args.zip and args.to_output:
        print("Give either --zip or --to-output, not both.")
        return 2
    copies = naming.plan(args.run)
    data: dict[str, Any] = {"copies": [{"path": c.path, "status": c.status, "why": naming.reason_text(c.reasons),
                                        "original": c.original, "item_id": c.item_id} for c in copies]}
    lines = [f"  {c.path}  <- {c.original}" + (f"  ({naming.reason_text(c.reasons)})" if c.reasons else "") for c in copies]
    lines.insert(0, f"{sum(c.status == 'ready' for c in copies)} ready, {sum(c.status == 'review' for c in copies)} to review:")
    if args.zip:
        with open(args.zip, "xb") as fh:  # never overwrites an existing file
            data["written"] = {"zip": str(Path(args.zip).resolve()), **naming.write_zip(args.run, fh)}
    elif args.to_output:
        folder = app_settings.output_folder()
        if not folder:
            print("No output folder is set (Settings > Work folders in the UI).")
            return 2
        data["written"] = naming.write_to_folder(args.run, Path(folder))
    if "written" in data:
        w = data["written"]
        lines.append(f"Written: {w.get('zip') or w.get('path')} ({w['ready']} ready, {w['review']} to review, {w['skipped']} skipped)")
    return _out(args, data, "\n".join(lines))


def cmd_worker(args):
    from jav.runtime import applog, lock, worker
    applog.setup("worker")  # 063: persistent rotating log (runs/logs/worker.log): start, errors with traceback, stop
    try:
        info = worker.run_worker(once=args.once, max_jobs=args.max_jobs)
    except lock.AlreadyRunning:
        print("Már fut egy feldolgozó ezen az adattáron; egyszerre csak egy futhat.")
        return 3
    note = ", leállítási kérésre kilépett" if info["stopped"] else ""
    return _out(args, info, f"Feldolgozó: indulás {info['startup']}, feldolgozva {info['processed']}, eredmény {info['results']}{note}")


def cmd_worker_status(args):
    from jav import work_views
    st = work_views.worker_status()
    text = (f"Feldolgozó: {'fut' if st['running'] else 'nem fut'}"
            f"{', leállítás kérve' if st['stop_requested'] else ''}  feladatok: {st['jobs']}")
    return _out(args, st, text)


def cmd_worker_stop(args):
    from jav import work_views
    from jav.runtime import worker
    worker.request_stop()
    st = work_views.worker_status()
    return _out(args, st, "Leállítás kérve; a feldolgozó a folyamatban lévő tétel után kilép." if st["running"]
                else "Nem fut feldolgozó (a kérés a következő indításkor törlődik).")


def cmd_calls_uncertain(args):
    from jav.runtime import calls
    rows = calls.uncertain_list()
    lines = [f"{r['id']}  {r['run_id']} / {r['step_id']} ({r['provider']}, próbálkozás {r['attempt']}): lekötve {_usd(r['max_cost_usd'])}"
             for r in rows]
    return _out(args, {"uncertain": rows}, "\n".join(lines) or "Nincs bizonytalan kimenetű hívás.")


def cmd_calls_resolve(args):
    from jav.runtime import calls
    cost = Decimal(args.cost) if args.cost is not None else None
    calls.resolve_uncertain(args.invocation_id, cost_usd=cost, note=args.note)
    return _out(args, {"resolved": args.invocation_id, "cost_usd": cost},
                f"Rendezve: {args.invocation_id} ({'költség ' + _usd(cost) if cost is not None else 'ismeretlen költség, a maximum lekötve marad'}); "
                "a lépés új próbálkozással futtatható.")


def cmd_serve(args):
    from jav import api
    api.serve(port=args.port)
    return 0


def register(sub) -> None:
    def add(name: str, fn, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--json", action="store_true", help="gépi (JSON) kimenet")
        p.set_defaults(fn=fn)
        return p

    add("recipes", cmd_recipes, "a folyamatrecept-katalógus (configs/recipes.json)")
    p = add("wp-create", cmd_wp_create, "munkacsomag egy mappa PDF-jeiből vagy megadott fájlokból")
    p.add_argument("folder", nargs="?")
    p.add_argument("--files", nargs="+")
    p.add_argument("--name")
    add("wp-list", cmd_wp_list, "munkacsomagok listája")
    p = add("wp-show", cmd_wp_show, "egy munkacsomag tételei, receptje és készenléte")
    p.add_argument("wp")
    p = add("wp-assign", cmd_wp_assign, "recept hozzárendelése egy munkacsomaghoz")
    p.add_argument("wp")
    p.add_argument("recipe")
    p.add_argument("--arm", choices=["S", "G"])
    p.add_argument("--doc-type")
    p.add_argument("--jev-cache", choices=["reuse", "live"], help="live: a JEV-gyorsítótár olvasása nélkül (élő próba)")
    p.add_argument("--note")
    p.add_argument("--actor", default="cli")
    p = add("run-start", cmd_run_start, "futás indítása rögzített bemenettel (idempotens)")
    p.add_argument("wp")
    p.add_argument("--mode", choices=["shadow", "apply"], default="shadow")
    p.add_argument("--actor", default="cli")
    p = add("run-list", cmd_run_list, "futások (egy munkacsomagé vagy az utolsó 50)")
    p.add_argument("wp", nargs="?")
    p = add("run-show", cmd_run_show, "egy futás tételei, munkasora, kerete, teendői")
    p.add_argument("run")
    p = add("run-cancel", cmd_run_cancel, "futás leállítása (sorban álló azonnal, futó a következő lépéshatáron)")
    p.add_argument("run")
    p = add("run-approve", cmd_run_approve, "éles futás jóváhagyása (csak nyitott teendő nélkül)")
    p.add_argument("run")
    p.add_argument("--actor", required=True)
    p = add("run-names", cmd_run_names, "078: content-based names of a run's documents; --zip or --to-output writes the copies")
    p.add_argument("run")
    p.add_argument("--zip", help="write the copies and the manifest into this new ZIP file")
    p.add_argument("--to-output", action="store_true", help="write them into a new subfolder of the output folder")
    p = add("worker", cmd_worker, "feldolgozó: a munkasor tételeinek futtatása")
    p.add_argument("--once", action="store_true", help="a sor kiürüléséig fut, utána kilép")
    p.add_argument("--max-jobs", type=int)
    add("worker-status", cmd_worker_status, "fut-e feldolgozó, és mennyi feladat vár")
    add("worker-stop", cmd_worker_stop, "a feldolgozó szabályos leállításának kérése")
    add("calls-uncertain", cmd_calls_uncertain, "bizonytalan kimenetű fizetős hívások (kézi rendezésre várnak)")
    p = add("calls-resolve", cmd_calls_resolve, "egy bizonytalan hívás kézi rendezése (a szolgáltatói felületen ellenőrizve)")
    p.add_argument("invocation_id", type=int)
    p.add_argument("--cost", help="a tényleges költség USD-ben, ha ismert")
    p.add_argument("--note", required=True)
    p = add("serve", cmd_serve, "helyi szolgáltatás a felülethez (csak 127.0.0.1)")
    p.add_argument("--port", type=int)
