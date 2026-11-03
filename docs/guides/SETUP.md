# Installation and local environment

**Valid from:** 2026-09-27; reviewed 2026-11-02 (a fresh clone installed on a clean folder by this guide). **Platform:** Windows 11, PowerShell 5.1, Python 3.12, [uv](https://docs.astral.sh/uv/) (for the Python environment), Node.js 20.19+ or 22.12+ (for the user interface), Tesseract 5 (for scanned documents), git.

## Plain-language summary

This guide lists what a machine needs to run the project. Git holds only the source code, the settings and the documentation. The keys, the local data and the large OCR language packs are not in it, so each machine has to obtain them separately: the language packs with one command, the keys by hand. A fresh clone runs the user interface, the work packages and the runs; the golden-set measurements also need the legacy project (section 4).

## 1. Python environment

**On a new machine, first.** Install the programs (with `winget`, which Windows 11 has, or from their own pages), then allow local PowerShell scripts for your user once, because Windows does not run them by default and the start script (`scripts\dev.ps1`) and the environment's `Activate.ps1` are such scripts:

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id UB-Mannheim.TesseractOCR -e      # Tesseract 5 (5.4.0 is the version the measurements used); section 3
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # local scripts run; downloaded, unsigned ones still do not
git clone <the repository's address> C:\JAV           # a private repository: git asks for an account with access
cd C:\JAV
```

Open a new PowerShell window after the installs, so the new programs are on the PATH. Clone into a short folder (for example `C:\JAV`): the deepest file of the Python environment is about 140 characters below the project folder, so the folder's own path should stay under about 100 characters unless long paths are switched on in Windows. The folder's name does not matter.

```powershell
uv venv --python 3.12.15 .venv   # the 3.12 patch release the tests run on; uv fetches it if it is missing (an older uv may not know it: uv self update)
uv pip install --require-hashes -r requirements-dev.lock   # the runtime packages and the development tools, each with its hash
.\.venv\Scripts\Activate.ps1
python -m jav.cli hooks-install      # data guard: a check before every commit and push; once per clone
uv tool install ruff==0.16.4         # the code check, in the version preflight counts with (pyproject.toml, ruff_version)
cd ui; npm ci; npm run build; cd ..  # the user interface (below); before preflight, so its tests run too
python -m jav.cli ocr --fetch-langs  # the OCR language packs (section 3)
python -m jav.cli preflight          # tests (Python + UI) + contract lint + engine matrix + configs + handoff + git + OCR + data guard + language guard + Ruff limit + state snapshot
```

On a fresh clone `preflight` is green. It notes that no handoff exists (the internal working documents stay on the machine that wrote them) and that the dependency audit has not run yet (`python -m jav.cli deps-audit`), and a few tests skip, each saying why: they need the internal working documents, the language packs or the legacy golden set. Without the user interface's packages its tests are skipped, not failed, so install them first.

**Package lists.** `requirements.txt` names the runtime packages, `requirements-dev.txt` adds the test tools; `requirements.lock` and `requirements-dev.lock` pin every package with its hashes, so an install refuses a package that differs from the one locked. A machine that only runs the service may install `requirements.lock`. A list change is locked again with the current pins as constraints, so nothing else moves: `uv pip compile requirements-dev.txt --generate-hashes -c requirements-dev.lock --python-version 3.12 --python-platform windows --no-header --no-annotate -o requirements-dev.lock` (and the same for `requirements.txt` into `requirements.lock`).

**Data guard.** `hooks-install` points git at the versioned hooks in `scripts/githooks/` (through `core.hooksPath`). From then on a check runs before every commit and push, and stops the operation if the lines going into git contain personal data or a key: for example a real-looking tax number, bank account number, email address or phone number, or a key from `.env`. It also stops the operation if an internal working document, a document file, an image or a database would go into git. Until the hooks are installed, the start-up check (`preflight`) reports a failure. `python -m jav.cli data-guard` reviews the files already under version control. The rules: [DEVELOPMENT §1](DEVELOPMENT.md).

**User interface.** It needs Node.js 20.19+ or 22.12+ (the requirement of Vite, the build tool; Node.js 21 is not supported):

```powershell
cd ui; npm ci; npm run build; cd ..   # dependencies as pinned in package-lock.json; type check and build into ui/dist
.\scripts\dev.ps1 start             # local service + the configured workers (one by default) in the background; user interface: http://127.0.0.1:8930/
.\scripts\dev.ps1 status            # are they running?
.\scripts\dev.ps1 stop              # stop both; an interrupted run resumes from its saved step
```

`start` waits until the service answers (at most 90 seconds, `-StartTimeoutSec`) and prints its address. If the service stops at start-up, it prints the reason and exits with code 1; on a new machine the usual reason is a port another program already uses (the service needs 8930, the invented registers of the insurance cases 8941). Start it on another port with `-Port`, or set `port` in `configs/service.json`. `python -m jav.cli serve` names a taken port the same way.

**Your own folders in the user interface.** By default, any existing local folder or file can be given in the user interface (for a work package or a work folder). The restriction can be switched back on with `restrict_paths: true` in `configs/service.json`. Documents can then be added only from allowed folders: the project's `inbox/` and `data/` folders, the legacy project's data, and the folders listed in the `JAV_API_ROOTS` variable in `.env` (separate several folders with `;`, and quote the value if a path contains a space). Example: `JAV_API_ROOTS="D:\Invoices\Incoming"`. After the change, run `.\scripts\dev.ps1 stop` and then `start`. The folder with the real documents stays on the machine and never goes into git.

During development, `npm run dev` serves the user interface at `http://127.0.0.1:5173/` and forwards the `/api` requests to the local service. `npm run lint` runs ESLint on the interface's code (the full `preflight` runs it too, after the type check).

## 2. Keys

Copy `.env.example` to `.env` and fill in:

- `TypeSafeJAV_API_KEY`: the JEV key (the SDK's own `TYPESAFE_API_KEY` name is also accepted);
- `OPENAI_API_KEY`: for the G path (GPT extraction), the task proposals, processing with GPT only, and OpenAI Decisions
  (the same key).

`.env` never goes into git; the data guard also looks for the secret values from `.env` in the lines being committed. Never write a key value into a log or a document. `python smoke_test.py` checks the environment and that the JEV key is there (it prints only the key's length); with `--jev-budget-usd 0.01` it makes one tiny live call under that budget (paid, a fraction of a cent), recorded in the call log.

Optional environment variables (in `.env` or in the shell):

| variable | purpose |
|---|---|
| `JAV_LEGACY_ROOT` | the location of the legacy project, if it is not the default (section 4) |
| `JAV_API_ROOTS` | allowed document folders when the folder restriction is on (section 1) |
| `JAV_INGEST_TOKEN` | the key of the standalone email receiver (`email-ingest-server`) used on the legacy, manual route; without it (and without `--token`) the receiver prints a one-off key at start-up |
| `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` | the Azure Document Intelligence resource for the paid recognition of weak scans, called directly (section 3); without them Azure is not set up on this machine and a weak scan keeps its local text, with a to-do |
| `JAV_PROVIDERS_ON`, `JAV_PROVIDERS_OFF` | the paid services this installation may call, over `configs/providers.json` `enabled` (names separated by `,`): for example `JAV_PROVIDERS_OFF=openai_decisions` switches OpenAI Decisions off, `jev` where JEV is not contracted |
| `JAV_TESSDATA_DIR` | the folder of the Tesseract language packs, if it is not `tools/tessdata` (section 3) |
| `JAV_OCR_ENGINE` | `native` or `azure_di` for one command; `azure_di` forces the paid Azure recognition (at most 12 pages, live only under a budget). The default comes from `configs/ocr.json` and never picks Azure. |
| `JAV_ALLOW_SDK_DEBUG` | `1`: allows the JEV library's detailed log; it also logs personal data, so use it only on made-up data |
| `JAV_HYPOTHESIS_EXAMPLES` | the number of generated examples per property-based test (default 150), for a deeper search |

## 3. OCR (for PDFs without a text layer and for images)

JPEG, PNG and TIFF images are documents too: each is read through a PDF that holds exactly its pixels (`jav/documents/image_input.py`, kept once under the image's fingerprint beside the source instances, in `store/derived/`), so it takes the same recognition as a scanned PDF.

- **Tesseract 5.x**, installed natively (`winget install --id UB-Mannheim.TesseractOCR -e`, the UB Mannheim build for Windows; the measurements used 5.4.0). It does not need to be on the PATH: `configs/ocr.json` lists where to look (the PATH, `%LOCALAPPDATA%\Programs\Tesseract-OCR` and `C:\Program Files\Tesseract-OCR`).
- **Language packs** (not in git; git-ignored): `tools/tessdata/` holds `eng`, `hun` and `osd`. `python -m jav.cli ocr --fetch-langs` downloads the missing ones from the tesseract-ocr project's `tessdata_fast` release 4.1.0 and keeps each file only when its SHA-256 matches the one pinned in `configs/ocr.json` (`tesseract.language_packs`): byte for byte the files every measurement read with, so recognition is the same on every machine. A different file already in the folder is left alone and reported. `JAV_TESSDATA_DIR` names another folder (for a second checkout or a worktree). Without a PDF, `python -m jav.cli ocr` prints the state of the engine and the language packs (which are missing, which differ from the pinned files), and `preflight` shows it on its OCR line. A scanned document read without them gets an OCR to-do, and the worker's log (`runs\logs\worker.log`) names the missing packs.
- **Azure Document Intelligence** (optional, paid): the more accurate cloud recognition of weak scans, and of every scan on a machine with no local engine. The system calls the service directly with this installation's own endpoint and key; nothing else is needed (no container, no other project). At most 12 pages of a document are analysed and billed (`max_pages` in `configs/ocr.json`), at about 0.0015 USD a page (the list price in `configs/models.json`). In a run it is used only within the run's Azure budget (the processing setting **Azure recognition**, 0.02 USD per document by default), every call is in the call log, and when the recognition cannot run the document keeps its local text with a to-do. A start the service refuses for load is repeated; a refused start costs nothing. `JAV_PROVIDERS_OFF=azure_di` switches it off on a machine.

  **Setting it up:**

  1. In the Azure portal create a **Document Intelligence** resource. Choose a region (for data kept in the EU, an EU region such as West Europe or Sweden Central) and the **Standard (S0)** pricing tier. The free tier (F0) analyses only the first two pages of a document and files up to 4 MB.
  2. On the resource's **Keys and Endpoint** page, copy the endpoint and one of the two keys into `.env`: `AZURE_DI_ENDPOINT=https://<resource>.cognitiveservices.azure.com/` and `AZURE_DI_KEY=<key>`. The endpoint must be an `https` address. The key is never printed or logged.
  3. Restart the service and the worker (`.\scripts\dev.ps1 stop`, then `start`), then check the endpoint and the key for free: `python -m jav.cli ocr --check-azure`. It asks the resource for its details; nothing is analysed or billed. `python -m jav.cli ocr` without a PDF shows the state, and the start-up check names it on its OCR line.
  4. A one-off live recognition from the command line needs its own Azure budget: `python -m jav.cli ocr <pdf> --engine azure_di --azure-budget-usd 0.02`.

## 4. Dependency on the legacy project: what works in a fresh clone

`jav/core/config.py` finds the golden sets and the legacy data folder under `<legacy-root>`, the root folder of the legacy project. They are only read. `<legacy-root>` comes from the `JAV_LEGACY_ROOT` environment variable (or a line in `.env`); without it, `jav/core/config.py` falls back to the `10_AIFLOW_V4` folder next to the project folder (`DEFAULT_OLD_PROJECT_ROOT`), which another machine usually does not have, so set the variable there if the legacy project is somewhere else.

A fresh GitHub clone has neither the legacy project, nor the golden sets, nor the internal working documents. In that case:

| works | needs the legacy project |
|---|---|
| the full test suite (tests that rely on a golden set are skipped without it, so the coverage is smaller) | `recall`, `golden`, `determinism`, `verifier-probe` (invoice golden set) |
| the user interface, the local service and the worker; work packages, recipes, trial and live runs with the keys | `detect-golden`, `detect-determinism` (detection golden set) |
| local OCR (the language packs have to be obtained separately, section 3), and Azure recognition with this installation's own endpoint and key | `email-golden`, `email-determinism`, `email-injection-probe` (email golden set) |
| downloads, reports and the local backup (the second backup location has to be set for the machine, section 6); the mailbox download and the standalone email receiver (the Outlook bridge, `scripts/outlook_bridge.ps1`, is in this repository) | |
| the data guard and the start-up check (a missing handoff is only a note) | `legacy-import` |

The start-up check is green on a fresh clone too, once the hooks are installed (`python -m jav.cli hooks-install`).

## 5. Local, git-ignored folders

| Folder | Contents | Can it be deleted? |
|---|---|---|
| `runs/` | raw runs, evidence, model and OCR caches, logs | No: it is the evidence of the completed measurements |
| `store/` | the local SQLite database (personal data) and the backups | No |
| `inbox/` | downloaded emails (personal data) | No |
| the internal working documents: handoffs, plans, reports, the backlog, the decisions log and the rest (list of paths: `jav/core/doc_scope.py`) | the local records of how the development went; a fresh clone does not have them | No: they are not under version control; the only second copy is in the daily backup |
| `docs/STATE.md` | the generated state snapshot | Yes: `preflight` regenerates it |
| `tools/tessdata/` | OCR language packs | Yes: `python -m jav.cli ocr --fetch-langs` downloads them again |
| `ui/node_modules/`, `ui/dist/` | user-interface dependencies and build | Yes: `npm ci` and `npm run build` recreate them |
| `.venv/` | the Python environment | Yes, it can be rebuilt from the lockfile |

### 5.1 A second installation: the start-up description

By default everything above lies in the program's folder. A second installation on the same machine (for example an
invented one to try something) gets its own folders through a start-up description: a JSON file that the environment
variable `JAV_START` names, read before anything else.

```json
{"data": "D:/jav-minta", "installation": "minta-a", "configs": "D:/jav-minta/configs", "env": "D:/jav-minta/.env"}
```

- `data`: where the installation writes everything: `store/` (with the backups and the worker's files next to the
  store), `runs/` (with the caches and the logs) and `inbox/`. The folder must exist.
- `installation`: the installation's own name (3 to 64 lowercase letters, digits and hyphens). Its store is stamped with
  it; a service or a worker started with a description naming another installation stops before it writes anything.
- `configs` and `env` (optional): its own rule files (for example another port in `service.json`) and keys; by default
  the program's.
- A relative path is read from the description's folder. A description that cannot be read, names an unknown key or a
  data folder that does not exist stops the start.

Start the second installation's service and worker from a shell with `JAV_START` set (`python -m jav.cli serve --port
<another port>` and `python -m jav.cli worker`); `scripts\dev.ps1` runs the installation of the program's own folder.

## 6. Backup, restore and logs

**Plain-language summary:** the database (work packages, runs, corrections and decisions) can be backed up with one command, even while the local service is running. The backup also checks that the database is intact. It can run by itself every day at a set time (12:00 by default), and a verified copy can also go to a second location, such as a network drive; both places keep the last 14 daily backups. Manual backups (the command below, or Back up now on the Operations page) are kept apart, the last 14 of them, so they never push out a daily one. The daily backup also takes the internal working documents (handoffs, plans, reports, the backlog, the decisions log), because git does not track them, the copies the system keeps of the documents added to work packages, each only once, and this machine's local settings (`.env`: the keys and the second backup location), so the machine can be set up again from a backup alone. The state of the last backup is shown on the Settings › Operations page. Errors of the local service and the worker go to permanent log files, so the cause of a stop can be found later.

**Backup:**

```powershell
python -m jav.cli backup                 # store\backups\<timestamp>\jav.sqlite + manifest.json; the last 14 manual backups are kept, apart from the daily ones
python -m jav.cli backup --with-burr     # also the flow-state store (store\burr_state.sqlite; it can be large)
python -m jav.cli backup --with-docs     # also the internal working documents, into internal-docs.zip (the daily backup does this by default)
python -m jav.cli backup --with-env      # also the local settings (.env and .env.* except .env.example), into local-env.zip (the daily backup does this by default)
python -m jav.cli backup --out D:\Backup --keep 30
```

The command uses SQLite's own backup procedure (a plain file copy of a live database can be corrupt) and runs the integrity check on the copy. The source instances (the unchanging copies of the documents added to work packages, `store\sources\`) go into one shared `sources\` folder beside the timestamped backups, locally and in the second location: each is copied once, checked against the content hash in its name, and never pruned; a damaged one is not copied and is named in the manifest. The check starts from the instances the saved database refers to, not only from the files found: one missing or damaged in `store\sources\` but intact in the backup is listed as preserved; one intact nowhere is listed as missing, the backup counts as failed (the status line names it) and no earlier backup is deleted, locally or in the second location. The database copy still goes to the second location. A backup contains personal data and, in `local-env.zip`, the keys (unencrypted): handle it like the `store\` folder and the `.env` file together, and keep the second location where only you can read it.

**Daily backup:** the settings are in the `backup` section of `configs\service.json`: the time, the retention, `copy_to`, `with_docs` (the internal working documents too), `with_env` (the local settings too) and `jev_version_usd` (the daily look at JEV's moving name, one tiny probe through the call log under this JEV budget a day; 0 turns it off, and the start-up check then says the look failed). The second location (for example a folder on a network drive) is machine-specific, so it is set in `.env` as `JAV_BACKUP_COPY_TO` (see `.env.example`); `copy_to` in the tracked config stays empty. Without either, the backup stays local; if the location is not reachable, `backup --scheduled` exits with code 2 to report that the copy failed.

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
   **and the flow-state store from the same moment:** if the backup was made `--with-burr`, copy its
   `burr_state.sqlite` back too; otherwise set the current `store\burr_state.sqlite` (and its `-wal`, `-shm` files)
   aside as well, so the worker starts the restored runs' unfinished items afresh. A flow state newer than the
   restored store would let an item resume past steps the store no longer holds, and it could end "done" without its
   data and to-dos;
4. copy the contents of the backup root's `sources\` folder into `store\sources\` (files already there can be kept: a file's name is its content hash);
5. unpack the backup's `native-artifacts.zip` into `store\` (its names start with `native/`);
6. if the project folder itself was lost: unpack `internal-docs.zip` and `local-env.zip` into the project root (their names are relative to it; do not overwrite a newer file);
7. `.\scripts\dev.ps1 start`.

A restore loses the runs, corrections and decisions made after the backup. The downloaded emails (`inbox\`) and the source documents are not in the database, so the backup does not affect them.

**Restoring the internal working documents:** the `internal-docs.zip` in the backup folder holds paths relative to the project root. Extract it into the project root, for example `Expand-Archive store\backups\<timestamp>\internal-docs.zip -DestinationPath . -Force`. This overwrites local files with the same names. To get an older version of a single file, extract into an empty folder first.

**Logs:**

- `runs\logs\api.log` belongs to the local service, `runs\logs\worker.log` to the worker and `runs\logs\backup.log` to the daily backup. They are permanent files that rotate every 5 MB and keep 5 old copies each. They receive the full traceback of every unexpected error, the start and stop of the worker, and the reason for every 404, 422 and 500 response.
- `runs\dev\*.log` is the redirected output of the start script; the output of the previous start is kept as `*.prev`.
