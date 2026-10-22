"""Command line, the email domain (202, plan G-core-generalisation M3a): the email flow on a folder and the
mail bridge's receiver. The email domain names this module (`COMMANDS`).
"""

from __future__ import annotations

import argparse
import json

from jav.cli_options import budget_args, engine_args, jev_on, under_budget


def cmd_email(args: argparse.Namespace) -> int:
    from jav.flow_email import run_email

    with under_budget(args, "email"):
        st = run_email(args.folder, tracker=not args.no_tracker, use_cache=not args.no_cache, jev=jev_on(args))
    r, m = st.result, st.message
    assert r is not None and m is not None
    print(f"=== {m.message_id} | {m.sender} | {m.subject!r}")
    print(f"intent={r.intent} conf={r.confidence:.2f} next_flow={st.next_flow} uncertain={st.uncertain}")
    print("signals: " + ", ".join(f"{k}={v:.2f}" for k, v in r.signals.items()))
    print("top3: " + json.dumps(dict(sorted(r.probabilities.items(), key=lambda kv: -kv[1])[:3]), ensure_ascii=False))
    for a in m.attachments:
        print(f"  csatolmány {a.filename}: {a.status} {a.doc_type or ''} {'' if a.type_conf is None else f'{a.type_conf:.2f}'}")
    print(f"[{r.call.request_id}] {r.call.input_tokens} tok, ${r.call.cost_usd:.5f}, {r.call.seconds}s, cached={r.call.cached}")
    return 0


def cmd_email_ingest_server(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.ingest_server import INBOX_ROOT, serve

    serve(port=args.port, run_flow=args.run, inbox_root=Path(args.inbox) if args.inbox else INBOX_ROOT, token=args.token)
    return 0


def register(sub) -> None:
    p = sub.add_parser("email", help="M3: egy levél (inbox/<mailbox>/<msgid>/ mappa) szándéka Jevvel")
    p.add_argument("folder")
    p.add_argument("--no-tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    budget_args(p)
    engine_args(p, measurement=False)
    p.set_defaults(fn=cmd_email)
    p = sub.add_parser("email-ingest-server", help="M3: helyi fogadó a régi outlook_bridge.ps1 /ingest/email POST-jaihoz -> inbox/")
    p.add_argument("--port", type=int, default=8901)
    p.add_argument("--inbox", help="cél inbox-gyökér (alap: <projekt>/inbox)")
    p.add_argument("--run", action="store_true", help="a levél érkezésekor azonnal fusson az M3 gráf (szinkron)")
    p.add_argument("--token", help="kötelező Bearer-kulcs a bridge felé (alap: JAV_INGEST_TOKEN környezeti változó; a bridge -ApiToken-nel küldi)")
    p.set_defaults(fn=cmd_email_ingest_server)
