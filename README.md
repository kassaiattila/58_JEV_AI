# 58_JAV_AI — an AI-flow framework for documents and email

A multilingual framework for AI flows that read documents and emails. It combines Burr (flow orchestration), Pydantic AI (GPT) and JEV/TypeSafe (typed judgements), keeps its data in a local SQLite database, and runs on Windows. The Hungarian invoice flows — document type recognition (M1), invoice data extraction (M2) and email intent (M3) — are the reference flows against which the framework's quality is measured.

**Current stable version: `v1.61.0`** (2026-10-29). What each release brought: [changelog](CHANGELOG.md).

## Plain-language summary

The system reads invoices, other documents and emails. It recognises what type each one is, extracts its data and checks it; anything uncertain goes to a person for review instead of being accepted silently. Documents can be grouped into a work package. One processing then runs on the package in the background through a durable job queue: it recognises each item's type itself, so nothing has to be chosen in advance, and before the start it lists the paid services the run may call and their budget. It works with a cost budget, resumption after a stop and to-dos grouped by reason. You can use it in the browser (`http://127.0.0.1:8930/`), from the command line, or through the local service.

## What it can do now

| Area | Capability | Status |
|---|---|---|
| Native documents | **DOCX, XLSX, TXT and CSV** through the work-package workflow: preserve paragraphs, cells and text positions; extract source-linked facts in bounded requests with recorded source coverage; review and correct values or citations; approve the displayed version and export the results. Excel links remain inert, and saved formula values retain their unverified status. Partial readings and failed interpretations remain visible. [Native processing](docs/guides/NATIVE_PROCESSING.md) | Works within reader limits; model accuracy requires evaluation on the intended documents |
| Recognition | **Document type recognition** (M1): 14 broad types plus "unknown" (the newest: a customer's request for a quote), the document's language and issuer; within a broad type it also picks one of 25 detailed types (for example the statement of a given bank, or a utility bill) | Works |
| Extraction | **Data extraction** (M2) on two paths: code finds the candidates and JEV chooses (S path), or GPT extracts and JEV verifies (G path). Type packs for Hungarian and foreign invoices, six kinds of utility bill and the other detailed types | Works |
| | **Invoice line items**: the line list of an invoice, with a line-total check and per-line checks; line lists can be corrected in the UI, and the checks re-run on the corrected data | Works |
| | **Data checks** in code: one number reader for every path (amounts and quantities read whole, in Hungarian and English notation; money never with three decimals; an ambiguous reading becomes a to-do); one date reader for every path (month names in six languages, two-digit years, the document's own dates decide the order of day and month, an undecided order becomes a to-do; new); tax numbers and bank account numbers by format and check digit; one party in two roles (two role fields sharing a name or tax number) becomes a to-do on every path; an invoice whose supplier and buyer stand the other way round than on most earlier invoices of the same two companies becomes a to-do (new); an unfilled template field or a value whose kind (money, percentage, date, time) conflicts with its property becomes a to-do in Word, Excel and text sources (new); a field with no candidate is flagged "No estimate"; a PDF without a fitting type pack still gets source-bound general facts (switchable per package; a scan through local text recognition, with a to-do); limits on file size, page count and image size | Works |
| | **OCR** for PDFs without a text layer: local Tesseract, with optional paid escalation to Azure Document Intelligence when the local result is weak. Azure is a processing setting and is paid from the run's budget | Works |
| Email | **Email intent** (M3): 12 intents (the newest: a quote request), attachment types and a suggested next step; PDF attachments are processed as documents of the same package | Works; real-world accuracy is not proven without a hand-labelled golden set |
| | **Quote requests**: a customer's request for a price quote is read from the email's own text (its sender, date and subject, without the quoted messages), an attached request form or a request list: the customer, its tax number, the contact, the deadline, the customer's reference and the requested items with their quantities; what is uncertain becomes a to-do of the email, and a part that lacks a field (the items stand in the attached list, not in the text) is only a note. An Excel or CSV list attached to the email is read as a part of the request. A processing setting, on by default | New; measured on an invented set only |
| | **Quotes**: a quote is a case of the IT quote process, started from a processed quote request, also straight from the request's email. The seller's price lists are kept in Settings › Price lists: uploaded from Excel with checks, versioned, with discount rules. For each requested item code looks for the item's code first, then the AI proposes a price-list item or none; prices, discounts, VAT and totals are always computed by code. On the quote's page the request stands beside the editable quote: every change is saved at once, a manual price needs a note, a line to review waits for a person, and the approved quote is kept as a version that can be reopened with a reason. The approved quote becomes a Word document (a built-in Hungarian or English template, or the person's own Word template), and a reply letter draft opens in Outlook with it attached: GPT writes a few sentences without numbers, a person accepts the letter, the system never sends it | New; measured on an invented set only |
| | **Partner register**: Settings › Partners keeps the outside parties the processes deal with (customers, suppliers, the insured, brokers), every change a version, retired rather than deleted; the same tax number or name is not recorded twice. It starts empty: the suppliers and buyers of the invoices read are offered as proposals, and only a person records one. A case's page shows the partners its process names (an IT quote: the request's customer) and links it to the register. A process may also keep its own values over its pack's resources (which price list, which template) and over the rule values its steps allow (a quote's lines, the rounding unit), versioned and previewed on its earlier decisions, a case keeping the values it started with (Settings › Processes) | New |
| | **Task proposals from emails**: GPT proposes a concrete task (action, deadline, assignee) with a verbatim quote; a code gate drops any proposal the quote does not support; only a person can accept one | Works; off by default |
| | **Email routing**: each invoice, outgoing invoice and bank statement that arrived by email is proposed for the open work package of its own party, period and role (incoming invoices, outgoing invoices, bank statements), or a new one; a person accepts, chooses another package or leaves it unrouted, and a document that cannot be placed says why. Code only, no AI call; offered on an email package's result and as a workflow after a mailbox download | Works; new |
| | **Mailbox download** from the Outlook running on the machine, by mailbox and period, once or on a schedule, with a free message-count preview; new emails become a work package | Works; needs desktop Outlook |
| Work packages | **Work packages, processing settings and runs**: a package from a folder (optionally with its subfolders; folders and files can be chosen in the Windows picker), an upload, a mailbox or a watched folder; one processing that handles each item by its kind (type recognition, then extraction; email intent and attachments), with versioned settings and a pre-start overview of the services and budget; a readiness check; an idempotent start on a fixed input; trial and live runs; approval and release | Works |
| | **Source instances**: an unchanging copy of every document added to a package, kept once per content; processing, the review page image and the named copies read this copy, so what a person checks is exactly what the result was made from, even if the original is later changed or deleted | Works |
| | **Reliable execution**: a durable job queue and one or more background workers (one by default); resumption from the saved step; a call log and an up-front cost reservation for every paid call (a call sent without an answer counts as uncertain and is never repeated by itself); the cost of each item, run and work package per provider and model, with the run's total first; to-dos grouped by reason | Works on the worker path |
| Review | **Workspace** in the browser: each package has three stages — Processing, Review and Result. To-dos are shown on the document's page image with boxed fields, alternative candidates and selection on the image; every field has a tick (correct, recorded as verified) and a cross (fix it), with a filter and keyboard navigation; field corrections are versioned. Hungarian and English, light and dark theme | Works |
| | **Users and assignment**: "Who is working?", a package owner, "Only my work packages" and "My work today" | Works; choosing a name is not a login |
| Results | **Reports and export**: Excel, CSV and JSON exports of documents, data points (with page and source text) and line items; a monthly utility-cost grid by point of consumption, showing missing, partial and overlapping months, with its own Excel download; **own Excel templates** for a package's workbook, the utility cost and the reconciliation statement: uploaded in Settings, checked (no formulas, macros, links or unknown markers), versioned and previewed with made-up data, then chosen beside each download; a released or approved file is stored, never rebuilt | Works |
| | **Unified data view**: one shared table for every list and result (search, per-column filters and sorting, paging, column picker, selection) and one download panel | Works |
| | **Content-based file names**: copies of a run's documents under uniform names built from their data (date, type, partner, identifier; per-type rules), as a ZIP or into an output folder, with a manifest; the originals never change, and copies with an uncertain name go to a separate review subfolder; the item lists can show each document under its unified name | Works |
| Operations | **Local service** shared by the UI and the command line; it listens on the local machine only and validates every input | Works |
| | **Operations**: a verified daily backup with an optional second location, persistent logs, thinning of the flow-state store and a weekly dependency audit; JEV asked by a pinned version, with a daily look for a newer one; the System page shows the running version, the worker, the backup, the audit and the JEV version | Works |
| | **Repository safeguards**: a data guard before every commit and push, so that personal data, keys, internal working documents and document files cannot get into git | Works |
| | **Rules and their trace**: Settings › Rules shows, for each kind of decision the system makes on its own, what it decides, the values it decides with, the version of its rule files in use and how many decisions it has made; every such decision is recorded with its inputs, its outcome and the rule versions it used (`python -m jav.cli trace`), and every run, item, case and approval names the code and the rule files it was computed with (`python -m jav.cli snapshot`); a proposed version of a rule file can first be tried on the earlier decisions, free (`python -m jav.cli rules-preview`), and each field of work keeps its rules in a file of its own (the email routes `configs/email.json`, the finance rules `configs/finance.json`) | Works |
| Learning | **Teaching a document type**: field proposals from the general facts of a held-out family's development documents, an edited draft from which code makes the type pack, a measurement on documents the draft has not seen, and turning the type on or off by command (a taught type only with that measurement) | Works on one family (the admission ticket: 40/40 fields on its unseen half); one layout of one issuer |
| | **Learning branches**: source-anchored data-point candidates and draft type packs for new document types | Experimental |
| Measurement | Golden-set runs, determinism runs, a shared evaluation report and a cost ledger | Works; the golden sets live in the legacy project |

How it is built: [architecture](docs/ARCHITECTURE.md). How to use the workspace: [user guide](docs/guides/USER_GUIDE.md).

**Known limitations:**
- The call log and the budget apply only on the path that runs through the worker. The measurement commands call the models directly, so that closed measurements stay comparable.
- One worker runs by default (`configs/service.json` `workers` allows more on the same store and machine). With one worker, document items wait while a mailbox download is in progress.
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
python -m jav.cli preflight            # tests (Python + UI) + contract lint + engine matrix + configs + handoff + git + data guard + language guard + Ruff limit + state snapshot
python smoke_test.py                   # keys + one live JEV call
```

In a fresh clone, without the legacy project (`10_AIFLOW_V4`) and its golden set, the UI, work packages and runs all work; the golden-set measurements and the legacy Outlook bridge need the legacy project. Details: [setup, fresh clone](docs/guides/SETUP.md).

## Main commands

```powershell
python -m jav.cli run <pdf> --arm S|G [--type invoice_foreign]      # one invoice through the flow, saved to the store
python -m jav.cli measure [<golden set> ...] [--list] [--store <copy>]   # every golden set with one command (data points, types, intents, logic packs); free from earlier answers; receipt runs/*_measure.jsonl
python -m jav.cli type-propose <family> | type-candidate <key>     # teaching a type: field proposals from a held-out family's facts | the candidate pack of an edited draft
python -m jav.cli type-activate <key> [--replace <pack>] | type-withdraw <key> [--restore]   # turn a type pack's detection on or off (no AI call)
python -m jav.cli golden --arm S|G [--type <pack>] [--no-cache]    # golden-set run (runs/*_golden_*.jsonl; needs the legacy project's golden set)
python -m jav.cli golden --arm S --type <pack> --synthetic         # the invented cases of configs/golden_synthetic.json (runs/*_synthetic_*.jsonl)
python -m jav.cli golden --arm S --type <pack> --cases <file> --store <copy>   # a local case list with reference values (runs/*_local_*.jsonl; agreement, not accuracy)
python -m jav.cli determinism --arm S --n 5                        # repeated runs without the cache (legacy project)
python -m jav.cli detect <pdf> | detect-golden | detect-corpus <folder>   # detect-golden needs the legacy project
python -m jav.cli email <inbox/<mailbox>/<msgid>> | email-golden | email-inbox inbox/   # email-golden needs the legacy project
python -m jav.cli ocr [<pdf>]                                      # without a PDF: the OCR engine's status
python -m jav.cli eval-report [runs/*.jsonl]                       # shared evaluation report from the raw runs, no model calls
# golden, detect-golden and extract_cases with --budget-usd exit with code 3 when the budget left cases without a result;
# golden and email-golden take a hard JEV budget with --jev-budget-usd (a provider without a budget cannot be called)
# every command that can make paid calls (also run, detect, detect-corpus, email, email-inbox and the determinism ones)
# needs the sub-budget for live calls: --jev-budget-usd, --budget-usd (OpenAI); Azure is never called from the command
# line; without a budget only earlier answers count (the JEV cache) and a live call becomes a to-do
# every command that asks AI takes --engine jev|gpt (--no-jev = --engine gpt): run, detect, detect-corpus, email and
# email-inbox follow the application's AI engine (Settings > Processing) when they name none; the measurements measure
# JEV and GPT unless told, and the S path needs JEV
python -m jav.cli store | admin | configs | flows --check | docs   # store, admin screen, config versions, contract lint, generated docs
python -m jav.cli recipes | wp-create <folder> [--recursive] | wp-assign <wp> processing [--engine jev|gpt] | wp-show <wp> | processing-migrate [--write]   # work packages and processing
python -m jav.cli run-start <wp> [--mode shadow|apply] | worker --once | run-show <run> | run-cancel <run> | run-approve <run> --actor <name>   # shadow = trial run, apply = live run
cd ui; npm ci; npm run build; cd ..                               # build the UI (once, and after every ui/src change)
.\scripts\dev.ps1 start | status | stop                          # UI + service: http://127.0.0.1:8930/ (endpoint list: /api/openapi.json) + worker
python -m jav.cli serve | worker-status | worker-stop              # the same, one piece at a time
python -m jav.cli backup [--with-docs] [--with-env] | burr-prune                # store backup (daily backup settings: configs/service.json); thin the flow-state store
python -m jav.cli hooks-install | data-guard [--all]               # enable the data guard; scan the version-controlled tree
python -m jav.cli calls-uncertain | calls-resolve <id> --note N    # settle a paid call with an uncertain outcome by hand
burr                                                               # Burr tracker: http://localhost:7241
```

Full list: `python -m jav.cli --help`, or section 5 of [CLAUDE.md](CLAUDE.md).

**Live email intake:** the recommended route is the UI's Mailbox view. The manual route uses the Outlook bridge in `scripts/outlook_bridge.ps1` (ported from the legacy project; it reads the Inbox, its direct subfolders and, with `-MailFolders 'Sent Items'`, the sent messages; an unknown folder is an error): first start `python -m jav.cli email-ingest-server --port 8931 --run [--token <key>]`, then run the bridge in a separate window with the `-ApiToken <key>` switch. The receiver accepts requests only with a key: without `--token` (or the `JAV_INGEST_TOKEN` environment variable) it prints a one-off key at start-up. It rejects requests that come from a browser.

```powershell
powershell -File scripts\outlook_bridge.ps1 -RepoRoot inbox\.bridge -OrchUrl http://127.0.0.1:8931/ingest/email -Accounts <smtp> -PeriodMode recent -SinceDays 30 -MaxItems 50 -AllEmails -ManualRun -NoArchive -WorkflowId email-intent -WorkflowVersion 1 -ApiToken <key> [-Force]
```

## Repository layout

| Path | Contents |
|---|---|
| `jav/` | the Python package, one folder per layer ([architecture](docs/ARCHITECTURE.md)): `core/` (store, settings, registries, call log, job queue), `documents/` (PDF, OCR, native readers), `ai/` (JEV and GPT, candidates, type packs, validators, decision rules), `flows/` (the Burr graphs), `app/` (work packages, runs, results, outputs, workflows), `runtime/` (the worker), `domains/` (email, finance, quotes), `service/` (the local service), `cli/` (the command line), `evals/` (measurement), `devtools/` (preflight, guards, generated documents), `legacy/` (the legacy port) |
| `jav/evals/` (`jev_estimate.py`, `extract_cases.py`, `document_injection_probe.py`), `configs/experiments/` | three stand-alone measurement tools (free JEV estimate, extraction on a case list, injected-instruction probe); runtime code does not import them |
| `configs/` | configuration as data: type and intent registries, type packs, call sites, thresholds, models, OCR, the service's limits and backup, recipes, datasets, reports, the data guard ([guide](docs/guides/CONFIGS.md)) |
| `ui/` | the browser workspace (React; build: `ui/dist/`, which the service serves at the root) |
| `tests/` | offline tests (with synthetic data) |
| `scripts/` | the service launcher (`dev.ps1`), the daily backup task, the Claude hooks (`hooks/`), the git hooks (`githooks/`, data guard), one-off experimental scripts |
| `docs/` | codebase documentation (see below); the internal working documents live here too, but git does not track them |
| `runs/`, `store/`, `inbox/` | local runs, the store, emails — not in git (PII) |

## Documentation

Documents in the repository:

- [User guide](docs/guides/USER_GUIDE.md): how to use the workspace
- [Design system](docs/guides/DESIGN.md): the workspace's colours, type, components and the check for a changed screen
- [Architecture](docs/ARCHITECTURE.md) · [Security notes](docs/SECURITY.md) · [Glossary](docs/GLOSSARY.md) · [JEV playbook](docs/JEV_PLAYBOOK.md)
- [Documentation standard](docs/guides/DOCUMENTATION.md) · [Development workflow](docs/guides/DEVELOPMENT.md) · [Setup](docs/guides/SETUP.md) · [Configuration files](docs/guides/CONFIGS.md)
- [Changelog](CHANGELOG.md): the releases in brief
- Generated flow descriptions: [docs/flows/](docs/flows/) (`python -m jav.cli flows`)
- Bank files the system reads (generated): [docs/BANK_FILES.md](docs/BANK_FILES.md) (`python -m jav.cli docs`)
- [Claude instructions](CLAUDE.md): standing working rules for the development model
- Official TypeSafe/JEV documentation: [docs.typesafe.ai](https://docs.typesafe.ai/llms.txt)

The development process also keeps internal working documents (plans, reports, handoffs, the backlog and the decisions log) and a few generated local pages outside git; the [documentation standard](docs/guides/DOCUMENTATION.md) describes how the two groups are kept apart.
