# 58_JAV_AI — an AI-flow framework for documents and email

A multilingual framework for AI flows that read documents and emails. It combines Burr (flow orchestration), Pydantic AI (GPT) and JEV/TypeSafe (typed judgements), keeps its data in a local SQLite database, and runs on Windows. The Hungarian invoice flows — document type recognition (M1), invoice data extraction (M2) and email intent (M3) — are the reference flows against which the framework's quality is measured.

**Current stable version: `v1.4.0`** (2026-10-01). What each release brought: [changelog](CHANGELOG.md).

## Plain-language summary

The system reads invoices, other documents and emails. It recognises what type each one is, extracts its data and checks it; anything uncertain goes to a person for review instead of being accepted silently. Documents can be grouped into a work package. One processing then runs on the package in the background through a durable job queue: it recognises each item's type itself, so nothing has to be chosen in advance, and before the start it lists the paid services the run may call and their budget. It works with a cost budget, resumption after a stop and to-dos grouped by reason. You can use it in the browser (`http://127.0.0.1:8930/`), from the command line, or through the local service.

## What it can do now

| Area | Capability | Status |
|---|---|---|
| Recognition | **Document type recognition** (M1): 12 broad types plus "unknown", the document's language and issuer; within a broad type it also picks one of 23 detailed types (for example the statement of a given bank, or a utility bill) | Works |
| Extraction | **Data extraction** (M2) on two paths: code finds the candidates and JEV chooses (S path), or GPT extracts and JEV verifies (G path). Type packs for Hungarian and foreign invoices, six kinds of utility bill and the other detailed types | Works |
| | **Invoice line items**: the line list of an invoice, with a line-total check and per-line checks; line lists can be corrected in the UI, and the checks re-run on the corrected data | Works |
| | **Data checks** in code: one number reader for every path (amounts and quantities read whole, in Hungarian and English notation; money never with three decimals; an ambiguous reading becomes a to-do); tax numbers and bank account numbers by format and check digit; a field with no candidate is flagged "No estimate"; a document without a type pack gets a to-do; limits on file size, page count and image size | Works |
| | **OCR** for PDFs without a text layer: local Tesseract, with optional paid escalation to Azure Document Intelligence when the local result is weak. Azure is a processing setting and is paid from the run's budget | Works |
| Email | **Email intent** (M3): 11 intents, attachment types and a suggested next step; PDF attachments are processed as documents of the same package | Works; real-world accuracy is not proven without a hand-labelled golden set |
| | **Task proposals from emails**: GPT proposes a concrete task (action, deadline, assignee) with a verbatim quote; a code gate drops any proposal the quote does not support; only a person can accept one | Works; off by default |
| | **Mailbox download** from the Outlook running on the machine, by mailbox and period, once or on a schedule, with a free message-count preview; new emails become a work package | Works; needs desktop Outlook |
| Work packages | **Work packages, processing settings and runs**: a package from a folder (optionally with its subfolders; folders and files can be chosen in the Windows picker), an upload, a mailbox or a watched folder; one processing that handles each item by its kind (type recognition, then extraction; email intent and attachments), with versioned settings and a pre-start overview of the services and budget; a readiness check; an idempotent start on a fixed input; trial and live runs; approval and release | Works |
| | **Source instances**: an unchanging copy of every document added to a package, kept once per content; processing, the review page image and the named copies read this copy, so what a person checks is exactly what the result was made from, even if the original is later changed or deleted | Works |
| | **Reliable execution**: a durable job queue and a single background worker; resumption from the saved step; a call log and an up-front cost reservation for every paid call; the cost of each item, run and work package per provider and model, with the run's total first (new); to-dos grouped by reason | Works on the worker path |
| Review | **Workspace** in the browser: each package has three stages — Processing, Review and Result. To-dos are shown on the document's page image with boxed fields, alternative candidates and selection on the image; every field has a tick (correct, recorded as verified) and a cross (fix it), with a filter and keyboard navigation (new); field corrections are versioned. Hungarian and English, light and dark theme | Works |
| | **Users and assignment**: "Who is working?", a package owner, "Only my work packages" and "My work today" | Works; choosing a name is not a login |
| Results | **Reports and export**: Excel, CSV and JSON exports of documents, data points (with page and source text) and line items; a monthly utility-cost grid by point of consumption, showing missing, partial and overlapping months | Works |
| | **Unified data view**: one shared table for every list and result (search, per-column filters and sorting, paging, column picker, selection) and one download panel | Works |
| | **Content-based file names**: copies of a run's documents under uniform names built from their data (date, type, partner, identifier; per-type rules), as a ZIP or into an output folder, with a manifest; the originals never change, and copies with an uncertain name go to a separate review subfolder; the item lists can show each document under its unified name (new) | Works |
| Operations | **Local service** shared by the UI and the command line; it listens on the local machine only and validates every input | Works |
| | **Operations**: a verified daily backup with an optional second location, persistent logs, thinning of the flow-state store and a weekly dependency audit; the System page shows the running version, the worker, the backup and the audit | Works |
| | **Repository safeguards**: a data guard before every commit and push, so that personal data, keys, internal working documents and document files cannot get into git | Works |
| Learning | **Learning branches**: source-anchored data-point candidates and draft type packs for new document types | Experimental |
| Measurement | Golden-set runs, determinism runs, a shared evaluation report and a cost ledger | Works; the golden sets live in the legacy project |

