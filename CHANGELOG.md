# Changelog

Releases in brief, newest first. Release rules: [development guide §1](docs/guides/DEVELOPMENT.md).

**Tags:** the repository's first tag is `v1.0.5`; the earlier releases are listed here without a tag.

## Plain-language summary

This list shows what each release brought. `v1.0.0` was the first stable version: work packages, recipes, review on the document's page image, results and approval. The `v1.0.1`–`v1.0.4` fix rounds corrected problems found in daily use and in reviews; the most important of them was the tax-number check. `v1.0.5` is a security round: no personal data can reach GitHub, the browser does not store document data, and you can see which code is running. `v1.1.0` is a second security round after a repeated audit: paid calls, Azure recognition included, stay within a real, reserved upper bound, the documents shown for review are verified, and the repository's documentation is in English. `v1.1.1` cleans the public documents of internal information, keeps machine-specific values out of the repository, and settles uncertain paid calls in the UI. `v1.1.2` adds copies of the processed documents under uniform, content-based names, reads PDFs in an isolated helper process, and no longer lets an unreadable email attachment fail the whole email. `v1.2.0` keeps an unchanging copy of every document added to a work package and works from it, and replaces the choice of recipe with one processing that recognises each item's type itself, with a few processing settings and an overview of the paid services before the start. `v1.3.0` takes a folder's subfolders on request, lets every path be chosen in the Windows picker, and reads every amount and quantity whole by one shared rule, so "28,000" or "28.000" is never read as 28. `v1.4.0` can list documents under their unified, content-based names, shows what each item, run and work package cost, and makes review faster: a tick and a cross next to every field, keyboard navigation, and a readable highlight for a value over several lines. `v1.5.0` reads dates in every common form by one shared rule (month names in six languages, two-digit years, and a to-do instead of a guess when the order of day and month is undecided), and closes the findings of a second security re-audit: an approval covers exactly the result the approver saw, the backup checks and repairs its source copies, a document over the size limit fills no disk, and a paid call without an answer is never repeated by itself. `v1.6.0` can process documents and emails with GPT alone, without JEV, reuses earlier GPT answers, and shows how sure GPT is of each field. `v1.7.0` reads Word, Excel, text and CSV files, proposes source-bound facts for PDFs of an unknown type too, opens to-dos for content errors that used to pass silently, and calls Azure recognition directly for documents in any folder. `v1.8.0` recognises pro forma invoices and receipts from foreign providers, checks a narrower document type before taking it, reads digitally signed PDFs, flags a party pair standing the other way round, gives GPT extraction a shared instruction that treats document text as data, and keeps the valid facts when a single fact of an unknown document is malformed. `v1.8.1` updates two dependencies for security advisories published after the previous audit. `v1.9.0` reads a scanned PDF of an unknown type from the Azure recognition the system already paid for, so its reading can be complete, and no longer pays again for an unchanged document after a change to the reader. `v1.10.0` flags the same invoice reaching the system twice, shows the two documents side by side, and lets a person decide whether it is a copy, a modified version or a different invoice; a copy stays marked and counts once. `v1.11.0` makes the JEV path more precise: every JEV question says that document text is data, not instructions, the questions no longer carry the operator's own company data, and the buyer, a credit note's own number, a receipt's identifier and a pro forma invoice are read more reliably; measurements get a hard JEV limit and a free cost estimate. `v1.12.0` proposes which bank statement line paid which incoming invoice, lets a person confirm or reject each proposal on the review page, and shows each run's invoices and statement lines with their payment state; it never calls an invoice unpaid. A party name now ends at its legal form, and GPT is asked again only when the text it is sent has changed. `v1.13.0` turns reconciliation into its own kind of work package: one own party's bank statements, read by code from the banks' exports and PDFs, are paired with its invoices on cards that show every fact of both sides, a person decides each pair, and the result is a summary that can be downloaded in Excel and approved as a locked version. `v1.14.0` chains the steps of a recurring job into a workflow that can be repeated for the next period, opens pairing with a quick review in groups, tells an own party's outgoing invoices from its incoming ones and pairs incoming money with them (in another currency too, at the official MNB rate), reads sent mail for its attachments only, and no longer lets a trial run's to-dos stand as work to do. `v1.15.0` lets a person supersede an older live run that a later one repeated and shows in the list where one waits, makes the package list answer at once, and brings the fixes of a four-way review: amounts and pairings in reconciliation, review and workflow behaviour, speed on large runs, and bounded reading of untrusted bank files. `v1.16.0` gives every screen one refined design — one accent for the main action, states as small marks in their own colours, the cost of every run on its button — treats a domestic account number and its IBAN as one, and opens the own-tax to-do on the invoices already in the store. `v1.17.0` asks the AI what kind of incoming money a bank line without an invoice is, and lists a customer's payment that has no outgoing invoice as an invoice to expect; the package list opens at once after a restart and no longer slows the service every two minutes, and the dependency audit says when Python is behind its latest patch. `v1.17.1` fixes the serious findings of a full code review: a pairing or a mark that lost its invoice or its line, a credit note settling the wrong month, an interrupted mailbox download or step start in a workflow, stopping a finished run, manual backups pushing out the daily ones, and a value found only in part counted as printed. `v1.18.0` makes GPT alone, without JEV, a choice everywhere: one AI engine setting for the application, a workflow step's own choice and `--engine` on every command; a JEV question is never asked in that mode, the AI engine of a result shows beside its approval, and measurements reuse earlier GPT answers and count the wrong answers that passed without a to-do. `v1.19.0` keeps a work package open after its first run: a document can be removed with a reason and restored, more documents can be added, and a run can take only the new ones, so the documents already processed are not paid for again. `v1.19.1` puts adding documents where they are looked for, shows the service's errors in the interface's language, and fixes the smaller findings of two code reviews. `v1.20.0` gives a work package one current result and one Approve and release, whose released versions keep their downloads unchanged, and lists a package's items, a reconciliation's inputs too, in one place. `v1.21.0` makes the reconciliation, the duplicate search and the bank statements read the same result the package shows, and fixes the reconciliation's remaining review findings. `v1.22.0` shows a person's duplicate decisions, statement choices and own workflow steps in "My work today", and describes the checks, the activities and the two kinds of work package that do work of their own in one place each, without a visible change. `v1.22.1` gives every to-do a sentence instead of its raw code (twelve kinds, among them JEV's checks of an extracted value, showed the code) and names a watched folder's package as made from that folder. `v1.23.0` lets a person make the Excel downloads from their own templates — a package's workbook, the reconciliation statement and a new utility-cost workbook — uploaded and checked in Settings and chosen beside each download, and stores an approved reconciliation statement's file instead of rebuilding it. `v1.24.0` routes the invoices, outgoing invoices and bank statements that arrive by email to the work package of their own party, period and role, on a person's acceptance, and lets a workflow ask only for the party and the period its steps need. `v1.24.1` makes a released package's stage bar say its release state after a trial run, and lets the start-up check run on a fresh store. `v1.24.2` fixes what the first real trial of the email routing showed: an attachment that was read but left no data is placed by its recognised type instead of being reported as not processed, and an incoming invoice found in a sent email is proposed with a note. `v1.24.3` keeps the rows of the facts table short and shows a mailbox package's source and the reason beside an uncertain unified name in the interface's language. `v1.25.0` moves what the finance and the email domain had written into the shared code into the domains' own modules, without a visible change, so a new kind of work is added in one place. `v1.26.0` keeps what every kind of work package belongs to in one shared place, and a reconciliation's approved statements as versions of the shared release, without a visible change. `v1.27.0` records every change of a person's decision, of any kind, in one decision journal, refuses a decision made on a page that is stale by now, and fixes three gaps the survey of the shared services found. `v1.28.0` measures every golden set — the data points of each document type, the type recognition, the email intent and the reconciliation's — with one command, free from earlier answers, and gives the record of a document's data a general name, without a visible change. `v1.28.1` updates three dependencies for security advisories published since. `v1.29.0` adds the quote as a third kind of work: a customer's quote request is read from an email's own text, an attached form or an attached list; the seller's price lists are kept with versions and discount rules; the system proposes a price-list item for each requested item, code prices the quote, and a person edits and approves it beside the request, starting it straight from the request's email if they like. `v1.30.0` makes an approved quote a Word document, from a built-in Hungarian or English template or from a person's own Word template with the same markers as the Excel ones, and drafts the reply letter: GPT writes a few sentences fitted to the request, never a number, the code checks them, a person accepts the letter and opens it in Outlook with the Word quote attached; the system never sends it. `v1.31.0` teaches a new document type from its documents' general facts, measures it on documents it has not seen, and turns a type on or off by command; the admission ticket is the first taught type in use. `v1.31.1` stops the false "not printed" to-do on every admission ticket's event time, lets a person supersede an older trial run's open to-dos, fixes two faults of the shared measurement, and updates a test tool for two security advisories. `v1.32.0` asks JEV by a fixed version, so its answers no longer change when the provider moves its "latest" name, says on the System page when a newer version is out, and no longer sends again a request JEV refused as too large. `v1.33.0` settles a failed paid call at its certain cost, makes large runs and their list quick, and tidies the code base: the experiments and the September learning branches are archived, without a visible change in the interface. `v1.34.0` puts every module of the code base into the folder of its layer, the instructions sent to the models among the settings and the email domain's tables into the domain, without a visible change. `v1.35.0` runs today's workflows on the new process core: every workflow is a case that keeps its history, the workflows made earlier carry on from where they stood, and a person's start is recorded in their name, without a visible change in the interface. `v1.36.0` keeps everything that waits for a person — a document's or an email's to-dos, a live run's approval, a reconciliation's or a quote's approval, a workflow step's budget — as a human task of the process core that says whose it is and who settled it, writes a person's decision together with the to-dos it settles, and lets a workflow go on right after an approval, without another visible change. `v1.37.0` shows what waits for the person working now: "Waiting for me" in the header counts their open live tasks, and its page lists the to-dos, approvals and budgets that wait for them or for anyone, each leading to where it is done. `v1.38.0` shows the rules the system decides by on a page of their own, records which rule of which version made each of its decisions and with what, and names the code and the rules every run was computed with. `v1.39.0` tries a proposed rule on the system's earlier decisions before it changes, keeps each field of work's rules in a file of its own, and keeps the versions and approvals of what a person edits with one shared code, without another visible change. `v1.39.1` updates two dependencies for security advisories published since. `v1.40.0` tidies the process core without another visible change: an approved reconciliation statement warns only when its content changed, the invoice states left half-done before `v1.28.0` load again, every decision reads its rule file when it applies, and a workflow step's state is kept in one place, in the process core. `v1.41.0` builds the structure the enterprise tools will be connected to, without a visible change: every operation of the local service names itself, knows who acts and asks the authorisation check; every decision, approval, correction and setting records who acted by a stable id beside the name; the process core keeps its own boundary; no lower layer of the code refers to a higher one; and the finance domain's part of the own parties is its own. `v1.42.0` runs the IT quote as the first process pack: a case of the process core built only from registered general capabilities, started from an email or the new work wizard, on a page that looks as the quote package's did, with the same results. `v1.43.0` lets the IT quote's case send the accepted letter — into the output folder, or as a draft in the person's Outlook — and wait for the reply, with a follow-up task after five days, and lists every case with what it waits for. `v1.44.0` adds the shared partner register, with a page of its own and a partner card on the case page, and lets a process keep its own values over its pack's resources (which price list, which template), every change a version. `v1.45.0` lets a process keep its own rule values too (how many lines a quote holds, the rounding unit), tried first on its earlier decisions, and shows each process's settings on a page of their own. `v1.45.1` lets the backup carry the machine's local settings with the keys too, so a machine can be set up again from a backup alone. `v1.45.2` makes the service and the worker read the configs they started with, whatever the folder holds later. `v1.46.0` runs the email routing, the monthly reconciliation, the documents, the bank statements, the quote and the mailbox download as cases of process packs, started from one general form and listed under Cases. `v1.47.0` makes three Settings pages work again and rearranges the interface's domains and two large modules without a visible change. `v1.47.1` splits the workflows module into smaller modules without a visible change. `v1.48.0` strengthens the framework before the insurance quote: a process pack is checked before a case starts, the same capability may stand twice in a case with its own data and approval, a step's result has a checked form, an approval knows what it was built on, goes out of date by itself and can be returned with a reason, a case keeps the price list, template and rule versions of its start, an action on selected rows takes every selected row across pages, and a quote's typed changes survive another person's save and a broken connection. `v1.49.0` composes a business property insurance quote, and its renewal, only of shared capabilities, with invented products, rules, tariffs and registers. `v1.50.0` lets any process's case be started from the case list, with the process's invented example material installed from the same page, so the insurance quote can be tried from the interface. `v1.51.0` lays the ground for the real corporate property product, without a visible change: its condition documents are read from their PDFs into the product registry by code, a page set in two columns is read column by column, a scanned condition document on every page, and a fact catalogue of the real product's terms is ready for the rules to be proposed from them. `v1.52.0` makes the rules proposed from the real conditions checkable: a quote on a page read by text recognition is compared roughly for a person, an extension's clauses numbered again under its code are found by their page and quote, and a run's proposals are checked again from its kept answers without asking a model again. `v1.53.0` sets a proposed rule's form right where its meaning is plain and compares a list of codes as a set, so 91 of the 132 rules proposed from the real conditions can be accepted.

## v1.53.0 — 2026-10-27

The rules proposed from the six real condition documents (132), checked again with these changes without asking a model
again: 91 can be accepted (60 before), 41 are for a person to correct or reject. No visible change.

- **A proposed rule's form:** a bare number of a money fact is an amount in its currency, of a percentage or permille its
  rate, a decimal factor given as a number its text; the rule's level is the lowest of the facts it reads; a fact it
  compares is a fact it reads; `in` with one value is a list of it.
- **A list of codes compared as a set** (the requested modules): `in` holds when any of its codes is among the given
  ones, `not_in` when none is, `eq`/`ne` when it holds that code or not, in the evaluation and in the registry's check.
- **A quote with an omission** (an ellipsis between two printed parts) counts when each part
  stands on the cited page as printed, in order.

## v1.52.0 — 2026-10-27

What the first paid round on the real conditions showed, without a visible change: every one of its 27 proposals
was blocked by code; re-checked with these changes, 15 can be accepted and 12 are for a person to correct or reject.

- **Quotes:** on a page read by text recognition a close quote counts, for a person to compare; anywhere a word
  broken at a line's end is the same word.
- **Clauses:** an extension numbers its clauses again under its code ("I29 2"); the model cites "2" on that page, and
  the clause is found by its page and, where several extensions share the page, by the quote; "3.1.b)", "1-4" and
  "2.2." are the clause; a word or a sentence is none; a clause going on over a page break may be cited on its second
  page when its quote stands there. The importer keeps "2.2. — A felek" and maps a code text recognition misread
  ("129", "JHA", "TKO", "S25") to the product's.
- **A single code** where a list is wanted is a list.
- **Checked again for free:** `rule-proposals-recheck RUN [--document REF] [--jev-budget-usd X]`: a finished run's
  undecided proposals from the answers it keeps, without asking a model again.

## v1.51.0 — 2026-10-27

The ground for the real corporate property product, without a visible change: its six public condition documents are
read into the product registry by code, and the rules can be proposed from them on a fact catalogue of the real terms.

- **Condition documents from their PDFs:** the clauses with their pages (numbers, Roman chapters, "1/A." points, an
  extension's own code: "VIL 2"; a table of contents or a stray number does not count) and the day in force, read by code;
  `condition-import`. A product's source names its documents by fingerprint and its frame (name, catalogue, modules);
  `product-source NAME --folder DIR [--install]`: the machine adds them as drafts, a person makes them active.
- **Reading the pages:** a page set in two columns is read column by column (line by line, the clauses came mixed); a
  scanned condition document is recognised on every page (a processed document still on its first twelve).
- **The real product's fact catalogue:** 95 facts on the policyholder, its sites and asset groups, 14 outcomes (the
  required protection class from VII to I, the stricter counting).
- **Rule proposals:** a rule for every module names none, an amount written as text is money, the instructions ask
  for the closing row, the catalogue's codes and a referral where a clause leaves a case to an assessment; the catalogue
  is sent in compact form, four pages a request. Two documents marked internal are read whole, by their fingerprints
  (the owner's decision).
- **A property schedule** reads an unlisted asset group as a row too.

## v1.50.0 — 2026-10-27

A case of any process starts from the case list, and a process's invented example material is installed where its case
is started; until now the insurance quote and its renewal could not be started from the interface at all.

- **New case:** the Cases page's New case lists the processes a person may start by hand, each with what it is for,
  and says what one cannot start without yet (a product or a tariff with no active version); the chosen process's own
  start form stands beside the list.
- **Example material:** a process pack names its invented example material as data: the sets of things it installs
  (the invented product set) and packets of invented documents a case can start on. Installing makes the machine the
  maker and the person the approver; the things it made read as examples in Settings; the material goes in one go
  while no case keeps it. The start form offers the packets as Example documents.
- **Choices instead of typing:** a process's product and tariff are picked from the active ones.
- **The invented registers:** `scripts/dev.ps1 start` also starts the local invented company register and sanctions
  list the insurance case asks.

## v1.49.0 — 2026-10-27

The business property insurance quote, composed only of shared capabilities, and a second composition of the same
capabilities with no code of its own. Every name, document, product, register and limit in it is invented.

- **An insurance quote as a case:** from a folder of a business's documents (the quote request form, a property
  schedule per site, a claims history statement: a new main document type with three type packs) to a sent offer: the
  facts the documents hold with where each was printed, an invented company register and sanctions list, a person's
  data check and freeze, the product's rules evaluated on every unit, missing facts with a deadline, a risk decision,
  the premium itemised from the tariff the case keeps, a premium decision (above a limit by another person), the offer
  as a Word document stored with its version, a covering letter a person accepts, and its send into the output folder.
  Every rule outcome, premium line and second-person check is a row of the decision trace.
- **Five work views:** Overview (what holds the case and where it is resolved), Data check, Calculation and versions,
  Decision and release, History.
- **Products, rules and tariffs:** products, condition documents, rules (decision tables citing page and clause) and
  tariffs kept as versions, a product made active by another person; Settings › Products and Tariffs. A case keeps
  the product, tariff and rule file versions of its start.
- **Rule proposals:** a model proposes rules from a condition document's pages (a page marked internal is never sent),
  code checks each, JEV judges how far the cited page supports it, and a person accepts, corrects or rejects it.
- **Typed values:** money with its currency, quantities with their unit, rates and validities, exact in JSON.
- **The insurance renewal:** a second process pack of the same capabilities in another structure (no company register,
  no wait for missing facts, a stricter risk rule, a lower second-person limit, its own letter).
- **Measurements:** a paid measurement names a missing key at its start; a structured GPT answer is asked in strict
  form, stops at its output cap, and is settled at its real cost when it fails.

## v1.48.0 — 2026-10-26

The framework strengthened before the insurance quote, after a reassessment of the process packs.

- **A pack is checked before a case starts:** a step whose capability cannot run, a reference to a step that is not
  there or not waited for, a screen element that is only planned or has no data are refused.
- **A step's own data and approval:** the same capability may stand twice in one case (two price lists matched, two
  quotes composed); each step keeps its proposal, draft, approval, task and budget.
