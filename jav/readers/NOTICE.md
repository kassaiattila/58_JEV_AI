# Source contract provenance

## Plain-language summary

The source contract preserves original content separately from its occurrences and reading attempts. It follows the earlier provider/result boundary and immutable evidence patterns in AIFLOW V4. Its structural and inventory models are newly written for this application. The contract module does not load the earlier application or parse Office files; separate native adapters in this package implement Office reading, and the delivery pipeline saves and reloads frozen evidence.

## Pattern references

AIFLOW V4 revision `4256cba9ee2b6f007c69d81eafc64d1419418e7f`:

| Source | Referenced behaviour | Local implementation |
|---|---|---|
| `sidecar/app/providers/base.py`, `Parser`, `ParsedDocument` | A small reader interface and an explicit result/evidence boundary | `contracts.py`: `Parser`, `ParsedDocument`, `EvidenceRef` |
| `sidecar/app/ocr_evidence.py`, `canonical_bytes`, `persist`, `load` | Canonical evidence bound to source and artifact digests; reload without another recognition call | `contracts.py`: `canonical_bytes`, `verify_evidence`; `pipeline.py`: `Delivery.save`, `Delivery.load` for isolated evidence persistence |
| `sidecar/app/grounding/source_layer.py`, `persist`, `load` | Source identity and incomplete-evidence distinction | `contracts.py`: manifest binding and visible reading issues |

The reference project declares [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0).
These are newly written behavioural adaptations, not copied implementations.
No legacy database, network client, storage path resolver or approval implementation
is carried over. No third-party Office reader implementation is bundled.

## Native adapter extension

The new `native.py` uses the `DocxParser.parse` and `XlsxParser.parse` behavioural
patterns from `sidecar/app/providers/docx.py` and `xlsx.py` at the same revision:
open through `python-docx`/`openpyxl`, iterate library objects and close workbooks
in `finally`. The code is newly authored around structural references, two Excel
views, an explicit child inventory and bounded isolated execution. It does not
copy the earlier paragraph-first/table-last or empty-cell-dropping algorithms.

The runtime dependencies retain their own licences: python-docx (MIT), openpyxl
(MIT), lxml (BSD family, including its bundled libraries), defusedxml (PSF) and
Pillow (MIT-CMU). The isolated experiment records exact installed licence files,
versions and hashes. Docling and Unstructured are comparison candidates in a
separate environment and are not runtime dependencies of these adapters.

The local OCR process has its own resource boundary; it does not inherit the
Python reader's audit policy. Saved attempts distinguish these protection scopes
and retain an explicit partial result when OCR lacks filesystem/network isolation.
The subprocess environment disables dotenv loading before application imports;
normal application configuration loading is unchanged.

## PDF and local recognition extension

`visual.py` reuses this repository's `jav/pdf.py:build_layout` and
`jav/source_layer.py:build` without persisting into the application store.
`visual_ocr.py` reuses `jav/ocr.py:parse_tsv` at pixel scale. These preserve the
same-reading text/geometry pattern referenced above; no legacy runtime is loaded.

PDF parsing uses the existing pdfplumber dependency (MIT); page rendering uses
the existing pypdfium2/PDFium dependency and its bundled third-party notices.
Local recognition uses installed Tesseract (Apache-2.0), without redistributing
its executable or language models. The standard
[TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html) and
[PDFium rendering API](https://pypdfium2.readthedocs.io/en/stable/python_api.html)
are used with explicit source-coordinate mapping and retained raw evidence.
