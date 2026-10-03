# Changelog

Releases in brief, newest first. Release rules: [development guide §1](docs/guides/DEVELOPMENT.md).

**Tags:** the repository's first tag is `v1.0.5`; the earlier releases are listed here without a tag.

## Plain-language summary

This list shows what each release brought. `v1.0.0` was the first stable version: work packages, recipes, review on the document's page image, results and approval. The `v1.0.1`–`v1.0.4` fix rounds corrected problems found in daily use and in reviews; the most important of them was the tax-number check. `v1.0.5` is a security round: no personal data can reach GitHub, the browser does not store document data, and you can see which code is running. `v1.1.0` is a second security round after a repeated audit: paid calls, Azure recognition included, stay within a real, reserved upper bound, the documents shown for review are verified, and the repository's documentation is in English. `v1.1.1` cleans the public documents of internal information, keeps machine-specific values out of the repository, and settles uncertain paid calls in the UI. `v1.1.2` adds copies of the processed documents under uniform, content-based names, reads PDFs in an isolated helper process, and no longer lets an unreadable email attachment fail the whole email. `v1.2.0` keeps an unchanging copy of every document added to a work package and works from it, and replaces the choice of recipe with one processing that recognises each item's type itself, with a few processing settings and an overview of the paid services before the start. `v1.3.0` takes a folder's subfolders on request, lets every path be chosen in the Windows picker, and reads every amount and quantity whole by one shared rule, so "28,000" or "28.000" is never read as 28. `v1.4.0` can list documents under their unified, content-based names, shows what each item, run and work package cost, and makes review faster: a tick and a cross next to every field, keyboard navigation, and a readable highlight for a value over several lines. `v1.5.0` reads dates in every common form by one shared rule (month names in six languages, two-digit years, and a to-do instead of a guess when the order of day and month is undecided), and closes the findings of a second security re-audit: an approval covers exactly the result the approver saw, the backup checks and repairs its source copies, a document over the size limit fills no disk, and a paid call without an answer is never repeated by itself.

## v1.6.0 — 2026-10-03

Processing without JEV, reusable GPT answers, field confidence and stronger protection of reviewed results.

- **Processing without JEV:** GPT can recognise document types and email intents and extract document fields;
  source matching and deterministic checks still apply. One processing-path selector covers automatic selection,
  JEV where supported, GPT with JEV, and GPT without JEV. A missing JEV key creates a review to-do instead of failing
  the item. A code cross-check flags contradictions in GPT's document classification.
- **Reusable GPT answers:** an earlier answer can be reused when the model, instructions, schema and input match.
  The processing settings make reuse explicit for both providers; reused answers incur no new provider charge.
- **Field confidence and review:** GPT fields carry their own confidence indication without JEV. Below the configured
  threshold, scored non-informational fields and high-stakes fields require review. Confidence is a model signal,
  not proof that a value is correct. Failed field checks now identify the affected field.
- **Source highlights:** shared matching rules handle multi-line and rearranged addresses, identifiers printed beside
  labels, and currency or country representations. The code-only source check uses the same rules; recomputing a
  highlight preserves the basis of the field's GPT confidence. GPT unit prices may retain four decimal places.
- **Approval and email history:** approval uses the version of the rows actually displayed; a conflict reloads the
  result before approval can be retried. Email task decisions belong to that version and cannot change after approval.
  Historical email results and downloads use the exact source version processed, or report that it is missing.
- **Edits, backups and paid calls:** edits made while a save is pending are preserved. A backup fails visibly when a
  referenced source is missing and retains earlier copies. Only uncertain calls can be settled manually, and a worker
  restart takes over reservations only from processes that have stopped; late answers cannot overwrite a settlement.
- **Operation and diagnostics:** the service and worker load their code at start; the browser asks for a reload when
  the running version or UI build changes. Full checks retain raw pytest output and JUnit results, and the security
  documentation describes the document copies included in backups.

The PDF memory-limit status and strict mode, further document-instruction hardening, and business duplicate and
reconciliation workflows remain future work. This release does not claim that all security work is complete.

## v1.5.0 — 2026-10-01

Dates in every common form, read by one shared rule, and the fixes of the second security re-audit.

