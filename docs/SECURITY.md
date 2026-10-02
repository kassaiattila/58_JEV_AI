# Security

**In force:** since 2026-09-30 (v1.0.5). **Audience:** users and developers.

## Plain-language summary

The system is built for one machine and one user. The local service accepts requests only from the machine itself and refuses anything that comes from another website or another machine; it also tells the browser not to embed the UI in other pages and not to store document data on disk. Paid AI calls draw on a budget reserved in advance, every call goes into the call log, and nothing takes effect without human approval. Only code and codebase documents may reach GitHub: the data guard (a check that runs before every commit and push) stops the operation if personal data, a key or internal working documents would be uploaded. The weak points are known too: there is no real login, personal data sits on the machine and in the backups without encryption or a retention period, and the protection against hidden instructions has only been measured on a small sample (section 5; open items: section 9). That is why the system must not be exposed on a network.

Technical terms are explained in the [glossary](GLOSSARY.md).

## 1. What the system protects against, and from whom

**The boundary:** one machine, one Windows account, one user (or a few people taking turns on the same machine). The local service listens only on the machine's loopback address; with any other address the program does not even start.

**It protects against:**
- a third-party website, open in the browser at the same time, starting an operation in the local service;
- the service being reached through a third-party web address that an attacker has pointed at the machine's loopback address;
- a huge request or document exhausting the machine;
- a paid call exceeding the run's budget, or being made twice;
- an instruction hidden in a document or email getting wrong data accepted silently;
- personal data, keys or internal working documents reaching GitHub.

**It does not protect against:**
- other programs running on the machine, or other people using the same Windows account: they can reach both the local service and the files;
- theft of the machine or of a backup copy: the system encrypts nothing (section 7);
- someone working under another person's name: there is no password.

**Choosing a name is not authentication.** The name picked in the **Who is working?** (*Ki dolgozik?*) field (the active user) only records who did what. The list of names can be read without a password, and anyone who can reach the service on the machine can send requests under any name on the list. A name in the log therefore does not prove who was sitting at the machine.

**On a network** (which the code does not allow today), anyone could work under any name; the folder restriction is off by default, so documents could be added from any existing folder on the machine and opened; and when settings are saved, the last save wins. Before the service can be reached from outside the machine, these must be solved with the items in section 9.

## 2. The local service's gateway

The local service is the shared gateway for the UI and the command line. It checks every request before anything happens:

