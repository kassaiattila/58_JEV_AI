# Development workflow: git, checks, handoff

**In force:** since 2026-09-27 (040); English commit messages since 2026-09-30 (073).

## Plain-language summary

The project used to run without version control. The reproducibility of finished measurements was protected by hand-recorded fingerprints of 223 files, and a bad change could not be undone in one step. Now git records every change. The main branch always works, every development stage is built on its own branch, and every measurement names the code state (commit) it ran on. Everything that reaches GitHub, including commit messages, is written in English.

## 1. Branches and tags

- **`main`** is always green: `python -m jav.cli preflight` passes on it.
- Development happens **on a separate branch per stage**, named after the plan item, for example `k1-adatmodell`, `k3-ui-munkacsomagok`; since 073, new branch names are English (`ui-fixes-073`, `lang-docs-073`). A small fix may use a `fix-<topic>` branch.
- A branch is merged into `main` once the full `preflight` is green; the handoff is written at the end of the session (§5). Merges use `--no-ff`, so that a stage stays visible as one unit.
- **Tags:** `baseline-039` is the state before git was introduced. A stage ends with a `k<N>-kesz` tag. A finished measurement may get a `meres-<id>` tag if it has to be reproduced later.
- **Release version (063):** a state the owner marks as stable gets an annotated `vX.Y.Z` tag on the merge commit in `main`, with release notes (internal: `reports/YYYY-MM-DD-vX.Y.Z-kiadas.md`). Before that, a full `preflight` and a live end-to-end check on a clean working tree are mandatory. Patch release (`vX.Y.Z+1`): bug fixes; a `feat` commit may only be included if it is a small change that completes a fix. New capability: `vX.Y+1.0`.
  - **Single version source (071):** the `version` field of `pyproject.toml` (`jav/version.py`). The release commit bumps `ui/package.json`, `ui/package-lock.json` and the README's current-stable-version line together with it; `tests/test_version_071.py` checks that they match. Between releases the version stays at the last release, and the commit identifies the development state.
  - The running service shows its version and the commit it was started from in the `/api/health` response and on the Settings › System page (with a warning if there were uncommitted changes). New code only takes effect after the service is restarted.