- **Fixes from the second security re-audit:**
  - **Approval:** a correction can no longer be written after a concurrent approval (the writing transaction checks
    the approval again), and the approval names the version of the result the approver saw: a correction saved
    meanwhile, for example in another tab, makes it fail (409) until the new state has been looked at.
  - **Backup:** a saved source copy is checked by its content hash on every backup, not only by its size; a damaged
    copy is replaced from the intact source, and if none is left, the backup fails visibly.
  - **Intake:** a document over the input limit is not copied into the store (the size is checked first and the copy
    stops at the limit); it is still added, and processing stops it with the named size error.
  - **Paid calls:** a call that was sent but got no answer (a timeout or a broken connection after sending) is now
    uncertain instead of failed: its maximum cost stays reserved, it is not repeated automatically, and it appears on
    the System page to be settled by hand. A restart that closes a call from its saved answer keeps the stop on further
    calls when that answer cost more than its reservation.
  - **System page:** the list of uncertain calls shows *Loading…* until it has loaded, and only the error if loading
    failed, instead of saying there is none.
- **Dates in every common form:** one date reader (`jav/dates.py`) for every path — the S path's candidates on every
  candidate profile, the value JEV chooses, GPT's values, the JEV check's value search, a selection on the page image
  and a manual correction. It reads year-first dates, month names and abbreviations in Hungarian, English, German,
  French, Spanish and Italian (any letter case, with or without accents, ordinal endings, "04-DEC-22",
  "4 de diciembre de 2022"), two-digit years by a fixed rule, and ignores a time or weekday beside the date; a
  four-digit year is 1900–2099. In an all-number date a number above 12 decides the order of day and month, then the
  document's own dates; a dot date is day first. A slash date, or an all-number date with a two-digit year (it may be
  the Hungarian short form with the year first), that nothing decides becomes the to-do **Uncertain order of day and
  month** instead of a silent guess (on Hungarian and utility documents an all-number two-digit-year date is a
  candidate only when the document's own dates decide it, as such text there is mostly a code) (`date:order_ambiguous`; the JEV option text does not change). A typed date is
  taken in every unambiguous form and stored as YYYY-MM-DD; an ambiguous one is refused (422 `ambiguous_date`) with a
  hint to type the year first; the save message reads the stored date back. The two Hungarian date patterns of the type
  recognition request stay unchanged, so recognition requests do not change; the S path's date candidates change on the
  documents that print the newly read forms.

## v1.4.0 — 2026-10-01

Unified names in the item lists, a cost view, and a faster review with a tick and a cross next to every field.

- **Unified names in the item lists:** the package's documents, the items of a run and the item list of Review can
  show each document under its unified, content-based file name (the one of the File names view) instead of its
  original name. A **Name:** switch above each list chooses Original or Unified (remembered per person in the browser;
  Unified by default). A document gets its unified name once a run has processed it (in the package's list, from its
  latest run that did); until then the original name stays, with a note. An uncertain name (one whose copy would go
  to the review folder) carries a ⚠ mark with the reason, and the tooltip gives the original name. The service
  delivers the chosen name, so searching, sorting, filtering and downloads follow it; **Unified name**, **Original
  name** and **Unified name status** can be added as columns. Datasets `workpackage_items` and `run_items` take the
  optional scope `names` (`original` / `unified`), and `GET /api/runs/{id}?names=unified` adds the items' names for the
  review queue. No paid calls; the model requests do not change.
- **Cost view:** the processing cost per item, run and work package, per provider and model, read from the call log
  and the ledger (nothing is stored twice). A run's items get one cost column per provider and model it called, a
  total, and the count of questions answered free from earlier answers; the package's runs table gets each run's cost;
  the new **Cost of the work package** table adds up every run per provider and model. On the run's page, **Planned
  and actual** shows per provider what the pre-start overview expected next to the actual calls, cost and models, and
  warns when a provider was called against the overview (the overview is now saved with the run: `runs.plan`). A call
  whose cost is not known (a failed or interrupted attempt) is no longer mistaken for a cost: its reserved amount is
  shown apart. Text taken from an earlier Azure recognition is now written to the ledger at 0 USD, so it counts among
  the answers reused from earlier. The budget bars name the providers. Dataset `package_costs`; `GET /api/runs/{id}`
  carries `costs`. No paid calls; the model requests do not change.
- **Fix — a stopped run could stay "running":** a stop cancelled the queued jobs one by one; if the worker noticed the
  stop request on the running item at once, it finished that item and refreshed the run while queued jobs were still
  left, so the run stayed "running" after every job had ended (and in that window the worker could even start the next
  queued item). A running item that failed after a stop also went back to the queue, where a stopped job is never
  claimed again. Now a stop cancels the queued jobs and asks the running one to stop in one transaction, and a job that
  fails or is released after a stop request is cancelled, so the run ends as stopped without a manual refresh.
- **The run's total cost first:** the run's page now opens its cost part with **Cost of the run**, the actual cost over
  every provider, followed by each provider's paid calls, cost and models and the number of questions answered from
  earlier answers. **Planned and actual** sets each provider's plan against its actual cost. The budget bars moved into
  a closed **Budget** part whose title gives each provider's share used; it opens by itself when a budget is at least
  80% used or the budget stopped something in the run. The run view's `costs` carries `total` (cost, paid calls, failed
  calls, reserved amount, reused answers). No paid calls; the model requests do not change.
