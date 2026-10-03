# Source contracts

## Plain-language summary

A source object describes original bytes, while an occurrence records where those bytes arrived. A reading result keeps structure, exact values and visible gaps separate from later interpretation and human review. The independent native readers use this contract for Office and other supported files, and their delivery pipeline saves and reloads frozen evidence. Integration with application ingestion, review and approval remains separate work; see [Native readers](NATIVE_READERS.md).

## Model boundaries

`jav/readers/contracts.py` is independent of the store, application operations and
provider clients. Its immutable Pydantic models reject unknown fields. External
JSON enters through `read_bundle`, which bounds its size, depth and node count,
rejects duplicate keys and uses strict types. These are envelope-validation
bounds, not production file-size or parser-resource policies.

| Model | Responsibility |
|---|---|
| `SourceObject` | SHA-256, received byte count and detected media type |
| `SourceOccurrence` | Independent identity, parent, acquisition snapshot, original name, role and acquisition gaps |
| `ChildInventory` | Known or unknown direct-child denominator, including missing and excluded children |
| `ParseAttempt` | Source binding, reader/configuration/model versions, experiment limits and protection observations |
| `SourceElement` | Hierarchy, sibling order, native values and typed structural locations |
| `EvidenceRef` | Immutable raw output linked to the same source and reading identity |
| `ParsedDocument` | Structural result and reading gaps; interpretation and human review remain unperformed |
| `SourceBundle` | Referential integrity across objects, occurrences and results |

Inventory completeness means all known children have entries, including children
whose bytes are missing. Acquisition completeness is assessed separately.
`reading_status` exposes received content without a reading as `not_attempted`.
It uses the last result for an occurrence in the supplied tuple; that order is
part of the immutable envelope and must come from the future attempt journal.

Cells retain their address, empty position and lexical value. Formula text and
saved results have separate fields; cached results are explicitly unverified.
Word locations describe a document part and structural position without inventing
page numbers. Images refer to frozen objects and original pixel regions. The PDF
location model only proposes a reference to an existing source layer; it neither
converts nor rewrites that layer. Cross-file byte, geometric and literal-location
checks belong to the adapters and evidence pipeline rather than these models.

Reading identity includes the source digest, reader and contract versions,
configuration/model digests, execution kind and limits. Occurrences remain
separate even when their content can share a reading. A fixture cannot share a
reading key with a real parser. Evidence bytes are checked using
`verify_evidence`; no OCR or other reader is invoked during that check.

There is no approval operation here. The bundle digest is an input for a future
integration with the existing reviewed-version contract. It must not replace
that contract, its manual decisions or its atomic publication rules.

## Synthetic examples

Run from the repository root with the project virtual environment:

```powershell
python -m pytest tests/test_reader_contracts.py -q
python tests/export_reader_samples.py runs/reader-contract-examples
```

The exporter writes a JSON schema, three result envelopes, original fixture
bytes and raw evidence. It refuses to overwrite different frozen output.
The spreadsheet and Word originals are **JSON blueprints**, explicitly labelled
as such. The embedded picture is a generated PNG. Expected cell positions and
Word order are hand-authored contract examples, not Office extraction results.
The email example includes duplicate content in separate occurrences, inline
content, a missing download and an unsupported binary.

## Reader implementation requirements

The `Parser` protocol preserves a small adapter interface. Its availability probe
must stay local and side-effect free. Real readers must enforce input, expansion,
entry, cell, pixel, output, wall-time, memory and whole-source-tree bounds; block
network access and active content; and preserve explicit gaps. Protection flags
are reports supplied by an implementation, not operating-system enforcement by
this model. The independent native readers and their bounded Windows process
boundary are implemented separately in this package; their capabilities and
protection limits are described in [Native readers](NATIVE_READERS.md).

Adapters must use maintained format libraries, preserve raw evidence from the
same reading and reconcile output with a bounded source inventory. `Delivery.save`
and `Delivery.load` preserve isolated reading evidence without reparsing. Integration
with the application store, atomic publication, application routing, UI preview
and schema activation remains separate work. See the package
[provenance notice](../../jav/readers/NOTICE.md).
