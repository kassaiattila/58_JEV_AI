# Configuration files

**In force:** since 2026-09-30 (071, v1.0.5). **Audience:** developers, and users who configure the system.

## Plain-language summary

Every tunable part of the system lives in a configuration file, not in the program code: the descriptions of document types and email intents, the questions put to the AI models, the decision thresholds, the models and their prices, the recipes' budgets and the limits of the local service. Every file has a version number and a changelog, and a fingerprint computed from its content goes into the call-log row of every paid call, so any measurement can be traced back to the settings it ran with. When a question or description sent to a model changes, the next measurement goes through paid calls again, so a sub-budget has to be approved first; thresholds, limits, budgets and switching on a new flow are the owner's decision. The running local service and the worker read the configuration only when they start, so they must be restarted after a change.

## 1. Common rules

A configuration file puts the "config as data" principle into practice ([glossary](../GLOSSARY.md)): the program is the mechanism, the file holds the parameters. Changing a setting is therefore a matter of editing a file and measuring, not of programming, and every change leaves a trace.

1. **Format.** JSON, UTF-8, LF line endings (written from Python with `encoding="utf-8"`). Every file starts with a `meta` block: `name`, `version` (three parts, for example `1.4.0`) and `changelog` (entries with `version`, `date` and `note`). The loader (`jav/cfg.py`) rejects a file without a version.
2. **Fingerprint (`config_hash`, "hash" from here on).** The hash is a shortened sha256 of the file's content (16 hex digits). The changelog is not part of it, so a note does not change it; the version number is part of it. The hash goes into the call-log row of every JEV and GPT call made by the flows, together with all the configuration inputs of that call: the call site, the registry or type pack, and the pack's instruction and schema files.
3. **When re-measuring costs money.** The JEV cache key is made up of the exact model version, the state sent and the questions; the hash is not part of it. Any change to a question, the instruction, the glossary or the description of an option (`what` / `not_for` / `examples`) therefore produces a new key, and the next golden run goes through live, paid calls. A bare version bump, or a change to a label or a threshold, does not trigger new calls (OCR is the exception, see section 3). GPT extraction has no response cache, so every run of the G path is paid.
4. **How a content change is made** (CLAUDE.md §4):
   - bump `meta.version` (by convention the third number for a fix and the second for an extension), and append a `changelog` entry that names the round and the reason;
   - run the affected tests;
   - if text sent to the model has changed, do a golden run on the affected flow;
   - run `python -m jav.cli docs` to regenerate the call-site catalogue (local, not in the repository) and the flow descriptions;
   - restart the local service and the worker (section 3).

   A live, paid measurement may only start with a pre-approved sub-budget, on a clean working tree, with the commit hash recorded.
5. **The owner decides** (CLAUDE.md §1 and §2) on thresholds and routes, the set of types and intents (type boundaries), budgets, the limits of the local service, and switching on a new flow or a paid step. The decision is recorded, with its date, in the decisions log (local, not in the repository). The "Decision needed?" column in section 2 shows this for each file.
6. **Personal data** must not go into a configuration file either; examples must use made-up values. If a made-up tax number or bank account number happens to have valid check digits, the value must be added to the data guard's exception list ([development workflow](DEVELOPMENT.md), section 1).

## 2. Top-level files (`configs/*.json`)

Every change in every row requires a version bump and a changelog entry; the "After a change" column lists what else is needed. "Restart" means `.\scripts\dev.ps1 stop`, then `start`, if the service is running.

