# Development workflow: git, checks, handoff

**In force:** since 2026-09-27; English commit messages since 2026-09-30.

## Plain-language summary

Git records every change, so a bad change can be undone in one step. The main branch always works, every development stage is built on its own branch, and every measurement names the code state (commit) it ran on. A check before every commit and push keeps personal data, keys and internal working documents out of git. Everything that reaches GitHub, including commit messages, is written in English.

## 1. Branches and tags

- **`main`** is always green: `python -m jav.cli preflight` passes on it.
- Development happens **on a separate branch per stage**, named in English after its topic, usually with the session number: `<topic>-NNN`. A small fix may use a `fix-<topic>` branch.
- A branch is merged into `main` once the full `preflight` is green; the handoff is written at the end of the session (§5). Merges use `--no-ff`, so that a stage stays visible as one unit.
- **Tags:** release tags (`vX.Y.Z`, below). A finished measurement may get a `meres-<id>` tag if it has to be reproduced later.
- **Release version:** a state the owner marks as stable gets an annotated `vX.Y.Z` tag on the merge commit in `main`. Its release notes are kept as an internal working document; the [changelog](../../CHANGELOG.md) gets a short public entry. Before that, a full `preflight` and a live end-to-end check on a clean working tree are mandatory. Patch release (`vX.Y.Z+1`): bug fixes; a `feat` commit may only be included if it is a small change that completes a fix. New capability: `vX.Y+1.0`.
  - **Single version source:** the `version` field of `pyproject.toml` (`jav/version.py`). The release commit bumps `ui/package.json`, `ui/package-lock.json` and the README's current-stable-version line together with it; `tests/test_version_071.py` checks that they match. Between releases the version stays at the last release, and the commit identifies the development state.
  - The running service shows its version and the commit it was started from in the `/api/health` response and on the Settings › System page (with a warning if there were uncommitted changes). New code only takes effect after the service is restarted. The service and the worker load all their code when they start, so editing files in the working tree does not change a running process; restart them to run the new code. A browser tab loaded before the restart (or before a new UI build) shows a banner asking for a reload (it compares the commit and `ui_build` from `/api/health` with those at page load).
- **Remote:** `origin` is the project's GitHub repository.
  - The GitHub history starts at the repository's root commit: `git rev-list --max-parents=0 main`.
  - Only `main`, stage branches and tags built on that root are pushed, each by name: `git push origin <branch>` or `git push origin <tag>`. `--all`, `--tags` and `--mirror` are forbidden.
  - **Local protection:** the versioned `scripts/githooks/pre-push` hook rejects the push of any branch or tag whose history contains a commit listed under `forbidden_history` in `configs/data_guard.json`. It also checks the content of the commits being pushed (see the data guard below). After `hooks-install`, hooks in `.git/hooks` no longer run.
- **Data guard:** versioned git hooks under `scripts/githooks/`, enabled once per clone with `python -m jav.cli hooks-install` (`core.hooksPath`). The start-up check reports an error if they are not enabled.
  - **Before a commit** (`pre-commit`) and **before a push** (`pre-push`, for commits not yet pushed) it checks the new lines going into git; for a renamed or copied file, its whole content under the new path. It stops on a real-looking tax number, IBAN or bank account number: their check digits are valid, so they might be real. A value with invalid check digits cannot be real and passes. It also stops on email addresses that are not made up, Hungarian phone numbers, foreign tax numbers, known key formats and any secret value from the local `.env`. It also stops on a forbidden phrase (stored only as a fingerprint), even written without spaces. By path, it rejects internal working documents, `.env`, local data folders, document, image and store files, and every binary file.
  - **Exceptions** live in `configs/data_guard.json` (with a version bump): `allow` = made-up or public company values in plain text; `known` = tolerated old values, stored only as sha256 and passing only in the listed files (anywhere else it stops; see the [security notes](../SECURITY.md), section 8); `deny` = sha256 and length of the forbidden phrases. Output is always masked.
  - To scan the whole tracked tree: `python -m jav.cli data-guard [--all]`; the test suite and the start-up check run it too. Bypassing the hook (`--no-verify`) is forbidden; if a hit is a made-up value, it goes onto the exception list.
- **Internal working documents:** git does not track handoffs, plans, reports, the backlog, the decisions log, the roadmap or the local generated pages. The exclusion list is in `.gitignore`; its single source is `jav/doc_scope.py`. These files never go into a commit or to GitHub; the daily backup copies them. `git add` must only add codebase files; `git add -f` on an internal path is forbidden.
  - **Pitfall:** switching to (or merging) a commit or branch that still tracks internal files overwrites the local internal files, and switching back deletes them. To look at such a state, use `git show <commit>:<path>` or a separate worktree: `git worktree add <folder> <commit>`. Back up first: `python -m jav.cli backup --with-docs`. A worktree has no `.venv` or `tools/tessdata` of its own: run its tests with the main checkout's interpreter (the isolated reader takes that interpreter's packages) and set `JAV_TESSDATA_DIR` to the main checkout's `tools/tessdata`.