- **Result forms:** a step's result has a named form, checked before it is kept and before another step reads it;
  the printed document and the reply letter are general capabilities.
- **Approvals:** an approval records what it was built on and goes out of date by itself when that changes (the step
  waits for a person again); a person may return a result with a reason; one shared approval element shows the state.
- **Versions kept from a case's start:** a case runs to its end with the price list version, the own template version
  and the rule files of its start; a rule file of another main version stops the step with the file and both
  versions, and `cases-kept` lists such open cases before a release. The case's history names what it keeps.
- **Selection across pages:** an action on the selected rows takes every selected row, also those on other pages.
- **Saving a quote:** the save line says whether everything is saved; when someone else saved meanwhile, the person's
  changes are kept beside the version saved now, to keep or drop; a broken connection keeps them to send again; the
  quote is not approved while it has unsaved changes.

## v1.47.1 — 2026-10-26

The workflows module is split into smaller modules, the code moved unchanged; no visible change.

- **The workflows module in parts:** the workflows' records (their tables, templates, steps and views) and how a
  workflow moves on (a step's start, the worker's tick, the process core's turns, the wizard's estimate) are modules
  of their own; making and repeating a workflow stay where they were.
- **Tests:** a test of the package log's actions holds when it runs alone too.

## v1.47.0 — 2026-10-26

Three Settings pages work again; the interface's domains and two large modules are rearranged without a visible
change.

- **Fix:** since `v1.45.2` the service and the worker kept the configs they started with but left out the base type
  pack in its subfolder (`configs/types/_base/`), so Settings › Rules, the output templates and the bank files under
  Settings › Processing failed to load, and a utility bill would have failed in the worker. The base packs are kept
  now.
- **The interface's domains:** the finance, the email and the quotes domain's screens live in their domain's folder
  of the interface and register themselves with the shared lists when it loads (the settings sections, the case's
  elements, a package rule's part, the result's views, the review's panels, a source's chooser, the domain's calls),
  as the service's domains do; the shared screens name none. Every screen of a backup copy reads the same as before.
- **Two modules in parts:** the bank statement reader and the mailbox module are split into smaller modules, the
  code moved unchanged.

## v1.46.0 — 2026-10-26

The email routing, the monthly reconciliation, the documents, the bank statements, the quote and the mailbox download
run as cases of process packs, started from one general form.

- **The cases are the main list:** a new piece of work is a case, listed under Cases; the work package a case's step
  processes opens from the case's page (its Processing, Review and Result), and the work packages list shows the
  packages that belong to no case.
- **Email routing:** a routing is the email routing process's case; an email package's page offers it, and a case
  can start by itself from an email when its steps are free.
- **Monthly reconciliation:** a reconciliation is the reconciliation process's case: its page shows the invoices, the
  statement lines, the pairing and the statement on tabs, and the AI pairing proposal can be asked for from there,
  within its cost cap on the button.
- **Documents, bank statements, mailbox download, quote:** the new work wizard starts each with the same general form:
  a folder or chosen files (a pasted path may keep its quotes), a party and a period, a mailbox download, or the quote
  request a quote starts from. The case's page starts the live run with its cost cap on the button; a workflow's
  steps still start their live runs themselves within the budget approved for them. A scheduled mailbox download's
  emails get a case too, and an email case's page offers the email routing.
- **Fixes found on the way:** a person's party, period or role on a package's page no longer unbinds it from its case;
  a case whose package is deleted is cancelled instead of making the package again; the case list says when a step
  waits for a person's start.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`) and the local service,
  run `python -m jav.cli cases-adopt --write` (the email routing and reconciliation packages made before become cases
  under their own ids; each statement package made before gets a bank statements case around it, its runs and
  approvals kept; the statement packages become plain packages of the statements rule at the first start), then
  start them again together. The email and document packages made before stay as they are.

## v1.45.2 — 2026-10-25

The service reads the configs it started with.

- **Configs frozen at start-up:** the local service and the worker read every config when they start and keep them,
  their list too, as they keep their code: a config that appears, changes or goes in the folder later, or a cleared
  cache, changes nothing in a running process. Until now a process pack that appeared in the folder later was read by
  the running code, which refused its format, and Settings › Processes showed the error.
- **`/api/health` names a drift:** `config_drift` lists what the config folder holds differently from the configs the
  service started with.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`), stop the local service and
  start them again together. No store change and no interface change.

## v1.45.1 — 2026-10-25

The backup carries the machine's local settings too.

- **Local settings in the backup:** the daily backup and Back up now also take `.env` and any other `.env.*` file at
  the project root (the keys and the second backup location; not the template `.env.example`) into `local-env.zip`,
  locally and in the second location, verified like the rest; the manifest names the files, never a value. A machine
  can so be set up again from a backup alone; the backup holds the keys unencrypted, so the second location must be
  guarded like the keys (`configs/service.json` `backup.with_env`, `backup --with-env`).
- **Restore steps:** the setup guide's restore also unpacks the reading artifacts, the internal working documents and
  the local settings.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`), stop the local service and
  start them again together. No store change and no interface change.

