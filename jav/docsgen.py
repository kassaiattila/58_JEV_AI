"""Documentation generated from the config and the ledger: the catalogue of JEV call sites (`docs/callsites/<site>.md`).

This is the "JEV loops" description, always from the current content of `configs/` and the facts in the `ledger`
table: per call site, the questions (kind, key, instruction, criteria source), the consuming thresholds
(`configs/policy.json`), the make-up of the state (from the code's docstring), and the run statistics per config
version (calls, cache ratio, cost, average time). Run: `python -m jav.cli docs` (next to `flows`). Do not edit by
hand - regenerate.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from jav import cfg, store
from jav.config import PROJECT_ROOT

CALLSITES_DOC_DIR = PROJECT_ROOT / "docs" / "callsites"

# Call site -> (ledger steps, the state-building module.function, the consumers of the answers, the flow and step)
CALLSITES: dict[str, dict[str, Any]] = {
    "detect": {
        "steps": ["detect"], "registry": "doc_types", "flow": "doc_detect / detect", "state_fn": "jav.detect.build_state",
        "consumers": {
            "doc_type": "documents.doc_type + type_conf; policy.detect.low_confidence alatt review_queue (M1); M3 route: m2:<típus>",
            "issuer_is_hungarian": "documents.issuer_hu (jel, küszöb nélkül)",
            "language": "jel a riportokhoz (küszöb nélkül)",
        },
    },
    "email_intent": {
        "steps": ["email_intent"], "registry": "intents", "flow": "email_intent / intent", "state_fn": "jav.intent.build_state",
        "consumers": {
            "intent": "emails.intent + intent_conf; policy.email.intent_human_max_conf alatt human:low_confidence, különben policy.email.intent_route / csatolmány-típus",
            "requires_action": "emails.signals (jel; még nem küszöbölt)",
            "mentions_deadline": "emails.signals (jel)",
            "attachment_is_the_subject": "emails.signals (jel)",
            "urgency": "emails.signals.scores (Score: szint + várható érték + eloszlás; jel, küszöb nélkül)",
            "multiple_requests": "emails.signals (jel; csak mérhető, nem review-ok)",
            "prompt_injection": "emails.signals; policy.email.signal_review -> review-ok `signal:prompt_injection`, policy.email.signal_routes -> human:suspicious",
        },
    },
    "select": {
        "steps": ["parties", "header", "money"], "registry": None, "flow": "invoice / jev_select (S-kar, típus-csomag: invoice_hu)", "state_fn": "jav.jev_select._select_request",
        "consumers": {
            "*": "FieldPick mezőnként: label -> InvoiceHU; policy invoice.pick sáv (human 0,60) alatt review, a csomag high_stakes mezőinél invoice.pick.high_stakes sáv; a csomag required mezői none -> review",
        },
    },
    "verify": {
        "steps": ["verify"], "registry": None, "flow": "invoice / jev_verify (G-kar, típus-csomag: invoice_hu)", "state_fn": "jav.jev_verify.verify",
        "consumers": {
            "*": "JevVerdicts.flags mezőnként (off_target, wrong_kind, incomplete, absence_wrong) és doc_flags; policy invoice.verify sáv (yes 0,70) fölött review; unsupported = kód döntötte (evidencia nélkül)",
        },
    },
    "select_foreign": {
        "steps": ["foreign_parties", "foreign_header", "foreign_money"], "registry": None, "flow": "invoice / jev_select (S-kar, típus-csomag: invoice_foreign)", "state_fn": "jav.jev_select._select_request",
        "consumers": {
            "*": "FieldPick mezőnként: label -> InvoiceHU (supplier_country is); a csomag required (invoice_number, gross_total) és high_stakes mezői; a policy sávjai a magyar számláéval azonosak",
            "supplier_country": "Choice ISO-kódok közül (a szállító címe / adószám-előtagja alapján) - következtetett mező, jelölt nélkül",
            "currency": "a számlázási pénznem (a HUF adóbevallási átváltás informatív, nem pénznem)",
        },
    },
    "verify_foreign": {
        "steps": ["verify_foreign"], "registry": None, "flow": "invoice / jev_verify (G-kar, típus-csomag: invoice_foreign)", "state_fn": "jav.jev_verify.verify",
        "consumers": {
            "*": "mint a `verify`: a Noul-kérdések a verify.json-ból öröklődnek (inherits), a mező-leírások a külföldi számláé; a country mező evidenciája az ország neve / jele a dokumentumon",
        },
    },
    "select_utility": {
        "steps": ["utility_parties", "utility_header", "utility_money", "utility_meter"], "registry": None,
        "flow": "invoice / jev_select (S-kar, típus-csomagok: villamos_energia_szamla, foldgaz_szamla, viz_szamla, mohu_szamla, vizmuvek_szamla, csatorna_szamla - mind extends _base/utility_bill_hu; OCR-szöveg)",
        "state_fn": "jav.jev_select._select_request",
        "consumers": {
            "*": "FieldPick mezőnként: label -> InvoiceHU (+ extra: a csomag további mezői); EGY kérdéskészlet a hat csomag unió-mezőire, minden csomag csak a saját mezőit kérdezi; number fajta = a szám-jelöltek közül (mennyiség, mérőállás), text fajta = címkés szöveg-jelöltek (text_labels)",
            "payment_method": "zárt Choice (postai csekk / csoportos beszedés / átutalás / elektronikus / ...), a header kérésben",
            "reading_method": "zárt Choice (Leol / Becs / Dikt / EII / none), a meter kérésben",
            "currency": "zárt Choice (HUF / EUR / none), a money kérésben",
        },
    },
    "verify_utility": {
        "steps": ["verify_utility"], "registry": None, "flow": "invoice / jev_verify (G-kar, a hat közmű típus-csomag; OCR-szöveg)", "state_fn": "jav.jev_verify.verify",
        "consumers": {
            "*": "mint a `verify`: a Noul-kérdések a verify.json-ból öröklődnek (inherits), a mező-leírások a közmű unió-mezőké; a number fajta evidenciája a szám-illesztés (mint a pénzé)",
        },
    },
}


def all_callsites() -> list[str]:
    """067 (066 Á45): every configured call site (configs/callsites/*.json), not only the hand-described ones."""
    return sorted(n.split(":", 1)[1] for n in cfg.all_names() if n.startswith("callsite:"))


def spec_for(name: str) -> dict[str, Any]:
    """The hand-written description (CALLSITES), or a basic description generated from the config: the ledger steps are
    the request names (`requests`) or the `request_id`; the consumer description is missing in that case."""
    if name in CALLSITES:
        return CALLSITES[name]
    data = cfg.load(f"callsite:{name}")
    steps = list(data["requests"]) if "requests" in data else [data.get("request_id") or name]
    kind = "G-kar ellenőrzés (jev_verify)" if name.startswith("verify") else "S-kar választás (jev_select)" if name.startswith("select")         else "részletes típus (detect_detail)" if name == "detect_detail" else "JEV-hívás"
    return {"steps": steps, "registry": None, "flow": f"{kind}; generált alap-leírás (kézi leírás nincs)", "state_fn": None, "consumers": {}}


def code_hashes(name: str) -> dict[str, str]:
    """067 (066 Á18): the call site's identifier(s) exactly as the code writes them to the call log: for detect and the
    email intent, the module's; for the S path and G path call sites, one per type pack (the pack's identifier is part
    of it, so a shared call site, e.g. the utility bills', has a different identifier per pack)."""
    if name == "detect":
        from jav.detect import CONFIG_HASH

        return {"detect": CONFIG_HASH}
    if name == "email_intent":
        from jav.intent import CONFIG_HASH

        return {"email_intent": CONFIG_HASH}
    if name == "detect_detail":
        from jav import detect_detail

        return {"detect_detail": detect_detail.config_hash()}
    from jav import typepack
    from jav.jev_select import site_for as select_site
    from jav.jev_verify import site_for as verify_site

    out: dict[str, str] = {}
    for key in typepack.keys():
        pack = typepack.get(key)
        if name.startswith("select") and pack.select_callsite == name:
            out[key] = select_site(key).config_hash
        elif name.startswith("verify") and pack.verify_callsite == name:
            out[key] = verify_site(key).config_hash
    return out


def _hash_text(name: str) -> str:
    hashes = code_hashes(name)
    if len(hashes) == 1:
        return f"`{next(iter(hashes.values()))}`"
    return "típuscsomagonként: " + ", ".join(f"{k} `{h}`" for k, h in hashes.items())


def _ledger_stats(steps: list[str]) -> list[dict[str, Any]]:
    marks = ",".join("?" * len(steps))
    with store.connect() as c:
        rows = c.execute(
            f"SELECT COALESCE(config_hash, '(hash előtti)') h, COUNT(*) n, SUM(cached) cached, ROUND(SUM(cost_usd), 4) usd,"
            f" ROUND(AVG(CASE WHEN cached=0 THEN seconds END), 2) live_s, ROUND(AVG(input_tokens), 0) tok, MIN(created_at) first, MAX(created_at) last"
            f" FROM ledger WHERE step IN ({marks}) AND provider='jev' GROUP BY h ORDER BY first",
            steps,
        ).fetchall()
    return [dict(r) for r in rows]


def _state_doc(dotted: str) -> str:
    mod_name, fn_name = dotted.rsplit(".", 1)
    import importlib

    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name, None)
    doc = (inspect.getdoc(fn) or "").strip() if fn else ""
    mod_doc = (inspect.getdoc(mod) or "").strip()
    return doc or mod_doc.split("\n\n")[-1]


def _q_rows(name: str, data: dict[str, Any]) -> list[str]:
    rows = ["| kulcs | fajta | instrukció (eleje) | kritériumok |", "|---|---|---|---|"]
    if name in ("detect", "email_intent"):
        for key, q in data["questions"].items():
            crit = q["criteria"]
            crit_s = f"regiszter `configs/{crit.split(':')[1]}.json`" if isinstance(crit, str) else ", ".join(crit)
            rows.append(f"| `{key}` | {q['kind']} | {q['instructions'][:140]}… | {crit_s} |")
    elif name.startswith("select"):
        for rid, r in data["requests"].items():
            for f in r["fields"]:
                rows.append(f"| `{f}` ({rid}) | choice | {data['instructions'][f][:140]}… | jelöltek (kód, max 250) + `{cfg.load('policy')['none_label']}` |")
        for key, q in data["extra_questions"].items():
            crit = ", ".join(q["criteria"])
            rows.append(f"| `{key}` ({q.get('request', 'money')}) | choice | {q['instructions'][:140]}… | {crit[:160] + ('…' if len(crit) > 160 else '')} |")
        if "presence_template" in data:
            rows.append(f"| `<mező>__present` (minden Choice-mező mellé, ugyanabban a kérésben) | noul | {data['presence_template'][:140]}… | true / false; `presence_what` mezőnként |")
    elif name.startswith("verify"):
        nouls = data.get("nouls") or cfg.load(f"callsite:{data['inherits']}")["nouls"]  # verify_foreign inherits them
        if "inherits" in data:
            rows.append(f"| (örökölt) | - | a Noul-kérdések a `configs/callsites/{data['inherits']}.json`-ból; itt csak a mező-leírások (`field_specs`) sajátok | - |")
        for key, q in nouls.items():
            scope = "mezőnként" if key in ("absence_wrong", "off_target", "wrong_kind", "incomplete") else "dokumentum"
            text = q.get("question") or q.get("instructions", "")  # v1.1.0: structured, `question` = question text
            rows.append(f"| `{key}` ({scope}) | noul (strukturált: field_spec / extracted_field / printed_on / question) | {text[:140]}… | true / false |")
    return rows


def callsite_md(name: str) -> str:
    spec = spec_for(name)
    data = cfg.load(f"callsite:{name}")
    lines = [f"# Jev-hívási hely — `{name}`", "",
             "> Generálva a `configs/` tartalmából és a `ledger` táblából (`jav/docsgen.py`, `python -m jav.cli docs`). Ne szerkeszd kézzel.", "",
             f"- **Flow / lépés:** {spec['flow']}",
             f"- **Konfig:** `configs/callsites/{name}.json` v{data['meta']['version']}" + (f" + regiszter `configs/{spec['registry']}.json` v{cfg.version(spec['registry'])}" if spec["registry"] else "") + f" → `config_hash` = {_hash_text(name)}",
             f"- **Ledger step-ek:** {', '.join(f'`{s}`' for s in spec['steps'])}; adapter: `jav/adapters/jev.py` (kérés-hash cache, ledger)",
             *([f"- **State ({spec['state_fn']}):** {_state_doc(spec['state_fn'])}"] if spec["state_fn"] else []), "",
             "## Kérdések", "", *_q_rows(name, data), "",
             "## A válaszok fogyasztói (küszöbök: `configs/policy.json`)", ""]
    for k, v in spec["consumers"].items():
        lines.append(f"- `{k}`: {v}")
    if not spec["consumers"]:
        lines.append("- (kézi leírás nincs; a hívó modul a folyamatleírásban: `docs/flows/`)")
    lines += ["", "## Futási statisztika konfig-verziónként (ledger)", "",
              "| config_hash | hívás | cache-találat | költség USD | élő átlag s | átlag input token | első | utolsó |", "|---|---|---|---|---|---|---|---|"]
    for r in _ledger_stats(spec["steps"]):
        lines.append(f"| `{r['h']}` | {r['n']} | {r['cached']} | {r['usd']} | {r['live_s'] or '-'} | {int(r['tok'] or 0)} | {r['first'][:16]} | {r['last'][:16]} |")
    lines += ["", "A `(hash előtti)` sor a 2026-09-20-i konfig-kiszervezés előtti hívások. Mérés: golden / determinizmus parancsok a README-ben.", ""]
    return "\n".join(lines)


def write_callsite_docs(out_dir: Path | None = None) -> list[Path]:
    d = out_dir or CALLSITES_DOC_DIR
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for name in all_callsites():
        p = d / f"{name}.md"
        p.write_text(callsite_md(name), encoding="utf-8", newline="\n")  # LF (CLAUDE.md §7)
        out.append(p)
    index = ["# Jev-hívási helyek", "", "> Generált katalógus (`python -m jav.cli docs`). A folyamat egésze: `docs/ARCHITECTURE.md`; a gráfok: `docs/flows/`.", "",
             "| hívási hely | flow / lépés | konfig | hash |", "|---|---|---|---|"]
    for name in all_callsites():
        spec = spec_for(name)
        index.append(f"| [`{name}`]({name}.md) | {spec['flow']} | `configs/callsites/{name}.json` v{cfg.version(f'callsite:{name}')} | {_hash_text(name)} |")
    p = d / "README.md"
    p.write_text("\n".join(index) + "\n", encoding="utf-8", newline="\n")
    out.append(p)
    return out
