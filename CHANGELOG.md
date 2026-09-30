# Changelog

Releases in brief, newest first. The detailed release notes and measurement evidence are internal working documents and are not in the repository. Release rules: [development guide §1](docs/guides/DEVELOPMENT.md).

**About the GitHub history:** the repository's history starts with a new root commit on 2026-09-30, which holds the code as it stood after `v1.0.4`. The `v1.0.0`–`v1.0.4` tags sit on the older history, which is kept only locally. On the new line, `v1.0.5` is the first tag.

## Plain-language summary

This list shows what each release brought. `v1.0.0` was the first version the owner marked as stable: work packages, recipes, review on the document's page image, results and approval. The `v1.0.1`–`v1.0.4` fix rounds corrected problems found in real trials and reviews; the most important of them was the tax-number check. `v1.0.5` is a security round: no personal data can reach GitHub, the browser does not store document data, and you can see which code is running.

## Unreleased

- **UI fixes (2026-09-30):**
  - To-dos raised by task proposals are shown as a readable sentence instead of a raw code.
  - Known Outlook errors are now shown in the UI language in the download log and in the schedules' "Last" column as well, not only in the preview; other errors are shown unchanged.
  - The Recipes settings page has an English label.
  - Deleting a mailbox schedule, removing an item from a package and removing a user now ask for a second click to confirm, as approving and stopping already did.
- **Security fixes after the repeated audit (2026-09-30):**
  - The JEV SDK is upgraded to 0.7.2, which validates the API key early and keeps it out of logged exceptions.
  - The service and worker logs, and the error text stored for a failed item, mask every key, token and password from the environment, including in the exception chain.
  - A dependency audit checks the pinned Python and UI packages for known vulnerabilities once a week, with the daily backup, or by hand (`python -m jav.cli deps-audit`). The System page shows its date and result, and the start-up check fails on a known vulnerability.
- **Bank account check (2026-09-30):** a Hungarian domestic account number, and the account inside a Hungarian IBAN, is accepted only when both of its check digits are right; before, any 16 or 24 digits passed. A wrong number now raises a to-do. The data guard uses the same rule. Of 507 bank accounts extracted so far, 506 pass; the golden sets are unchanged.
- **Data guard and renames (2026-09-30):** before a commit, a renamed or copied file is now checked in full under its new name; before, a pure rename had no new line to check (the push check already caught it).
- **Source identity (2026-09-30):** the source document and its page images are served only after a full content check on every request, from exactly the checked bytes. Before, a file changed in place with the same size and date could be shown under the original item.
- **English repository:** the repository's documentation, code comments and commit messages are switching to English. Hungarian document vocabulary (the wording on Hungarian invoices that the code and the models match against) stays as it is.

## v1.0.5 — 2026-09-30

Security fix round; free, with no paid calls.

- **Internal working documents are not in git.** Git does not track the handoffs, plans, reports, backlog or decisions log; the daily backup carries them, both locally and to the second backup location. Codebase documents do not link to them, and a test checks this.
- **Data guard before commit and push.** It stops the commit or push if the lines going into git contain a real-looking tax number, bank account number, email address, phone number or key. It also stops it if an internal working document, a document file, an image, a database or a binary file would go into git, or if the old history would be pushed. Enable it once per clone: `python -m jav.cli hooks-install`.
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

Checks, and the remaining points of the 066 review that needed no decision.

- Input limits: file size, page count, page-image pixel count.
- The browser origin must match exactly: other local ports cannot call the service.
- Dependency-vulnerability and coverage checks, property-based tests.
- A probe for instructions hidden in documents, on synthetic invoices: the injected instruction did not steer the result.

## v1.0.2 — 2026-09-29

Fixes from an in-depth technical review.

- Approval gaps closed.
- Real data left in the tests replaced with invented values of the same shape.
- The email receiver accepts requests only with a key and rejects requests that come from a browser.
- Stopping also requires the user's name.

## v1.0.1 — 2026-09-29

Joint trial on real work.

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