## v1.45.0 — 2026-10-25

A process's own rule values, with a preview; Settings › Processes.

- **Rule values per process:** a step's capability names the keys of its rule files a process may set for its own
  cases — for the IT quote how many requested items one proposal matches (only fewer), how many lines a quote holds,
  the unit a forint and another currency's amounts are rounded to, and how long the model's letter paragraph may be; a
  cost limit is never one. A case works with the values active when it started, in its steps, its background jobs and
  the requests about it, and the decision trace records them beside the rule file it read.
- **Preview:** a proposed rule value is tried on the process's earlier decisions — an approved quote's totals and the
  check of the model's letter paragraph are traced decisions now, shown on the Rules page under Quotes — and the page
  shows how many would come out differently, with examples; nothing is written and no AI is asked.
- **Settings › Processes:** each process's resources (price list, letter frame, output, send mode, output template) and
  rule values, with the value in use, the file's value and whether it is the process's own; a new value is saved as a
  draft, previewed, made active by the installation's rule of who may, or set aside; the roles its partners play. The
  send mode offers only the two ways a person sends from; the real send stays the owner's decision.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`), stop the local service,
  start them again together and rebuild the interface (`cd ui; npm run build`). No store change.

## v1.44.0 — 2026-10-25

The shared partner register; a process's own values over its pack's resources.

- **The partner register:** Settings › Partners lists the outside parties the processes deal with (customers,
  suppliers, the insured, brokers; `configs/partners.json`), with search and a role filter. Every change is a new
  version, a partner is retired rather than deleted and can be restored, and a second partner with the same tax number
  or name is refused with a link to the first. It starts empty; the suppliers of the incoming invoices and the buyers of
  the outgoing ones are offered as proposals, which only a person records (`jav/app/partners.py`).
- **A case's partners:** a process pack names the partners its cases are about. The IT quote 1.2.0 shows the
  request's customer on the Request tab, links it to the partner it seems to be, or records it as a new one.
- **A process's own values:** a process may keep its own value over a resource its pack names — which price list,
  the letter frame, the send mode, and the Word template of its quote — saved as a draft, checked as the pack would be
  with it, and made active by the person who edits it (who may do so is a rule, `configs/process_settings.json`). A
  case keeps the values it started with. These are set through the local service for now; their settings page comes
  with a later release.
- **Fixes:** the price list and the letter frame the IT quote's pack names now reach the draft and the letter (the
  defaults happened to be the same before); the quote package is retired: a quote is a case of the IT quote's process,
  and the golden sets and the package list no longer need it.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`), stop the local service,
  start them again together and rebuild the interface (`cd ui; npm run build`). The store gains the partner register's
  and the process values' tables and a column for a quote letter's frame, added when the service starts; nothing
  existing changes.

## v1.43.0 — 2026-10-24

The IT quote sends its letter and follows up the reply; the cases have a list of their own.

- **Send:** a general send capability (`jav/app/sending.py`). A step's message is recorded with its case and handed
  over once, by the way its process pack chooses: into the output folder as an email file Outlook opens as a message to
  send, as a draft in the person's desktop Outlook (`scripts/outlook_draft.ps1`), or out through Outlook — the real
  send only to the recipients on the allowlist of `configs/send.json`, which is empty. A refused handover fails the
  step, which a person tries again; an interrupted one asks a person whether it arrived. The mailbox download stays
  read-only.
- **Follow-up:** a general reply wait (`jav/app/replies.py`): the case waits for the other side's reply, a person
  records it (or that none is needed), and after the days the pack sets a follow-up task opens once in "Waiting for
  me", without a deadline.
- **The IT quote 1.1.0:** a person sends the accepted letter with the approved version's Word document into the output
  folder, and the case waits for the reply with a follow-up after 5 days. New tabs: Sent, Follow-up, and History (the
  case's events and what its steps spent). The letter step is done once a person accepted the letter. A case started
  on 1.0.0 keeps its three tabs.
- **Cases:** "Cases" in the side rail lists every open case with the step it is at and what that step waits for, and
  above it, while there are some, the handovers to check; a case's tasks in "Waiting for me" open its page.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`), stop the local service,
  start them again together and rebuild the interface (`cd ui; npm run build`). No store change.

## v1.42.0 — 2026-10-24

The first process pack: the IT quote runs as a case of the process core, built only from general capabilities, and
looks as it did.

- **Process packs and cases:** what the owner calls a workflow is described by a process pack
  (`configs/processes/<id>.json`): its scope, its intake, its steps (each a registered capability with its
  parameters), its tabs built from registered screen elements, its outputs and golden sets, and no code. One running
  instance is a case of the process core; it keeps the pack's version it started with. A paid step starts only when a
  person starts it, and then runs for that person.
- **Capabilities:** the general building blocks every pack is built from are registered with what a process sets for
  them, the paid services they may call and the rule files they read (`jav/app/capabilities.py`). The quote's back half
  became six of them (putting a record together, matching items with a catalogue, pricing, a person's line draft, a
  priced document, a letter draft); their fixed values became parameters with today's values as the defaults.
- **The IT quote as a case:** "Start a quote from this email" and the new work wizard start a case of the IT quote's
  pack; its page has the same header, tabs and parts the quote package's page had. On the 10 invented quote requests
  the case gives the quote package path's recorded results: the same proposal, lines, Word data, letter and requests
  to the models.