How it is built: [architecture](docs/ARCHITECTURE.md). How to use the workspace: [user guide](docs/guides/USER_GUIDE.md).

**Known limitations:**
- The call log and the budget apply only on the path that runs through the worker. The measurement commands call the models directly, so that closed measurements stay comparable.
- Only one worker runs at a time. While a mailbox download is in progress, the worker does not process document items.
- It is a single-user tool for the local machine, without a login. The open security items are listed in the [security notes](docs/SECURITY.md).
- Mailbox download needs desktop Outlook to be running. Image attachments of emails (for example signature logos) are not processed.
- Runs made with older versions may have no boxes on the page image; the `reground` command recalculates them.
- The utility-cost report breaks down only the gross amount, and it is built from a single run.
- We do not claim real-world accuracy without an independent hand-labelled golden set.

## Getting started

```powershell
uv venv --python 3.12 .venv; uv pip install -r requirements.lock   # details, OCR, keys: docs/guides/SETUP.md
.\.venv\Scripts\Activate.ps1
python -m jav.cli hooks-install        # data guard: checks before commit and push (once per clone)
python -m jav.cli preflight            # tests (Python + UI) + contract lint + configs + handoff + git + data guard + language guard + Ruff limit + state snapshot
python smoke_test.py                   # keys + one live JEV call
```

In a fresh clone, without the legacy project (`10_AIFLOW_V4`) and its golden set, the UI, work packages and runs all work; the golden-set measurements and the legacy Outlook bridge need the legacy project. Details: [setup, fresh clone](docs/guides/SETUP.md).

## Main commands

```powershell
python -m jav.cli run <pdf> --arm S|G [--type invoice_foreign]      # one invoice through the flow, saved to the store
python -m jav.cli golden --arm S|G [--type <pack>] [--no-cache]    # golden-set run (runs/*_golden_*.jsonl; needs the legacy project's golden set)
python -m jav.cli determinism --arm S --n 5                        # repeated runs without the cache (legacy project)
python -m jav.cli detect <pdf> | detect-golden | detect-corpus <folder>   # detect-golden needs the legacy project
python -m jav.cli email <inbox/<mailbox>/<msgid>> | email-golden | email-inbox inbox/   # email-golden needs the legacy project
python -m jav.cli ocr [<pdf>]                                      # without a PDF: the OCR engine's status
python -m jav.cli eval-report [runs/*.jsonl]                       # shared evaluation report from the raw runs, no model calls
python -m jav.cli store | admin | configs | flows --check | docs   # store, admin screen, config versions, contract lint, generated docs
python -m jav.cli recipes | wp-create <folder> [--recursive] | wp-assign <wp> processing | wp-show <wp> | processing-migrate [--write]   # work packages and processing
python -m jav.cli run-start <wp> [--mode shadow|apply] | worker --once | run-show <run> | run-cancel <run> | run-approve <run> --actor <name>   # shadow = trial run, apply = live run
cd ui; npm ci; npm run build; cd ..                               # build the UI (once, and after every ui/src change)
.\scripts\dev.ps1 start | status | stop                          # UI + service: http://127.0.0.1:8930/ (endpoint list: /api/openapi.json) + worker
python -m jav.cli serve | worker-status | worker-stop              # the same, one piece at a time
python -m jav.cli backup [--with-docs] | burr-prune                # store backup (daily backup settings: configs/service.json); thin the flow-state store
python -m jav.cli hooks-install | data-guard [--all]               # enable the data guard; scan the version-controlled tree
python -m jav.cli calls-uncertain | calls-resolve <id> --note N    # settle a paid call with an uncertain outcome by hand
burr                                                               # Burr tracker: http://localhost:7241
```