- **Tick and cross next to each field in Review:** every simple field has ✓ (correct) and ✗ (wrong, fix it) right
  next to its value, and a field's to-dos are shown at the field; only the to-dos about the whole document stay at the
  top with **Resolved**. ✓ saves that field only, records that a person verified it (the field shows **verified** until
  its value changes) and closes the field's to-dos in the run; with an empty box it records that the document has no
  value. ✗ empties the field, puts the cursor in it and turns on selecting on the image; ↺ brings the original value
  back. A filter above the fields shows **To fix**, **Uncertain** or **All**, with counts. An earlier run's to-do on a
  field is shown at the field ("from an earlier run", merged when several runs left the same one) and the field's ✓
  closes it too; the earlier to-dos about the whole document sit closed at the bottom of the panel. Selecting on the
  image is always on (the toggle and the s key are gone). Keyboard: the cursor opens in the first field with its value
  selected; Tab / ↓ and Shift+Tab / ↑ move between the fields, Enter is the tick and goes on (after the last field to
  the next item with to-dos), Esc brings back the original value, PageDown / PageUp switch items. Previous / next item
  buttons sit at the top of the panel. The correction save takes
  `confirm` (the fields verified) and the version records `confirmed` (field → value); each to-do of a document item
  carries `field`. No paid calls; the model requests do not change.
- **Fix — a value over several lines was unreadable on the image:** each line of the field being checked got its own
  thick frame with a white ring, drawn over the neighbouring lines, and the other candidates' boxes and tags covered the
  same text. The value is now highlighted line by line like a see-through marker, inside one thin frame outside the text;
  a candidate within the value shows only its tag, and tags sit beside their box. A long candidate button in the panel
  wraps instead of running out of it.
- **The S path says what it does:** the path once called "JEV only" is now **JEV where possible — cheaper, no line
  items; GPT elsewhere (S)**. Behaviour is unchanged: a document type without a JEV path (fifteen types, for example
  NAV receipts and bank statements) runs on the G path with S chosen too, so that its data is still read. The help,
  the comparison of the paths and the user guide say so, and the pre-start overview names how many documents go to
  GPT because their type has no JEV path. Config `recipe_help.json` 1.3.0 (help text only; no model request changes).

## v1.3.0 — 2026-10-01

Subfolders and folder browsing, and one safe number reader for every path.

- **Subfolders and folder browsing:** a new package from a folder can take the PDFs of its subfolders too
  (‘Include subfolders’, off by default, as for watched folders); the output folder of the named copies is then left
  out, and a document in a subfolder is shown with its path below the folder. Every path field (the package's folder
  and files, a watched folder, the output folder) has a **Browse…** button that opens the Windows folder or file
  picker through the local service; several files can be chosen at once, and a path can still be typed. Command line:
  `wp-create <folder> --recursive`. Settings: `configs/service.json` `picker`. The model requests do not change.
