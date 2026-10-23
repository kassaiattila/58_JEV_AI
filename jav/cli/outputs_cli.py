"""Command line, own output templates (202, plan G-core-generalisation M3a; 178). Registered by `jav.cli`.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def cmd_output_templates(args: argparse.Namespace) -> int:
    """178 (plan 170 L4): the own output templates with their versions."""
    from jav.app.outputs import templates

    for t in templates.listing(args.output):
        state = f"active: version {t['active']}" if t["active"] else "retired" if t["retired"] else "no active version"
        print(f"{t['template']} {t['output']} {t['name']!r} ({state})")
        for v in t["versions"]:
            print(f"  version {v['version']} {v['state']} {v['file_name']} {v['uploaded_by']} {v['uploaded_at']}")
    return 0


def cmd_output_template_add(args: argparse.Namespace) -> int:
    """178: checks a workbook as a template of an output and stores it as a draft version (exit code 2: refused)."""
    from jav.app.outputs import templates

    path = Path(args.file)
    try:
        v = templates.add(args.output, args.name, path.name, path.read_bytes(), actor=args.actor, template=args.template)
    except templates.TemplateRefused as e:
        for p in e.check["problems"]:
            print(f"problem: {p['code']} {p['where']} {p['detail']}".rstrip())
        return 2
    for w in v["check"]["warnings"]:
        print(f"warning: {w['code']} {w['where']}".rstrip())
    print(f"{v['template']} version {v['version']} ({v['state']}); values: {', '.join(v['check']['values']) or '-'};"
          f" tables: {', '.join(v['check']['tables']) or '-'}")
    return 0


def cmd_output_template_activate(args: argparse.Namespace) -> int:
    from jav.app.outputs import templates

    v = templates.activate(args.template, args.version, actor=args.actor)
    print(f"{v['template']} version {v['version']} is active")
    return 0


def cmd_output_template_retire(args: argparse.Namespace) -> int:
    from jav.app.outputs import templates

    v = templates.retire(args.template, actor=args.actor)
    print(f"{v['template']} retired (version {v['version']})")
    return 0


def cmd_output_template_preview(args: argparse.Namespace) -> int:
    """178: a version filled with made-up data, written to a new file."""
    from jav.app.outputs import templates

    out = Path(args.out)
    if out.exists():
        print(f"exists, not overwritten: {out}")
        return 2
    content, _name = templates.preview(args.template, args.version)
    out.write_bytes(content)
    print(f"preview: {out}")
    return 0


def cmd_output_template_choose(args: argparse.Namespace) -> int:
    """178: the template a package's output is made with (--builtin: the built-in template)."""
    from jav.app.outputs import templates

    if (args.template is None) == (not args.builtin):
        print("give a template or --builtin")
        return 2
    chosen = templates.choose(args.wp, args.output, None if args.builtin else args.template, actor=args.actor)
    ch = chosen["outputs"][args.output]["chosen"]
    print(f"{args.wp} {args.output}: " + (f"{ch['template']} version {ch['version']}" if ch else "built-in template"))
    return 0


def register(sub) -> None:
    p = sub.add_parser("output-templates", help="178: the own output templates and their versions")
    p.add_argument("--output", help="only the templates of this output (configs/outputs.json)")
    p.set_defaults(fn=cmd_output_templates)
    p = sub.add_parser("output-template-add", help="178: check a workbook as a template of an output, store it as a draft")
    p.add_argument("file")
    p.add_argument("--output", required=True, help="package_result, utility_cost or reconcile_statement")
    p.add_argument("--name", required=True)
    p.add_argument("--template", help="the next version of this template")
    p.add_argument("--actor", required=True)
    p.set_defaults(fn=cmd_output_template_add)
    p = sub.add_parser("output-template-activate", help="178: make a version its template's active one")
    p.add_argument("template")
    p.add_argument("version", type=int)
    p.add_argument("--actor", required=True)
    p.set_defaults(fn=cmd_output_template_activate)
    p = sub.add_parser("output-template-retire", help="178: retire a template (packages that chose it get the built-in one)")
    p.add_argument("template")
    p.add_argument("--actor", required=True)
    p.set_defaults(fn=cmd_output_template_retire)
    p = sub.add_parser("output-template-preview", help="178: a version filled with made-up data, into a new file")
    p.add_argument("template")
    p.add_argument("version", type=int)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_output_template_preview)
    p = sub.add_parser("output-template-choose", help="178: the template a package's output is made with")
    p.add_argument("wp")
    p.add_argument("output")
    p.add_argument("template", nargs="?")
    p.add_argument("--builtin", action="store_true", help="the built-in template")
    p.add_argument("--actor", required=True)
    p.set_defaults(fn=cmd_output_template_choose)
