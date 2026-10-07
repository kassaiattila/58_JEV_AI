# CLAUDE.md

Codex starts from [AGENTS.md](AGENTS.md). The project rules below are shared; host-specific hook and tool behaviour is described in that entry point.

Standing working rules for Claude Code in this repository. **Session state, progress and measured numbers do not belong here.** The current state lives in: the latest `docs/handoffs/NNN-*.md`, the generated `docs/STATE.md`, `docs/BACKLOG.md` and the current plan (`docs/INDEX.md` → "Aktuális munka"). These are **internal working documents** (070): they exist only locally, git does not track them, and a fresh clone does not have them. How the documents are organised is described in [docs/guides/DOCUMENTATION.md](docs/guides/DOCUMENTATION.md), the git workflow in [docs/guides/DEVELOPMENT.md](docs/guides/DEVELOPMENT.md).

## 1. What this project is

A general, multilingual **AI-flow framework for processing documents and emails**: Burr (orchestration) + Pydantic AI (GPT) + JEV/TypeSafe (typed judgements), with local SQLite. The Hungarian invoice flows (**M1** document type recognition, **M2** data-point extraction, **M3** email intent) are **reference flows**: they are how we measure the quality of the framework. When adding a capability, generalise the framework layer; do not grow invoice-specific code. Secondary goal: a new document type should be teachable, and the data points of unknown text should also be stored in a structured way.

- **Language (decision of 2026-09-30, 073; supersedes the earlier "comments and documentation in Hungarian" rule):**
  - Talk to the owner in Hungarian (§8).
  - Everything that reaches GitHub is native-level **British English**: code, identifiers, comments, docstrings, CLI/API/log messages, test names, codebase documents, commit and tag messages. The UI's source strings are English; Hungarian comes from the UI translation files and stays the default display language.
  - Internal working documents (handoffs, plans, reports, backlog, decisions log, roadmap) stay Hungarian.
  - Hungarian text printed on documents (labels such as *számla sorszáma*, keyword lists, glossary lines inside prompts) is document vocabulary and stays Hungarian: changing text sent to a model creates new cache keys and needs a paid re-measurement.
  - The conversion of the existing Hungarian code and documents is backlog item N-angol (plan 073). New and changed code is written in English from now on.
- **PII** (real documents, emails, golden-set content) never goes into git, only sha256 + path. New tests use synthetic or anonymised data only.
- **Legacy project:** `10_AIFLOW_V4`, a sibling folder of this repository (`JAV_LEGACY_ROOT` overrides it; `jav/config.py`), read-only (see §3). It is Burr-native; its state of 2026-09-09 also contains LangGraph. It is not Langflow, even when the owner calls it that.

### Standing constraints from the owner (details and dates: `docs/DECISIONS.md`; do not reopen)

- OpenAI and JEV may both be used on the document and email samples already approved. Do not ask again for a general provider permission.
- Overall budget: separate OpenAI and JEV budgets approved by the owner. The amounts and their increases are only in the decisions log (internal: `DECISIONS.md`, budget increase of 2026-09-28; decision of 2026-09-30: not on GitHub). The remainder is in the current accounting file (linked from the latest handoff). Allocate a sub-budget within it before each new measurement; never merge old budgets or raise them implicitly.
- Manual labelling is postponed and is not a prerequisite. Never call model agreement accuracy.
- Enterprise and productisation work (SSO/RBAC, tenants, HA, pricing) is not a priority now.
- Production thresholds, policies or processes are activated only by an owner decision.

## 2. Session protocol (explicitly requested by the owner)