- **Safe number reading:** one number reader (`jav/numbers.py`) for every path. An invoice printed in English notation
  ("28,000.00") was read as net 28 / VAT 7.56 / gross 35.56 on the S path, without a to-do, because the Hungarian
  candidate pattern cut "28,000" to "28,00" and the three wrong values still added up. Now a number is never cut
  apart, money never has three decimals ("28.000" and "28,000" are 28 000), a quantity follows the document's own
  notation and is flagged when that is unknown, and a value GPT copied in the document's notation is read the same
  way. On foreign invoices a candidate is no longer read together with its neighbouring number ("€11.99 1 pc" gave
  11.991). A safety check gives a to-do when a picked value is only a piece of a longer printed number. Manual
  corrections are shown and typed the Hungarian way ("35,56"; "28.000" = 28 000), an ambiguous form is refused, and
  the saved value is named in the message. The changed candidates change the S path's JEV requests on the documents
  concerned.

## v1.2.0 — 2026-10-01

Source instances and one processing with processing settings; the model requests do not change.

- **Source instances:** when a document is added to a work package, the system keeps an unchanging copy of it
  (`store/sources/`, one copy per content), and processing, the review page image, the source view and the named
  copies work from that copy. What a person checks is therefore exactly what the result was made from, even if the
  original file is later edited, moved or deleted; a changed or missing original is a warning instead of a blocker,
  and the review view says so. The copies go into the daily backup once each, locally and in the second location.
  Documents added before this change keep working from their original file. The model requests do not change.
  The email flow's own recognition of a PDF attachment reads the same kept copy as the attachment's document item.
- **One processing with processing settings:** there is no recipe to choose any more. One processing handles every
  item by its kind: a PDF document gets type recognition and then the recognised type's extraction, an email gets
  intent recognition and its PDF attachments are processed as documents. The type is never given in advance in the
  interface (the internal recipe with a given type remains for tests and command-line measurement). The package's
  **Processing settings** card shows the path, Azure recognition, reuse of earlier JEV answers and task proposals with
  their meaning; a package without saved settings runs with the default ones, saved when the run starts. The path
  options have descriptive names (‘Automatic (recommended)’, ‘JEV only — no line items, cheaper (S)’, ‘GPT + JEV —
  with line items (G)’), and Settings › **Processing** (formerly Recipes) compares the two paths with the measured
  agreement with the golden set and the typical cost per document. Before a run, **What happens when the run starts**
  lists each service the run may call with its budget and what it is for, and names the services that will not be
  called. Existing packages and watched folders move onto the processing with `python -m jav.cli processing-migrate
  --write`, keeping their settings; old runs keep their own recipe. The model requests do not change.

## v1.1.2 — 2026-09-30

Content-based file names, isolated PDF reading and a fix for unreadable email attachments; the UI code comments are in
English.

- **Isolated PDF reading (2026-09-30):** the PDF parsers (the text layer, the page images for OCR, the page sizes and
  the page images for review) run in a separate helper process with a time limit per request and a memory limit, so
  a broken or hostile PDF cannot hang the worker or the local service. Over a limit, text extraction stops the item
  with a named error and without a retry, the OCR page images give a to-do, and a review page image is refused; the
  next document gets a new helper. A document over an input limit is no longer retried either. Settings:
  `configs/service.json` `pdf_reader`.
- **UI code comments in English (2026-09-30):** every comment in the UI sources (TypeScript, CSS, the i18n checker)
  and the UI package description are now in British English; a machine comparison confirms that no code changed.
  The UI's own texts are unchanged.
- **Content-based file names (2026-09-30):** a run's documents can be copied under uniform names built from their
  content, date first and without accents (for example `2026-09-12_SZAMLA_Minta-Kft_SZ-2026-001234.pdf`); the
  originals are never changed. The name comes from the corrected data, with no AI call; a copy whose name rests on an
  open to-do, an empty field or an unknown type goes into the `ellenorzendo` (to review) subfolder. New: the **File
  names** view in the Result section with a ZIP download and writing to an output folder (a new
  subfolder each time, nothing overwritten), the output folder in Settings › Work folders (never overlapping a watched
  folder), a manifest (`jegyzek.csv`) and `python -m jav.cli run-names`. Rules: `configs/naming.json`.