Full list: `python -m jav.cli --help`, or section 5 of [CLAUDE.md](CLAUDE.md).

**Live email intake:** the recommended route is the UI's Mailbox view. The older manual route uses the legacy project's Outlook bridge unchanged (it writes into the legacy project's `data/` folder): first start `python -m jav.cli email-ingest-server --port 8931 --run [--token <key>]`, then run the bridge in a separate window with the `-ApiToken <key>` switch. The receiver accepts requests only with a key: without `--token` (or the `JAV_INGEST_TOKEN` environment variable) it prints a one-off key at start-up. It rejects requests that come from a browser.

```powershell
powershell -File <legacy-root>\scripts\outlook_bridge.ps1 -RepoRoot <legacy-root> -OrchUrl http://127.0.0.1:8931/ingest/email -Accounts <smtp> -PeriodMode recent -SinceDays 30 -MaxItems 50 -AllEmails -ManualRun -NoArchive -WorkflowId email-intent -WorkflowVersion 1 -ApiToken <key> [-Force]
```

## Repository layout

| Path | Contents |
|---|---|
| `jav/` | the Python package: flows (`flow*.py`), candidate search, JEV/GPT adapters (`adapters/`), validators, store, OCR, evaluation, command line |
| `jav/experiments/`, `configs/experiments/` | closed and ongoing experiments; runtime code does not import them |
| `configs/` | configuration as data: type and intent registries, type packs, call sites, thresholds, models, OCR, the service's limits and backup, recipes, datasets, reports, the data guard ([guide](docs/guides/CONFIGS.md)) |
| `ui/` | the browser workspace (React; build: `ui/dist/`, which the service serves at the root) |
| `tests/` | offline tests (with synthetic data) |
| `scripts/` | the service launcher (`dev.ps1`), the daily backup task, the Claude hooks (`hooks/`), the git hooks (`githooks/`, data guard), one-off experimental scripts |
| `docs/` | codebase documentation (see below); the internal working documents live here too, but git does not track them |
| `runs/`, `store/`, `inbox/` | local runs, the store, emails — not in git (PII) |

## Documentation

Documents in the repository:

- [User guide](docs/guides/USER_GUIDE.md): how to use the workspace
- [Architecture](docs/ARCHITECTURE.md) · [Security notes](docs/SECURITY.md) · [Glossary](docs/GLOSSARY.md) · [JEV playbook](docs/JEV_PLAYBOOK.md)
- [Documentation standard](docs/guides/DOCUMENTATION.md) · [Development workflow](docs/guides/DEVELOPMENT.md) · [Setup](docs/guides/SETUP.md) · [Configuration files](docs/guides/CONFIGS.md)
- [Changelog](CHANGELOG.md): the releases in brief
- Generated flow descriptions: [docs/flows/](docs/flows/) (`python -m jav.cli flows`)
- [Claude instructions](CLAUDE.md): standing working rules for the development model
- Official TypeSafe/JEV documentation: [docs.typesafe.ai](https://docs.typesafe.ai/llms.txt)

The development process also keeps internal working documents (plans, reports, handoffs, the backlog and the decisions log) and a few generated local pages outside git; the [documentation standard](docs/guides/DOCUMENTATION.md) describes how the two groups are kept apart.
