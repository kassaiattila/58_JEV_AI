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
  - The running service shows its version and the commit it was started from in the `/api/health` response and on the Settings › System page (with a warning if there were uncommitted changes). New code only takes effect after the service is restarted. A browser tab loaded before the restart (or before a new UI build) shows a banner asking for a reload (091: it compares the commit and `ui_build` from `/api/health` with those at page load).
- **Remote:** `origin` is the project's GitHub repository.
  - The GitHub history starts at the repository's root commit: `git rev-list --max-parents=0 main`.
  - Only `main`, stage branches and tags built on that root are pushed, each by name: `git push origin <branch>` or `git push origin <tag>`. `--all`, `--tags` and `--mirror` are forbidden.
  - **Local protection:** the versioned `scripts/githooks/pre-push` hook rejects the push of any branch or tag whose history contains a commit listed under `forbidden_history` in `configs/data_guard.json`. It also checks the content of the commits being pushed (see the data guard below). After `hooks-install`, hooks in `.git/hooks` no longer run.
- **Data guard:** versioned git hooks under `scripts/githooks/`, enabled once per clone with `python -m jav.cli hooks-install` (`core.hooksPath`). The start-up check reports an error if they are not enabled.
  - **Before a commit** (`pre-commit`) and **before a push** (`pre-push`, for commits not yet pushed) it checks the new lines going into git; for a renamed or copied file, its whole content under the new path. It stops on a real-looking tax number, IBAN or bank account number: their check digits are valid, so they might be real. A value with invalid check digits cannot be real and passes. It also stops on email addresses that are not made up, Hungarian phone numbers, foreign tax numbers, known key formats and any secret value from the local `.env`. It also stops on a forbidden phrase (stored only as a fingerprint), even written without spaces. By path, it rejects internal working documents, `.env`, local data folders, document, image and store files, and every binary file.
  - **Exceptions** live in `configs/data_guard.json` (with a version bump): `allow` = made-up or public company values in plain text; `known` = tolerated old values, stored only as sha256 and passing only in the listed files (anywhere else it stops; see the [security notes](../SECURITY.md), section 8); `deny` = sha256 and length of the forbidden phrases. Output is always masked.
  - To scan the whole tracked tree: `python -m jav.cli data-guard [--all]`; the test suite and the start-up check run it too. Bypassing the hook (`--no-verify`) is forbidden; if a hit is a made-up value, it goes onto the exception list.
- **Internal working documents:** git does not track handoffs, plans, reports, the backlog, the decisions log, the roadmap or the local generated pages. The exclusion list is in `.gitignore`; its single source is `jav/doc_scope.py`. These files never go into a commit or to GitHub; the daily backup copies them. `git add` must only add codebase files; `git add -f` on an internal path is forbidden.
  - **Pitfall:** switching to (or merging) a commit or branch that still tracks internal files overwrites the local internal files, and switching back deletes them. To look at such a state, use `git show <commit>:<path>` or a separate worktree: `git worktree add <folder> <commit>`. Back up first: `python -m jav.cli backup --with-docs`.

## 2. Commits

```text
<type>(<area>): <short English summary>

<why and what, 1–5 lines; reference to the plan / backlog item>

Co-Authored-By: ...
```

Types: `feat` (new capability), `fix` (bug), `refactor` (no behaviour change), `test`, `docs`, `chore` (tooling, settings), `exp` (experiment, measurement). The area is the module or the stage, for example `runtime`, `mail`, `ui`, `recipes`. The session number goes at the end of the summary line, as three digits in brackets: `(NNN)`.

- **Language:** commit and tag messages are in English (since 2026-09-30). Earlier commits with Hungarian messages are not rewritten.
- One commit is one logical change. Its tests and codebase documentation go into the same commit; internal working documents are updated locally, without a commit.
- Before a commit: `python -m jav.cli preflight --skip-pytest` and the affected tests (`pytest tests/test_<x>.py`). Before a merge: the full `preflight`.
- **Never in git:** `.env`, `runs/`, `store/`, `inbox/`, OCR language data, real documents or emails. New tests need **synthetic or anonymised** data. A test that needs check-digit patterns (tax number, IBAN) computes them at run time, or the made-up value goes onto the `allow` list in `configs/data_guard.json`; the data guard (§1) checks this before the commit.
- Any further remote repository is added only after an explicit decision by the owner.

## 3. Measurements and reproducibility

- The raw run and receipt of every new measurement record the **commit hash** and whether the working tree was clean. Live, paid measurements never start on a dirty working tree.
- Experimental code must never be imported by the runtime. An experiment gets its own ID, recipe and receipt.

## 4. How a session runs

1. **Start:** `python -m jav.cli preflight`, the latest handoff, `git status` and `git log --oneline -10`. Then a short summary and agreement with the owner (CLAUDE.md §2).
2. **Work:** on the stage branch, in small commits, test-first wherever code changes.
3. **Close:** the documentation checklist ([DOCUMENTATION.md](DOCUMENTATION.md) §5), green preflight, commit, then a handoff with the commit hash. The handoff is an internal working document: it stays local and is not committed.

## 5. When is a new handoff needed?

Only at the end of a session and when a stage closes. A finished measurement also counts as the close of a stage, and a session also ends when the context is roughly half full. The git log is the fine-grained history, so the handoff can be short: what was done, decisions, open questions, next step, pitfalls. The Stop hook does not force a handoff; it only reminds about uncommitted changes and the number of commits since the last handoff.

## 6. Security and quality checks

Run them before a release, after updating dependencies, or when a sensitive area has changed. None of them costs money. The start-up check runs none of them; it only reads the dependency audit's last result (it fails on a known vulnerability and notes an audit older than a week). The daily backup renews that result once a week, and the System page shows it.

```powershell
python -m jav.cli deps-audit                          # known vulnerabilities in the pinned Python and UI packages (needs network)
pytest tests/ --cov=jav --cov-report=term-missing     # test coverage: which lines no test executes
$env:JAV_HYPOTHESIS_EXAMPLES = "3000"; pytest tests/test_properties_067.py   # property-based tests with a deeper search
```

The property-based tests (`tests/test_properties_067.py`) do not pin single examples; they state rules. For example: the check always accepts a valid tax number and always notices a single wrong digit in it. Another rule: the grand total stays a candidate whatever ID or date lines are placed next to it. The `hypothesis` library tries hundreds of generated inputs and, on failure, shows the smallest counterexample. The test suite runs 150 examples per test. The input limits (file size, page count, page-image pixels) are in the `input_limits` section of `configs/service.json`.