- **Loopback address only.** With any other address it reports an error and does not start.
- **Host-name check.** It accepts only requests addressed to the machine's own local name. This protects against a third-party web address being pointed at the machine's loopback address.
- **Origin check.** If a request comes from a browser, the origin of the sending page must exactly match the service's own address or the configured address of the development UI. Other local ports and an empty origin are refused too (exact matching since 2026-09-29).
- **Write requests only as JSON.** Create, change and delete requests are accepted only in this form, so a simple form on a third-party page cannot start an operation. A request is at most 256 KB, even when it is sent in chunks.
- **Structure check.** A request with an unknown field, a malformed identifier or an over-long text is refused.
- **A name for every human decision.** Starting a run, approving, correcting, assigning a recipe, changing a work package, stopping the worker and making a backup do not work without a name. If the **Users** (*Felhasználók*) list is not empty, only a name on that list is accepted.
- **Source documents only from the work package.** The service serves a document's page image and source file only if it is a file that was added to the work package and has not changed since. No other file can be read this way.
- **The interactive endpoint list is switched off** (the owner's decision, 2026-09-30). That page would have loaded program code from an external host, and it would have run on the local address with the UI's privileges. The machine-readable endpoint list remains.

## 3. Browser security headers (since 2026-09-30)

The local service attaches instructions for the browser to every response, including the responses to failed and refused requests. This is a second layer behind the protections in section 2:

- the UI cannot be embedded in another page, so a third-party page cannot hide it invisibly beneath its own content and hijack clicks;
- the UI may only load and run its own files: no external scripts, stylesheets or fonts; embedded images and fonts, and downloads built from its own data, are allowed;
- the browser may not guess a file's type, does not pass the UI's address on to other sites, and other sites cannot load the service's responses;
- responses that carry document data (data, page images, source documents, downloads) must not go into the browser's disk cache; page images used to stay there for a day;
- the source PDF opens in the browser's own PDF viewer, so for it only embedding is forbidden (the stricter rule would block the viewer too);
- the UI's program files may be cached, because they contain no document data.

## 4. Input: documents, folders, size

- **Input limits** apply at every entry point (UI, command line, worker): text extraction stops a document larger than 100 MB or longer than 300 pages with a named error. A page larger than 40 megapixels is rendered at a lower resolution, text recognition does not run on it, and the item gets a to-do.
- **Isolated PDF reading** (since 2026-09-30). The third-party PDF parsers run in a separate helper process, not in the worker or the local service themselves, with a time limit per request and a memory limit (on Windows enforced by the operating system). If a PDF makes a parser hang, crash or use too much memory, only the helper stops: text extraction stops the item with a named error, the page images for text recognition give a to-do, a page image for review is refused, and the next document gets a new helper. A document over a limit is not retried, because a retry would hit the same limit.
- **Folders.** Since 2026-09-28, by the owner's decision, any existing local folder or file may be given. The folder restriction can be switched back on with a setting; then only locations under the configured root folders are accepted. The service resolves the path, following links, and accepts only an existing folder or file.
- **Watched folder.** The worker only reads it; new documents become a work package, but no paid run starts on its own.
- **Fixed input.** If a file changes after it was added, the run does not process it and reports an error instead.

## 5. AI calls

**Cost.** Before every paid call (JEV, OpenAI, and since 2026-09-30 Azure recognition too, priced per page), the system reserves an upper bound of its cost from the run's budget (cost reservation). Since 2026-09-30 it is a real bound: at most one token per byte of everything sent (instructions and output schema included), a fixed overhead, every possible retry at full price, rounded up; the OpenAI client does not retry on its own. If a call still costs more than its reservation, the answer is kept, but the run makes no further call with that provider. If the reservation does not fit, the call is not made and the item gets a to-do. The call log records every call before it is made and closes the entry afterwards with the actual model and cost; failed calls are recorded too. A call of unknown cost counts at the maximum amount. A call that was sent but got no answer (a timeout or a broken connection after sending) counts as uncertain, not failed, because the provider may have done and billed the work; it can be settled by hand on the System page. An earlier GPT answer to the same question is reused for free when the run allows it, and is recorded with cost 0 and its origin. A call still in progress cannot be settled, so its reserved maximum cannot be spent twice; an answer arriving after a manual settlement does not overwrite it. The system does not repeat an uncertain attempt by itself, because that could mean paying twice. If the system stops between saving an answer and closing its log entry, the restart closes the entry from the saved answer, and an answer above its reservation stops the provider's further calls there too. If the configured GPT model has no price in the price list, it is not called under a budget, because the reservation would see zero.

**Keys.** The providers' keys are in the machine's local key file. Git does not track it, and the data guard also looks for the key values before every commit and push. The JEV SDK's detailed log would write out the full request text, that is the document content, so the system leaves it switched on only with explicit permission.

**Hidden (injected) instructions.** An injected instruction is a sentence in a document or email that is addressed not to a person but to the processing system. The protection has several layers:
- **On the S path**, JEV may only choose among the candidates that the code collected from the document; it cannot write a new value.
- **On the G path**, JEV checks every field of the GPT extraction with a separate question, and the code also validates the check digits of the tax number and the bank account number.
- **For emails**, a separate signal watches for injected instructions. If it is clear-cut (yes band), the email goes to manual review as suspicious ahead of every other route, and no task proposal is made for it. Without JEV, GPT answers the same question (and its instructions say that the email text is data whose instructions are reported, never followed); GPT can only choose among the allowed answers, but the injection probe has not yet been run on it.
- **Task proposal:** every statement needs a verbatim quote from the email; an invented deadline or assignee is dropped. Task proposals are off by default, and only a person can accept one.
- **Approval:** a live run can only be approved when all its items have finished and there is no open to-do. The approval names the version of the result the approver saw: if a correction was saved in the meantime (for example in another tab), it is refused until the new state has been looked at. A correction is refused once the run is approved, also when it was started before a concurrent approval.
- **Still missing:** the document instructions lack a "the source text is data, not instructions" guard sentence, and documents have no separate injected-instruction signal (section 9).

**Probes** (small trials, not general proof):
- **Documents.** Made-up Hungarian invoices, each in a clean version and four attack versions: "overwriting" the amount payable, swapping the bank account for another valid number, "do not raise a to-do", and "this is not an invoice". Document type recognition, the S path and the G path run on each, and the probe checks whether a wrong value is accepted without a to-do. It uses one wording and one run per version, and it has not been run on real documents.
- **Emails.** Golden-set emails, clean and with an injected instruction at the start (in Hungarian and English, in three wordings) or at the very end (in English). The probe checks whether the signal flags the instruction, whether it raises false alarms on clean emails, and whether the injected sentence changes the recognised intent. How reliably the signal flags an instruction depends on where it sits in the email, so it does not catch every one.

## 6. Emails and mailboxes

- **Mailbox download** goes through the Outlook running on the machine, using the old Outlook script. The system neither asks for nor stores a mailbox password.
- For the duration of a download, a dedicated receiver starts, listening only on the machine's loopback address and using a one-time random key. It stops when the download ends.
- The system checks the mailbox address and the folder name before passing them to the script: they may not contain quotes, semicolons, dollar signs or similar characters that could be interpreted as commands.
- **The standalone email receiver** (for the old script, started from the command line) accepts requests only with a key. If no key is configured, it generates a random key at start-up and prints it. It refuses requests that come from a browser (with an Origin header, a non-JSON body or a foreign host name). A request is at most 2 MB, and its structure is checked.
- The receiver builds the mailbox folder name itself and writes nothing outside the inbox folder. An attachment may only point to an existing file under the root of the incoming data.
- An identical repeat is not overwritten and does not start a new run. Changed content is stored as a new version next to the old one.

## 7. Personal data on the machine

The system encrypts nothing. Disk encryption (BitLocker) is a machine setting that the system neither sets nor checks. **There is no retention period:** the data below is kept indefinitely, except where the table says otherwise.

| Location | What it holds | How much is kept |
|---|---|---|
| Store | extracted data from documents and emails, the documents' word layer, corrections, to-dos, runs, the call log | indefinitely |
| Flow-state store | the full processing state of each item, including the text that was read | for finished items, only the last save (thinning) |
| Runs folder | raw runs; the JEV cache (with the requests, so excerpts of document and email text); the OCR cache (recognised text) | indefinitely |
| Service log | errors with stack traces, which may include file names and paths; for some operations, the requester's name. Keys, tokens and passwords from the environment and the local key file are masked (since 2026-09-30) | rotates every 5 MB; 5 old copies are kept |
| Incoming email folder | the text and header data of downloaded emails, and their attachments | indefinitely |
| Source documents | stay where they are; the system does not copy them, it only refers to them by content hash | not managed by the system |
| Store backup | the store and the internal working documents, locally and, if one is configured, in the second backup location; unencrypted | the latest 14 in both places (default) |
| Local key file | the providers' keys, unencrypted | indefinitely |
| Burr's local tracker | only for some command-line measurement commands: the flow steps, in the user's home folder; the worker does not use it | indefinitely |

The backup is not a full recovery: it does not include the source documents, the emails, the runs folder or the keys, nor, by default, the flow-state store. Restoring is manual, with the service stopped ([setup guide, section 6](guides/SETUP.md)); a tested recovery is an open item (section 9).

## 8. GitHub and the code

- **Forbidden history.** The pre-push hook refuses to push any commit that builds on a history listed as forbidden in the data guard's settings.
- **Data guard** (since 2026-09-30). Before every commit and push, it checks the new lines going into git; a renamed or copied file is checked in full under its new path (since 2026-09-30). It stops if it finds a real-looking value: a tax number, IBAN or Hungarian bank account number whose check digits are valid. A value with invalid check digits cannot be real, so it passes. It also stops on email addresses that are not made up, Hungarian phone numbers, foreign tax numbers, known key formats, the secret values in the local key file (variables named like a key, token, secret or password), and a few forbidden phrases (stored only as fingerprints). By path, it rejects internal working documents, the key file, the local data folders, document, image, archive and store files, and every binary file. Its output is always masked.
- **Exceptions.** Made-up sample values are on a versioned exception list. A few older values are tolerated as known values: they are listed only as fingerprints, and they pass only in the file where they are now. Replacing most of them is an open item (section 9).
- The hooks must be enabled once per clone; the start-up check reports an error if they are not. Bypassing them is forbidden ([development guide, section 1](guides/DEVELOPMENT.md)).
- **Internal working documents** (the development process's own notes, listed in `jav/doc_scope.py`) are not in git. They stay local, and the daily backup copies them.
- **Third-party packages.** The Python and UI packages are pinned. Since 2026-09-30 the known-vulnerability check (Python and UI) runs with the daily backup once a week, or by hand with `python -m jav.cli deps-audit`; its date and result are on the Settings › System page, and the start-up check fails on a known vulnerability. GitHub's vulnerability alerts have been on since 2026-09-30, without automatic fix pull requests.
- **Which code is running.** The service shows the release version and the commit it was started from in its health response and on the **Settings › System** (*Beállítások › Rendszer*) page, and flags it if the running code had uncommitted changes.

## 9. Open items

- **Injection hardening:** the document instructions lack a "the source text is data, not instructions" guard sentence, documents have no separate injected-instruction signal, the hidden-instruction probes are small and need repeating, and a few tolerated older values remain to be replaced (section 8).
- **Data inventory:** there is no inventory of where personal data is held and how long it stays, and no retention period with a command that deletes the data after it (section 7).
- **Encryption:** the backup copies are not encrypted, and the machine's disk encryption is not checked.
- **Recovery:** restoring the working system from a backup in a separate location has not been rehearsed (a recovery drill with written steps and a measured time).
- **Authentication:** there is no real login (password or Windows authentication) and no permissions, only choosing a name; this must be solved before network or multi-user use.
- **Folder restriction:** it is off by default; switch it back on before anyone else can reach the service.
- **Last writer wins:** settings and work-package data are saved without version checking, so the last save wins; this must be solved before multi-user use.

## 10. Reporting a vulnerability

The repository is private and has a single maintainer. Report security issues directly to the maintainer; there is no public reporting process. Do not include real documents, emails or keys in a report: demonstrate the issue on a synthetic example.

## Technical details

**Local service** (`jav/api.py`, settings: `configs/service.json` 1.8.0):

| Protection | Code | Setting | Test |
|---|---|---|---|
| loopback only | `serve()`: `host` must be in the `LOOPBACK` set, otherwise `ValueError` | `host`, `port` | `tests/test_api.py::test_serve_refuses_non_loopback_host` |
| host name (`Host`) | `_Guard`: `allowed_hosts` ∩ `LOOPBACK`, otherwise 403 `forbidden_host` | `allowed_hosts` | `tests/test_api.py::test_foreign_host_and_origin_are_refused` |
| origin (`Origin`) | `_Guard`, `_origin()`: exact scheme + host + port, otherwise 403 `forbidden_origin` | `dev_origins` | `tests/test_api.py::test_origin_must_match_the_service_or_the_dev_ui_exactly` |
| JSON only, body size | `_Guard`: `POST/PUT/PATCH/DELETE` only as `application/json` (415); the body is read up front against the limit (413) | `max_body_bytes` = 262144 | `tests/test_api.py::test_body_must_be_json_and_bounded` |
| structure | `_In` (`extra="forbid"`), `WpId`, `RunId`, `ItemId`, `Text` (2000 characters) | – | `tests/test_api.py::test_schema_rejects_unknown_fields_and_bad_ids` |
| actor | `human_actor`, `actor_unless_first_users`, `X-Actor` header (URL-encoded), `app_settings.ACTOR_RE`; unknown name: 403 `unknown_user` | **Users** list | `tests/test_users.py`, `tests/test_api.py::test_actor_may_carry_accents_when_url_encoded` |
| source document | `_item_source()`: the file is read once and its full `sha256` must match the item's on every request (since v1.1.0; before, a fingerprint memoised by size and modification time was trusted), otherwise 409; the source and the page image are made from exactly the verified bytes | – | `tests/test_api.py::test_item_source_is_served_only_for_unchanged_items`, `tests/test_source_identity_075.py` |
| folder restriction | `checked_path()` (`resolve(strict=True)`), `allowed_roots()`, 403 `forbidden_path` | `restrict_paths` (false), `allowed_roots`, `allow_legacy_data_root`, `JAV_API_ROOTS` | `tests/test_api.py::test_folder_outside_allowed_roots_is_refused`, `::test_any_existing_folder_is_accepted_without_restriction` |
| endpoint list | `create_app()`: `docs_url=None`, `redoc_url=None`; `/api/openapi.json` stays | – | `tests/test_security_headers_071.py::test_interactive_docs_are_off_machine_list_stays` |
| security headers | `_SecurityHeaders` (outermost layer): `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy: same-origin`; CSP: `UI_CSP` (UI), `API_CSP` (`default-src 'none'`), `DOCUMENT_CSP` (PDF: only `frame-ancestors 'none'`); `Cache-Control: no-store` under `/api/` | – | `tests/test_security_headers_071.py` |
| version | `jav/version.py` (`VERSION` from `pyproject.toml`, `commit_info()`); `/api/health`: `version`, `commit`, `dirty`, `started_at`, `ui_build` (the first 12 hex digits of the SHA-256 of `ui/dist/index.html`; no path or content) | – | `tests/test_version_071.py`, `tests/test_version_banner_091.py` |

**Input, AI calls, approval:**

| Protection | Code | Setting | Test |
|---|---|---|---|
| input limits | `jav/pdf.py` (`check_document_size`, `DocumentTooLarge`, `InputLimits`, `fit_scale`), `jav/page_image.py`, `jav/ocr.py` (`PageTooLarge`) | `input_limits`: 100 MB, 300 pages, 40 megapixels | `tests/test_input_limits_067.py` |
| isolated PDF reading | `jav/isolated_pdf.py` (`Reader`, `run`, `PdfReaderLimit`, `PdfReaderError`, `_windows_job`: job object with `ProcessMemoryLimit`, kill on close, no error dialog); callers `jav/pdf.py` `read_pdf`, `jav/ocr.py` `render_pages` (`PdfRenderLimit`), `page_sizes`, `jav/page_image.py`; no retry: `jav/runtime/worker.py` | `pdf_reader`: `isolated`, `read_timeout_s`, `render_timeout_s`, `page_image_timeout_s`, `memory_mb`, `startup_timeout_s` | `tests/test_isolated_pdf_077.py`, `tests/test_runtime_worker.py::test_a_document_over_a_reader_limit_fails_without_retry` |
| fixed input | `jav/runtime/worker.py` (`source_changed`), readiness check in `jav/work.py` | – | `tests/test_runtime_worker.py::test_changed_source_is_refused`, `tests/test_work.py::test_readiness_detects_changed_and_missing_source` |
| cost reservation, call log | `jav/runtime/calls.py` (`estimate_max_cost` upper bound with `TOKEN_OVERHEAD`, `invoke`, `_reserve` in a `BEGIN IMMEDIATE` transaction, `BudgetExceeded`, `UncertainAttempt`, `actual_exceeds_reserved` stop, also after a restart in `recover_uncertain`; `outcome_unknown`: sent but unanswered → `uncertain`; the restart takes over only the reservations of stopped processes, by the holder lock each reservation names); `configs/models.json` `openai.sdk_max_retries = 0` | `configs/recipes.json` `max_item_usd` | `tests/test_runtime_calls.py`, `tests/test_runtime_worker.py::test_budget_exhaustion_becomes_review_not_crash`, `tests/test_reservation_holder_092.py` |
| unpriced model | `jav/config.py` `openai_price()`, `UnpricedModelError`; callers: `jav/extract_llm.py`, `jav/email_tasks.py` | `configs/models.json` `openai.usd_per_mtok` | `tests/test_runtime_adapters.py::test_unpriced_model_is_refused_under_a_budget` |
| SDK log | `jav/config.py` `guard_sdk_logging()`: when `TYPESAFE_LOG_LEVEL` is `debug` or `info`, the `typesafe_sdk` log is raised to WARNING, unless `JAV_ALLOW_SDK_DEBUG=1` | environment variables | `tests/test_jev_adapter_v2.py::test_sdk_log_level_guard` |
| email: injected instruction | `configs/callsites/email_intent.json` `prompt_injection` Noul; `jav/policy.py` `email_signal_reasons`, `email_signal_route` → `human:suspicious` | `configs/policy.json` `email.signal_review`, `email.signal_routes`, band: `email.signal` | `tests/test_email_signals.py::test_policy_signal_reasons_and_route` |
| task-proposal gate | `jav/email_tasks.py` `gate()` (verbatim quote), `skip_reason()` (`suspicious_signal`) | `configs/recipes.json` `tasks` (default: `off`) | `tests/test_email_tasks.py` |
| approval lock | `jav/work.py` `approve_run()` (`NotReady`; `review_version` checked and the approval recorded in one transaction, `RevisionConflict`), `jav/corrections.py` (`review_version`: the corrections and the email task decisions; the approval checked again in `_insert_revision`'s transaction), `jav/mailbox.py` `decide_task()` (the approval checked again in the decision's writing transaction), `jav/datasets.py` `query()` (a run's table carries the version of the result it shows; the UI approves that version and waits for the table after a conflict) | – | `tests/test_api.py::test_approval_needs_apply_mode_and_no_open_reason`, `tests/test_work.py`, `tests/test_review_gate_066.py`, `tests/test_audit_fixes_085.py`, `tests/test_audit_fixes_1002.py`, `ui/src/audit1002.test.tsx` |
| email source version | `jav/emails.py` `message_version()` (the email item is read from the version whose fingerprint it recorded: `message.json` or a kept `message.v<N>.json`); the item view, its title and the download use it | an email received again with a changed content does not change what an earlier run shows; if that version is gone, the view says so and shows no other text | `tests/test_audit_fixes_1002.py` |
| export formula protection | `jav/export.py` `_safe_text()` (CSV: prefixed with `'`), `_write_sheet()` (Excel: text stored with `data_type="s"`); `jav/datasets.py` `export_file()` uses the same | `configs/reports.json` `export.formula_prefixes` | `tests/test_reports.py::test_csv_guards_formulas_but_keeps_numbers`, `tests/test_datasets.py::test_export_guards_formulas` |

**Emails:**

| Protection | Code | Setting | Test |
|---|---|---|---|
| email receiver | `jav/ingest_server.py`: `_authorized()` (`Authorization: Bearer`, `hmac.compare_digest`), `_from_browser()`, `_read()` (`Content-Length` required, `MAX_BODY_BYTES` = 2 MB), `validate_payload()`, `safe_mailbox_dir()`, `host_path()`; `make_server()` binds only to `127.0.0.1` | `JAV_INGEST_TOKEN` or `--token`, otherwise `secrets.token_urlsafe(24)` | `tests/test_ingest_security.py` |
| mailbox download | `jav/mailbox.py` `fetch()`: one-time key, temporary receiver on a free port; `MailboxRequest` (`_ACCOUNT`, `_FOLDER` patterns, `extra="forbid"`) | – | `tests/test_mailbox.py` |

**GitHub and backup:**

| Protection | Code | Setting | Test |
|---|---|---|---|
| data guard | `jav/data_guard.py`, `scripts/githooks/pre-commit`, `scripts/githooks/pre-push`; enabling: `python -m jav.cli hooks-install` (`core.hooksPath`); whole tree: `python -m jav.cli data-guard [--all]` | `configs/data_guard.json`: `forbidden_history`, `blocked_paths`, `blocked_extensions`, `allow`, `known`, `deny` | `tests/test_data_guard_071.py` |
| internal working documents | `jav/doc_scope.py` (`INTERNAL_DOC_PATTERNS`), `.gitignore` | – | `tests/test_doc_scope_070.py`, `tests/test_doc_links.py` |
| backup | `jav/backup.py` (`Connection.backup`, `PRAGMA integrity_check`, the copy verified by content hash; `internal-docs.zip`; `_sync_sources`: every saved source instance checked by its content hash, a damaged one repaired; every instance the saved database refers to must be intact in the backup, or the backup fails) | `backup`: `keep` 14, `with_burr` false, `with_docs` true, `copy_to` | `tests/test_ops_064.py`, `tests/test_backup_docs_070.py` |

**Data locations** (section 7): store `store/jav.sqlite`; flow-state store `store/burr_state.sqlite`; backups `store/backups/`; raw runs `runs/`; JEV cache `runs/cache/`; OCR cache `runs/ocr/`; service log `runs/logs/` (`jav/runtime/applog.py`: `MAX_BYTES` 5 000 000, `BACKUPS` 5); emails `inbox/`, attachments `inbox/.bridge/data/`; keys `.env`; Burr's tracker `~/.burr` (the library's default; the worker runs with `tracker=False`).

**Injection probes** (section 5):
- Documents: `python -m jav.experiments.document_injection_probe --live`, `configs/experiments/document_injection.json` 1.0.0. The S path's JEV request is narrowed to ±1 line around the candidates, so it sees the sentence below the heading only partly; the G path gets the full text. Offline parts: `tests/test_document_injection_probe.py`.
- Emails: `python -m jav.cli email-injection-probe` (`jav/evals_email.py` `INJECTIONS`: `clean`, `en_override_top`, `hu_override_top`, `hu_reroute_top`, `en_override_end`); call site: `configs/callsites/email_intent.json` 1.1.0.

**Dependency audit** ([development guide, section 6](guides/DEVELOPMENT.md)): `python -m jav.cli deps-audit` (`jav/deps_audit.py`: `pip-audit -r requirements.lock --no-deps` and `npm audit --json` in `ui/`; result in `runs/deps-audit.json`; refreshed by `backup --scheduled` when older than 7 days; `GET /api/system/deps-audit`). GitHub's vulnerability alerts are the repository's Dependabot alerts (on since 2026-09-30); automatic fix pull requests are not enabled.
