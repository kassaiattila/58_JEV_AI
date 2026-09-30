# JEV playbook: model facts, call sites and question design

**Valid from:** 2026-09-20 · **Fully refreshed:** 2026-09-30 (073), against the code and the live pages of docs.typesafe.ai · **Model:** `jev-1.13.0` (behind the `jev-latest` alias)

## Plain-language summary

JEV is the TypeSafe model that answers narrow, typed questions about a document or an email: pick one option (Choice), give the probability of a yes (Noul), or place something on a graded scale (Score). This playbook records what the model can and cannot do according to its official documentation, how this project calls it, and the rules for writing new questions. Every call goes through a single adapter that caches answers, records the cost and turns an outage into a to-do instead of a failed run. The thresholds that decide what a person must review live in one policy file, never in the code. The model's known weak spots (counting, arithmetic, dates, long irrelevant text) are handled in code before the question is asked.

## 1. Model facts (jev-1.13.0, checked 2026-09-30)

| fact | value and source | what it means here |
|---|---|---|
| price | $0.042 per million input tokens; output tokens are free ([Models](https://docs.typesafe.ai/models)) | The state size is the only cost driver; one more question in the same request is almost free. The price is in `configs/models.json` (`jev.usd_per_mtok_input`). |
| context | 64k tokens per request (the state plus all questions); 32k for the state plus the single longest question ([Models](https://docs.typesafe.ai/models)) | A whole 1–3 page PDF fits; a corpus does not. Long documents use the request-size budget (section 3). |
| Choice options | **at most 255 per Choice**: "A Choice question accepts up to 255 options" ([Choice](https://docs.typesafe.ai/primitives/choice)); "You can have a maximum of 255 options per Choice" ([API reference](https://docs.typesafe.ai/api)). The installed SDK (`typesafe-sdk` 0.7.0) does not check the count on the client side; the limit belongs to the API. | Our code caps the candidates at 250 (`MAX_OPTIONS` in `jav/candidates.py`), so `none` and a small reserve always fit under 255 (section 3). |
| Score levels | at least 2, "the API accepts up to 10"; each level needs a distinct description ([Score](https://docs.typesafe.ai/primitives/score)) | Grades use a Score, never a Noul. A bare number is a poor level description. |
| rate limits | 100K tokens per second and 40 requests per second for jev-1.13.0; "adjusting dynamically" and may change without notice; over the limit → `429` ([Models](https://docs.typesafe.ai/models)). The 2026-09-17 docs said 250k tokens/s and 1,200 requests/min. | The SDK retries with backoff; our explicit `RetryPolicy` is in `configs/models.json` (`jev.retry`). |
| input | text only: a string, a JSON object or an array of text values | Scans are turned into text first (OCR, `jav/ocr.py`). |
| language | "English is the primary training language"; other languages "are handled but not equally well; test on your own content" ([Models](https://docs.typesafe.ai/models)) | Only our own golden sets show that a Hungarian or German verbatim state works, and only for the measured model version. |
| alias | `jev-latest` and `jev-preview` both point to `jev-1.13.0`; an alias moves when a new release ships; the response's `model` field reports the version that answered | The cache key and the ledger use the concrete version (section 2). |
| model list | `GET /v1/models` lists only the aliases; versioned IDs such as `jev-1.13.0` are accepted anyway | The adapter resolves the alias with a small probe request (section 2). |
| customisation | no fine-tuning; answers are shaped through the state, the instructions, the criteria and code composition | This matches our "configuration as data" rule: questions live in JSON files. |
| SDK logging | `TYPESAFE_LOG_LEVEL=debug` logs the request body unredacted | `guard_sdk_logging()` in `jav/config.py` lowers the SDK log to WARNING unless `JAV_ALLOW_SDK_DEBUG=1` is set. |
| SDK version | locked at `typesafe-sdk==0.7.0` (`requirements.lock`): Pydantic-based, provides `TypeSafeClient`, `AsyncTypeSafeClient`, `RetryPolicy` and `response_model`. Newer releases ([changelog](https://docs.typesafe.ai/sdk/python/changelog)): 0.7.1 (2026-09-21, validates the API key early and keeps the key value out of logged exceptions) and 0.7.2 (2026-09-26, optional `http2` extra). | An upgrade is a lockfile change followed by a golden run. The 0.7.1 key-redaction fix is relevant to our security rules. |

**Known weak spots** ([Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)): the model reads literally; it does not count or do arithmetic; it does not compare dates; indirection and double negation hurt it; a large state full of irrelevant detail lowers accuracy ("context rot"); adversarial content can shift the answer; contradictory instructions and criteria confuse it; it has **no structural invariants** (a Noul is not a yes/no Choice, P(yes) and P(no) from two separate Nouls need not add up to 1, and a Noul threshold cannot be reused for a Choice); it does not generate text. Our answer to each: compute, filter and compare in code, and split the decision into atomic questions.

## 2. The single entry point: `JevAdapter.ask()`

Every JEV call in the runtime goes through `jav/adapters/jev.py`: `get_adapter().ask(request_id, state, questions, run_id=…, use_cache=…, config_hash=…)`. Flows never call the SDK directly.

| concern | behaviour | where |
|---|---|---|
| request-hash cache | The key is the SHA-256 of the cache version, the **concrete** model version, the state and the questions; the answer is stored as `runs/cache/<sha256>.json`. A cache hit costs nothing, so re-evaluation and golden reruns are free. Any change to an instruction, option or description gives a new key, so the next call is live and paid. An unreadable cache file becomes a live call and is rewritten atomically. | `request_hash()`; `configs/models.json` `jev.cache_version` (2) |
| model version in the key | The alias is resolved with a one-Noul probe (about 100 tokens) and remembered in `runs/cache/_model_versions.json` for `alias_ttl_hours` (24). Offline, an expired entry is still used, with a warning. If a live answer reports a different version, the answer is stored under that version's key and the resolution is refreshed. | `resolve_model()`, `_remember()` |
| retries and timeouts | An explicit `RetryPolicy` from `configs/models.json` `jev.retry`: 3 retries, backoff 0.5–8 s with jitter, 240 s in total per SDK call; the per-request timeout is `jev.timeout_s` (90 s). The SDK retries 408, 429 and 5xx by default. | `jav/config.py` `make_client()`, `build_retry_policy()` |
| ledger | Every call becomes a row in the SQLite `ledger` table: run id, step, provider, concrete model, tokens, USD, seconds, cache hit, cache key, `config_hash` and error. Cache hits, the probe and failed calls are recorded too. | `store.ledger_add()` |
| cost | Input tokens × `usd_per_mtok_input` (0.042); output is free; cache hits and replays cost 0. | `JEV_USD_PER_MTOK` |
| call log and budget | Inside a worker run the physical call goes through the call log: it reserves an upper cost estimate from the run's budget before the call, and a replayed step returns the saved answer without a new charge. An exceeded budget becomes `budget_exceeded`; an earlier attempt with an unknown outcome becomes `uncertain_attempt`. | `jav/runtime/calls.py`, `JevAdapter._live()` |
| failures | An SDK error after the retries (rate limit, 5xx, timeout, connection, an incomplete or invalid response) writes a ledger row with the error and raises `JevUnavailableError(reason)`, for example `TypeSafeRateLimitError:429` or `TypeSafeBadRequestError:400:max_tokens_exceeded`. The flows turn it into the review reason `jev_unavailable:<reason>` (a to-do for a person) and carry on; the email flow routes the message to `human:jev_unavailable`. Programming errors still raise. | `jav/flow.py`, `jav/flow_detect.py`, `jav/flow_email.py`; `configs/policy.json` `email.jev_unavailable_route` |
| determinism measurement | `use_cache=False` inside `with adapter.no_cache_write():` reads nothing from the cache and does not overwrite the stored reference answers, so the measurement sees the real run-to-run variation. | `no_cache_write()` |
| replay and tests | `CacheOnlyAdapter` answers only from the cache and never calls the provider; `use_adapter()` binds an adapter to one run without replacing the default. | same file |

## 3. Request size and the option limit

The server limit is in tokens (section 1), but counting tokens needs the model, so our budget is in **characters**. Hungarian text averages about 2.5 characters per token, but the ratio depends on the text source: the Azure OCR text gave more tokens per character than the tesseract text. The character budget is therefore an estimate, backed by one retry.

- **`request_char_budget`** (call-site key, characters). `select_utility` and every `verify_*` call site except `verify` and `verify_foreign` use 110,000. Without the key there is no fitting and no retry.
- **`ask_within_budget()`** (`jav/jev_budget.py`) builds the request to fit the budget and asks. If the server still returns `max_tokens_exceeded`, it retries **once** with the smaller of the budget and the size actually sent, times 0.6 (`RETRY_BUDGET_FACTOR`). If that also fails, the error reaches the flow as `jev_unavailable:<reason>`. The failed first call stays in the ledger, and the reduction is visible in the raw run (`JevCall.state_chars`).
- **Fitting on the S path** (`jav/jev_select.py`, `_fit_budget`), step by step until the request fits: (1) the state keeps only the candidate lines of the fields being asked; (2) the option context shrinks to 80 characters; (3) the options per question are capped at 60, 40, then 25, keeping candidates on total lines first and the rest in document order. The questions and the `none` option never change.
- **Fitting on the G path** (`jav/jev_verify.py`): (1) `source_lines` shrinks to the evidence lines ±1; (2) if that is still too large, `source_lines` is dropped and the Nouls judge from `printed_on` alone. With `glossary_in_state: true` the glossary goes into the state once instead of into every Noul instruction.
- **`option_context_max`** (`select_utility`: 170) limits the characters of source context in each Choice option description, for candidate-heavy OCR requests.
- **Option cap.** `build_choice()` keeps the first 250 candidates (`MAX_OPTIONS`) and adds `none`, so a Choice has at most 251 options, under the 255 limit. The cap truncates; it does not split a long list into windows. Money candidates on utility bills are capped lower, at 100 (`max_money_options` in the utility candidate profile, `jav/candidates.py`).

## 4. Call sites

A call site is a point in a flow where we ask JEV (see the [glossary](GLOSSARY.md)). Each one has a JSON file in `configs/callsites/` that holds everything the model sees: the English instructions and glossary, the option descriptions, the Noul questions, the presence template, the state limits and the request-size budget. Any text change in that file gives a new cache key, so the next golden run and every new run make live, paid calls. The file's `config_hash` (combined with the registry or the type pack) goes into every ledger row. `python -m jav.cli docs` generates a catalogue of the call sites with ledger statistics into `docs/callsites/` (local, not in the repository). The file format is described in [the configuration files guide](guides/CONFIGS.md).

There are 24 call sites: 3 for selection, 18 for verification, 2 for detection and 1 for email intent.

### 4.1 Selection (S path): code finds candidates, JEV chooses

Module: `jav/jev_select.py`. For each document there is one request per field family (the `requests` block). Each request holds a Choice per field over the candidates that code found, plus `none`; a presence Noul `<field>__present` for each field ("is this field printed at all?"); and extra Choice questions. The state is the document lines where that family's candidates appear (±1 line), with line ids such as `L01:`. Code copies and normalises the chosen value; the record confidence is the weakest judgement.

| call site | type packs | requests | extra questions |
|---|---|---|---|
| `select` (1.1.2) | `invoice_hu` (Hungarian invoice) | `parties`, `header`, `money` | `currency`, `payment_method` |
| `select_foreign` (1.0.0) | `invoice_foreign` (foreign supplier invoice) | `foreign_parties`, `foreign_header`, `foreign_money` | `currency`, `supplier_country` |
| `select_utility` (1.0.1) | the six Hungarian utility packs that extend `utility_bill_hu`: `villamos_energia_szamla` (electricity), `foldgaz_szamla` (gas), `viz_szamla` (water), `vizmuvek_szamla` (Budapest waterworks), `csatorna_szamla` (sewerage), `mohu_szamla` (waste) | `utility_parties`, `utility_header`, `utility_money`, `utility_meter` | `currency`, `payment_method`, `reading_method` |

### 4.2 Verification (G path): GPT extracts, JEV checks

Module: `jav/jev_verify.py`. Code first checks that each extracted value is printed in the source (`find_evidence`); a value with no source line is `unsupported`, and JEV is never asked to do fuzzy string matching. JEV judges only what needs understanding, with all Nouls in one request (fan-out). Each Noul instruction is an object rather than a formatted string: `glossary`, `field_spec` (name and meaning), `extracted_field` (the raw value), `printed_on` (the evidence lines) and `question` (the SDE-cascade pattern, `verify` 1.1.0).

The Noul questions are defined once in `verify.json`; the other verification call sites inherit them (`inherits: verify`) and add only their own field descriptions (`field_specs`) and field lists.

| Noul | a "yes" means |
|---|---|
| `absence_wrong` | the field was left empty, but the document prints a value for it |
| `off_target` | the value belongs to another field |
| `wrong_kind` | the value is a different kind of number (for example a phone number given as a tax number) |
| `incomplete` | the printed value is longer or more complete than the extracted one |
| `parties_swapped` | the supplier and the buyer are swapped |
| `line_items_missing_rows` | at least one printed goods or service row is missing from the extraction |
| `line_items_extra_rows` | the extraction contains a row that is not a printed goods or service row |

| call site | type packs | notes |
|---|---|---|
| `verify` (1.1.0) | `invoice_hu` | defines the Noul questions |
| `verify_foreign` (1.0.0) | `invoice_foreign` | inherits the Nouls; own field descriptions |
| `verify_utility` (1.0.1) | the six utility packs | inherits; `request_char_budget` 110,000; glossary in the state |
| 15 × `verify_<type>` (1.1.0, 047) | one type pack each, converted from the legacy project; these packs have only a G path | inherits; `request_char_budget` 110,000; glossary in the state |

The 15 type-specific call sites: `verify_altalanos_szerzodesi_feltetelek` (general terms and conditions), `verify_belepo_jegy` (admission ticket), `verify_certificate`, `verify_csapatmenedzser_utasitas` (team manager instruction), `verify_id_document`, `verify_insurance_claim_form`, `verify_invoice_out` (outgoing invoice), `verify_meeting_minutes`, `verify_meghivo` (invitation), `verify_nav_certificate`, `verify_nav_receipt`, `verify_nav_tax_return` (NAV is the Hungarian tax authority), `verify_statement_cib`, `verify_statement_erste` (bank statements), `verify_terkep_adat` (map data).

### 4.3 Detection (M1)

| call site | module | questions and state |
|---|---|---|
| `detect` (1.0.0) | `jav/detect.py` | One request: `doc_type` Choice over the type registry (`configs/doc_types.json`: 12 types plus `unknown`, each described by `what / not_for / examples / parent`); `issuer_is_hungarian` Noul; `language` Choice. State: the first 40 and last 8 lines (at most 160 characters each), code-side `features` (counts of tax numbers, VAT ids, IBANs, dates, currencies) and keyword `anchor_hits`. The `config_hash` covers both the call site and the registry. |
| `detect_detail` (1.0.0) | `jav/detect_detail.py` | `detail_type` Choice: the detailed type within the broad category. The options are the type packs of that category, described by each pack's `document` field, plus `none`. JEV is asked only when the legacy keyword anchors leave more than one type: code decides alone when the leading type has a required anchor and leads the second by at least `detect_detail.anchor_margin` (0.75, `configs/policy.json`). State: the first 40 lines. |

### 4.4 Email intent (M3)

| call site | module | questions and state |
|---|---|---|
| `email_intent` (1.1.0) | `jav/intent.py` | One request: `intent` Choice over the intent registry (`configs/intents.json`, 11 intents in 6 families); Nouls `requires_action`, `mentions_deadline`, `attachment_is_the_subject`, `multiple_requests` (measured only, it changes nothing) and `prompt_injection` (a "yes" opens a to-do and routes the message to `human:suspicious`); Score `urgency` (4 levels, each a concrete situation). State: subject, sender, attachment names and types, code-side `features`, and up to 60 cleaned body lines (at most 200 characters each). |

### 4.5 Outside the catalogue

The learning branches (`jav/learning_runtime.py`, `jav/email_learning_runtime.py`) and the experiments (`jav/experiments/`, settings in `configs/experiments/`) call the same `ask()` with their own question sets. They are measured separately and are not part of the call-site catalogue.

## 5. Policy thresholds (`configs/policy.json`)

Raw probabilities stay in the state; thresholds live only in `configs/policy.json` and are read by `jav/policy.py`. The review latch is additive: `needs_review` can only change from False to True. Changing a threshold is the owner's decision, followed by a version bump and a golden run. `python -m jav.cli eval-report` re-evaluates earlier raw runs under the current bands at no cost.

Band sets (policy 1.9.0):

| band set | key | value | meaning |
|---|---|---|---|
| `default` | `noul_no_max` | 0.3 | a Noul P(yes) below this is "no" |
| `default` | `noul_yes_min` | 0.7 | at or above this is "yes"; in between is "uncertain" |
| `default` | `choice_human_max_conf` | 0.6 | a Choice confidence below this goes to a person |
| `default` | `choice_second_min_gap` | 0.2 | a gap between the top two options below this is "uncertain" |
| `default` | `uncertain_review` | false | the "uncertain" band alone does not open a to-do |
| `default` | `parent_min_prob` | 0.85 | when the type or intent is uncertain, the parent family can serve as the label if its summed probability reaches this |
| `high_stakes` | `choice_human_max_conf` | 0.85 | stricter for high-stakes fields (the list is in each type pack) |
| `verify_flag` | (empty) | — | inherits every value from `default` |

`band_for` maps each judgement point to a band set; the longest matching prefix wins. `invoice.pick.high_stakes` uses `high_stakes`, `invoice.verify` uses `verify_flag`, and everything else uses `default` (`invoice.pick`, `invoice.pick.presence`, `detect.doc_type`, `detect.issuer_is_hungarian`, `detect.detail_type`, `email.intent`, `email.signal`, `email.urgency`).

Other sections of the same file: `email` (intent routes, `low_conf_route` `human:low_confidence`, `jev_unavailable_route` `human:jev_unavailable`, `signal_review` and `signal_routes` for `prompt_injection` → `human:suspicious`), `detect_detail.anchor_margin` (0.75), and `ocr` (review and Azure-escalation thresholds for OCR quality, which do not involve JEV).

## 6. Question-design checklist

The short form of this list is the JEV checklist in `CLAUDE.md`.

**Language and state**

- Write the instructions and the glossary in English. The state is verbatim text, in Hungarian or English; option keys are verbatim or normalised source values.
- Put into the state only what the question uses; irrelevant text distracts the model. Number the lines (`L01:`) so that an answer can point to its evidence.

**The question**

- Name the narrowest deciding fact. If explaining a wrong answer needs "what I actually meant was…", that half-sentence is missing from the instruction.
- One judgement per question; never hide several judgements in one.
- Pick the type by the shape of the answer: Choice for a closed set; Score for a grade (at most 10 levels, each level a concrete situation, not a degree); Noul for yes or no; Score also for an ordered three-way decision (not it / maybe / it).
- Every Choice has a `none`, `unknown` or `other` option. At most 255 options (our cap: 250 candidates plus `none`); deduplicate the candidates.
- Describe confusable Choice options with `what / not_for / examples` (the registry schema, `jav/registry.py`).
- Add few-shot examples only if they are consistent with the golden set.

**Thresholds and confidence**

- A Noul gets a two-sided band (no / uncertain / yes). Noul and Choice thresholds are not interchangeable, and no arithmetic identity holds between questions.
- Every optional field's Choice gets a presence Noul next to it. The record confidence is the weakest judgement.
- Thresholds go into `configs/policy.json` only.

**Code before the model**

- Numbers, dates, string matching, arithmetic and checksums are done in code, before the question. A different kind of number (a phone number offered as a tax number) gets only 0.57–0.63 from JEV, so a checksum validator is mandatory.

**Measurement**

- Measure with the concrete model version (the response's `model`, recorded in the ledger), not the alias. Re-measure calibration for every new version. Non-English accuracy is proven only by our own golden sets.
- Any change to a call-site file gives a new cache key: run the golden set (live, paid). Measure determinism with `use_cache=False` inside `no_cache_write()`. Say so openly when a refinement was tuned on the training examples.
- Before writing a new kind of JEV question, read the relevant page of docs.typesafe.ai.

**Never:** use JEV to generate text; use a Noul to measure a degree; let the model compare numbers or dates; hide several judgements in one question.

## 7. Documentation patterns we adopted

The first version of this playbook (2026-09-20) compared the docs' recommendations with each call site and proposed nine items. Their status on 2026-09-30:

| # | area | pattern from the docs | status |
|---|---|---|---|
| 1 | adapter | concrete version in the cache key; explicit `RetryPolicy`; errors into the ledger and a to-do instead of a failed flow; SDK log guard | done (2026-09-20). A parallel worker pool for bulk runs was not built: the worker processes one item at a time. |
| 2 | policy | two-sided Noul bands, second-option gap, stakes-based threshold, named band sets, coarser parent label when uncertain | done (policy 1.1.0–1.2.0) |
| 3 | evaluation | per-question accuracy and bands, calibration curve (bin by bin: probability against hit rate), top probability against `confidence`, policy re-evaluation, determinism | done (`jav/eval_report.py`, `eval-report`). A version-independent entropy-based confidence is still open (section 8). |
| 4 | registry schema | `what / not_for / examples / parent`; the Choice criteria are built from it | done (`jav/registry.py`) |
| 5 | S path | presence Noul for every optional field; record confidence = minimum; line id of the evidence stored with the data point | done |
| 6 | G path | structured Noul instruction; two-sided band for the flags | done (`verify` 1.1.0). On the verifier probe (deliberately corrupted values): 2 corruptions moved from the uncertain band into the yes band, so they are now caught, with 0 false alarms. |
| 7 | email signals | `urgency` Score instead of a yes/no, `multiple_requests` Noul, `prompt_injection` Noul | done (`email_intent` 1.1.0). Intent golden set 96/96 with 0 flips; an instruction planted at the top of an email was caught 24/24, but one placed in the part that the body cleaner removes was invisible: the guard question sees only what the decision sees. An injection check on documents before the G path is still open (see the [security notes](SECURITY.md)). |
| 8 | method | this checklist, in `CLAUDE.md` and in section 6 | done |
| 9 | extensions | B1 line stitching and block types (autoformat cookbook), B2 ML gate with CatBoost (autoresearch cookbook), B3 matching and deduplication (entity-alignment and re-ranking cookbooks), B4 hierarchy (hierarchical-classification cookbook) | plans only; re-read the cookbook when the work starts |

The measurement evidence for items 1–7 is in handoffs 006–011 and their raw runs (local, not in the repository).

## 8. What the docs leave open

- **Accuracy on non-English text.** The docs give no number. Ours was 100% on 12 + 49 + 96 golden cases (invoice selection, document detection, email intent) on 2026-09-20: a small sample, and the questions were refined on the same cases.
- **The confidence formula** is not published; the docs promise a separate cookbook. Noul answers carry no `confidence`. The formula on an older migration page (1 − normalised entropy) can be computed from `probabilities` as a version-independent measure, but the evaluation report does not compute it yet.
- **Rate limits and the version behind `jev-latest`** can change without notice. The model recorded in the ledger is the ground truth.
- **Characters per token** vary with the text source, so the request-size budget is an estimate with one retry (section 3).

## Technical details

- Official docs (read in full 2026-09-17 to 2026-09-20; the facts in section 1 re-checked 2026-09-30): the index is `https://docs.typesafe.ai/llms.txt`; every page is also available as Markdown at `https://docs.typesafe.ai/<path>.md`. Pages used here: `models`, `primitives/choice`, `primitives/score`, `api`, `confidence`, `model-jaggedness/jev-1.13`, `sdk/python/changelog`.
- Background reports (local, not in the repository): `JEV_CAPABILITY_INTEGRATION_2026-09-21.md` (JEV capabilities against our own development experience) and `STACK_TRIAL_RESULTS_2026-09-21.md` (a comparative measurement).
- Code: `jav/adapters/jev.py` (entry point), `jav/jev_budget.py` (request-size budget), `jav/jev_select.py` (S path), `jav/jev_verify.py` (G path), `jav/detect.py`, `jav/detect_detail.py`, `jav/intent.py`, `jav/policy.py`, `jav/registry.py`, `jav/candidates.py` (`MAX_OPTIONS`), `jav/config.py` (`make_client`, `build_retry_policy`, `guard_sdk_logging`).
- Settings: `configs/models.json` (1.2.0), `configs/policy.json` (1.9.0), `configs/callsites/*.json`, `configs/doc_types.json`, `configs/intents.json`, `configs/types/*.json`.
- Related documents: [architecture](ARCHITECTURE.md), [configuration files](guides/CONFIGS.md), [glossary](GLOSSARY.md).