1. **Start = situation assessment, not coding.** Run `python -m jav.cli preflight`, `git status`, `git log --oneline -10`. Read the latest handoff (the SessionStart hook loads it), `docs/STATE.md`, `docs/BACKLOG.md`, the end of `docs/DECISIONS.md` and the current plan. Then give a 5–8 line summary following the §8 structure, with open decisions and a proposed order, and **ask the owner whether they agree** before building anything.
2. **Independent professional judgement.** An earlier plan or handoff is input, not an order. Check it against the code and the measured facts. If you deviate from it, say so and explain why.
3. **Git.** `main` is always green. One branch per stage, small commits, tests and codebase documentation in the same commit as the code. Internal working documents (handoffs, plans, reports, BACKLOG, DECISIONS, ROADMAP, INDEX, `docs/callsites/`; list: `jav/doc_scope.py`) are never committed, and no codebase document links to them (DOCUMENTATION §1.7). Format and tags: see the DEVELOPMENT guide. Before a commit: `preflight --skip-pytest` + the affected tests; before a merge: the full `preflight`. The data guard runs before every commit and push (`hooks-install`, DEVELOPMENT §1); `--no-verify` is forbidden. Use a remote only with an owner decision. `origin` (GitHub) only receives `main`, release tags and stage branches built on the repository's current root commit; never push the local archive branches, older stage branches or old tags. `--all` / `--tags` / `--mirror` are forbidden; the local `pre-push` hook rejects them (DEVELOPMENT §1).
4. **Handoff** (`docs/handoffs/NNN-YYYY-MM-DD-handoff.md`, template: `TEMPLATE.md`; earlier handoffs are never modified; written in Hungarian). A new handoff is needed only at the end of a session and when a stage closes (decision of 2026-09-27; git carries the fine-grained history). A finished measurement also closes a stage; a session also ends when the context is roughly half full. Contents: what was built (table), owner decisions with dates (the same ones go into `DECISIONS.md`), measurements with evidence links, open questions, next step, pitfalls, **commit hash**. The handoff stays local and is not committed (070). Never copy status numbers by hand; refer to `STATE.md`.
5. **Claude Code hooks** (`.claude/settings.json`, `scripts/hooks/handoff_guard.py`): SessionStart loads the handoff and prints the git state; PreCompact warns; Stop refreshes `STATE.md` when the handoff is stale and gives a **non-blocking** reminder (uncommitted files, commits since the handoff; decision of 2026-09-27). The PostToolUse handoff review agent is specific to Claude Code. In Codex, use the separate hook configuration and direct handoff review described in AGENTS.md; do not assume the Claude hooks ran.
6. **The owner decides.** For unresolved policy questions (type boundaries, order, class sets, budget), use the host's available clarification tool with options and a recommendation. Continue work already authorised in the session without repeating the same question. Record decisions in the handoff and `DECISIONS.md`, with a date. Update persistent memory only when explicitly requested by the owner.

## 3. Reuse: search first, write only afterwards

Before building, check whether the legacy project already has it: `scripts/` (e.g. `outlook_bridge.ps1`), `flows/*-bare/` (flow + CONTRACT + golden), `orchestrator/framework/` (jobq, tabular, businessworkflows…), `sidecar/app/`, `ui/src/` (behavioural patterns and tests), `data/golden/`, `.planning/`. If it exists, reference it (path in `jav/config.py`) or port it selectively with a provenance note. Within this repository, too, extend existing code instead of duplicating it. The runtime must never import the legacy orchestrator through `sys.path` tricks or read the legacy production database. State the decision in the handoff: "existed / ported / new, because…".

## 4. Development rules

- **Choose tools by measurement.** Exact calculations, and format and source matching, are done in code. GPT and JEV may be used separately or together for interpretation, extraction, categorisation and verification. Measurement decides the division of roles: correctness, completeness, false acceptance, robustness, latency and cost. Model agreement and JEV support are not independent evidence of correctness. For a new JEV question, read the relevant part of `docs.typesafe.ai`.
- **JEV checklist** (details: `docs/JEV_PLAYBOOK.md`):
  - Write English instructions and glossaries; the state is verbatim text, in Hungarian or English.
  - Always offer a `none`/`unknown`/`other` answer; candidates are deduplicated. The API accepts at most 255 options per Choice; our own cap is 250 candidates plus `none` (`MAX_OPTIONS` in `jav/candidates.py`), and a longer list is cut off, not split.
  - A few-shot example may only be included if it is consistent with the golden set.
  - The question names the narrowest deciding fact.
  - Choice descriptions: `what / not_for / examples`. Grades need a Score (≤ 10 levels); yes/no needs a Noul with a two-sided band.
  - Every optional field gets a presence Noul. The record confidence is the weakest judgement.
  - Number, date and string matching happens in code, before the question. In measurements the concrete `model` version counts, not the alias.
