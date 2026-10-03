# Independent native readers and source-bound interpretation

## Plain-language summary

The experimental reader package processes local files and decoded email attachments through the same bounded reading path. It preserves original bytes, source occurrences, structural evidence and visible gaps. It can propose flexible business facts through GPT, choose requested fields with JEV, or ask JEV to assess GPT proposals. Model results remain unreviewed; literal source matching is not a claim of business correctness.

The package runs separately from application ingestion, workers, review and the production store. Its command does not download mail or call a provider. Existing PDF processing remains in the application; this experimental command does not yet bridge to it.

## Run a local experiment

Use a separate Windows checkout and virtual environment. In addition to the repository dependencies, the measured native environment contains `python-docx==1.2.0`, `lxml==6.0.2` and `defusedxml==0.7.1`. Dependency changes have not been activated in the shared application environment. Missing reader dependencies produce a visible unsupported result.

```powershell
& .\.venv\Scripts\python.exe -m jav.readers .\synthetic-inbox --output .\runs\new-reading
& .\.venv\Scripts\python.exe tests/export_native_corpus.py .\runs\new-synthetic-corpus
```

The output directory must be new. It contains `bundle.json`, original content-addressed objects, frozen reading evidence and exact text versions. Loading a delivery verifies hashes, sizes, element content and child inventories without running a reader again. There is no schema migration or second persistent work queue.

## Measured native scope

| Input | Preserved output | Explicit remaining limitations |
|---|---|---|
| DOCX | Paragraph/table order, nested table structure, header/footer parts, image bytes and paragraph hosts | Images require OCR. Revisions, comments, text boxes, fields, merged table details and other unsupported structures remain visible gaps. No invented page number. |
| XLSX | Sheet/cell coordinates, empty positions, string identifiers, formula and saved-result distinction, hidden rows/columns/sheets, merged ranges | No formula evaluation. Display formatting remains in the original with a gap; media anchors, charts and other advanced parts need more adapters. |
| CSV | Row/column positions and literal values | UTF-8 and standard comma-delimited CSV only; dialect discovery is not claimed. |
| TXT | Exact decoded text and character references | UTF-8 only. |
| JSON/XML/HTML | Bounded, inert source text; JSON/XML validity checks | Dedicated structured paths and HTML layout are not implemented. No external XML resources or active HTML execution. |
| PNG/JPEG/TIFF/WebP | Original image frames and pixel bounds | OCR has not run; text extraction is not claimed. |
| EML | Headers, body text, decoded attachments, inline items, nested messages and visible MIME defects | Nested message serialization is derived from its original parent. This is an offered-file inventory, not proof that a mailbox bridge downloaded everything. |
| Other formats | Original occurrence and explicit unsupported result | No implicit Office conversion, legacy runtime import or unknown binary execution. |

## Boundaries and evidence

The parent passes frozen bytes into a Windows process after attaching a Job Object. It bounds memory, process count, wall time and output, removes provider credentials from the worker environment and kills the process on close. ZIP entry count, expansion size/ratio, cell visits, pixels and the complete source tree are bounded. Unsafe paths, active Office parts and external relationships are rejected.

After trusted dependencies load, a Python audit policy denies network, process, mutation and unrelated filesystem access. It is **not an operating-system sandbox for arbitrary malicious native code**. The measured adapters use in-memory Office/image libraries and forbid XML entities and external relationships. A future native dependency needs its own threat review. Failure to install the process boundary prevents parsing.

Large binary children are stored separately from the bounded structural evidence, which records their hashes and sizes. Reading, acquisition, interpretation and human review are separate states. A partial result must not be presented as full-source extraction.

The new package does not change `review_version`, existing source identities, approval behavior, current prompts or provider reservation rules. Windows integration requires the relevant application fixes and a coordinated shared-file change window.

## AI interpretation and comparison

`interpretation.py` defines entities, named properties, literal values, units, roles, related entities, citations and missing/conflicting states. It rejects invented quotes and mismatched occurrence/element references. Matching a quote does not establish that its proposed business role is correct.

`providers.py` implements three separately measured paths: GPT proposals, JEV selection from literal code-produced candidates, and JEV semantic support for grounded proposals. It uses the existing `calls` reservation ledger and the existing JEV adapter. The caller must select an isolated store and provider-specific measurement budget. Complete request sizes are checked; no silent source truncation occurs. JEV selection confidence and Noul support probabilities remain distinct, with no new activation thresholds.

The saved interpretation can be stored with the existing generic `store.save_artifact` operation in an explicitly scoped experiment. No document-specific table or automatic schema activation is introduced. Application worker/API/UI integration remains separate work.

A received GPT answer is saved as a private call receipt even when its interpretation schema is invalid. The receipt contains the original provider response, validation locations and reported usage. Such an answer raises `InterpretationRejected` and never becomes an interpretation; replaying it does not pay for another request. Transport failures retain the existing failed/uncertain handling, and an unknown price keeps the maximum reservation. A financially completed call is distinct from an accepted business result.

Compare extraction completeness and false claims against independently prepared labels. Report native reading coverage, exact evidence binding, semantic support, human correctness, latency and provider costs separately. Synthetic provider stubs test plumbing; they are never reported as live model quality.

## Library references and provenance

The native adapters use the provider/result boundary and library-opening/iteration/closing patterns documented in [NOTICE](../../jav/readers/NOTICE.md). They do not import the older runtime or implement an Office file format.

Word order uses the documented [`iter_inner_content` API](https://python-docx.readthedocs.io/en/latest/api/document.html). Excel formula and saved-value views use [`load_workbook`](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html). The local comparison exercises [Docling conversion](https://docling-project.github.io/docling/usage/) and [Unstructured partitioning](https://docs.unstructured.io/open-source/core-functionality/partitioning) on identical artificial Office bytes, without runtime network access. This small comparison does not establish a final general-purpose library choice or image/OCR capability.

New JEV questions follow the official [Choice](https://docs.typesafe.ai/primitives/choice) and [Noul](https://docs.typesafe.ai/primitives/noul) schemas. Their model outputs do not replace independent correctness labels or human approval.
