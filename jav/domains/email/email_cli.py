"""Command line, the email domain (202, plan G-core-generalisation M3a): the email flow on a folder and the
mail bridge's receiver. The email domain names this module (`COMMANDS`).
"""

from __future__ import annotations

import argparse
import json

from jav.cli.cli_options import budget_args, engine_args, jev_on, under_budget


def cmd_email(args: argparse.Namespace) -> int:
    from jav.domains.email.flow_email import run_email

    with under_budget(args, "email"):
        st = run_email(args.folder, tracker=not args.no_tracker, use_cache=not args.no_cache, jev=jev_on(args))
    r, m = st.result, st.message
    assert r is not None and m is not None
    print(f"=== {m.message_id} | {m.sender} | {m.subject!r}")
    print(f"intent={r.intent} conf={r.confidence:.2f} next_flow={st.next_flow} uncertain={st.uncertain}")
    print("signals: " + ", ".join(f"{k}={v:.2f}" for k, v in r.signals.items()))
    print("top3: " + json.dumps(dict(sorted(r.probabilities.items(), key=lambda kv: -kv[1])[:3]), ensure_ascii=False))
    for a in m.attachments:
        print(f"  attachment {a.filename}: {a.status} {a.doc_type or ''} {'' if a.type_conf is None else f'{a.type_conf:.2f}'}")
    print(f"[{r.call.request_id}] {r.call.input_tokens} tok, ${r.call.cost_usd:.5f}, {r.call.seconds}s, cached={r.call.cached}")
    return 0


def cmd_email_ingest_server(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.domains.email.ingest_server import INBOX_ROOT, serve

    serve(port=args.port, run_flow=args.run, inbox_root=Path(args.inbox) if args.inbox else INBOX_ROOT, token=args.token)
    return 0


def register(sub) -> None:
    p = sub.add_parser("email", help="M3: an email's intent (an inbox/<mailbox>/<msgid>/ folder), asked of JEV")
    p.add_argument("folder")
    p.add_argument("--no-tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    budget_args(p)
    engine_args(p, measurement=False)
    p.set_defaults(fn=cmd_email)
    p = sub.add_parser("email-ingest-server", help="M3: a local receiver for the legacy outlook_bridge.ps1's /ingest/email POSTs -> inbox/")
    p.add_argument("--port", type=int, default=8901)
    p.add_argument("--inbox", help="the inbox root to write into (default: <project>/inbox)")
    p.add_argument("--run", action="store_true", help="run the M3 graph as soon as an email arrives (synchronously)")
    p.add_argument("--token", help="the Bearer key the bridge must send (default: the JAV_INGEST_TOKEN environment variable; the bridge sends it with -ApiToken)")
    p.set_defaults(fn=cmd_email_ingest_server)
