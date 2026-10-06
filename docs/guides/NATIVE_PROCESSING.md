# Native document processing

## Plain-language summary

Word documents, Excel workbooks, UTF-8 text and CSV files retain their original
structure and literal values throughout processing and review. Reading a file,
receiving a model answer and approving a result are separate events. A saved
result preserves reading gaps, provider uncertainty and the original proposal,
even when a reviewer later supplies a corrected value.

## Application boundaries

`native_contracts.py` defines the shared format registry and typed result shapes.
PDF continues through the existing document graph. Native formats use
`flow_native.py`; OCR is disabled on this route, with one exception below. A PDF
whose recognised type has no fitting type pack (no pack for its category, "none
of these" for the detailed type, or the unknown type) continues from detection into this graph
on the G path, when the recipe's `unknown_documents` setting is `facts` (the
default since 120; `review` keeps the earlier stop). A text PDF is read as it is;
a scan, whose detection text came from OCR, is read with the reader's local OCR
under its own reading identity, and such a reading is always `partial` (local OCR
has no filesystem or network isolation), so it keeps a to-do. It is not continued
after a failed classification step or without any text. The recognised
type and its uncertainty to-dos stay; only the "no extraction for this type"
to-do is closed. Every place that chooses between the native and the classic
result asks `native_results.native_item`, so such a PDF is reviewed, exported
and approved as a native result. The graph receives the frozen
work-run, item, graph, source and recipe identities explicitly. It uses the
existing worker, budget context and review queue.

The graph saves a reading, interprets its bounded source view, publishes the
result and records review reasons. Burr state contains references and processing
settings, not a second copy of the source text. A resumed graph reuses saved
outcomes and publications. A started but uncertain provider attempt cannot cause
an automatic replacement call.

## Immutable evidence and publication

`native_results.py` owns three record families: readings, terminal interpretation
outcomes and run-item publications. A reading freezes the complete reader
Delivery: `objects`, `evidence`, `texts`, `rasters` and the canonical `bundle.json`.
Files live beside the selected application database under `native/readings/`.
The reader implementation, configuration and models contribute to reading
identity; a changed reader creates another reading rather than rewriting one.

The complete Delivery is written, loaded and verified before its database
reference is published. Interrupted directories remain unreferenced. No automatic
cleanup is performed. Backup callers obtain verified relative paths, sizes and
digests through `referenced_artifacts`.

A publication binds one run item to one source, reading, outcome and optional
successful Interpretation. It verifies the frozen run input and recipe under a
writer transaction. Repeating identical publication returns the existing record;
different content is a conflict. A caller-supplied SQLite connection is borrowed
without commit or close. Approval prevents adding another publication.

Result-version fingerprints include immutable evidence identities. Their read
path verifies saved artifacts before a cached result can be returned. Missing,
redirected or changed evidence fails explicitly; it is never silently reparsed.

## Outcomes and receipts

Reading status and interpretation outcome are independent. Before publication,
the item has no result identity and `result_ready` is false. A terminal publication
makes `result_ready` true, including rejected, failed or uncertain outcomes. This
flag means an intact published record is available; approval additionally needs
successful interpretation and intact evidence.

The interpretation outcomes are `not_started`, `running`, `succeeded`, `rejected`,
`failed` and `uncertain`. Only `succeeded` carries a valid reader Interpretation.
A successful answer containing no facts is an empty success, not a refusal or
transport failure. Received invalid, empty or refused GPT responses retain their
private response receipts and reported usage. Unknown cost remains null and keeps
the existing reservation semantics.

`native_processing.py` calls the existing reader provider adapters and
`runtime.calls`; it adds no provider ledger or SDK route. Budget estimates bound
the GPT request and output, optional JEV verification and JEV alias resolution.
The JEV-off setting omits both its budget and its call. The S path is rejected
before processing because native discovery has no predefined selection contract.

Large source views are partitioned into requests within the same 80,000-byte
transfer limit. Worksheet rows stay together, with the first two rows repeated
as context. Every readable element is accounted for in the saved interpretation's
coverage record and request digests. Identical proposals with identical citations
are deduplicated; conflicting proposals remain separate. Cross-part relationships
remain an explicit review gap. JEV verification batches preserve cited rows and
headings. A row or citation context that cannot fit fails explicitly before that
provider stage starts. Each request retains its own receipt and uses the existing
run budget: partitioning does not increase an approved budget. A later failure
preserves the receipts and produces a failed or uncertain outcome, never a
successful partial interpretation. The reader's separate cell limit still applies.

Explicit reuse allows the existing request-key receipt/cache mechanisms. Live
mode disables cross-run GPT reuse and JEV cache reads/writes, while same-step
crash recovery still replays a completed receipt. The native JEV cache is scoped
to the selected store. A cache-only answer is preserved as a private artifact;
it does not invent an invocation or the original answer's unknown paid cost.

## Source views and human review

Source pagination returns complete reader elements, including empty cells,
containers, order, formula and cached-value distinctions. It is not the reduced
model-input view. Every page carries the publication and result identities.

Citation requests contain only occurrence, element and exact quote. The server
resolves the locator from that publication's verified reading. TXT positions use
Unicode codepoints. An exact quote span is returned only when the quote has a
unique occurrence within its element; repeated matches retain their count and
have no falsely unique span.

Stable fact identifiers preserve duplicate properties and original proposals.
Literal grounding, raw semantic support, effective corrected value and human
confirmation remain distinct. A correction does not turn a partial reading into
a complete one or establish the machine proposal's factual correctness.

Formula text, saved formula results and their unverified state reach the model
together. Citations to an exact saved result resolve to its original cell. A
formula or saved result used as a business value raises a review warning; no
recalculation occurs. The shared content checks (`configs/fact_checks.json`,
`jav/fact_checks.py`) also raise a warning when a value is an unfilled template
field (`[Name]`, a run of dots, a date mask) or when its kind (money,
percentage, date, time) conflicts with the meaning of its property and unit;
a currency value claimed as a time quantity is one such conflict. A JEV support
in the existing default band's `no` range (`native.support` in `policy.json`)
opens a `native:fact:<n>:unsupported:<p>` to-do; the uncertain range does not,
as on the PDF path. These checks preserve the original proposal and literal
match; they do not establish general semantic correctness or introduce a new
threshold. Older saved interpretation hashes remain unchanged on reload, and
earlier results are not re-checked automatically.

The provenance and parser limitations remain documented in
[Native readers](NATIVE_READERS.md) and [Reader provenance](../../jav/readers/NOTICE.md).