- **Raw probabilities in the state, thresholds only in `configs/policy.json`** (`jav/policy.py`). The review latch is additive: `needs_review` may only change from False to True. `run_id` is the backbone. Every AI call goes into the ledger, failed ones too. On `JevUnavailableError` a `jev_unavailable:<reason>` review item is queued and the flow does not fail. Money: `Decimal`.
- **Config as data.** Type and intent registries, instructions, schemas and thresholds live in versioned JSON (`meta`); the `config_hash` goes into the ledger. After a config change: version bump, golden run, `python -m jav.cli docs`.
- **The Burr graph is the contract.** Phases, steps and edges are data structures; `FLOW.md` and the Mermaid diagram are generated from them, and a lint checks that they match. A new framework module is only created once two flows have already written the same thing by hand.
- **Measure before and after.** A registry, instruction or threshold change needs a golden run. Determinism is only measurable with `use_cache=False` and `no_cache_write()`. Say so when a refinement was measured on its own training examples. Before a code change: `recall` + `pytest`, test-first. A live, paid measurement only starts on a clean working tree, with the commit hash recorded.
- **Diagnosis order:** `runs/*.jsonl` → a `--no-cache` run / `verifier-probe` → only then an instruction or description change, as a general rule, never as a fixture hack.
- **Code quality.** New or substantially changed code is Ruff-clean, with no wildcard imports and no swallowed exceptions. Public operations have typed inputs and outputs and named errors. Dependency direction: UI/CLI → application operation → business module/runtime → adapter/store. Runtime code never imports experimental code.

## 5. Commands

Activated venv: `.\.venv\Scripts\Activate.ps1`; without it: `.venv\Scripts\python.exe`. Installation: [docs/guides/SETUP.md](docs/guides/SETUP.md).

```powershell
python -m jav.cli preflight [--skip-pytest]      # session start: tests (Python + UI) + contract lint + configs + handoff + git + data guard + language guard + Ruff limit + state snapshot
pytest tests/                                     # offline tests; a single test: pytest tests/test_emails.py -k next_flow
python smoke_test.py                              # venv + keys + one live JEV call
python -m jav.cli recall | golden --arm S|G | determinism --arm S --n 5 | verifier-probe [--no-cache] [--type invoice_foreign]
python -m jav.cli detect <pdf> | detect-golden | detect-determinism --n 3 | detect-corpus <folder> [--redo-unknown] | detect-sample <folder>
python -m jav.cli email <folder> | email-golden | email-determinism --n 3 | email-inbox inbox/ | email-sample | email-injection-probe
python -m jav.cli email-ingest-server --port 8931 --run   # receiver for the legacy outlook_bridge.ps1 (8901 = legacy Docker)
python -m jav.cli recipes | wp-* | run-* | worker [--once] | worker-status | worker-stop   # work package → run (jav/work_cli.py)
python -m jav.cli calls-uncertain | calls-resolve <id> [--cost USD] --note N   # settle a paid call with an uncertain outcome by hand
.\scripts\dev.ps1 start|status|stop                     # UI + local service (serve, 127.0.0.1:8930) + one worker
cd ui; npm run build | npm test | npm run dev             # UI (ui/): build into ui/dist, vitest, dev server :5173
python -m jav.cli ocr [<pdf>] [--force] [--psm N] [--limit N]   # without a PDF: status of the OCR engine
python -m jav.cli store | eval-report [runs/*.jsonl] [--out f] | admin [--write] | configs | flows [--check] | docs
python -m jav.cli backup [--with-docs] [--with-burr] [--copy-to <dir>] | burr-prune [--no-vacuum]   # store backup (daily: --scheduled) | thin out the Burr state store
python -m jav.cli hooks-install | data-guard [--all]        # 071 data guard: enable the git hooks (once per clone) | scan the tracked tree
python -m jav.cli deps-audit [--show]                       # 075 known vulnerabilities in the pinned packages (weekly with the daily backup)
python -m jav.capability_catalog                  # deterministic inventory of types and intents
```

`JAV_OCR_ENGINE=azure_di <command>`: Azure DI, called directly when `AZURE_DI_ENDPOINT` and `AZURE_DI_KEY` are in `.env` (121, `jav/adapters/azure_di.py`), otherwise through the legacy sidecar (only for PDFs under the legacy data folder). **Paid**, page-limited, never chosen by `auto`, but OCR escalation (`configs/ocr.json`) calls it automatically on weak local OCR; since 075 only within the run's Azure budget (recipe switch `azure_ocr`, 0.02 USD per document by default) and through the call log (`jav/ocr.py` `azure_recognise`). Live Outlook download: from the UI (Settings › Mailboxes) or with the legacy bridge unchanged; the exact command is in the README's email section. Keys live in `.env` (`TypeSafeJAV_API_KEY`, `OPENAI_API_KEY`, optionally `AZURE_DI_ENDPOINT` + `AZURE_DI_KEY`; optional variables: `.env.example`); never print a value.