- **Unreadable email attachments (2026-09-30):** a corrupt or over-limit PDF attachment no longer fails the whole
  email: the attachment is marked as unreadable, the email gets a to-do (`attachment:unreadable`), and the intent is
  still recognised. Any other error still fails the item.

## v1.1.1 — 2026-09-30

Fix round: public documents without internal information, fixes from the repeated audit's acceptance conditions, and
settling uncertain paid calls in the UI.

- **Public documents (2026-09-30):** every document in the repository now describes the system, not the development
  process: no references to internal working documents, no internal round or stage codes, no figures from real use,
  no details of the machine it was developed on. The README's capability table is rewritten by area, and a test keeps
  the documents this way.
- **No machine-specific values in tracked files (2026-09-30):**
  - the second location of the daily backup comes from `JAV_BACKUP_COPY_TO` in `.env` (see `.env.example`);
  - the legacy project defaults to the `10_AIFLOW_V4` folder next to the repository (`JAV_LEGACY_ROOT` overrides it);
  - the OCR cache key covers only the settings that can change the recognised text, so moving a folder or editing a
    note no longer makes every scanned document go through OCR again; `python -m jav.cli ocr-rekey --from-rev <rev>`
    moves an existing cache to the new key once, and refuses if the older settings read differently.
- **Cut candidate lists (2026-09-30):** when a field had more candidates than could be offered to JEV (above 250, or
  trimmed to fit the request size) and JEV answered "none", the document gets a to-do, because the right value may have
  been among the skipped ones. The found and sent candidate counts are recorded.
- **Email receiver time limits (2026-09-30):** every read waits at most 30 seconds and the whole message must arrive
  within 60 seconds, so a slow client cannot hold a connection open.
- **Uncertain paid calls on the System page (2026-09-30):** a paid call interrupted mid-way keeps its maximum cost
  reserved and blocks its step until a person settles it. The System page lists these calls and settles one with the
  actual cost (or none) and a note, as `calls-resolve` does on the command line.
- **Smaller fixes:** the state snapshot skips a golden run in which every case failed and names it, instead of showing
  "no cases"; the invented bank account numbers of the injection probe pass the domestic check digits too.

## v1.1.0 — 2026-09-30

Second security round after a repeated audit, and the repository in English.

- **UI fixes (2026-09-30):**
  - To-dos raised by task proposals are shown as a readable sentence instead of a raw code.
  - Known Outlook errors are now shown in the UI language in the download log and in the schedules' "Last" column as well, not only in the preview; other errors are shown unchanged.
  - The Recipes settings page has an English label.
  - Deleting a mailbox schedule, removing an item from a package and removing a user now ask for a second click to confirm, as approving and stopping already did.
- **Security fixes after the repeated audit (2026-09-30):**
  - The JEV SDK is upgraded to 0.7.2, which validates the API key early and keeps it out of logged exceptions.
  - The service and worker logs, and the error text stored for a failed item, mask every key, token and password from the environment, including in the exception chain.
  - A dependency audit checks the pinned Python and UI packages for known vulnerabilities once a week, with the daily backup, or by hand (`python -m jav.cli deps-audit`). The System page shows its date and result, and the start-up check fails on a known vulnerability.
- **Bank account check (2026-09-30):** a Hungarian domestic account number, and the account inside a Hungarian IBAN, is accepted only when both of its check digits are right; before, any 16 or 24 digits passed. A wrong number now raises a to-do. The data guard uses the same rule.
- **Data guard and renames (2026-09-30):** before a commit, a renamed or copied file is now checked in full under its new name; before, a pure rename had no new line to check (the push check already caught it).
- **Source identity (2026-09-30):** the source document and its page images are served only after a full content check on every request, from exactly the checked bytes. Before, a file changed in place with the same size and date could be shown under the original item.
- **Cost reservation is a real upper bound (2026-09-30):** before a paid call the system now reserves at most one token per byte of everything it sends (instructions and output schema too), a fixed overhead and every possible retry, rounded up. Before, it assumed two characters per token, which is not a bound. Reservations are larger, while actual spending does not change. The per-item OpenAI budget of the recipes rises from 0.10 to 0.15 USD accordingly, so a single-document run on the G path still fits. The OpenAI client no longer retries on its own (the work queue repeats a failed item). If a call still costs more than its reservation, the run makes no further call with that provider.
- **Azure recognition as a recipe switch (2026-09-30):** Azure recognition of weak scans used to be called outside the run's budget and the call log. Now every recipe has an Azure recognition switch (on by default, 0.02 USD per document, about 13 pages at the list price); the pages are reserved from the run's Azure budget before the call, every call goes into the call log, and if the budget runs out the local text goes on with a to-do. With the switch off, Azure is never called in that run.
- **English repository:** the repository's documentation, code comments and commit messages are switching to English. Hungarian document vocabulary (the wording on Hungarian invoices that the code and the models match against) stays as it is.