| File | Role | Read by | After a change | Decision needed? |
|---|---|---|---|---|
| `capability_catalog.json` | The expected inventory of types and intents: which detailed types and intents must exist, and which old intents have been retired. A coverage check that makes no calls. | `jav/capability_catalog.py` | `python -m jav.capability_catalog`; `pytest tests/test_capability_catalog.py` | Follows the decision on the set of types and intents |
| `data_guard.json` | The data guard's rules: blocked and allowed paths, blocked extensions, value and key patterns, the email domains accepted as made up, the exception list of made-up values (`allow`, `allow_why`), tolerated own data (`known`) and forbidden phrases (`deny`), both stored only as sha256, and the old history that must not be pushed (`forbidden_history`). | `jav/data_guard.py` (pre-commit and pre-push hooks) | Applies from the next commit; to scan the whole tree: `python -m jav.cli data-guard` | `allow`: no, but a reason is required; `known`, `deny`, `forbidden_history`: yes |
| `datasets.json` | Hungarian labels for the enumerated values in datasets (statuses, modes, next step), the size of the run-data cache, and the row limit for downloads. | `jav/datasets.py`, `jav/export.py`, `jav/mailbox.py` | restart | No |
| `doc_types.json` | The document-type registry (M1): broad categories with `what / not_for / examples / parent` descriptions, parent families and the unknown type; `old_type_map` maps each detailed type to its broad category. | `jav/doc_types.py`, `jav/detect.py`, `jav/capability_catalog.py` | `detect-golden` (new key, live calls), `detect-determinism`; `docs`; restart | Yes (type boundaries, set of classes) |
| `email_tasks.json` | The task proposal's set of actions, evidence rules and length limits, and the routes that never get a proposal. The GPT instruction is in `jav/prompts/email_tasks_prompt.md`; the hash covers it too. | `jav/email_tasks.py`, `jav/datasets.py`, `jav/export.py`, UI | restart; `cd ui; npm run build` | Yes for the set of actions, no for the limits |
| `field_labels.json` | The Hungarian names of fields, list columns and document types in the UI and in downloads. | `jav/datasets.py`, `jav/export.py`, `jav/mailbox.py`, UI | `pytest tests/test_field_labels.py`; restart; `npm run build` | No |
| `grounding.json` | The label dictionary used to find source locations (the printed labels for each field) and its distance tolerances. | `jav/grounding.py` | `pytest tests/test_grounding.py`; restart; machine-found source locations change in new runs, and `python -m jav.cli reground` recomputes them for existing runs (without AI calls); the UI searches again for the location of a corrected field when it is opened | No |
| `intents.json` | The email intent registry (M3): intents with `what / not_for / examples / parent` descriptions, families and the "other" intent. | `jav/intents.py`, `jav/intent.py`, UI | `email-golden` (live), `email-determinism`; `docs`; restart; `npm run build` | Yes (set of classes) |
| `lang_guard.json` | The language guard's ratchet (073): for each tracked file, the maximum number of lines containing Hungarian letters (`baseline`; a file without an entry may have none), and the patterns that are never counted (`allow`, for example the UI translation files). | `jav/lang_guard.py` (`python -m jav.cli lang-guard`, start-up check) | `python -m jav.cli lang-guard --update` lowers the baseline after a conversion step, and `--accept <path>` raises it for one file (document vocabulary, test data); the command rewrites `baseline` itself, without a version bump | No; every accepted file shows up in the diff |
| `models.json` | JEV alias and GPT model, price list, timeout, retries (075: `openai.sdk_max_retries`, the OpenAI client's own retries, 0), the JEV cache version, how long a resolved alias stays valid, the Burr project names, and the Azure DI page price (`azure_di.usd_per_page`, 075; here and not in `ocr.json`, whose hash is part of every OCR cache key). | `jav/config.py` (directly, at start-up), `jav/adapters/jev.py`, `jav/admin.py` | Bumping `cache_version` invalidates every cache key (every call becomes live); the budget does not allow a GPT model without a price to be called; restart | Yes for a model change and for the cache version; prices follow the provider's price list |
| `ocr.json` | The OCR pipeline: engine, resolution, page limit, the tesseract settings and location, the old Docker and Azure routes, and the switch for the paid Azure escalation (currently on; its thresholds are in `policy.json`; since 075 a worker run escalates only within its Azure budget, set by the recipe's `azure_ocr` switch). | `jav/ocr.py` | `python -m jav.cli ocr` (engine status); every document goes through OCR again (section 3); restart | Yes for the escalation switch (paid) |
| `policy.json` | The decision rules: bands and thresholds (`bands`, `band_for`), OCR quality and escalation thresholds, the email routes, the anchor margin for detailed types, and the "none of these" label (`none_label`). | `jav/policy.py`, `jav/eval_report.py`, `jav/admin.py` | No rerun is needed: `eval-report` shows for free, from the raw runs, how many cases would change band; restart. The exception is `none_label`, because it goes into the question as an option | Yes |
| `recipe_help.json` | Explanatory text for the recipes and their settings (the **Recipes** (*Receptek*) page and the recipe card). It is a separate file so that correcting the text does not flag a recipe change. | `jav/work_views.py` | `pytest tests/test_recipe_help.py`; restart | No |
| `recipes.json` | The flow recipes: steps, input, parameters, the per-item budget by path and provider (`max_item_usd`, `max_item_usd_by_kind`, `param_item_usd`; 075: `azure_ocr` on = 0.02 USD Azure DI per document, and a parameter missing from an older assignment counts with its default), and the number of attempts (`max_attempts`). Each recipe also carries its own `version`. | `jav/work.py`; the worker reads the run's copy of the recipe | The recipe's own `version` is bumped too; existing assignments show a "recipe changed" warning (`recipe_changed`); restart | Yes (budget, new recipe, default setting) |
| `reports.json` | The fields of the utility-cost report and the download format (CSV separator, and the prefixes of cells that look like formulas). | `jav/report_utility.py`, `jav/export.py` | restart; the formula-protection list must not be narrowed | No |
| `service.json` | The local service: address and port, allowed host names, request size, the folder restriction and allowed roots, the development UI's address, the display limits of the confidence bands, input limits, and the daily backup (time, retention, and the second backup location, for example a network drive). | `jav/api.py`, `jav/pdf.py`, `jav/ocr.py`, `jav/backup.py`, `scripts/backup-task.ps1` | restart; for the backup time: `.\scripts\backup-task.ps1 install` | Yes (limits, folders, backup) |

Besides these files, the `python -m jav.cli configs` list also includes the call sites (`callsite:<name>`) and the type packs (`type:<key>`). The base packs, the experiments and the legacy type copies are not in it (sections 5–7).

## 3. When a change takes effect

The local service and the worker read each configuration file once, when it is first used, and keep it in memory until the process ends; they do not re-read it while running. Command-line commands see the current state every time they start.

| Where | When it sees the change |
|---|---|
| Local service and worker | After a restart (`.\scripts\dev.ps1 stop`, then `start`). |
| A run that has already started | The recipe and the budget are fixed when the run starts (configuration snapshot), so a recipe change does not affect it. The worker read the type pack, the questions and the thresholds when it started, and keeps working with those. |
| UI | `field_labels.json`, `intents.json` and `email_tasks.json` are built into the UI: `cd ui; npm run build`, then reload the browser. |
| Command line (golden, `configs`, `backup`) | Immediately, every time it starts. |
| Data guard (git hooks) | At the next commit or push. |
| Daily backup | The backup starts as a new process every day and reads the `backup` section itself. Only a change of the **time** requires the task to be reinstalled: `.\scripts\backup-task.ps1 install`. |
| OCR cache | The key includes the hash of `ocr.json`: after any change (even a bare version bump), every document goes through OCR again. With escalation switched on, this can also mean paid Azure pages. |

## 4. Call sites (`configs/callsites/`)

A call site ([glossary](../GLOSSARY.md)) is a point in a flow where JEV is asked a question. Its file holds everything the model sees of the question: the English instruction and glossary, the descriptions of the options, the yes/no questions, the template of the presence question, the number of lines that go into the state, and the request-size budget. Any textual change to the file therefore produces a new cache key: the next golden run and every new run go through live, paid calls. The rules for writing these files are in the [JEV playbook](../JEV_PLAYBOOK.md) and in the JEV checklist of CLAUDE.md.

| File | What it asks | Read by | Measurement after a change |
|---|---|---|---|
| `detect.json` | Broad document type (Choice over the registry), whether the issuer is Hungarian, language (M1) | `jav/detect.py` (hash together with the registry) | `detect-golden`, `detect-determinism` |
| `detect_detail.json` | The detailed type within the broad category, when the anchor score does not decide; the options are the type packs' descriptions | `jav/detect_detail.py` (hash together with all type packs) | `detect-golden` |
| `email_intent.json` | Email intent (Choice), signals (Noul), urgency (Score), injected instruction (M3) | `jav/intent.py` (hash together with the intent registry) | `email-golden`, `email-determinism`, `email-injection-probe` |
| `select.json`, `select_foreign.json`, `select_utility.json` | S path: a choice per field among the code's candidates, with a presence question, grouped into requests | `jav/jev_select.py` (hash together with the type pack) | `golden --arm S --type <key>`; before that, the free `recall` |
| `verify.json`, `verify_<key>.json` | G path: error flags (Noul) on the fields of the GPT extraction | `jav/jev_verify.py` (hash together with the type pack) | `golden --arm G --type <key>`, `verifier-probe` |

- The `select_callsite` and `verify_callsite` fields of a type pack name the call sites it uses.
- A `verify_<key>.json` inherits the shared error questions through `"inherits": "verify"`, and mainly adds the type's field descriptions (`field_specs`), glossary and request-size budget. The verification call sites of the types taken over from the legacy project were built this way (`jav/typepack_convert.py`).
- `request_char_budget` and `option_context_max` make up the request-size budget ([glossary](../GLOSSARY.md)): for an oversized request, the code trims first the text, then the descriptions, and finally the number of candidates.

## 5. Type packs (`configs/types/`)

A type pack ([glossary](../GLOSSARY.md)) holds all the type-specific data needed to extract data from one document type. It states which fields exist and of what kind, which of them are required, high-stakes or informational only, which checks run, which path the extraction takes, and which question set it uses. The extraction flow is type-independent, so a new type needs a new pack, not new code, as long as the existing field kinds are enough. The loader (`jav/typepack.py`) checks the kinds and the field names in the lists, and raises an error on a mismatch.

| Key | Role |
|---|---|
| `document`, `parent`, `detect`, `auto_detect` | Description (also one of the options of the detailed-type question); broad category from the registry; the keywords of the anchor score (`required_any`, `supporting`, `excluders`); whether the type takes part in automatic detailed detection |
| `fields`, `list_fields`, `enums` | Field → field kind; the columns of line lists; the enumerated values |
| `scored_fields`, `informational_fields`, `required`, `high_stakes` | Scored, informational-only, required and high-stakes fields; these determine the band check and which fields get presence questions |
| `validators`, `text_labels` | Code checks (`"review": false` = flag-only check); the labels of free-text fields |
| `candidate_profile`, `arms`, `default_arm` | Candidate profile (`hu`, `intl`, `utility`); the paths the pack can run; the recommended path |
| `select_callsite`, `verify_callsite` | The names of the two call sites (for a pack without an S path, the first is `null`) |
| `prompt_file`, `schema_file` | The G path's instruction and output schema under `jav/prompts/`; the pack's hash covers their content too |
| `golden_type_key`, `extends` | The golden set's type name in the legacy project; the name of the inherited base pack |
| `legacy_transforms` | The legacy project's transformation rules, recorded by the one-off converter for reference; the runtime does not read them |

**Inheritance.** With `extends`, a pack inherits a base pack from `configs/types/_base/` ([glossary](../GLOSSARY.md): base pack). The base's fields, lists, checks and schema are placed before the child's; today the common part of Hungarian utility bills is such a base. A base pack cannot run on its own and is not in the `configs` list, but the child's hash covers it.

**After a change:** `golden --arm S|G --type <key>` where a golden set exists (the types taken over from the legacy project only have synthetic samples); for the S path, the free `recall` first. The description and the field lists also go into the question, so changing them may produce a new cache key.

**Adding a new type** (there is no separate guide yet):

1. pack: `configs/types/<key>.json`, with a `meta` block, and `extends` if needed;
2. instruction and schema: `jav/prompts/<key>_prompt.md` and `<key>_schema.json`;
3. verification call site: `configs/callsites/verify_<key>.json` (`"inherits": "verify"`), and a selection call site too for the S path;
4. a Hungarian name for every field and list column in `field_labels.json` (`tests/test_field_labels.py` flags any that are missing);
5. inventory: `doc_types.json` → `old_type_map` and `capability_catalog.json` → `expected_document_keys`, otherwise the inventory check fails;
6. tests with synthetic data only, then `python -m jav.cli docs`;
7. until the owner has decided on the type boundary, `"auto_detect": false`, so the type does not take part in automatic detection.

## 6. Experiments (`configs/experiments/`)

Settings and synthetic cases for finished and ongoing capability trials: claim assessment, source finding, injected instructions, learning branches and the like. Their format is not uniform: some have a `meta` block, others use a top-level `version` field. Neither the `configs` list nor the shared hash covers them; the experiment code records its own source fingerprints in the raw run. They are read by the experiment code (`jav/experiments/`) and by a few learning or trial modules run from separate commands (`jav/document_learning.py`, `jav/document_chunks.py`, `jav/claim_assessment.py`, `jav/source_find.py`); the local service and the worker do not read them. Changing them therefore has no effect on work-package runs. A paid trial needs a pre-approved sub-budget (some files also set their own cost cap, for example `budget_usd`), and case descriptions may only use synthetic or anonymised data.

## 7. Legacy type copies (`configs/legacy_types/`)

A verbatim copy, per type, of the legacy project's type folders: schema, instruction, rules, detection keywords and the old descriptor. Alongside them is a `manifest.json` with the source path and the sha256 of every file. Some folders also contain `fixtures/synth_*.json`; these are purely synthetic samples. They are read by:

- `jav/legacy_packs.py`: checks the fingerprints on loading and raises an error on a mismatch;
- `jav/legacy_runtime.py`: the learning branch's extraction, following the old schema;
- `jav/capability_catalog.py`: coverage;
- `jav/typepack_convert.py`: the one-off converter that built the corresponding type packs and verification call sites from them.

These files are not edited, because they are source copies. Behaviour is changed in the type pack or call site built from them. They have no `meta` block, they are not in the `configs` list, and automatic routing is switched off for them (`automatic_routing_enabled: false`).

## 8. Checks

- `python -m jav.cli configs`: the name, version, hash and latest changelog entry of every top-level file, call site and type pack. Look up versions and hashes there; this guide deliberately does not list them. `python -m jav.cli admin` shows the same together with the models and prices, and the generated state snapshot (local, not in the repository) contains it too.
- `python -m jav.cli preflight`: its configuration line lists the same. Load errors (invalid JSON, a missing version) show up here and in the tests.
- Tests: `tests/test_cfg.py` (every file loads, the version has three parts, the changelog is not empty, the hash is stable and unaffected by the changelog), `tests/test_field_labels.py`, `tests/test_capability_catalog.py`, `tests/test_recipe_help.py`, `tests/test_encoding_guard.py` (accented text written back with the wrong encoding), `tests/test_docs_071.py` (this guide names every `configs/*.json` file).
- When a new top-level configuration file is added, `tests/test_docs_071.py` fails until this guide names it; its row in the section 2 table still has to be written by hand.

The full order of changes (which measurement follows which change): [architecture](../ARCHITECTURE.md), section 4, "Tuning and changes". Installation and the folder restriction: [setup](SETUP.md).