## 6. Architecture (details: `docs/ARCHITECTURE.md`)

- **Work package → run → worker → UI** (040 K1–K3): work packages, recipes (`configs/recipes.json`), readiness, runs and approval live in `jav/work.py`; the items of a run go into the durable job queue (`jav/runtime/queue.py`); the worker (`jav/runtime/worker.py`, single-instance lock: `lock.py`) runs the graphs below with Burr state persistence (`persistence.py`); every paid call reserves from the run's budget and goes into the call log (`jav/runtime/calls.py`). The UI (`ui/`, React) and the CLI call the same operations through the local service (`jav/api.py`, shared views: `jav/work_views.py`); the service never runs anything itself, it only enqueues and reads.
- **Burr graphs** (`@action.pydantic`, local tracker, `run_id` = app_id):
  - `jav/flow.py` (M2, S and G paths, type-agnostic; the type pack is `configs/types/<type>.json` + `jav/typepack.py`, inheritance via `extends`);
  - `jav/flow_detect.py` (M1);
  - `jav/flow_email.py` (M3, calls M1 on the attachments);
  - `flow_learning.py`, `flow_email_learning.py` (learning branches).
- **S path (S arm):** code finds candidates (`candidates.py`), a JEV Choice picks one, with a presence Noul per field (`jev_select.py`). **G path (G arm):** GPT extraction (`extract_llm.py`) + JEV Noul verification (`jev_verify.py`). A run takes one path (`arm` = S or G, chosen by the recipe or the eval); an agreement gate comparing the two paths is not built — the planned second opinion (H-065: the G path only on documents the S path left with to-dos) is the first combination. The safety net is `validators.py`.
- **Every JEV call** goes through `ask()` in `jav/adapters/jev.py`: request-hash cache keyed by the concrete model version, RetryPolicy, ledger, cost. An SDK error raises `JevUnavailableError`. Flows never call the SDK directly.
- **OCR:** the `ocr_pdf` step (`jav/ocr.py`, `configs/ocr.json`): native tesseract, Azure escalation on a weak result (`ocr_with_escalation`; an escalation that cannot run raises an `ocr:escalation_blocked:*` to-do, except when the recipe switch is off). Evals use `jav/pdf.py: read_document()`, without escalation.
- **Registries:** `doc_types.py` (12 types + unknown), `intents.py` (the 11 legacy intents); per element `what / not_for / examples / parent`. Routing in code: `policy.py` (`decide`, `email_next_flow`). Detailed type inventory: `configs/capability_catalog.json` (23 schemas, 11 active intents).
- **Store:** `store/jav.sqlite`. Tables by owning module:
  - `store.py`: documents · datapoints · emails · email_results · email_task_decisions · review_queue · review_reasons · ledger · golden_labels · artifacts · meta;
  - `work.py`: workpackages · workpackage_items · workpackage_events · recipe_assignments · runs · run_items · file_fingerprints;
  - `runtime/queue.py`: jobs · queue_control; `runtime/calls.py`: invocations · budgets;
  - `app_settings.py`: app_users · watched_folders · watched_packages · watched_seen; `mailbox.py`: mailbox_schedules · mailbox_pulls;
  - `corrections.py`: run_item_corrections; `source_layer.py`: source_layers; `legacy_import.py`: legacy_results.

  Burr state: `store/burr_state.sqlite` (thinned out by `burr-prune`). Backups: `store/backups/` (daily, `configs/service.json` `backup`). The golden sets stay in the legacy project and are only referenced.
- **Evals:** `evals*.py`, shared report `eval_report.py`; raw runs in `runs/*.jsonl`. Experiments: `jav/experiments/` + `configs/experiments/`.
- **Email input** (both paths write `inbox/<mailbox>/<msgid>/message.json`):
  - from the UI or a schedule: `jav/mailbox.py` → `scripts/mail_bridge_call.ps1` → the legacy `outlook_bridge.ps1` → a temporary receiver with a one-time token (`jav/ingest_server.py`) → a new work package with the email intent recipe (no paid run starts by itself);
  - standalone: the legacy `outlook_bridge.ps1` → `python -m jav.cli email-ingest-server` (`jav/ingest_server.py`).