## v1.0.5 — 2026-09-30

Security fix round.

- **Internal working documents are not in git.** They stay local, and the daily backup carries them. Codebase documents do not link to them, and a test checks this.
- **Data guard before commit and push.** It stops the commit or push if the lines going into git contain a real-looking tax number, bank account number, email address, phone number or key. It also stops it if an internal working document, a document file, an image, a database or a binary file would go into git, or if a push would build on a history listed as forbidden in its settings. Enable it once per clone: `python -m jav.cli hooks-install`.
- **Browser security headers on every response.**
  - The UI loads only its own files and cannot be embedded in another page.
  - The browser does not store document data (page images included) on its disk.
  - The clickable endpoint list is switched off, because it would load program code from an external host. The machine-readable endpoint list stays (`/api/openapi.json`).
- **A single version.** The version has one source, the project file. The System page and the health endpoint show the running version and the commit the service was started from.
- **Documentation:**
  - new: [security notes](docs/SECURITY.md), [user guide](docs/guides/USER_GUIDE.md), [configuration files guide](docs/guides/CONFIGS.md) and this changelog;
  - the README, the architecture description, the setup guide and the glossary were reviewed.

## v1.0.4 — 2026-09-29

The four points of the independent review that needed a decision.

- **Tax-number check:**
  - Tax numbers are checked against recognised formats (Hungarian domestic, Hungarian EU (community) VAT, other EU and a few common non-EU formats), for both parties and on foreign invoices too.
  - The label is stripped.
  - A phone number or a value with a wrong check digit gets a to-do.
- **Field without candidates:** a "No estimate" flag and a presence question, instead of 100%.
- **Lost glyph:** a damaged currency sign no longer turns into a negative amount.
- **Document without a type pack:** a recognised type that has no type pack gets a to-do.

## v1.0.3 — 2026-09-29

Checks, and the remaining points of the technical review (`v1.0.2`) that needed no decision.

- Input limits: file size, page count, page-image pixel count.
- The browser origin must match exactly: other local ports cannot call the service.
- Dependency-vulnerability and coverage checks, property-based tests.
- A probe for instructions hidden in documents, run on synthetic invoices.

## v1.0.2 — 2026-09-29

Fixes from an in-depth technical review.

- Approval gaps closed.
- Test data replaced with invented values of the same shape.
- The email receiver accepts requests only with a key and rejects requests that come from a browser.
- Stopping also requires the user's name.

## v1.0.1 — 2026-09-29

Fixes from the first trial in daily use.

- The candidate finder was extended: lost glyph, invoice number below the heading, receipt ID, credit note, OSS and Dutch tax numbers.
- A new package's owner is its creator.
- Cost is reserved according to the path actually taken.
- The mailbox counter shows new emails and emails in the period separately.
- An email's attachment to-do belongs to the run.

## v1.0.0 — 2026-09-29

The first stable version.

- **Work packages and recipes:** document recognition and data extraction, invoice data extraction, email intent recognition. Trial and live runs, a durable job queue, a cost budget, approval.
- **Review on the document's page image:** boxed fields, alternative candidates, selection on the image; to-dos by reason.
- **Result:**
  - a shared table with search, filtering and sorting;
  - download to Excel, CSV and JSON;
  - a utility-cost report;
  - invoice line items.
- **Mailbox and watched folders:** download from the Outlook running on the machine, on a schedule too; task proposals from emails (off by default; only a person can accept them).
- **UI:** Hungarian and English, light and dark themes, recipe explanations.
- **Operational foundations:** a persistent log, a daily database backup locally and to the second backup location, thinning of the flow-state store.
