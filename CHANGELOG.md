# Changelog

Releases in brief, newest first. Release rules: [development guide §1](docs/guides/DEVELOPMENT.md).

**Tags:** the repository's first tag is `v1.0.5`; the earlier releases are listed here without a tag.

## Plain-language summary

This list shows what each release brought. `v1.0.0` was the first stable version: work packages, recipes, review on the document's page image, results and approval. The `v1.0.1`–`v1.0.4` fix rounds corrected problems found in daily use and in reviews; the most important of them was the tax-number check. `v1.0.5` is a security round: no personal data can reach GitHub, the browser does not store document data, and you can see which code is running. `v1.1.0` is a second security round after a repeated audit: paid calls, Azure recognition included, stay within a real, reserved upper bound, the documents shown for review are verified, and the repository's documentation is in English. `v1.1.1` cleans the public documents of internal information, keeps machine-specific values out of the repository, and settles uncertain paid calls in the UI. `v1.1.2` adds copies of the processed documents under uniform, content-based names, reads PDFs in an isolated helper process, and no longer lets an unreadable email attachment fail the whole email.

## Unreleased

- **Source instances:** when a document is added to a work package, the system keeps an unchanging copy of it
  (`store/sources/`, one copy per content), and processing, the review page image, the source view and the named
  copies work from that copy. What a person checks is therefore exactly what the result was made from, even if the
  original file is later edited, moved or deleted; a changed or missing original is a warning instead of a blocker,
  and the review view says so. The copies go into the daily backup once each, locally and in the second location.
  Documents added before this change keep working from their original file. The model requests do not change.
  The email flow's own recognition of a PDF attachment reads the same kept copy as the attachment's document item.

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