## 2. Commits

```text
<type>(<area>): <short English summary>

<why and what, 1–5 lines; reference to the plan / backlog item>

Co-Authored-By: ...
```

Types: `feat` (new capability), `fix` (bug), `refactor` (no behaviour change), `test`, `docs`, `chore` (tooling, settings), `exp` (experiment, measurement). The area is the module or the stage, for example `runtime`, `mail`, `ui`, `recipes`. The session number goes at the end of the summary line, as three digits in brackets: `(NNN)`.

- **Language:** commit and tag messages are in English (since 2026-09-30). Earlier commits with Hungarian messages are not rewritten.
- One commit is one logical change. Its tests and codebase documentation go into the same commit; internal working documents are updated locally, without a commit.
- Before a commit: `python -m jav.cli preflight --skip-pytest` and the affected tests (`pytest tests/test_<x>.py`). Before a merge: the full `preflight`. The slowest tests (over about 5 s each: separate processes, long inputs) carry the `slow` marker, so a quick loop over many files can leave them out with `pytest tests/ -m "not slow"`; the full check always runs every test. The full check keeps the raw pytest output and a JUnit file of each run under `runs/preflight/<timestamp>/` (the latest 20); on a failure its summary names the folder, so an intermittent failure can still be looked up. Since 189 the full check runs the Python tests in several processes (pytest-xdist: every core but two, at most six; one process when xdist is missing) and the UI checks at the same time, and lists the 25 slowest tests in the raw output; on an eight-core machine the Python tests take about 5 minutes instead of 30. A loop over many files can do the same: `pytest tests/ -n 6`. The tests' temporary stores do not wait for the disk after a write (`store.SYNCHRONOUS`, set in `tests/conftest.py`); the application keeps SQLite's own setting.
- **The real store and a development branch:** the start-up check and the state snapshot (`admin`) only read the store (`store.read_only`), and the backup copies it without opening it through the code, so neither runs a branch's schema change or data migration on the real store, and neither creates a missing store. Every other command opens the store with the checked-out code and runs its migrations. On a branch that migrates data, stop the service and the worker and back up before running such a command, or work on a copy of the store, as the before/after comparison does (§3).
- **Never in git:** `.env`, `runs/`, `store/`, `inbox/`, `data/`, OCR language data, real documents, emails or bank exports (the data guard blocks `.csv`, `.xml`, `.txt`, `.sta`, `.940` and `.camt`; a synthetic statement for a test is built at run time). New tests need **synthetic or anonymised** data. A test that needs check-digit patterns (tax number, IBAN) computes them at run time, or the made-up value goes onto the `allow` list in `configs/data_guard.json`; the data guard (§1) checks this before the commit.
- Any further remote repository is added only after an explicit decision by the owner.

## 3. Measurements and reproducibility

- The raw run and receipt of every new measurement record the **commit hash** and whether the working tree was clean. Live, paid measurements never start on a dirty working tree.
- **Every golden set with one command** (free): `python -m jav.cli measure --store <copy of the store>` measures each golden set from earlier answers, the way its own command does (`measure --list` names them; a selector picks some, for example `datapoints:invoice_hu` or `reconcile`). The receipt `runs/<stamp>_measure.jsonl` records the commit, whether the working tree was clean and one line per set; the sets' own reports are in `runs/<stamp>_measure.log`. A paid round names exactly one set, with its sub-budget. Without `--store` the measured results go into the work store, as with the sets' own commands.
- Experimental code must never be imported by the runtime. An experiment gets its own ID, recipe and receipt.
- **Before/after comparison of a refactoring step** (free; `jav/before_after.py`). A step meant to change nothing visible is checked on a backed-up copy of the store:
  1. Back up the store once: `python -m jav.cli backup --with-docs --copy-to <scratch folder>`. Every snapshot then reads a fresh copy of that backup, with its native readings and source copies, so the store in use is never touched.
  2. Take the "before" snapshot with the code before the step, from a separate worktree of that commit (DEVELOPMENT §1 pitfall), so no edit made meanwhile is loaded: `python -m jav.cli before-after-snapshot <backup folder> --work <folder> --out before.jsonl`.
  3. Take the "after" snapshot the same way with the new code, then compare: `python -m jav.cli before-after-diff before.jsonl after.jsonl` (exit code 1 if a view differs).
  - The snapshot reads the local service's own read views in process: packages, items, runs, reviews and next steps, each run's item results (`--no-items` leaves them out), journal and downloads, every dataset behind a table, the reconciliation views, parties, workflows, and the activity log of each person and day. It makes no AI call and opens no network connection.
  - A difference is allowed only where the step announced one, and the handoff names it.
  - A snapshot holds personal data. The tool refuses to write it inside the repository, except under the ignored `store/`.
  - Two snapshots of the same copy taken with the same code are identical: that is the tool's own check.
  - A snapshot taken in a worktree reads email attachments only from the message's own folder and under that worktree's own mail bridge folder (`jav/config.py` `BRIDGE_DATA_ROOT`, `inbox/.bridge/data/`, the attachment rule of `jav/emails.py`), which a worktree lacks. An email package's `attachments_missing` is therefore 0 there and the true count in the main folder (195). Compare such views between snapshots taken in the same kind of folder.
