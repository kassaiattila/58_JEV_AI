# Installation and local environment

**Valid from:** 2026-09-27; reviewed 2026-09-30. **Platform:** Windows 11, PowerShell 5.1, Python 3.12, [uv](https://docs.astral.sh/uv/) (for the Python environment), Node.js 20.19+ or 22.12+ (for the user interface), git.

## Plain-language summary

This guide lists what a machine needs to run the project. Git holds only the source code, the settings and the documentation. The keys, the local data and the large OCR language packs are not in it, so each machine has to obtain them separately. A fresh clone runs the user interface, the work packages and the runs; the golden-set measurements also need the legacy project (section 4).

## 1. Python environment

```powershell
uv venv --python 3.12 .venv
uv pip install -r requirements.lock
.\.venv\Scripts\Activate.ps1
python -m jav.cli hooks-install      # data guard: a check before every commit and push; once per clone
python -m jav.cli preflight          # tests (Python + UI) + contract lint + configs + handoff + git + data guard + language guard + Ruff limit + state snapshot
```

**Data guard.** `hooks-install` points git at the versioned hooks in `scripts/githooks/` (through `core.hooksPath`). From then on a check runs before every commit and push, and stops the operation if the lines going into git contain personal data or a key: for example a real-looking tax number, bank account number, email address or phone number, or a key from `.env`. It also stops the operation if an internal working document, a document file, an image or a database would go into git. Until the hooks are installed, the start-up check (`preflight`) reports a failure. `python -m jav.cli data-guard` reviews the files already under version control. The rules: [DEVELOPMENT §1](DEVELOPMENT.md).

**User interface.** It needs Node.js 20.19+ or 22.12+ (the requirement of Vite, the build tool; Node.js 21 is not supported):

```powershell
cd ui; npm ci; npm run build; cd ..   # dependencies as pinned in package-lock.json; type check and build into ui/dist
.\scripts\dev.ps1 start             # local service + one worker in the background; user interface: http://127.0.0.1:8930/
.\scripts\dev.ps1 status            # are they running?
.\scripts\dev.ps1 stop              # stop both; an interrupted run resumes from its saved step
```

**Your own folders in the user interface.** By default, any existing local folder or file can be given in the user interface (for a work package or a work folder). The restriction can be switched back on with `restrict_paths: true` in `configs/service.json`. Documents can then be added only from allowed folders: the project's `inbox/` and `data/` folders, the legacy project's data, and the folders listed in the `JAV_API_ROOTS` variable in `.env` (separate several folders with `;`, and quote the value if a path contains a space). Example: `JAV_API_ROOTS="D:\Invoices\Incoming"`. After the change, run `.\scripts\dev.ps1 stop` and then `start`. The folder with the real documents stays on the machine and never goes into git.

During development, `npm run dev` serves the user interface at `http://127.0.0.1:5173/` and forwards the `/api` requests to the local service.

## 2. Keys

Copy `.env.example` to `.env` and fill in:

- `TypeSafeJAV_API_KEY`: the JEV key (the SDK's own `TYPESAFE_API_KEY` name is also accepted);
- `OPENAI_API_KEY`: for the G path (GPT extraction) and the task proposals.

`.env` never goes into git; the data guard also looks for the secret values from `.env` in the lines being committed. Never write a key value into a log or a document. `python smoke_test.py` checks the environment and the JEV key with one tiny live call (paid, a fraction of a cent); it prints only a masked fragment of the key.

Optional environment variables (in `.env` or in the shell):

| variable | purpose |
|---|---|
| `JAV_LEGACY_ROOT` | the location of the legacy project, if it is not the default (section 4) |
| `JAV_API_ROOTS` | allowed document folders when the folder restriction is on (section 1) |
| `JAV_INGEST_TOKEN` | the key of the standalone email receiver (`email-ingest-server`) used on the legacy, manual route; without it (and without `--token`) the receiver prints a one-off key at start-up |
| `JAV_OCR_ENGINE` | `native`, `docker` or `azure_di` for one command; `azure_di` forces the paid Azure recognition (page-limited). The default comes from `configs/ocr.json` and never picks Azure. |
| `JAV_ALLOW_SDK_DEBUG` | `1`: allows the JEV library's detailed log; it also logs personal data, so use it only on made-up data |
| `JAV_HYPOTHESIS_EXAMPLES` | the number of generated examples per property-based test (default 150), for a deeper search |

## 3. OCR (for PDFs without a text layer)

- **Tesseract 5.x**, installed natively in `%LOCALAPPDATA%\Programs\Tesseract-OCR`. It does not need to be on the PATH: `configs/ocr.json` lists where to look (the PATH, this folder and `C:\Program Files\Tesseract-OCR`).
- **Language packs** (not in git; git-ignored): `tools/tessdata/` (eng, hun, osd; the project uses this one) and `tools/tessdata_best/`. Get them from the tesseract-ocr `tessdata_fast` and `tessdata_best` releases, or from the legacy sidecar's Docker image, where the original copy came from. Without a PDF, `python -m jav.cli ocr` prints the state of the engine and the language packs.
- The paid Azure Document Intelligence escalation goes through the legacy project's sidecar container. It is needed only to escalate weak local OCR. In a run it is used only within the run's Azure budget (the recipe's Azure recognition switch), and every call is in the call log.

## 4. Dependency on the legacy project: what works in a fresh clone

`jav/config.py` finds the golden sets, the legacy data folder and the Outlook bridge under `<legacy-root>`, the root folder of the legacy project. They are only read. `<legacy-root>` comes from the `JAV_LEGACY_ROOT` environment variable (or a line in `.env`); without it, `jav/config.py` falls back to a built-in default path (`DEFAULT_OLD_PROJECT_ROOT`), which is unlikely to exist on another machine, so set the variable there.

A fresh GitHub clone has neither the legacy project, nor the golden sets, nor the internal working documents. In that case:

| works | needs the legacy project |
|---|---|
| the full test suite (tests that rely on a golden set are skipped without it, so the coverage is smaller) | `recall`, `golden`, `determinism`, `verifier-probe` (invoice golden set) |
| the user interface, the local service and the worker; work packages, recipes, trial and live runs with the keys | `detect-golden`, `detect-determinism` (detection golden set) |
| local OCR (the language packs have to be obtained separately, section 3) | `email-golden`, `email-determinism`, `email-injection-probe` (email golden set) |
| downloads, reports and the local backup (the second backup location has to be set for the machine, section 6) | mailbox download and the standalone email receiver (the legacy Outlook bridge script) |
| the data guard and the start-up check (a missing handoff is only a note) | Azure recognition and the legacy Docker OCR (the legacy sidecar), and `legacy-import` |

The start-up check is green on a fresh clone too, once the hooks are installed (`python -m jav.cli hooks-install`).

## 5. Local, git-ignored folders

| Folder | Contents | Can it be deleted? |
|---|---|---|
| `runs/` | raw runs, evidence, model and OCR caches, logs | No: it is the evidence of the completed measurements |
| `store/` | the local SQLite database (personal data) and the backups | No |
| `inbox/` | downloaded emails (personal data) | No |
| the internal working documents: handoffs, plans, reports, the backlog, the decisions log and the rest (list of paths: `jav/doc_scope.py`) | the local records of how the development went; a fresh clone does not have them | No: they are not under version control; the only second copy is in the daily backup |
| `docs/STATE.md` | the generated state snapshot | Yes: `preflight` regenerates it |
| `tools/tessdata*/` | OCR language packs | Yes, they can be downloaded again |
| `ui/node_modules/`, `ui/dist/` | user-interface dependencies and build | Yes: `npm ci` and `npm run build` recreate them |
| `.venv/` | the Python environment | Yes, it can be rebuilt from the lockfile |

## 6. Backup, restore and logs

**Plain-language summary:** the database (work packages, runs, corrections and decisions) can be backed up with one command, even while the local service is running. The backup also checks that the database is intact. It can run by itself every day at a set time (12:00 by default), and a verified copy can also go to a second location, such as a network drive; both places keep the last 14 backups. The daily backup also takes the internal working documents (handoffs, plans, reports, the backlog, the decisions log), because git does not track them. The state of the last backup is shown on the Settings › System page. Errors of the local service and the worker go to permanent log files, so the cause of a stop can be found later.

**Backup:**

```powershell
python -m jav.cli backup                 # store\backups\<timestamp>\jav.sqlite + manifest.json; the last 14 are kept (the daily backup's retention)
python -m jav.cli backup --with-burr     # also the flow-state store (store\burr_state.sqlite; it can be large)
python -m jav.cli backup --with-docs     # also the internal working documents, into internal-docs.zip (the daily backup does this by default)
python -m jav.cli backup --out D:\Backup --keep 30
```

The command uses SQLite's own backup procedure (a plain file copy of a live database can be corrupt) and runs the integrity check on the copy. A backup contains personal data: handle it like the `store\` folder.

**Daily backup:** the settings are in the `backup` section of `configs\service.json`: the time, the retention, `copy_to` and `with_docs` (the internal working documents too). The second location (for example a folder on a network drive) is machine-specific, so it is set in `.env` as `JAV_BACKUP_COPY_TO` (see `.env.example`); `copy_to` in the tracked config stays empty. Without either, the backup stays local; if the location is not reachable, `backup --scheduled` exits with code 2 to report that the copy failed.

```powershell
.\scripts\backup-task.ps1 install   # entry in Windows Task Scheduler (daily at 12:00; a missed run starts at the next logon or start-up)
.\scripts\backup-task.ps1 status    # last and next run, result code
.\scripts\backup-task.ps1 run       # run it now, for a test
.\scripts\backup-task.ps1 remove    # delete the scheduled task
python -m jav.cli backup --scheduled # the same by hand: local backup + verified copy to the second location
python -m jav.cli backup --copy-to D:\Backup   # a one-off backup to any second location
```

The result code is 0 if everything is fine, 1 if the local backup failed, and 2 if the local backup is fine but the copy failed (for example, the second location is not reachable). The result of every run goes to `store\backups\backup-status.json`; the user interface shows the state from this file and warns if the last successful backup is older than 36 hours. The task runs as the logged-in user, without a window. If the integrity check of a backup fails, no older backup is deleted and nothing is copied to the second location; the folder of the failed backup is kept for inspection and does not count towards the retention.

**Flow-state store:** the worker saves the flow state after every step (`store\burr_state.sqlite`). For a finished item only the last state is kept, because only that is needed to resume. A store that still holds the states of every step can be thinned and compacted once:

```powershell
python -m jav.cli burr-prune          # thinning (also while the worker runs); compacting only with the worker stopped
python -m jav.cli burr-prune --no-vacuum
```

**Restore (by hand):**

1. `.\scripts\dev.ps1 stop` (stops the local service and the worker);
2. set the current `store\jav.sqlite` aside, for example as `store\jav.sqlite.broken`; rename the `jav.sqlite-wal` and `jav.sqlite-shm` files next to it as well;
3. copy the `jav.sqlite` file of the chosen backup back into `store\`;
4. `.\scripts\dev.ps1 start`.

A restore loses the runs, corrections and decisions made after the backup. The downloaded emails (`inbox\`) and the source documents are not in the database, so the backup does not affect them.

**Restoring the internal working documents:** the `internal-docs.zip` in the backup folder holds paths relative to the project root. Extract it into the project root, for example `Expand-Archive store\backups\<timestamp>\internal-docs.zip -DestinationPath . -Force`. This overwrites local files with the same names. To get an older version of a single file, extract into an empty folder first.

**Logs:**

- `runs\logs\api.log` belongs to the local service, `runs\logs\worker.log` to the worker and `runs\logs\backup.log` to the daily backup. They are permanent files that rotate every 5 MB and keep 5 old copies each. They receive the full traceback of every unexpected error, the start and stop of the worker, and the reason for every 404, 422 and 500 response.
- `runs\dev\*.log` is the redirected output of the start script; the output of the previous start is kept as `*.prev`.
