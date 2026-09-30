# 58_JAV_AI — an AI-flow framework for documents and email

A multilingual framework for AI flows that read documents and emails. It combines Burr (flow orchestration), Pydantic AI (GPT) and JEV/TypeSafe (typed judgements), keeps its data in a local SQLite database, and runs on Windows. The Hungarian invoice flows — document type recognition (M1), invoice data extraction (M2) and email intent (M3) — are the reference flows against which the framework's quality is measured.

**Current stable version: `v1.1.0`** (2026-09-30; a second security round after a repeated audit: Azure recognition as a recipe switch within the run's budget, a real upper bound for cost reservations, verified source documents, bank account check digits, a weekly dependency audit, and the repository's documentation in English — see the [changelog](CHANGELOG.md)). The code has been on GitHub, in a private repository, since 2026-09-29. The GitHub history starts with a new root commit on 2026-09-30; the earlier history is kept only locally ([development guide §1](docs/guides/DEVELOPMENT.md)).

Release notes, measurement reports, plans, handoffs, the backlog and the decisions log are **internal working documents**: they live only on the developer's machine and are not in the repository. Where this README refers to one, it is marked "(internal: …)" with its local path under `docs/`.

## Plain-language summary

The system reads invoices, other documents and emails. It recognises what type each one is, extracts its data and checks it; anything uncertain goes to a person for review instead of being accepted silently. Documents can be grouped into a work package. A recipe (a versioned description of the processing) then runs on the package in the background through a durable job queue, with a cost budget, resumption after a stop and to-dos grouped by reason. You can use it in the browser (`http://127.0.0.1:8930/`), from the command line, or through the local service. The detailed history of earlier measurements is in the README history (internal).

## What it can do now

