# Independent native readers and source-bound interpretation

## Plain-language summary

The experimental reader package processes local files and decoded email attachments through the same bounded reading path. It preserves original bytes, source occurrences, structural evidence and visible gaps. It can propose flexible business facts through GPT, choose requested fields with JEV, or ask JEV to assess GPT proposals. Model results remain unreviewed; literal source matching is not a claim of business correctness.

The package runs separately from application ingestion, workers, review and the production store. Its command does not download mail or call a provider. Its PDF adapter reuses the application's line builder and word-layer model without changing the existing application PDF path.

## Run a local experiment

Use a separate Windows checkout and virtual environment. The shared `requirements.lock` pins the measured native dependencies: `python-docx==1.2.0`, `lxml==6.0.2` and `defusedxml==0.7.1`; install that lockfile as described in [Setup](SETUP.md). Missing reader dependencies produce a visible unsupported result. Installing the dependencies does not by itself connect these readers to the application workflow.

```powershell
& .\.venv\Scripts\python.exe -m jav.readers .\synthetic-inbox --output .\runs\new-reading
& .\.venv\Scripts\python.exe -m jav.readers .\synthetic-images --ocr --output .\runs\new-local-ocr
& .\.venv\Scripts\python.exe tests/export_native_corpus.py .\runs\new-synthetic-corpus
```

The output directory must be new. It contains `bundle.json`, original content-addressed objects, frozen reading evidence, exact text versions and any recognition rasters. Loading a delivery verifies hashes, sizes, element content, child inventories and PDF word references without running a reader or OCR again. There is no schema migration or second persistent work queue.

## Measured native scope

| Input | Preserved output | Explicit remaining limitations |
|---|---|---|
| DOCX | Paragraph/table order, nested table structure, header/footer parts, image bytes and paragraph hosts | Images require OCR. Content controls, revisions, comments, text boxes, fields, merged table details and other unsupported structures remain visible gaps and prevent a complete status. No invented page number. |
| XLSX | Sheet/cell coordinates, empty positions, string identifiers, formula and saved-result distinction, hidden rows/columns/sheets, merged ranges | No formula evaluation. Display formatting remains in the original with a gap; media anchors, charts and other advanced parts need more adapters. |
| CSV | Row/column positions and literal values | UTF-8 and standard comma-delimited CSV only; dialect discovery is not claimed. |
| TXT | Exact decoded text and character references | UTF-8 only. |
| JSON/XML/HTML | Bounded, inert source text; JSON/XML validity checks | Dedicated structured paths and HTML layout are not implemented. No external XML resources or active HTML execution. |
| PDF | Native words, line references and frozen page-relative word layers; optional local OCR of visual pages | Active content and forms are excluded, except a form whose fields are all digital signatures (a signed PDF; any action, an XFA form or another field kind still excludes the file). An opening view setting (a page and a zoom) is not an action; an opening action is. Embedded files are never opened: the visible content is read and the reading is partial. An object a cross-reference table lists but the file lacks is skipped. Annotations remain visible gaps; only their presence is checked, so cyclic signature widgets do not stop the reading. A page with differing crop/media boxes or inconsistent rendered dimensions is omitted before admitting native words or OCR, with a visible partial-reading issue. Native text and recognised visual text are separate evidence layers. |
| PNG/JPEG/TIFF/WebP | Original image frames and pixel bounds; optional local OCR text with original-pixel regions | Without `--ocr`, unread text is explicit. Empty OCR is not proof of a blank image. Pixel orientation is preserved; no EXIF-based deskew or display rotation is inferred. |
| EML | Headers, body text, decoded attachments, inline items, nested messages and visible MIME defects | Nested message serialization is derived from its original parent. This is an offered-file inventory, not proof that a mailbox bridge downloaded everything. |
| Other formats | Original occurrence and explicit unsupported result | No implicit Office conversion, legacy runtime import or unknown binary execution. |

## Boundaries and evidence

The parent passes frozen bytes into a Windows process after attaching a Job Object. It bounds memory, process count, wall time and output, removes inherited provider credentials, disables child-process dotenv loading before imports and kills the process on close. This child-only setting does not disable the application's normal dotenv loading. ZIP entry count, expansion size/ratio, cell visits, pixels and the complete source tree are bounded. Unsafe paths, active Office parts and unknown external relationships are rejected. Spreadsheet hyperlinks and external workbook paths are retained without following them; external connections are not refreshed. They produce explicit reading gaps while local cells remain available. Macros, DDE, OLE and embedded executable parts remain excluded.

After trusted dependencies load, a Python audit policy denies network, process, mutation and unrelated filesystem access. It is **not an operating-system sandbox for arbitrary malicious native code**. The measured adapters use in-memory Office/image libraries, forbid XML entities and never resolve external relationships. A future native dependency needs its own threat review. Failure to install the process boundary prevents parsing.

Local OCR is explicit and uses only installed Tesseract and configured local language files. The adapter feeds canonical PNG bytes to a fixed stdin/stdout command in a separate Job Object, with a credential-free environment and bounded time, memory, process count and output. It does not use the application's paid OCR escalation. Tesseract is a trusted native dependency, not a Python process covered by the audit hook; this is not a claim of operating-system network isolation. Original filenames never become engine arguments. The executable, adjacent DLLs, model files and recognition settings contribute to the recorded model identity.