- **Replay from earlier answers** (free; `jav/before_after_replay.py`). A step that touches the processing itself (the flows, the worker, the checks) is also checked by processing again:
  1. Before the step's first edit: `python -m jav.cli before-after-replay <backup folder> --work <folder> --out before.jsonl`.
  2. After the step, the same command with `--out after.jsonl`, the same backup, the same work folder and on the same day (a few checks compare dates with today). Then `python -m jav.cli before-after-diff before.jsonl after.jsonl`.
  - About 150 units are replayed (an email together with its attachments counts as one). They are chosen so that every stratum appears at least once: flow, item kind, package kind, trial or live run, engine, the path of the data points, native facts, end state, email tasks and cross-document to-dos. Each item goes through the worker's own processing in a replayed copy of its run, one after the other in the original order.
  - Only earlier answers count: the JEV answer cache (`--jev-cache`, default `runs/cache`) and the call log's earlier GPT answers and Azure texts. The keys are placeholders, every HTTP request goes to a closed local port (checked before the replay starts), the exchange rate service is not asked, and the replayed runs have no budget. A question without an earlier answer therefore becomes a to-do, counted as "answers missing", never a call. The OCR cache and the operational log are copies in the work folder.
  - The gate: the call log and the ledger of the replayed runs may hold earlier answers only. Otherwise the command exits with code 3 and lists the calls.
  - The record holds each item's end state, its stored rows (data points, documents, to-dos in order, email result, native facts, ledger, call log) and its view, and each replayed run's views and tables, without times and process names.
  - Run both replays from the main folder, not from a worktree: the replay reads the code root's untracked JEV and OCR caches, OCR language pack and mailbox folders. Do not edit Python code while a replay runs, because the processing imports modules late.
  - Two replays of the same backup with the same code are identical: that is the tool's own check.

## 4. How a session runs

1. **Start:** `python -m jav.cli preflight`, the latest handoff, `git status` and `git log --oneline -10`. Then a short summary and agreement with the owner (CLAUDE.md §2).
2. **Work:** on the stage branch, in small commits, test-first wherever code changes.
3. **Close:** the documentation checklist ([DOCUMENTATION.md](DOCUMENTATION.md) §5), green preflight, commit, then a handoff with the commit hash. The handoff is an internal working document: it stays local and is not committed.

## 5. When is a new handoff needed?

Only at the end of a session and when a stage closes. A finished measurement also counts as the close of a stage, and a session also ends when the context is roughly half full. The git log is the fine-grained history, so the handoff can be short: what was done, decisions, open questions, next step, pitfalls. The Stop hook does not force a handoff; it only reminds about uncommitted changes and the number of commits since the last handoff.

## 6. Security and quality checks

Run them before a release, after updating dependencies, or when a sensitive area has changed. None of them costs money. The start-up check runs none of them; it only reads the dependency audit's last result (it fails on a known vulnerability and notes an audit older than a week). The daily backup renews that result once a week, and the System page shows it.

```powershell
python -m jav.cli deps-audit                          # known vulnerabilities in the pinned Python and UI packages, and whether the Python runtime is behind its latest patch (needs network)
pytest tests/ --cov=jav --cov-report=term-missing     # test coverage: which lines no test executes
$env:JAV_HYPOTHESIS_EXAMPLES = "3000"; pytest tests/test_properties_067.py   # property-based tests with a deeper search
$env:JAV_LEGACY_GOLDEN_TESTS = "1"; pytest tests/test_validators.py -k legacy   # the legacy golden set's expected invoice records through the validators
```

The validator test in the suite runs on synthetic expected records. The legacy golden set's records (values read from real invoices) are read only when `JAV_LEGACY_GOLDEN_TESTS=1` is set; otherwise that test is skipped with this reason.

The property-based tests (`tests/test_properties_067.py`) do not pin single examples; they state rules. For example: the check always accepts a valid tax number and always notices a single wrong digit in it. Another rule: the grand total stays a candidate whatever ID or date lines are placed next to it. The `hypothesis` library tries hundreds of generated inputs and, on failure, shows the smallest counterexample. The test suite runs 150 examples per test. The input limits (file size, page count, page-image pixels) are in the `input_limits` section of `configs/service.json`.