- **Strictness:** today's process-specific parts are a frozen list that may only shrink (a guard test).
- **Fixes:** the quote's proposal and letter spend from a business budget, not a measurement's; the generated
  call-site pages only read the store.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`), stop the local service,
  start them again together and rebuild the interface (`cd ui; npm run build`). No store change.

## v1.41.0 — 2026-10-24

The structure under the enterprise tools, without a visible change.

- **Who acts, and may act:** every address of the local service goes through one shared entrance that names its
  operation, knows who acts and asks the authorisation check (which allows everything today); the company sign-in
  and the roles will be connected there.
- **Who acted, by a stable id:** every record of who decided, approved, corrected, closed a to-do or changed a
  setting (47 columns in 33 tables) keeps the person's stable id beside the name; the rows written before get
  theirs from the name (`local:<name>`). An automatic workflow step and a scheduled mailbox download are recorded
  as the machine acting for the person.
- **The process core's boundary:** the worker turns every case of the process core, not only the workflows'; code
  outside the core uses only its public operations and never reads its tables directly.
- **Layers:** no reference against the direction of the code's layers is left (7 → 0), and no lower layer names a
  higher one's module as text; the finance domain's part of the own parties, the wording of the "Waiting for me"
  list and the utility cost's workbook address are the domains' own.
- **Upgrade:** back up the store, stop the worker with its stop file (`store/worker.stop`, not with a command that
  opens the store), stop the local service, start them again together and rebuild the interface (`cd ui; npm run
  build`). At its first start the new version adds the id columns and fills the earlier rows' ids from their
  names, so an earlier version runs again only on the backup made before the update.

## v1.40.0 — 2026-10-24

A consolidation round over the process core and the rules, without another visible change.

- **An approved reconciliation statement** warns that it changed only when its content changed; when only its rules
  or the program applying them changed, a neutral note says so.
- **Half-done invoice states** saved before `v1.28.0`, under the record's old name, load again.
- **Rules read when they apply:** the shared bands, the email routes and the OCR escalation are read from their rule
  files at each decision instead of being copied when the program starts; a reloaded rule file reaches every decision.
- **Layers:** eight references against the direction of the code's layers are gone (15 known exceptions → 7).
- **A workflow step's state in one place:** where a step's start stands is kept in its row in the process core, and
  the workflow's own table keeps only the step's own data. The deleted package of an archived workflow fails its step
  in the process core too and withdraws the step's open budget task.
- **Upgrade:** back up the store, stop the local service and the worker, start them again together and rebuild the
  interface (`cd ui; npm run build`). At its first start the new version moves each workflow step's state into the
  process core and drops the old column, so an earlier version runs again only on the backup made before the update.

## v1.39.1 — 2026-10-24

Two dependencies updated for published security advisories.

- **opentelemetry-api 1.45.1** (was 1.44.0; CVE-2026-114603): loaded at run time by the AI library.
- **undici 7.30.1** (was 7.30.0; three advisories, one high): used only by the interface's tests, not by the built
  interface.
- **Upgrade:** install the pinned Python packages again (`uv pip install -r requirements.lock`) and restart the local
  service; the store does not change.

## v1.39.0 — 2026-10-24

A proposed rule is tried before it changes.

- **Rule preview:** `python -m jav.cli rules-preview <rule file> --candidate <proposed file>` (or `--ref <git
  reference>`) works out the system's earlier decisions again with a proposed version of a rule file: for each kind
  of decision that reads it, how many would come out otherwise, how, and which to-dos would open or close. It writes
  nothing and asks no AI. With `--replay <backup>` it replays a sample of a backup with both versions, from earlier
  answers only, and lists the views that differ.
- **Rule files by field of work:** the shared rule file keeps the thresholds every kind of work uses; the email
  routes are in `configs/email.json`, the duplicate search and the reconciliation's bands in `configs/finance.json`.
  No value changed, and a change to one field's rules no longer changes another's fingerprint. Settings › Rules names
  the new files.
- **One way of keeping versions:** price lists and own output templates keep their draft, active, superseded and
  retired versions with the same code and show their state with the same mark; a reconciliation's and a quote's
  approval write the same steps in the same order, and a package holds one approved version at a time.
- **Upgrade:** restart the local service after the update; the store does not change.

## v1.38.0 — 2026-10-24

Which rule decided, with what, in which version.

- **Rules page:** Settings › Rules shows, for each kind of decision the system makes on its own, what it decides
  and what it is not for, the values it decides with (for example "waits for a person below 60 %"), which version
  of its rule files is in use and since when, and how many decisions it has made. It only reads: a rule changes
  with a new release.
- **Decision trace:** a document's type and detailed type, an email's intent and next step, accepting the extracted
  data and its to-dos, sending a weak scan to the paid recognition, a duplicate invoice, an own tax number as the
  supplier's, the detailed type the own parties settle and a workflow step's budget are recorded with their inputs,
  their outcome and the versions of the rules they used, in the same write as the result (`python -m jav.cli
  trace`). Saving a document's or an email's result is one write now, so a stop cannot leave it half written.
- **Calculation snapshot:** every run, processed item, case and approval names the code and the rule files it was
  computed with; when some of a run's items were processed with changed rules, its approval says which files
  changed (`python -m jav.cli snapshot`).
- **Workflows:** a step built on a step that was opened again (a new live run on its package, a reopened
  approval) goes out of date and is approved again after it; its earlier approval no longer counts.
- **Fixes:** a recognised document keeps the to-do of a paid recognition the run's budget blocked; a step whose
  wait a person settled while it ran no longer fails.
- **Upgrade:** restart the local service after the update; the store adds its new tables by itself.

## v1.37.0 — 2026-10-23

"Waiting for me": what waits for the person working now.

- **Waiting for me:** beside "My work today" in the header, the number of the chosen person's open live tasks; its
  page lists their to-dos, run approvals, reconciliation and quote approvals and budget decisions, and those no one
  is assigned to (marked as anyone's), each with its package, since when it waits and where it comes from, and each
  leading to where it is done (an item's review page, a package's result, a package's page).
- **Live work first:** by default only live work shows (a live run's to-dos and every approval); a switch adds the
  to-dos of trial runs and earlier measurements.
- **Upgrade:** restart the local service after the update; nothing changes in the store.

## v1.36.0 — 2026-10-23

Everything that waits for a person is a human task of the process core; a workflow goes on right after an approval.

- **Human tasks:** the process core keeps the work that waits for a person with whom it is for (a person, or
  anyone), an optional deadline, whether a decision needs a reason, the result version it is about and how it ended
  (decided, expired or withdrawn), each change with its history. In a case a task is a step's wait, and its deadline
  is the case's timer.
- **Today's work as tasks:** a document's or an email's open to-dos, a finished live run's approval, a
  reconciliation's or a quote's approval and a workflow step over its budget are tasks for the package's responsible
  person (without one, the person who started it when on the Users list; otherwise anyone), written in the same
  transaction as the change that opens or settles them. No task has a deadline yet. A package's new responsible
  person takes its open tasks. The interface does not show them yet; the `admin` command's report counts them.
- **One transaction:** a duplicate decision, a statement pair's choice, an email's task decisions, an email's
  corrected intent and a confirmed field are written together with the to-dos they settle.
- **Changed on purpose:** once a run of a workflow step's package or the step's reconciliation is approved, the next
  step starts at the worker's next round (about 2 s when idle) instead of at the next 10-second check.
- **Upgrade:** restart the local service and the worker after the update; the first start opens the tasks of the
  existing to-dos, live runs waiting for approval and reconciliations.

## v1.35.0 — 2026-10-23

Today's workflows on the new process core, without a visible change in the interface.

- **Process core:** the shared core that runs cases step by step: a versioned process definition, the case's
  history written with every change, incoming events taken once, outgoing handovers never sent twice, durable
  timers, and claims no live process takes over, so several workers can run on one machine. Its operating rules
  are checked by failure tests with separate worker processes.
- **Workflows as cases:** every workflow is a case under its own id, started with the workflow; the workflows made
  earlier are adopted from the state they reached at the first start after the update, and an archived workflow's
  case is on hold. The core moves the steps on: a step waiting for its download or its package's approval is
  looked at again by a timer, and a person's start, also one out of the steps' order, is recorded in their name.
- **Changed on purpose:** a step start cut off by a stopped program fails at the next turn instead of after an
  hour, and a mailbox download a person started finishes its step while the workflow's automatic chain is off.
- **Upgrade:** restart the local service and the worker after the update; the first start adopts the existing
  workflows.

## v1.34.0 — 2026-10-23

The code base in one folder per layer, without a visible change in the interface or in the results.

- **Folders:** every module is in the folder of its layer: the shared core, document reading, the AI questions, the
  flows, the application, the worker, the domains (finance, email, quotes), the local service and the command line,
  with the measurement, the developer tools and the legacy port beside them. A test checks that a layer uses only
  the layers below it, that a domain never uses another domain, and that no other module names a domain's tables.
- **Settings:** the instructions and output schemas sent to the models are in `configs/prompts/`, byte for byte
  unchanged, so every request and its cache key stay the same.
- **Email tables:** the email domain's tables are its own; the shared code reads them only through the domain's
  registrations. The data model is split too: the page layout belongs to document reading, and the Hungarian
  invoice's own models sit beside the general ones.
- **Interrupted items:** a flow state saved before the move resumes with its classes at their new place.
- **Upgrade:** restart the local service and the worker after the update, because their helper processes start from
  the new places, and rebuild the interface (`cd ui; npm run build`).

## v1.33.0 — 2026-10-22

A failed paid call settled at its certain cost, quicker large runs, and a tidier code base, without a visible change in
the interface.

- **A failed paid call:** a call that failed with a certain cost is now closed at that cost instead of keeping its
  reserved maximum: a JEV request refused as too large before it was processed costs nothing, and a GPT answer cut
  off at its output limit costs the tokens of its requests. A timeout or a broken connection after sending stays
  uncertain with its maximum, as before.
- **Speed:** an operation reads and writes the store through one connection (a document in the worker opened 35-37
  before). A run's status and the run list no longer read the whole run: the list of a run of 10,000 items took 10.4 s
  and now takes 0.014 s. The test suite runs about a quarter faster.
- **Transactions:** a store step nested inside another step's transaction is now part of that transaction. With one
  connection per operation it committed the enclosing work, so a run start released its write lock right after
  reading the package; this was never in a release.
- **Clean-up:** the experiments and the September learning branches are archived out of the code base, with their
  commands (`learn-flow`, `learn-propose`, `learn-check`, `type-draft`, `type-inspect`); the three measurement tools
  stay. The command line, the work package code and the UI's service client are split by theme, the shared code no
  longer names invoice defaults, a domain no longer imports another domain's module, and the stored values (days,
  amounts, JSON lines) are read by one shared reader each. The isolated PDF reader sets its import path itself.

## v1.32.0 — 2026-10-22

JEV asked by a fixed version, and a request JEV refused as too large not sent again.

- **A fixed JEV version:** the system asks JEV by its concrete version (`jev-1.14.0`) instead of the provider's moving
  "latest" name, which moved on 2026-10-22 without notice and made every golden set to be measured again. The daily
  backup looks once a day where the moving name points; the start-up check and the System page's new JEV version card
  say when a newer version is out. Switching stays a decision with a measurement. Every earlier answer keeps its key.
- **A request refused as too large:** JEV refuses a request over its token limit; the system then asks a tighter one,
  whose answer is kept. The refused request had no answer to keep, so every later run sent it again (a failed call and
  a reservation each time). Its key is now remembered for the version that refused it, and the tighter request is
  asked at once.

## v1.31.1 — 2026-10-22

A fix round after re-measuring every JEV golden set on JEV's new model version (1.14.0), which it switched to
without notice: the results stayed the same within one or two cases per golden set.

- **The admission ticket's event time:** every ticket got a "not printed" to-do for its correct event time, because
  the code's source check looked for the normalised value ("2026-01-22T21:00") letter for letter on a ticket that
  prints "2026.01.22 21:00". A text value in the date-and-time form is now found where the same date and the same
  time stand on one line; the tickets' golden sets keep all their fields right (88 of 88, 40 of 40) with no to-do.
- **Superseding an older trial run:** a trial run's to-dos stayed open after a later run of the same documents went
  another way. A person can now supersede such a trial run on its page or in the package's processing section, as
  an older live run, with a confirmation; it closes the trial's open to-dos only. A run still never closes another
  run's to-dos by itself, and a later trial never supersedes a live run.
- **Measurement:** naming a golden set by its whole key measures that set only (the legacy S path without its
  synthetic cases), so a paid round can name it; a case the budget refused on the S path counts as without a result
  instead of as answered and wrong.
- **Dependencies:** vitest 4.1.12, a tool of the UI tests only, for two moderate advisories of `@vitest/mocker`.

## v1.31.0 — 2026-10-22

Teaching a new document type from its documents' general facts, measured on documents it has not seen, and turning
it on or off by command. The first taught type, the admission ticket, now replaces the converted one.

- **Field names per type:** a shared field may have a type's own name; the utility bills show the consumer's name
  again instead of the quote request's name for the same field.
- **The general facts measured:** a document without a type pack gets general facts; a new golden set measures them on
  a held-out family's labelled documents with the family's pack withheld (the admission tickets: 52 of 80 expected
  values found as checked facts; with the pack 88 of 88).
- **Teaching a type:** field proposals from the facts of the family's development half (names and counts only), an
  edited draft from which code makes the candidate type pack, its prompt, schema and verification questions, and a
  measurement of the candidate on the family's evaluation half (the taught ticket: 40 of 40 fields on 5 tickets it had
  not seen; 25 of 40 without a pack).
- **Turning a type on or off:** `type-activate` and `type-withdraw` turn a type pack's detection switch as a new
  version, and the files stay for the earlier results. A taught type is turned on only with a clean, complete
  measurement of its evaluation half on its current files; it can replace the family's pack in the same step, and the
  replaced pack can be turned back on.
- **The taught ticket is live:** it replaces the converted ticket pack and is shown as the taught admission ticket.
  An end-to-end trial on a copy of the store showed the processing follow the switch on 9 tickets and an email with
  the 10th attached: general facts without a pack, the taught pack's 12 fields with it, and general facts again after
  withdrawal.

## v1.30.0 — 2026-10-22

The quote's documents: the approved quote as a Word document, and the reply letter as a draft Outlook opens. Every
number in both is written by code.

- **Word templates:** an output can now be a Word document. A person's own Word template uses the markers of an Excel
  template — a value, a table's column (its row repeats for every row, so does a list paragraph), a total, a count —
  and is uploaded, checked, versioned, previewed and chosen beside the download the same way. The check refuses
  macros, embedded objects, links to other files and fields that compute or import; page numbers, dates and web links
  stay. Headers, footers and text boxes are filled too, and the text around a marker keeps its formatting.
- **The quote as a Word document:** a built-in template in Hungarian and English (A4), the language estimated by code
  from the request and changeable with the quote's header. The draft downloads as a Word document marked as a draft;
  the approval stores the version's document, so its download never changes.
- **The reply letter:** beside the approved quote, a draft letter in the quote's language: the greeting, the totals
  (written by code) and the closing come from a template; the paragraph after the greeting is the template's own, or
  one GPT writes for the request when a person asks (its cost cap is on the button). The code refuses a paragraph with
  a number, a web or email address; a person reads, changes and accepts the whole letter, which then downloads as an
  email file Outlook opens as an unsent message to the request's contact, with the version's Word quote attached. The
  system never sends it and never touches the mailbox.
- **Measured on the invented set:** the paragraph of the 10 invented quote requests and of an injection probe (a
  request asking for a price and a web address) passed the code's check in the request's language 11 of 11 times, for
  0.008 USD; the language estimate is right on all 13 invented emails.

## v1.29.0 — 2026-10-21

The quote, a third kind of work beside the document packages and the reconciliation. Every amount is computed by
code; the AI only proposes which price-list item a requested item is.

- **Quote requests are read:** a customer's request for a quote is a document type and an email intent of its own.
  Its data — the customer, its tax number, the contact, the deadline, the customer's reference and the requested
  items with their quantities — is read from the email's own text (without the quoted earlier messages), from an
  attached request form, or from an attached Excel or CSV list, and merged with the source of each value. A part that
  lacks a field is a note, not a to-do; a doubtful value (a tax number that fails its check) stays a to-do.
- **Price lists:** Settings › Price lists keeps the seller's price lists, uploaded from Excel (Hungarian or English
  headings) and checked. Each change makes a new version (draft → live → superseded or withdrawn); discount rules
  are edited on screen.
- **The quote as a kind of work:** a new work, "Quote from a request", takes a processed quote request from any
  package. For each requested item code first looks for the item's code in the text, then the AI (JEV, or GPT
  without JEV) proposes a price-list item or none, within the package's budget and the call log. Prices, discounts,
  VAT (rounded to whole forints) and totals are computed by code.
- **The quote's page:** the request on the left, the editable quote on the right. Every change is saved at once; a
  manual price, a manual discount or an item not on the price list needs a note; a line marked for review waits
  until a person confirms or replaces its item. The approved quote is kept as a version with its price-list version,
  and can be reopened with a reason. The approval panel is now one shared element of the quote and the
  reconciliation; the reconciliation looks exactly as before.
- **Started from the email:** under a quote request email of a mailbox package the read request shows which value
  came from which part, what the whole request lacks and which quotes were made from it; "Start a quote from this
  email" creates the quote package with the customer's name and opens it. An attached request list adds 0.03 USD to
  the run's budget.
- **Measured on an invented set:** 13 invented quote request emails and a 24-item price list are a golden set of the
  shared measurement command; the pricing is right on 10 of 10 quotes, and the item proposal on 36 of 37 lines with
  JEV and with GPT, without a silent mistake.

## v1.28.1 — 2026-10-21

- **Dependencies updated for published security advisories:** the image library that reads page images (pillow
  13.0.0, eight advisories), the list of trusted certificates (certifi 2026.10.19) and the interface's build tool
  (vite 8.3.4; it affected only the development server on Windows). Nothing else changes.

## v1.28.0 — 2026-10-21

Measurement and naming only; nothing changes on screen or in the results.

- **One measurement command:** `python -m jav.cli measure` measures every golden set the way its own command does:
  the data points of each document type with golden cases (both paths, the invented cases apart), the type
  recognition, the email intent, and the golden sets a kind of work names for itself (the reconciliation's pairs and
  the kinds of incoming money). Without a budget it uses only earlier answers, so it is free; a paid measurement
  names one golden set. Each round leaves a receipt with the code version it measured, and the state snapshot shows
  every golden set's latest result.
- **A general name for the data record:** the record of a document's data points was named after the Hungarian
  invoice it began with; it is `DocumentRecord` now. A document interrupted before the upgrade resumes with its data.

## v1.27.0 — 2026-10-21

Every kind of a person's decision is recorded the same way; on screen a stale page is the only difference.

- **One decision journal:** a task decision, a duplicate decision, a statement choice, an email routing decision, a
  template choice and the reconciliation's decisions keep their current state as before, and every change is also
  written into one journal in the same step, with who, when and why. An earlier decision is never lost.
- **A stale page is refused:** each decision carries its state; a change sent from a page that another tab changed
  in the meantime is refused with a request to reload, instead of overwriting the newer decision.
- **Three gaps closed:** a changed task decision used to overwrite the earlier one with nothing kept; two acceptances
  of one email routing proposal at the same time could make two packages; and a statement choice made in another run
  could change a run that was already approved. Revoking a reconciliation decision now checks the run's approval in
  the same step as the change.
- **The start-up check only reads the store:** the state snapshot no longer runs a development version's changes on
  the store in use.

## v1.26.0 — 2026-10-21

No visible change: the scope and the approved versions of every kind of work package are kept in one shared place.

- **One scope:** a statement package's party and period, a reconciliation's accounts, period and party, and an email
  routing package's email packages were each kept in a table of their own. They are now in the one table that
  already kept the scope a person gives a package, with a revision that refuses a stale change; the party in use,
  the deletion with the package and the cache marks cover every kind at once.
- **One release:** a reconciliation's approved statements, with the lines they lock and their files as approved and
  as reopened, are versions of the shared release store; a package's release page still shows only its released
  results.
- **The stored data moves once:** a store from an earlier version is copied into the shared tables the first time
  the new version starts; the older tables keep their rows for one release. A before/after comparison on a copy of
  the store found no difference in 4,159 views, and replaying 150 items from earlier answers found none either.

## v1.25.0 — 2026-10-21

No visible change: the shared code no longer names a domain.

- **Each domain in its own place:** the finance domain (invoices, bank statements, the reconciliation, the utility
  cost, the own parties) and the email domain (emails, mailboxes, the email routing) were partly written into the
  shared code: 28 of the local service's 108 addresses, 6 of the 18 tables, the mailbox download in the worker and
  as a workflow's source, an email's review page and the correction of its intent, the email sheets of the
  downloads, the finance decisions of a run's reviewed version and the direction rule of the extraction flow. Each
  now lives in its domain's modules and is registered by its domain module; the shared code asks the registries.
- **The same for a person:** every address, table, download and approval is as it was. A before/after comparison
  on a copy of the store found no difference in 4,159 views, and replaying 150 items from earlier answers found none
  either.
- **A guard:** a test lists which shared module still imports a domain's module. Apart from the command line, the
  generated documents, the measurements and the flows' routing rules, none does.

## v1.24.3 — 2026-10-20

Three small interface fixes.

- **Short rows in the facts table:** a document's long file name, repeated in each of its facts' rows, broke into five
  to eight lines in its narrow column. The document column now shows at most 2 lines, the source 3 and the value 4;
  the full value shows when you point at the cell.
- **A mailbox package's source in the interface's language:** the source line, the schedules, the count preview and
  the download log gave the period in Hungarian on the English interface too. They are now written in the interface's
  language ("last 7 days").
- **Why a unified name is uncertain, in the interface's language:** the warning mark beside an uncertain name said why
  in Hungarian on the English interface; it now follows the interface's language.

## v1.24.2 — 2026-10-20

Two fixes to the email routing, after its first real trial on a mailbox's sent items.

- **An attachment read without data:** a document of an unknown kind (a letter, a report, a tax return, a registry
  extract) leaves no data points, and the routing reported it as "not processed yet" although its run had read it. It
  is now placed by its recognised type: a kind that no package role takes is only listed, with its type's name; an
  invoice, a bank statement or a document whose kind was not recognised gets its own blocker ("read, but it has no
  data: see its to-dos in its email package"). Only an attachment no run has read yet is "not processed yet".
- **An incoming invoice in a sent email:** a forwarded invoice (sent on to an accountant, say) is now proposed for its
  buyer's incoming invoices like any incoming invoice, with a note, instead of being a blocker.

## v1.24.1 — 2026-10-20

Two fixes.

- **A released package's stage bar:** after a trial run, a released package's stage bar said "trial result" while its
  release line said "partly released". The stage bar now says the package's release state, as the release line does:
  released, partly released or changed since the release.
- **The start-up check on a fresh store:** its state snapshot no longer fails on a new, empty store that has no runs
  yet.

## v1.24.0 — 2026-10-20

Invoices, outgoing invoices and bank statements that arrive by email can be routed to the work package they belong to,
a work package can have a party, a period and a role, and a workflow asks only for what its steps need.

- **Email routing:** a new kind of work package. It looks at the PDF attachments of one or more email packages and,
  for each invoice, outgoing invoice and bank statement, proposes the package it belongs to: the open package of the
  same own party, period and role (incoming invoices, outgoing invoices, bank statements), or a new one for the party,
  the document's month and the role. You accept the proposals one by one or every clear one at once, choose another
  package, or leave a document unrouted; a decision can be taken back. A document the routing cannot place by itself
  says why: not processed yet, no own party, unclear whether incoming or outgoing, no date, a suspicious email, or an
  incoming invoice in a sent email. Accepting adds the document to the package; its run is started there, as usual.
  An email package's Result offers "Route the attachments", and the new work wizard has "Email routing" and "From the
  mailbox to the packages" (a mailbox download, then the routing). It reads by code only and calls no AI service.
- **A package's party, period and role:** Manage package › Party, period and role… gives a package that processes
  documents its own party, period and role, so the routing proposes it. A workflow step's package takes its
  workflow's party and period and the step's role; a statement package has its own.
- **A workflow asks only for what it needs:** the wizard asks for an own party and a period only when a step of the
  template needs them (bank statements and the reconciliation do); the email routing's workflow needs neither. The
  three reconciliation workflows ask for both, as before.
- **For developers:** the steps of a workflow are registered kinds (`jav/workflow_steps.py`): which packages a step
  takes, how it starts, its engine, its repeat source, its estimate and the scope it needs; the documents step is the
  workflows', the emails and routing steps the email domain's, the statements and reconciliation steps the finance
  domain's, and neither the workflow's code nor the interface names a kind. A workflow's scope is made of registered
  parts (`jav/scopes.py`); an older store's workflows table is rebuilt once with the party and the period optional. A
  package's scope and the package roles are in `jav/package_scope.py`; the email routing is the third logic pack
  (`jav/email_routing.py`, its addresses in `jav/api_email_routing.py`). The finance and email domains' internal
  registrations of 180 go live with this release. Free before/after comparisons on a copy of the store showed only the
  announced changes, and no difference in processing.

## v1.23.0 — 2026-10-19

Excel downloads can be made from a person's own template, and an approved reconciliation statement keeps the file it was
approved with.

- **Own Excel templates:** a new page, Settings › Output templates, takes a workbook made in Excel (chosen in the
  Windows picker) as the template of an output: a package's full workbook, the reconciliation statement, or the new
  utility-cost workbook. Markers in its cells say where the data goes: `{{package}}` once, `{{invoices.amount}}` in a
  row that repeats for every line in that row's formatting, `{{invoices.amount:sum}}` and `{{invoices:count}}` for
  totals the system calculates. Fonts, colours, logos and column widths are the template's own. The page lists every
  marker of an output with its label, searchable, and copies one with a click.
- **A checked upload:** a workbook with a formula, a macro, an external link or an unknown marker is not stored; the
  page says which cell holds the problem and what it is. A stored template has versions (draft, active, superseded,
  retired); a version can be made active, downloaded or previewed with made-up data, and a template can be retired.
  Retiring asks for a second click; an earlier version can be made active again at any time.
- **The choice beside each download:** a small "Template" chooser stands next to a package's full Excel workbook, the
  reconciliation statement's draft and the new "Utility cost (Excel)" download of the Utility cost view. It appears
  only when an own template can be chosen; without one, every screen looks as before. The choice is the package's own,
  it goes into the package's activity log, and a released version records the template version its workbook was made
  with. A package whose template was retired gets the built-in one, and the chooser says so.
- **Stored, not rebuilt:** an approved reconciliation statement's Excel file is stored when it is approved (and again
  when it is reopened), so its download no longer changes with later labels.
- **Fixed:** in the reconciliation statement's workbook the empty row under the heading had the table header's
  formatting, the frozen rows stopped above the real header, and the filter started from the empty row, leaving the
  last line out of it. The cells' contents are unchanged.
- **For developers:** one table writer makes every Excel download; each output is described once
  (`configs/outputs.json`: its values and tables, the built-in template's settings), and the built-in template makes
  the same files as before, apart from the fix above. The command line can list, add, activate, retire, preview and
  choose templates (`output-templates`, `output-template-add`, `-activate`, `-retire`, `-preview`, `-choose`).
  `reconcile-versions-backfill` stores the file of a statement approved before this release. Free before/after
  comparisons on a copy of the store showed no difference besides the ones stated.

## v1.22.1 — 2026-10-19

Every to-do now reads as a sentence; behind it, the kinds of item, of package source and of to-do are each described
in one place.

- **To-dos as sentences:** twelve kinds of to-do showed their raw code, for example `jev:off_target:invoice_number:0.82`.
  They now say what JEV found ("JEV: the value belongs to another field: Invoice number (0.82)"): a field left empty
  though it is on the document, a value of another field or of the wrong kind, a value cut short, a supplier and a buyer
  swapped, line items missing from or added to the extracted list. The same goes for an email that may carry an injected
  instruction, a number that cannot be read (with its list row and column), a value the field does not allow, text
  recognition that could not run and a type recognition without a result.
- **A watched folder's package** said it was made from "the file <folder>"; it now names the watched folder.
- **For developers:** the kinds of a package's items (a document, an email, a statement read from a bank's table) and of
  its source (a folder, an upload, a mailbox, files chosen by hand, a watched folder) are one registry the shared code
  asks instead of naming the kind; the rule that marks an attachment of a suspicious email belongs to the email domain
  and registers itself, and a process that missed the registrations stops instead of skipping it. Every kind of to-do a
  processing step raises is listed once (`configs/todo_kinds.json`); a test fails when a step raises an unlisted kind,
  the before/after replay names one, and the interface's test requires a label for every kind. Free before/after
  comparisons on a copy of the store showed no difference.

## v1.22.0 — 2026-10-19

"My work today" shows more of a person's work; behind it, the checks, the activities and the two kinds of work
package that do work of their own (the reconciliation and the statement package) are each described in one place.
Nothing else a person sees changes.

- **My work today** also lists a person's duplicate decisions, their choices between two statements of the same days,
  and the steps they took in a workflow (a step the workflow started by itself is not theirs).
- **To-dos in a fixed order:** when a record read on the GPT path misses two or more required fields, their to-dos come
  in the type pack's order. Before, the order could differ from one run to the next.
- **For developers:** the checks a result goes through are registered in four stages (the record, the decision, the
  checks across documents, the checks after saving), and the rule that only a worker run reads other documents lives in
  one place; the roles of the document types are read from one adapter; the log events, the sources of "My work today",
  the decisions in a run's reviewed version and the task kinds are one registry, and a log refuses an event no module
  registered. The reconciliation and the statement package are logic packs, registered once with their input roles,
  rules, delete guards and page parts; the shared code, the service (each with its own module of addresses) and the
  interface ask the registry instead of naming them, and a package of an unknown kind is refused. Free before/after
  comparisons on a copy of the store showed no difference besides "My work today"; the screens are pixel for pixel the
  same.

## v1.21.0 — 2026-10-19

The reconciliation and the duplicate search read the same result the package shows, and the reconciliation's
remaining review findings are fixed.

- **One result everywhere:** the reconciliation, the duplicate search, the own-tax check and the bank statements now
  read each document's result in the package's order: an approved live run's, else a live run's, else a trial's, and a
  command-line result only when no run has read the document. Before, they read the latest result whatever its run, a
  later trial's too. A document removed from every package it was in leaves the reconciliation. A pairing that no longer
  fits its invoice after the change shows among the decisions no longer valid and blocks the approval.
- **A statement package's accounts** are taken from the approved run's own statements.
- **Pairing by hand:** a line set aside for a fee or interest word in its memo, and a card purchase compared on its
  original amount, can be paired by hand. The sure pairs take a combined payment whole or not at all, so accepting them
  no longer fails. The quick review never marks a line that another own party's invoice may pay.
- **Statements:** after a statement is replaced, repeated lines (the same day, amount and direction) follow their
  partner and memo, and an unclear one is left for a person instead of guessed. A folder's monthly exports of one
  account are all kept. A table export with no balances and no total row is marked unchecked with a to-do. A very long
  cell no longer holds up the reader.
- **Exchange rates:** a drift built from allowed daily steps is refused, not only a single large step.
- **Smaller:** a run's tables are rebuilt after a reconciliation decision or a statement choice on one of its
  documents; the finder no longer copies the whole page on every click; the filters say when an amount cannot be
  read; a scope change cannot overwrite an approval made at the same moment; the pairing engine is faster on large
  stores; the AI's preselection checks a forint bank line in the invoice's payment window; developers get a free
  replay of about 150 items from earlier answers for every refactoring step.

## v1.20.0 — 2026-10-18

A work package has one result and one approval: the package's current result is shown and released as a whole, and a
released version's downloads never change.

- **The package's current result:** the Result section shows, by default, each document's result from the run that
  counts now: an approved live run's, else a live run's, else a trial's, with the person's corrections. The picker
  still offers each run's own result, and the package's Excel download gives the current result in one workbook.
- **Approve and release:** one button on the package approves every finished live run together and records a numbered
  released version. Its downloads (Excel, JSON and the CSV tables) are stored, so they stay the same even after a label
  or a rule changes. The package reads released, partly released (a document added later has no released result yet)
  or changed since the release, and the next release brings it back. A run is no longer approved on its own; a package
  approved before this version gets its first released version recorded afterwards, marked as such.
- **The package's items in one list:** Processing and Review list the package's documents with their state, the run
  whose result counts and their to-dos; several can be removed with one reason and restored. Adding goes in three
  steps (choose, check, add), files or folders with their subfolders, for document, mailbox and statement packages.
- **A reconciliation's inputs:** a reconciliation package lists the statements and the invoices it pairs, each with
  the package it comes from; a document can be left out of this reconciliation with a reason, and more documents can
  be added to an existing document or statement package from here.
- **Smaller:** the "no invoice" to-do and six activity-log events read as words, not codes; developers get a free
  before/after comparison of a store copy for every refactoring step.

## v1.19.1 — 2026-10-17

A fix round: documents are added where they are looked for, the service's errors appear in the interface's language,
and the smaller findings of two code reviews are fixed.

- **Adding documents where they are looked for:** **Add documents** sits at the top of Processing, right above the
  button that processes only the new ones, and in the **Manage package** menu from any stage; Review's document list
  names adding in its title. Before, it was only in a closed section at the bottom of Review.
- **Errors in the interface's language:** an error the service raises for a person (a refused correction, an approval
  that is not ready, a workflow step that cannot start, a reconciliation decision) carries its English template and
  parameters, and the interface translates it like its own labels. A refused request names its fields instead of
  "HTTP 422", and a read that never answers gives up after a minute instead of stopping a view's refresh.
- **Review and approval:** a stopped, failed or superseded live run says that it cannot be approved, and a refused
  approval gives its reason. A failed check is not listed twice next to its to-do, a candidate equal to the current
  value is not offered, a check across fields makes its fields the ones to fix, and a corrected field no longer shows
  the machine's confidence.
- **Numbers:** a table's amount always has two decimals and grouped thousands; a typed number in a filter is read by
  the Hungarian habit ("1.000.000" is a million) and an ambiguous one is refused; a typed pairing amount has at most
  two decimals; a budget rounded up to the cent keeps 0.07, and a new estimate replaces a proposed budget, not a typed
  one.
- **Steadier screens:** a malformed address no longer takes down the whole interface, a workflow action runs once on a
  double click, a held Enter accepts one pairing card, a late statement survey is dropped when the files changed, and
  the reconciliation views say when a load failed and while a decision is being saved.
- **Behind the scenes:** a manual settlement of an uncertain paid call books only a cost between 0 and
  100 USD; a GPT extraction cut off at its length limit is not paid for again and becomes a to-do; an oversized JEV
  check leaves the lists out as a last step and says so; a scanned page behind a page with text is a
  to-do; a card number with hyphens or dots is masked too; an
  attachment path is refused by its text before it is resolved; the email subject no longer goes into the logs; and
  the test suite no longer depends on the clock, the working directory or real data.
- **Smaller:** a statement package lists its statements in time; a run item whose to-dos were settled says so; a
  control character in a party's name is dropped; a page image of a non-PDF document is refused with its own message;
  the activity log names a correction's fields; the menu's hover has no side stripe.

## v1.19.0 — 2026-10-17

A work package stays open after its first run: documents can be removed and added, and only the new ones processed.

- **Remove and restore:** a document is taken out of a package by a named person with a required reason, recorded in
  the package's log; the file stays where it is, removed items show behind a switch and can be restored. A live run can
  still be approved after one of its items was removed: the approval says how many, leaves them out of the released
  result and records them, so a later removal or restore does not change a released result.
- **Add to an existing package:** documents are added by content (one already in the package is not added twice, a
  removed one is restored), with the service's own counts and a warning for a document another package's live run has
  already processed; a statement package grows through its own survey. The package's next step becomes "N new
  item(s) to process", and the rerun says that it takes the package as it is now.
- **Process only the pending items:** "Live run, pending items only (N)" (or a trial) takes only the documents no run
  of that kind has finished yet, with their own maximum cost, so the documents already processed are not paid for
  again. The earlier runs and their approval stay as they are: each live run is reviewed and approved on its own, the
  oldest open one first, Review names the other open live run's to-dos, and a workflow step is done only when no live
  run of its package is left open.

## v1.18.0 — 2026-10-17

GPT alone, without JEV, as a choice everywhere, with a safety net and measured.

- **One AI engine setting:** Settings › Processing chooses "JEV and GPT" (recommended) or "GPT only" for the
  application. A new package, a package whose settings were never saved, a mailbox download, a watched folder and a
  workflow step without its own choice take it; saved settings and started runs keep their own. A workflow step that
  makes its own package may choose its engine, and the estimate follows it. Every command that asks AI takes
  `--engine jev|gpt` (`--no-jev` stays); a measurement measures JEV and GPT unless told otherwise. The AI proposals in
  reconciliation follow the setting; with GPT alone the quick review has no "AI sure" group.
- **A safety net:** with GPT only, a JEV question is never sent, not even from the cache, and becomes a "JEV switched
  off" to-do; the native reader keeps GPT's facts when JEV is out, a GPT confidence that cannot be measured on an
  accounting field is a to-do, and a command that can make paid calls never runs without a budget (without one only
  earlier answers count). Every flow is tested with both engines, and a check lists each JEV question's counterpart.
- **Shown and measured:** the approval line, the review bar and an email's intent show the AI engine of the result.
  Measurements reuse an earlier GPT answer to the same question (a repeatability measurement always asks again), and
  the evaluation report reads the measurements without JEV and counts the wrong answers that passed without a to-do.
  With GPT alone, an outgoing invoice's buyer address shows its confidence but no longer opens a to-do on every
  invoice.

## v1.17.1 — 2026-10-17

The serious findings of a full code review, fixed.

- **Reconciliation:** a pairing whose invoice left the pairing (its amount corrected to zero, its issue date removed, a
  second copy of it arrived) and a pairing or a "needs no invoice" mark whose statement line was changed or read again
  used to vanish without a word, and the package could be approved. They are now listed with the pairings that no
  longer fit, under "Decisions that no longer count", each with its reason; they block the approval and can be
  revoked. A credit note refunding a paid invoice no longer cancels the next unpaid invoice of the same amount. A
  mistyped date no longer stops the exchange rate refresh.
- **Runs and workflows:** an interrupted mailbox download in a workflow still runs the package of the emails that
  arrived; a step restarted after a late interruption reuses its package and run instead of making second ones; a step
  whose package was deleted fails with the reason, so it can be started again. Only a queued or running run can be
  stopped (a finished one is superseded), and a person's stop always ends as stopped.
- **Without JEV:** the code's source check counts only a whole printed value, so a truncated invoice or tax number, or
  an amount with a shifted decimal place, opens a to-do. A live run asks the type detection again too.
- **Backups and data:** manual backups are counted apart from the daily ones and never push them out; the System page's
  "back up now" counts as manual. The native facts' downloads and the JSON download mask a full card number. The tests
  no longer touch the real OCR cache.

## v1.17.0 — 2026-10-16

The kind of incoming money, a quicker package list, and Python 3.12.15.

- **The kind of incoming money:** a bank line that brings money in and has no invoice to pair with now reaches the AI
  too, with its own question and seven kinds: a customer's payment, a transfer between own accounts, salary or other
  income, interest, a refund, an owner's payment, or other. The request says that the money came in; a line going out
  keeps its question unchanged, so its earlier answers are reused. A customer's payment without an outgoing invoice is
  listed in the quick review under "Invoice expected", for information; income suggests the salary reason, interest
  the fee reason and a transfer between own accounts the own-transfer reason, while a refund, an owner's payment and
  other suggest none. A partner's kind is passed on only to lines of the same direction, and
  the preselection offers only invoices on the line's side. `reconcile-ai --incoming` asks about a package's incoming
  money alone; `reconcile-ai --golden` measures the question on invented lines (`configs/golden_credit_kinds.json`).
- **The quick review** counts only the lines a person decides, not the ones it lists for information.
- **The package list:** the service builds the list when it starts, so its first opening after a restart no longer
  waits 5-8 s, and a request for rows still being built waits for that build. The list no longer builds every
  reconciliation workspace again every two minutes when nothing has changed (5-6 s on one core, slowing every other
  request): its own safety bound is 15 minutes, while the pairing page keeps two minutes and a change shows at once.
- **The worker's status:** the PDF protection report no longer fails now and then while the service reads it, and the
  worker removes its own lock file when it stops and those of ended workers when it starts.
- **Dependencies:** the dependency audit also checks the public release list for the running Python's latest patch
  release; a runtime behind it is a notice in the start-up check, the command and the System page, not a failure. The
  setup guide names Python 3.12.15, which the full test suite passed on.

## v1.16.0 — 2026-10-16

A refined workspace, one candidate for a domestic account number and its IBAN, and a round of free fixes.

- **A refined workspace:** every screen follows one design system. Text is set in IBM Plex (self-hosted), the
  burgundy accent marks only the main action of a view, and a state is a small mark in its own colour — done green,
  running blue, a person's turn orange, failed red — in the light and the dark theme, for screens 1366–1920 px wide.
  Every button that starts a run shows what the run may spend, a trial included. Tables no longer run off the side,
  and only a name-like column (a name, a file name, a path, an address) breaks inside a long value. The Result section
  shows its release state on one line; Reconciliation marks each line's state and keeps one solid action per view;
  a workflow marks the step that needs a person and gives only its start the solid button; the view of Word, Excel,
  text and CSV documents uses the shared controls and nothing smaller than 12 px. An editor's save is solid only while
  there is something to save. There is one density for everyone: the density switch is gone.
- **Bank account numbers:** a 16-digit domestic account number and its 24-digit or IBAN form are one candidate, not
  two, so the account question no longer splits its answer between two forms of the same account.
- **Amounts:** a dollar invoice that writes an amount without a thousands separator ("486.00") no longer opens a
  separator to-do when the invoice's own sum (net + VAT = gross) confirms the reading.
- **Bank statements and email:** a statement that would replace another one with different lines waits for a person,
  even when the earlier one comes from an approved live run. Every attachment of a suspicious email is processed but
  marked, and the run cannot be approved until a person has looked at it; such a statement never replaces another by
  the rule.
- **An own party's tax number as the supplier's:** `python -m jav.cli own-tax [--write]` lists the incoming invoices
  already in the store that this check flags and opens its to-do once on runs not yet approved, as the duplicates'
  scan does.
- **Smaller fixes:** the wizard's work package chooser answers at once; a long folder path or package name no longer
  pushes a workflow step's card off the screen; the statement comparison's row labels no longer break inside a word;
  a link drawn as a button stays readable when pointed at; the delete button is readable in the dark theme.
- **Dependencies:** pydantic-ai 2.53.0 (with openai 3.31.0) for two published advisories; neither affected feature is
  used here. The setup guide names Python 3.12.13.

## v1.15.0 — 2026-10-13

Superseding older runs, a faster package list, and the fixes of a four-way review.

- **Superseding an older live run:** a live run that is not approved keeps its to-dos open until it is approved, even
  after a rerun. When a later finished live run has processed the same documents again, a person can supersede the
  older one: it stays as a stopped run, its own open to-dos close (they are kept), and the work done on it (closed
  to-dos, corrected documents) is named before the click. The package's Processing section lists every such run, and
  the work package list counts them ("Older runs to supersede").
- **What waits for a person:** the next step, the open to-dos and the Review and Result tabs follow the package's
  current run; a run a person stopped after an earlier finished run no longer hides that run's to-dos or approval.
- **A faster package list:** the list answers at once from its last rows and brings itself up to date in the
  background ("Updating…" below it for a few seconds); a package of several hundred documents opens in a fraction of
  a second, and the run page, an item's review and the quick review are several times faster.
- **Reconciliation:** a forint bank line can pay several invoices in another currency together, split in the ratio of
  their converted amounts. A typed amount follows the shared number rules ("60.50" is refused in Hungarian instead of
  being read as 6050). A pairing that no longer fits its line or invoice after a correction is listed, blocks the
  approval and can be revoked. A payment counts as a transfer between own accounts only to an account an own party
  holds; a statement package's live run gives a new account to its party when the run is approved. The approval's
  blockers are grouped by reason.
- **Outgoing invoices:** the JEV path extracts outgoing invoices too; the bank account question takes the one account
  that is listed, whether it is printed as an IBAN or as a domestic number. A zero amount such as "0.00" opens no
  separator to-do and can be typed in a correction.
- **Review:** the package header follows the to-dos closed in Review; Review keeps its place when an item's last
  to-do closes; a value that cannot be saved names its field; an invoice's VAT check reads as an invoice's; a package
  counts no other package's to-dos on the same documents.
- **Workflows:** a merge of own parties moves their workflows, and a party a workflow names cannot be deleted; the
  package of an open workflow's step cannot be deleted; an interrupted start is released so the step can be started
  again; the control view follows its steps after an action.
- **Security and privacy:** a crafted bank statement file no longer keeps the service busy (bounded lines and
  patterns), an oversized file is refused before it is read, and a CSV stops at the cell limit; an email attachment
  named as a network path is refused before it is resolved; a statement folder's survey keeps to the folder; the
  downloads' formula guard covers the header row; the named copies' manifest no longer carries full local paths; a
  stored exchange rate is never overwritten; a full payment card number is masked when extracted data is saved and in
  every download; the data guard blocks bank exports, the data folder and card numbers.
- **Smaller changes:** an approval is checked again inside its transaction, so a run stopped meanwhile is never
  approved; a summer-time change day is counted with its own length; the test suite never opens the real store, and
  the readers' tests pass in a second checkout too.

## v1.14.0 — 2026-10-12

Workflows, a quick review of the pairing, outgoing invoices and incoming money.

- **New work wizard and workflows:** a new package starts from a list of the kinds of work, described as data and
  grouped, with an explanation before the choice. A template of several steps (for example a month's invoices,
  statements and reconciliation for one own party) makes a workflow: its steps start one another when the earlier
  ones are approved, a paid step starts only within its budget and otherwise waits for one, and a control view shows
  each step's state and what needs a person first. A workflow can be repeated for the next period; its document step
  then takes only the documents no live run has processed yet.
- **Bank files the system reads:** a catalogue, generated from the readers' own configuration, of every bank file kind
  the system processes (bank, account or card kind, format, read by code or by AI, what is read and checked), in the
  settings and in the documentation.
- **Quick review:** a reconciliation package's pairing opens with the lines grouped by what is known of them: a sure
  pair, the reason a person gave the partner's other lines, the bank's own category, salary (by code or as an AI
  answer), the AI's confident answers and the ones to review. Each group can be accepted at once, for all of its lines
  or the chosen ones; the rest go to the cards. It opens several times faster on large packages.
- **Invoice direction:** an invoice is incoming, outgoing, between own parties, not an own party's or undecided,
  computed in code from both sides' names and tax numbers against the own parties; conflicting sides are never taken
  as outgoing. The direction is shown in the run's document list and its Excel download. An outgoing invoice is never
  a candidate for a payment out; when a detailed type is uncertain between an outgoing and an incoming invoice, the
  own parties settle it, and a contradiction opens a to-do.
- **Incoming money:** a credit line can pay an own party's outgoing invoice, shown by its buyer. A forint bank line
  meets an invoice in another currency at the MNB rate of the fulfilment day (within ±0.5%) or of the booking day
  (within ±2%); outside these bands it is only listed when the line names the invoice. The Swiss franc is a handled
  currency. A credit line without a candidate stays for information.
- **Sent mail:** the Outlook download reads the Sent Items folder too, and an unknown folder name is an error instead
  of an empty result. A sent message is not asked about its intent (the question reads the sender's aim); its
  attachments are processed and decide the next step.
- **Trial runs' to-dos:** a trial run cannot be approved, so after a trial with to-dos the package's next step is the
  live run, with the trial's count as information. On the review page the earlier to-dos left by trial runs are hidden
  by default; a switch shows them.
- **Smaller changes:** a GPT call whose full upper bound no longer fits the run's budget is sent with a lean bound (one
  request, no validation retries), so a narrow budget can be used up without being exceeded; the full check keeps the
  interface tests' output and names a failing test.

## v1.13.0 — 2026-10-11

Reconciliation packages, bank statements read by code, and an approved reconciliation result.

- **Own parties:** the companies and persons whose money is reconciled, with their tax numbers, name variants, bank
  accounts and cards (Settings › Own parties). Code proposes them from the processed documents for free, and a person
  accepts them. Each invoice and account belongs to a party; a month-by-month data status says which months of an
  account lack a statement, are covered only in part, or have balances that do not check out.
- **Statement packages:** a new package for one party's bank statements of a period. The files are surveyed before
  anything is stored: every statement a bank's export holds, what it does to the store (new, replaces a statement,
  already there) and whose account it is. One valid statement per account and day: a better source replaces the
  earlier one, a person chooses between equals, and the decisions carry over.
- **Statements read by code, without AI:** a bank's Excel or CSV export (for example Revolut), the Erste XML export
  completed from its PDF statement, a bank's standard XML statement (ISO 20022 camt.053), and the CIB current account,
  investment account and credit card statements from the PDF itself or from the bank's text export. Each statement's
  balances are checked; a line keeps the bank's reference, the card (only its first six and last four digits), the
  purchase time, the terminal, the authorisation code, the exchange rate and the fee where the bank prints them.
- **Reconciliation packages:** one party's lines and invoices in three stages: Preparation (scope, coverage, what
  blocks the approval), Pairing and Result. A decision belongs to the pair of a line and an invoice, with an amount, so
  instalments, combined payments and credit notes are handled; every package with the same line shows the same
  decision.
- **Pairing:** cards keep together what belongs together, with every fact of both sides, the delay against the due
  date in days, overdue invoices and possible double payments. Pairing by hand uses a finder that compares the selected
  line with every invoice and marks what matches: name, invoice number, bank account. The bank's own PDF opens with
  the line framed. New candidates: card payments of foreign-currency invoices through the official MNB exchange rate,
  or on the original amount the bank prints; bills paid through a cheque payment app; names learnt from a person's
  decisions; one transfer naming several invoices. An equal amount alone is still never a pair.
- **Lines that need no invoice:** marked with a reason, one by one or per partner; the reason given earlier for the
  partner, or the bank's own category, is suggested. On the command line, `reconcile-ai` asks JEV or GPT for each new
  line's kind of payment within a budget (once per partner), and `reconcile-ai --evaluate` scores those answers
  against a person's decisions for free.
- **Result and approval:** a summary of every invoice (paid, partly paid, settled by a credit note, no payment in the
  covered period, not covered by statements) and every line (paired, needs no invoice, left out, open), downloadable
  as an Excel workbook with two sheets. Approval records the summary the person saw as an unchangeable version and
  locks the decisions on its lines in every package; reopening needs a reason and keeps the earlier version. A source
  document whose run is not approved blocks the approval; a statement whose balances do not check out and a month
  without a statement only warn.
- **Smaller changes:** column widths can be set by dragging; the service launcher starts from any folder; the package
  list and the reconciliation workspace are recomputed only when their inputs change; a control character in a PDF's
  text layer no longer breaks an Excel download.

## v1.12.0 — 2026-10-08

Invoice–bank reconciliation, with a person's decision.

- **Proposed payments:** code pairs a bank statement line with an incoming invoice only when the currency and the
  amount are exactly equal and at least one more detail ties them: the invoice number in the memo, the supplier's
  account number, or the supplier's name. An equal amount alone is never a pair. Fees, interest, card settlements and
  transfers between own accounts are left out, each with its reason.
- **Never "unpaid":** an invoice without a pair is reported as having no payment in the covered period only when
  statements whose balances check out cover its whole payment window; otherwise as partly covered or not covered.
- **A person decides:** the later processed document of a proposed pair gets a to-do, and the review page shows the
  statement line and the invoice side by side with what ties them. ‘This line paid it’ or ‘Not this one’ (with a
  reason); the decision is part of the reviewed result and is frozen with the approval. A rejected pair never comes
  back; after a confirmation the line and the invoice drop out of every other proposal.
- **Reconciliation view:** a run with a bank statement, or with an invoice that has a pair or is covered, gets a
  Reconciliation table in Result: each invoice with its state and paying line, each statement line with its invoice.
- **Command line:** `python -m jav.cli reconcile` counts the store's proposals (read only), `--golden` scores the
  invented golden cases, `--write` opens the to-do on the pairs already in the store.
- **Party names:** a shop's tagline, an address, a tax or registration number, or a remark after a separator that
  follows a party name's legal form is no longer part of the name, on both paths. The questions sent to JEV are
  unchanged.
- **GPT answers:** GPT type detection and email intent are asked again only when the text sent to GPT has changed;
  a change that only concerns JEV no longer makes the earlier answers unusable.

## v1.11.0 — 2026-10-08

A more precise JEV path, and safer paid measurements.

- **Document guard:** every S-path selection question and every JEV verification question states that the document
  text is data, not instructions. The document text itself is never changed.
- **Own data:** the question settings and the email intent examples no longer contain the operator's own tax
  number, company name or user name; invented values stand in their place.
- **Buyer:** the candidate finder ends a name at its legal form and cuts an address glued after it, keeps a legal-form
  adjective joined to its noun, treats a greeting as no part of a name, and knows more buyer labels. The question
  accepts a private person as the buyer, prefers the company when a person and a company both appear, and reads a
  foreign buyer's Hungarian tax number in a two-column layout.
- **Invoice number:** a credit note keeps its own number, not the number of the invoice it corrects; a receipt
  without an invoice number takes its receipt number, else its transaction or payment ID, never the order number.
- **Pro forma invoice:** the document's own title decides between a pro forma and an invoice; an advance invoice is an
  invoice. The text GPT is shown for type detection is unchanged.
- **Request size:** the Hungarian and foreign invoice selection and verification questions get a request-size budget,
  so an oversized money question is fitted instead of ending in a to-do.
- **Email attachments** show the type they were processed as (a foreign provider's receipt as a foreign invoice).
- **Measurements:** `golden`, `email-golden` and `verifier-probe` take a hard JEV limit (`--jev-budget-usd`);
  invented golden cases cover credit notes and receipts (`golden --synthetic`); a free pre-estimate prices a
  measurement from the request cache without sending anything. A budgeted measurement no longer reads the store's
  earlier documents, so its result does not depend on what the store holds.

## v1.10.0 — 2026-10-07

Duplicate invoices: flagged by code, decided by a person.

- **Duplicate check:** an invoice-like document (Hungarian, foreign, outgoing and utility invoices, pro forma
  invoices) whose invoice number and supplier match an earlier document gets a to-do when it is processed. The
  supplier is the same by its tax number, or by its name when a tax number is missing. Code compares the extracted
  and corrected values; no AI call is made. A pro forma invoice is never a copy of a final invoice.
- **Kinds:** a copy (the date, gross total and currency match too), a modified version (one of them differs) or
  undecidable (one of them is missing).
- **Decision:** the review page shows both documents' values side by side, the differing ones highlighted, with
  three buttons: copy, modified version, not the same invoice. The decision closes the to-do on both documents, the
  pair does not come up again, and it is part of the reviewed result an approval covers.
- **Effect:** nothing is deleted or merged. The Documents table and the export mark the repeat; the utility cost
  report counts a pair once until a person marks the two as different.
- **Earlier documents:** `python -m jav.cli duplicates` lists the duplicate pairs already in the store (counts only);
  with `--write` it opens the same to-do once on runs not yet approved.

## v1.9.0 — 2026-10-07

Azure text for scanned documents of an unknown type, and answer reuse for general facts.

- **Azure recognition taken over:** when a scanned PDF whose type has no type pack continues into general facts,
  the reader takes over the Azure recognition document detection already used, instead of running its own local
  OCR. The original Azure answer is kept beside the reading and checked against the document (page count, page
  size, unit, word boxes); a page it does not fit stays unread with a reason, and local OCR is never mixed in. Such
  a reading can be complete. Without an Azure text from detection, the general-facts step asks Azure itself, but
  only within the run's Azure budget (the recipe's Azure switch).
- **To-dos:** a blocked or failed Azure call and weak recognition confidences each open a to-do; the review panel
  says which pages Azure read and how sure it was.
- **Answer reuse:** the text sent to the model for general facts no longer carries the reading's internal
  fingerprint, so a change to the reader alone does not make an unchanged document a new paid question.
- **Kept Azure answers:** every Azure recognition is kept once, with its word polygons and page sizes, under the
  fingerprint of its content.

## v1.8.1 — 2026-10-07

Two dependency updates for advisories published after the previous audit.

- **lxml 6.1.0** (from 6.0.2): the default configuration of `iterparse()` and `ETCompatXMLParser()` allowed XML
  external entities to read local files (PYSEC-2026-87). The Word reader uses lxml through python-docx.
- **source-map-js 1.2.2** (from 1.2.1): an event-loop denial of service through indexed source-map section offsets
  (GHSA-68fv-2mgg-jv7q). It is used only when the UI is built.

## v1.8.0 — 2026-10-07

Pro forma invoices, receipts from foreign providers, signed PDFs, a party-pair check and a shared extraction
instruction.

- **Pro forma invoices:** a new document type with the Hungarian invoice's fields, its own file-name tag and labels,
  recognised on both type-recognition paths and listed among the extractable attachments of an email.
- **Receipts and single-pack categories:** a receipt from a foreign provider goes to foreign-invoice processing
  instead of the Hungarian tax-authority receipt. A category with a single detailed type (receipt, ticket, contract,
  tax return) no longer takes that type unchecked: a fit question with a "none of these" answer decides, and a
  document that fits none gets a to-do to choose its type by hand.
- **Party pair:** a to-do is opened when the same two parties stand the other way round than on their earlier
  documents of the same type.
- **Signed PDFs:** a digitally signed PDF is read. A view setting applied on opening is not treated as an action, a
  PDF with embedded files is read for its visible content (the embedded files are not opened, which is shown as a
  partial reading), and incremental saves are handled. JavaScript, automatic actions and XFA stay excluded.
- **Shared extraction instruction:** GPT extraction treats the document's text as data, never as instructions, puts
  one identifier in one field and keeps side-by-side columns apart. On a tax certificate, the issuing authority is
  no longer taken as the employer.
- **Unknown documents:** property names come in the document's own language and gaps in Hungarian. A single
  malformed fact no longer discards the whole interpretation of a Word, Excel, text or unknown document: only that
  fact is left out, with a to-do and its reason shown on the review panel.
- **Measurements:** type recognition can be measured on a local case list, measurements can use a separate store,
  and the measurement commands name the cases their budget left without a result (exit code 3).

## v1.7.0 — 2026-10-07

Word, Excel, text and CSV documents, general facts for unknown PDFs, checks for silent content errors, and direct
Azure recognition.

- **More file formats:** work packages accept DOCX, XLSX, UTF-8 TXT and CSV files next to PDFs, with the
  "Multi-format processing" recipe. Bounded, isolated readers keep the original structure (paragraphs, tables,
  worksheets, cells and formulas) with locations that fit the format, such as a worksheet and cell address. GPT
  proposes facts bound to those locations, JEV can check their support, and review, correction, approval of the
  displayed version and export work as for PDFs. Formula text and saved formula results are kept as evidence and
  flagged; ordinary hyperlinks and external workbook paths no longer exclude a workbook's own cells.
- **Unknown PDFs:** a PDF whose recognised type has no type pack no longer stops at a to-do; it continues into
  general, source-bound facts (the "Unknown PDFs" setting of both document recipes, on by default). A scanned one is
  read with local text recognition and always marked as a partial reading. The recognised type and its uncertainty
  are kept.
- **Silent content errors:** a to-do is opened for an unfilled template placeholder, a value whose kind (money,
  percentage, date, time) contradicts its property, one party named in two roles (on every PDF path, from the type
  pack) and a Word or Excel fact that JEV explicitly does not support.
- **Readable results:** the results of the new formats show gaps and to-dos as sentences, grouped by kind; the
  provider details are folded under technical details, and a "Source" column shows a short quote and location.
- **Azure recognition:** with its endpoint and key set, the paid escalation of weak local OCR calls Azure Document
  Intelligence directly, for a document in any folder; the key is only sent to the configured address. An analysis
  that was accepted but whose result was lost is recorded as uncertain and never repeated by itself. When the
  recipe's Azure switch is on but the escalation cannot run, the document gets a to-do instead of silently keeping
  the weak text. Earlier recognised texts stay reusable without a new charge.
- **Operation:** the System page shows the actual PDF memory protection of the service and of the worker; the
  processing recipes have distinct titles and input-based help; source copies and retried JEV calls with an unknown
  outcome are guarded; the test suite runs without provider keys.

Large workbooks over the reading limit, digitally signed or form PDFs in the general-facts path, PowerPoint and image
files, complete email attachment handling, and business duplicate and reconciliation workflows remain future work.

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
