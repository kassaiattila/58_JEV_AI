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
`flow_native.py`; OCR is disabled on this route. The graph receives the frozen
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

The provenance and parser limitations remain documented in
[Native readers](NATIVE_READERS.md) and [Reader provenance](../../jav/readers/NOTICE.md).