An OCR attempt records parser and recognition protections separately, with the weakest values reported in its aggregate protections. Python-parser protections must remain enforced; OCR does not claim filesystem or network isolation. Recognised text is retained with `partial` status and an explicit `protection_unavailable` issue. The typed scopes must agree with the aggregate and frozen evidence, and the recognition resource bounds remain mandatory. Older parser-only deliveries omit these optional scope fields, preserving their saved bundle bytes and digest on reload.

A scanned PDF can instead take over an Azure Document Intelligence recognition that the application already obtained (124, `jav/readers/external_recognition.py`). The reader never calls Azure itself: it receives the kept original recognition, checks it against the frozen PDF (no more pages than the document, page size within one point, unit inch, every word box on its page, the word limit), and maps the word polygons onto the unread visual pages with the same word conversion and line tolerance as document detection. The result is a separate word layer with the engine `azure_di`. A page the recognition does not cover or does not fit stays unread with an explicit `needs_ocr` reason, and local OCR is never mixed in. The original is kept in the delivery under its digest (`recognitions/`), and the attempt records it as an `ExternalRecognition`. Loading a reading checks the kept recognition's digest, size and description and the saved layer's binding to it, without mapping it again: a later change to the shared word or line code must not make earlier readings unloadable. Such a reading has no local recognition boundary, so it can be complete.

PDF and image text, coordinates, rasters and raw TSV belong to the same source reading. OCR failures keep the source and a visible reason; native PDF words remain available when local recognition fails. PDF OCR coordinates are mapped using the actual raster width and height rather than an assumed DPI. The experimental PDF bound is at most twelve pages, further restricted by the supplied inventory and pixel budgets. Reopening saved evidence never backfills missing OCR automatically.

Large binary children are stored separately from the bounded structural evidence, which records their hashes and sizes. Reading, acquisition, interpretation and human review are separate states. A partial result must not be presented as full-source extraction.

The new package does not change `review_version`, existing source identities, approval behavior, current prompts or provider reservation rules. Windows integration requires the relevant application fixes and a coordinated shared-file change window.

## AI interpretation and comparison

`interpretation.py` defines entities, named properties, literal values, units, roles, related entities, citations and missing/conflicting states. It rejects invented quotes and mismatched occurrence/element references. Matching a quote does not establish that its proposed business role is correct.

`providers.py` implements three separately measured paths: GPT proposals, JEV selection from literal code-produced candidates, and JEV semantic support for grounded proposals. It uses the existing `calls` reservation ledger and the existing JEV adapter. The caller must select an isolated store and provider-specific measurement budget. Complete request sizes are checked; no silent source truncation occurs. JEV selection confidence and Noul support probabilities remain distinct, with no new activation thresholds.

Experiments can save interpretations with the existing generic `store.save_artifact` operation. The application uses the dedicated [native processing boundary](NATIVE_PROCESSING.md): immutable readings, terminal outcomes and once-only run-item publications. The source contracts remain independent of that application storage, and no inferred document type automatically activates a schema.

A received GPT answer is saved as a private call receipt even when its interpretation schema is invalid, the provider refuses the request or the answer is empty. A captured single response is required; validation details are optional. The receipt contains the original provider response, available validation locations and reported usage. Such an answer raises `InterpretationRejected` and never becomes an interpretation; replaying it does not pay for another request. One exception (123): when the only defect is the presence rule of single facts (a fact marked missing that quotes a value, or a stated value without citations), `salvage()` keeps the other facts and records the left-out ones in `Interpretation.discarded_facts`; the native graph opens a `native:discarded_facts:<n>` review item, and the review panel lists each left-out fact with its reason. Any other defect still rejects the whole answer. The schema sent to the model is unchanged, so saved answers keep their keys. Transport failures retain the existing failed/uncertain handling, and an unknown price keeps the maximum reservation. A financially completed call is distinct from an accepted business result.

Native GPT output explicitly requests the provider's strict JSON schema mode. Local Pydantic strictness alone does not enable that wire setting: optional defaults can make the SDK choose non-strict output. Request bounds and cache identity include the transformed wire schema; local field limits, citation checks and cross-field validation still apply after receipt.

Compare extraction completeness and false claims against independently prepared labels. Report native reading coverage, exact evidence binding, semantic support, human correctness, latency and provider costs separately. Synthetic provider stubs test plumbing; they are never reported as live model quality.

For a like-for-like comparison with JEV selection, `extract_gpt(fields=..., entity=...)` accepts the same requested field descriptions and names. This task is included in request bounds and replay identity. Keep this controlled extraction separate from open-ended property discovery: identical literal values with different discovered entity/property names do not pass an exact schema-label metric.

## Library references and provenance

The native adapters use the provider/result boundary and library-opening/iteration/closing patterns documented in [NOTICE](../../jav/readers/NOTICE.md). They do not import the older runtime or implement an Office file format.

Word order uses the documented [`iter_inner_content` API](https://python-docx.readthedocs.io/en/latest/api/document.html). Excel formula and saved-value views use [`load_workbook`](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html). The local comparison exercises [Docling conversion](https://docling-project.github.io/docling/usage/) and [Unstructured partitioning](https://docs.unstructured.io/open-source/core-functionality/partitioning) on identical artificial Office bytes, without runtime network access. This small comparison does not establish a final general-purpose library choice or image/OCR capability.

New JEV questions follow the official [Choice](https://docs.typesafe.ai/primitives/choice) and [Noul](https://docs.typesafe.ai/primitives/noul) schemas. Their model outputs do not replace independent correctness labels or human approval.