| Capability | Status | Details |
|---|---|---|
| **Document type recognition** (M1): 12 broad types plus unknown, language, issuer | Works; measured on the old golden set | history: M1 (internal: `reports/2026-09-27-readme-tortenet.md`) |
| **Invoice data extraction** (M2), on two paths: code finds candidates and JEV chooses (S path), or GPT extracts and JEV verifies (G path) | Works for Hungarian and foreign invoices and six utility-bill type packs | history (internal: `reports/2026-09-27-readme-tortenet.md`) |
| **Email intent** (M3): the legacy project's 11 intents, attachment types, next step | Works; real-world accuracy is not proven without a hand-labelled golden set | expansion (internal: `EXPANSION_2026-09-22.md`) |
| **OCR** for PDFs without a text layer: local Tesseract, with paid escalation to Azure when the result is weak (since 075 a recipe switch, within the run's Azure budget and the call log) | Works; skipped pages show up as to-dos | assessment, F07 (internal: `FRAMEWORK_ASSESSMENT_2026-09-22.md`) |
| **Unified document types** (047 T1): all 23 old types are full type packs; recognition also picks the detailed type; a document-processing recipe; old results can be imported for comparison | Works; on the old recognition golden set the detailed type matches in 95 of 97 cases; line lists (e.g. bank statement transactions) can be corrected on a separate tab in the UI, and the statement rules re-run on the corrected data (048) | T1 report (internal: `reports/2026-09-28-t1-tipusegyesites.md`), [architecture §10](docs/ARCHITECTURE.md#10-unified-document-types-047-t1-2026-09-28) |
| **Learning branches:** source-anchored data-point candidates, draft type packs | Experimental | document learning (internal: `DOCUMENT_LEARNING_2026-09-21.md`) |
| **Work package → run** (040 K1): package from a folder, recipe, readiness check, idempotent start with a fixed input, background worker, trial/live mode, approval | Works from the command line; the first recipe was invoice extraction | [architecture §6](docs/ARCHITECTURE.md#6-execution-layer-work-package--run--worker-040-k1-2026-09-27) |
| **Reliable execution** (040 K1): call log and up-front cost reservation, resumption from the saved step, to-dos by reason, flagging of partial OCR, a protected email receiver | Works on the path that runs through the worker | [failure probes](docs/ARCHITECTURE.md#6-execution-layer-work-package--run--worker-040-k1-2026-09-27) |
| **Local service** (040 K2): the whole lifecycle can be driven without a browser; own machine only, with validated input; versioned field corrections; a single worker instance that can be stopped cleanly | Works; the UI (K3) is built on it | [architecture §7](docs/ARCHITECTURE.md#7-local-service-040-k2-2026-09-27) |
| **Workspace** (040 K3, 045 K3b): work packages with their items; to-dos on the document's page image with boxed fields, alternative candidates and selection on the image; choosing a recipe and starting a run; following a run, its cost and its approval (since 057 in the package's stages, see below) | First version; live trial on 5 real invoices; in the cached rerun 77 of 82 fields got an exact box and 1 an approximate one (046; 71 before) | [architecture §8](docs/ARCHITECTURE.md#8-user-interface-040-k3-2026-09-27), live trial (internal: `reports/2026-09-27-k3-elo-proba.md`) |
| **Mailbox** (048 T2): download from the Outlook running on the machine, by mailbox and period, with a free message-count preview, once or on a schedule (default: hourly); new emails become a work package with the email-intent recipe; a person starts the paid run | Works; tried on two real mailboxes on 2026-09-28 (45 + 2 emails, trial mode), see handoff 051 (internal) | [architecture §11](docs/ARCHITECTURE.md#11-mailbox-reading-and-scheduling-048-t2-2026-09-28) |
| **Invoice line items** (053 T3): the line items of Hungarian and utility invoices as a line list, with a line-total check and per-line checks; utility invoices use the G path by default | Works; on the 49 utility documents the line items add up to the invoice total in 44 cases | T3.4 measurement (internal: `reports/2026-09-28-t3-szamlatetelek-meres.md`) |
| **Boxes on the page image** (054): every field found gets a coloured box; a value that appears in several places is placed where it is most likely; line items are located too, and clicking a line jumps to it | Works; on the T3.4 package 79% of fields and 88% of line items get a position | handoff 054 (internal: `handoffs/054-2026-09-28-handoff.md`) |
| **Reports** (054 K4): run export to Excel, CSV and JSON (documents; data points with page and source text; line items); monthly utility cost by point of consumption and utility, showing missing, partial and overlapping months, with the source invoices behind each cell | Works; on the T3.4 package 6 time series, 4 duplicate invoices filtered out | [architecture §10](docs/ARCHITECTURE.md#10-unified-document-types-047-t1-2026-09-28) |
| **Unified data view** (056 U1): every list and result table uses one shared table (search, per-column filtering and sorting, paging, column picker, selection); the run's result tables (since 057 in the package's Result stage); a searchable picker instead of every drop-down; a shared download panel (Excel / CSV / JSON; all, filtered or selected rows; columns) | Works; the 1,336 data points of the T3.4 run paged and filtered; after the first request a run's data comes from a cache (0.1 s instead of 10 s) | 056 plan (internal: `plans/056/PLAN.md`), [architecture §10](docs/ARCHITECTURE.md#10-unified-document-types-047-t1-2026-09-28) |
| **New UI structure** (057): two main areas, Work packages and Settings. A package has three stages: Processing (trial / live run, rerun), Review (to-dos, document downloads) and Result (tables, utility cost, download, approval); the button in the header is always the next step. Settings: mailboxes, work folders (watched folders), users, appearance (light / dark), language (Hungarian / English), system; since 063 also recipes | Works; checked in the browser in both languages and in the dark theme | 057 plan (internal: `plans/057/PLAN.md`) |
| **UI fixes** (058): hiding and renaming a package, and deleting one that never had a run; the status badge updates once the to-dos are closed; readable Hungarian names instead of code names (recipe, email intent, path); shortened links in emails; one highlighted run button with an explanation; previously used mailboxes can be picked; Result offers only the views that contain data; every table header shows its sorting; every field has a Hungarian name; large packages open faster | Works; checked in the browser; the 96-document package opens in 0.6 s instead of 3.0 s | handoff 058 (internal: `handoffs/058-2026-09-28-handoff.md`) |
| **Emails as a second recipe** (058 K5.1–K5.2): the email result is kept for each run; the Result stage's "Emails" view and the Emails sheet of the full Excel workbook (intent, suggested next step, attachments, the part of the email text that was read); the intent can be corrected by hand and the next step is recalculated from it; the email's PDF attachments run in the package as documents with the same recipe (including data extraction), traced back to the email | Works; tested with synthetic emails; the Emails view checked on the 45 real emails (without paid calls) | handoff 059 (internal: `handoffs/059-2026-09-28-handoff.md`) |
| **Task proposals from emails** (058 K5.3): using the legacy project's prompt, GPT proposes a concrete task for each email (action, deadline, assignee) with a verbatim quote; a code gate drops any proposal the quote does not support; no proposal is requested for emails that are to be archived; only a person can accept a proposal (email view, Tasks view, Excel Tasks sheet). Off by default in the email recipe | Measured: of the 47 real emails, a proposal was requested for 4 and no task was proposed for any of them, identically in two runs; without the skip rule, 1 of 38 newsletters got false tasks; on the legacy project's 7 synthetic golden cases, 14/14 agreement; USD 0.21 | measurement (internal: `reports/2026-09-28-k5-feladatjavaslat-meres.md`) |
| **Recipe explanations and bolder controls** (063): on the package's Recipe card, the meaning of the chosen value for each setting and the cost budget per item; a Settings › Recipes page with the full description (what it is for, when to choose it, what it needs, steps, result, what the person has to do); buttons with an accent-coloured border and an icon, larger menu items | Works; checked in the browser in both languages, in light and dark themes | release note (internal: `reports/2026-09-29-v1.0.0-kiadas.md`) |
| **Operational foundations** (063, 064): the worker does not stop on a failing job; interrupted work is restarted a limited number of times; emails from an interrupted download and files in a watched folder are not lost; a persistent log (`runs/logs/`); a daily database backup at 12:00, locally and on the NAS (14 are kept; since 070 together with the internal working documents), with its status on the System page; the flow-state store is thinned for each closed item | Works; 16 + 10 operational tests; backup and NAS copy checked on the real database; live end-to-end check for USD 0.001 | [SETUP §6](docs/guides/SETUP.md), release note (internal: `reports/2026-09-29-v1.0.0-kiadas.md`) |
| **Users and assignment** (061, 062): choosing a name is mandatory ("Who is working?"); each package has an owner; "Only my work packages" and "My work today"; a run is started from a confirmation page; an accepted task can be marked "done" by hand | Works; choosing a name is not authentication (there is no login) | [user guide](docs/guides/USER_GUIDE.md) |
| **Data checks** (067, 069 `v1.0.4`): tax numbers are checked by recognised format and check digit, for both parties and on foreign invoices too (the label is stripped; a phone number or a value with a wrong check digit gets a to-do); a field without candidates gets a "No estimate" flag and a presence question; a lost glyph no longer produces a negative amount; a document without a type pack gets a to-do; input limits (100 MB, 300 pages, 40 megapixels per page) | Works; re-measured on the four counterexamples from the independent audit | [architecture](docs/ARCHITECTURE.md) |
| **Security fix round** (071, `v1.0.5`): a data guard before every commit and push (personal data, keys, internal working documents and document files cannot get into git; the old history cannot be pushed); browser security headers on every response, and the browser does not store document data; the System page and the health endpoint show the running version and commit | Works; 52 new program tests and 3 UI tests; 18 views checked in the browser with 0 policy violations | [security notes](docs/SECURITY.md) |
| **Second security round** (075, `v1.1.0`): Azure recognition of weak scans as a recipe switch, reserved from the run's budget and logged; the cost reservation is a real upper bound; source documents and page images are served only after a full content check; Hungarian bank account numbers need valid check digits; the data guard checks renamed files in full; the JEV SDK 0.7.2 and key masking in the logs; a weekly dependency audit on the System page | Works; 47 new program tests and 4 UI tests; the golden sets are unchanged; checked in the browser | [security notes](docs/SECURITY.md) |
| **Measurement:** golden-set runs, determinism, a shared evaluation report, a cost ledger | Works | commands below |

**Known limitations:**
- The call log and the budget apply only on the path that runs through the worker. The old measurement commands still call the models the earlier way, so that closed measurements stay comparable.
- Only one worker can run at a time (a lock enforces this).
- The local service has no login: it is a single-user tool for your own machine.
- Mailbox download needs Outlook to be running; while a download is in progress, the worker does not process document items. Image attachments of emails (e.g. signature logos) are not processed.
- Runs from before 2026-09-28 have no boxes; they get them after a rerun (the word layer of old OCR results is filled in). The boxes of an existing run can be recalculated with the `reground` command.
- The utility-cost report breaks down only the gross amount, and it is built from a single run (merging several runs is not supported yet).
- A few management operations (delete, hide, rename, the name and folder lists) run without a version check; the backup is not encrypted; personal data has no retention period yet. Open security items: [security notes](docs/SECURITY.md).
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
python -m jav.cli recipes | wp-create <folder> | wp-assign <wp> invoice-extraction | wp-show <wp>   # work packages and recipes
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

**Live email intake:** the recommended route is the UI's Mailbox view (048). The older manual route uses the legacy project's Outlook bridge unchanged (it writes into the legacy project's `data/` folder): first start `python -m jav.cli email-ingest-server --port 8931 --run [--token <key>]`, then run the bridge in a separate window with the `-ApiToken <key>` switch. Since 066 the receiver accepts requests only with a key: without `--token` (or the `JAV_INGEST_TOKEN` environment variable) it prints a one-off key at start-up. It rejects requests that come from a browser.

```powershell
powershell -File C:\00_DEV_LOCAL\10_AIFLOW_V4\scripts\outlook_bridge.ps1 -RepoRoot C:\00_DEV_LOCAL\10_AIFLOW_V4 -OrchUrl http://127.0.0.1:8931/ingest/email -Accounts <smtp> -PeriodMode recent -SinceDays 30 -MaxItems 50 -AllEmails -ManualRun -NoArchive -WorkflowId email-intent -WorkflowVersion 1 -ApiToken <key> [-Force]
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

Local only, outside git (internal working documents; see the [documentation standard](docs/guides/DOCUMENTATION.md)):
- the internal entry page (`docs/INDEX.md`): the current plan and an index of reports;
- the backlog, the decisions log and the roadmap;
- plans, reports and handoffs;
- generated pages: the state snapshot (`docs/STATE.md`) and the call-site catalogue (`docs/callsites/`, `python -m jav.cli docs`).