## 7. Pitfalls

- **Encoding:** on Windows cp1252/cp1250, output must be UTF-8 (`jav/__init__.py`). Write files from Python with `encoding="utf-8"`. The repository uses LF line endings throughout (`.gitattributes`). When writing a text file, make sure there is no CRLF and the accented characters survive: two sections of the decisions log were once corrupted into "?".
- **Shell:** PowerShell 5.1 has no `&&`, and non-ASCII string literals are best avoided. PowerShell variable names are case-insensitive, so an inner `$action` overwrites the `$Action` parameter. In a Bash heredoc `\n` and `\\` can get mangled, so write code files with the Write/Edit tools.
- **PDF and OCR:**
  - `pdfplumber layout=True` glues words together, so word-level reconstruction is needed (`jav/pdf.py`). A broken font triggers OCR; if that yields no text either, the result is `needs_ocr`.
  - tesseract is not on the PATH. The Hungarian language pack is only in `tools/tessdata` (`--tessdata-dir`). `tsv` output needs `-c tessedit_create_tsv=1`.
  - The legacy sidecar's Docker OCR is about 30× slower; fallback only.
- **JEV:**
  - Many candidates plus a long state produce `max_tokens_exceeded` (400); the call site's `request_char_budget` / `option_context_max` settings help.
  - A "different kind of number" (e.g. a phone number offered as a tax number) only gets a probability of 0.57–0.63, so a check-digit validator is mandatory.
  - Any change to a Choice criterion produces a new cache key, so every case becomes a live call. Never mix two registry versions in a determinism measurement.
- **Burr:** needs `[tracking-client,tracking-server]` + `loguru`. The `[start]` extra pulls in streamlit.
- **Data:** the legacy inbox folders only contain attachments; the email bodies stayed in the legacy Postgres. Labelling in Markdown tables does not work; labelling only works with a full-text view.
- **Documents:** `docs/handoffs/TEMPLATE.md` is not a handoff. `docs/STATE.md` is generated; never edit it by hand. Changes to internal working documents do not show up in `git status`; they still have to be made (backlog, decisions log, handoff), and the daily backup copies them. **Never switch (`git switch` / `checkout` / `merge`) to a commit or branch that still tracks the internal files** (the local archive branches and older commits): git overwrites the local internal files and deletes them when you switch back. Look at an old state with `git show <commit>:<path>` or a separate worktree (`git worktree add`); run `backup --with-docs` first. The frozen file list of 036 (223 hashes) is only valid for the old measurements; new measurements are identified by commit hash.

## 8. Communication and documentation for the owner (2026-09-20, the owner's request — mandatory)

The owner reported that undefined jargon, numbers without context and code identifiers mixed into prose made it impossible to steer the work. Therefore every text addressed to the owner (chat replies, handoffs, decision questions) is written **in Hungarian** and follows this order:

1. **The glossary is the only dictionary** (`docs/GLOSSARY.md`; its Hungarian column gives the words to use with the owner). A new term may only appear in text after it has been added to the glossary. On first use, explain it in half a sentence or link to the glossary.
2. **Mandatory structure:** (a) what the goal was, in one everyday sentence; (b) what we did and what the system can do now; (c) what the result means, numbers with a point of comparison; (d) the decision or question, with options and a recommendation; (e) only then, under a "Technikai részletek" heading, file names, commands, versions.
3. **No code identifiers in prose.** Exception: the technical-details block and the technical sections of documents. In prose, name the thing by its role, in Hungarian.
4. **Numbers only with meaning:** what it measures, compared with what, and what follows from it. Give the count next to every percentage.
5. **Length:** a chat summary is at most 10 sentences before the technical details; anything longer goes into a document. Handoffs and codebase documents start with a plain-language summary (3–5 sentences; in Hungarian documents "Laikus összefoglaló", in English ones "Plain-language summary").
6. **English expressions** in Hungarian text only as JEV documentation or code names (Choice, Noul, Score), with a Hungarian explanation.
7. **If the owner says they do not understand,** do not justify yourself: rewrite it in the glossary's language, and add the missing word to the glossary.