- **Remote (069, decision of 2026-09-29):** `origin` = `https://github.com/kassaiattila/58_JEV_AI.git` (private).
  - Since 2026-09-30 the GitHub history starts with a second root commit (070, the owner's decision): the code state after `v1.0.4`, without internal working documents. It is the first commit of `main`: `git rev-list --max-parents=0 main`.
  - The earlier 236 commits and their tags exist only locally, on the `archiv/elotortenet-069` branch, because commits before 066 contain personal data.
  - The first root commit from 069 (`669e851`) and the commits built on it also carry the internal working documents. They live on the `archiv/elotortenet-070` branch.
  - **Never push** the two archive branches or the old tags.
  - Push only `main` and stage branches that start from the new root: `git push origin <branch>`. Stage branches from before 070 (for example `k3-ui`, `v104-javitokor`, `d-dokumentacio-070`) carry the old history and must not be pushed. `--all`, `--tags` and `--mirror` are forbidden.
  - After a push, new tags may only point to commits after the new root.
  - **Local protection (versioned since 071):** `scripts/githooks/pre-push` rejects pushing any branch or tag built on the old history (whose ancestor is `baseline-039` or `669e851`; list: `configs/data_guard.json` `forbidden_history`). The old, unversioned `.git/hooks/pre-push` no longer runs after `hooks-install`. A fresh clone has no old history; there the hook checks the content of the commits being pushed (see the data guard).
- **Data guard (071, plan 070 item S-adatőr):** versioned git hooks under `scripts/githooks/`, enabled once per clone with `python -m jav.cli hooks-install` (`core.hooksPath`). The start-up check reports an error if they are not enabled.
  - **Before a commit** (`pre-commit`) and **before a push** (`pre-push`, for commits not yet pushed) it checks the new lines going into git. It stops on a real-looking tax number, IBAN or bank account number: their check digits are valid, so they might be real. A value with invalid check digits cannot be real and passes. It also stops on email addresses that are not made up, Hungarian phone numbers, foreign tax numbers, known key formats and any secret value from the local `.env`. It also stops on a forbidden phrase (the owner's company name, the user name), even written without spaces. By path, it rejects internal working documents, `.env`, local data folders, document, image and store files, and every binary file.
  - **Exceptions** live in `configs/data_guard.json` (with a version bump): `allow` = made-up or public company values in plain text; `known` = personal data that stays for now under the 069 decision, only as sha256 and only in the listed files (anywhere else it stops); `deny` = sha256 and length of the forbidden phrases. Output is always masked.
  - To scan the whole tracked tree: `python -m jav.cli data-guard [--all]`; the test suite and the start-up check run it too. Bypassing the hook (`--no-verify`) is forbidden; if a hit is a made-up value, it goes onto the exception list.
- **Internal working documents (070, decision of 2026-09-29):** git does not track handoffs, plans, reports, the backlog, the decisions log, the roadmap or the local generated pages. The exclusion list is in `.gitignore`; its single source is `jav/doc_scope.py`. These files never go into a commit or to GitHub; the daily backup copies them. Their old state can be read on the archive branches. `git add` must only add codebase files; `git add -f` on an internal path is forbidden.
  - **Pitfall:** switching to a commit or branch that still tracks the internal files (the archive branches, commits before the 070 split) overwrites the local internal files, and switching back deletes them. This happened on 2026-09-30 during a merge; the files were restored from a commit of the same day. To look at an old state use `git show <commit>:<path>` or a separate worktree: `git worktree add ..\jav-regi archiv/elotortenet-070`. Back up first: `python -m jav.cli backup --with-docs`.

## 2. Commits

```text
<type>(<area>): <short English summary>

<why and what, 1–5 lines; reference to the plan / backlog item>

Co-Authored-By: ...
```

Types: `feat` (new capability), `fix` (bug), `refactor` (no behaviour change), `test`, `docs`, `chore` (tooling, settings), `exp` (experiment, measurement). The area is the module or the stage, for example `runtime`, `mail`, `ui`, `k1`. The session number goes at the end of the summary line, e.g. `(073)`.

- **Language (073, decision of 2026-09-30):** commit and tag messages are English. Commits already on GitHub with Hungarian messages are not rewritten.
- One commit is one logical change. Its tests and codebase documentation go into the same commit; internal working documents are updated locally, without a commit.
- Before a commit: `python -m jav.cli preflight --skip-pytest` and the affected tests (`pytest tests/test_<x>.py`). Before a merge: the full `preflight`.
- **Never in git:** `.env`, `runs/`, `store/`, `inbox/`, OCR language data, real documents or emails. New tests need **synthetic or anonymised** data. A test that needs check-digit patterns (tax number, IBAN) computes them at run time, or the made-up value goes onto the `allow` list in `configs/data_guard.json`; the data guard (§1) checks this before the commit. The owner's company name and EU VAT number left in older tests are replaced together with the next prompt change, under the 069 decision (until then they are `known`).
- A remote repository (GitHub or similar) is used only after an explicit decision by the owner.

## 3. Measurements and reproducibility

- The raw run and receipt of every new measurement record the **commit hash** and whether the working tree was clean. Live, paid measurements never start on a dirty working tree.
- The frozen file list of 036 (223 hashes) remains valid for the **old** measurements. New measurements are identified by commit and tag instead.
- Experimental code must never be imported by the runtime. An experiment gets its own ID, recipe and receipt.

## 4. How a session runs

1. **Start:** `python -m jav.cli preflight`, the latest handoff, `git status` and `git log --oneline -10`. Then a short summary and agreement with the owner (CLAUDE.md §2).
2. **Work:** on the stage branch, in small commits, test-first wherever code changes.
3. **Close:** the documentation checklist ([DOCUMENTATION.md](DOCUMENTATION.md) §5), green preflight, commit, then a handoff with the commit hash. Since 2026-09-29 the handoff stays local and is not committed (070).

## 5. When is a new handoff needed?

Only at the end of a session and when a stage closes (the owner's decision of 2026-09-27). A finished measurement also counts as the close of a stage, and a session also ends when the context is roughly half full. The git log is the fine-grained history, so the handoff can be short: what was done, decisions, open questions, next step, pitfalls. Since 2026-09-27 the Stop hook no longer forces an hourly handoff; it only reminds about uncommitted changes and the number of commits since the last handoff.

## 6. Security and quality checks (067)

These are not part of the start-up check. Run them before a release, after updating dependencies, or when a sensitive area has changed. None of them costs money.

```powershell
uvx pip-audit -r requirements.lock --no-deps          # known vulnerabilities in the pinned Python packages (needs network)
cd ui; npm audit; cd ..                               # the same for the UI packages
pytest tests/ --cov=jav --cov-report=term-missing     # test coverage: which lines no test executes
$env:JAV_HYPOTHESIS_EXAMPLES = "3000"; pytest tests/test_properties_067.py   # property-based tests with a deeper search
```

The property-based tests (`tests/test_properties_067.py`) do not pin single examples; they state rules. For example: the check always accepts a valid tax number and always notices a single wrong digit in it. Another rule: the grand total stays a candidate whatever ID or date lines are placed next to it. The `hypothesis` library tries hundreds of generated inputs and, on failure, shows the smallest counterexample. The test suite runs 150 examples per test. The input limits (file size, page count, page-image pixels) are in the `input_limits` section of `configs/service.json`.
