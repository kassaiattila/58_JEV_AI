"""Export bounded, synthetic contract examples without opening a store or a reader."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jav.readers.contracts import SourceBundle, canonical_bytes, read_bundle, verify_evidence  # noqa: E402
from reader_samples import raw_evidence_payload, sample_bundles, synthetic_payloads  # noqa: E402


def export_examples(destination: Path) -> dict:
    """Write fixtures once; refuse to replace a previously frozen artifact."""
    destination.mkdir(parents=True, exist_ok=True)

    def save(relative: str, payload: bytes) -> None:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != payload:
                raise ValueError(f"Refusing to replace a different frozen artifact: {relative}")
            return
        with target.open("xb") as stream:
            stream.write(payload)

    payloads = synthetic_payloads()
    by_hash = {hashlib.sha256(value).hexdigest(): (name, value) for name, value in payloads.items()}
    for digest, (name, value) in by_hash.items():
        save(f"objects/{digest}", value)
        save(f"inputs/{name}", value)
    summaries = {}
    for name, bundle in sample_bundles().items():
        payload = canonical_bytes(bundle)
        save(f"{name}.json", payload)
        assert read_bundle(payload) == bundle
        for result in bundle.results:
            source_name, source = by_hash[result.attempt.source_sha256]
            evidence = raw_evidence_payload(result, source_name)
            verify_evidence(result.raw_evidence, source, evidence)
            save(f"evidence/{result.raw_evidence.sha256}.json", evidence)
        summaries[name] = {
            "kind": "hand_authored_contract_fixture_not_a_reader_measurement",
            "sha256": bundle.digest(), "objects": len(bundle.manifest.objects),
            "occurrences": len(bundle.manifest.occurrences),
            "acquisition_status": bundle.manifest.acquisition_status(),
            "reading_states": {item.occurrence_id: bundle.reading_status(item.occurrence_id)
                               for item in bundle.manifest.occurrences},
            "elements": sum(len(result.elements) for result in bundle.results),
        }
    schema = json.dumps(SourceBundle.model_json_schema(), indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    save("source-bundle.schema.json", schema)
    save("summary.json", json.dumps(summaries, indent=2).encode("utf-8") + b"\n")
    return summaries


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tests/export_reader_samples.py OUTPUT_DIRECTORY")
    export_examples(Path(sys.argv[1]))
    print(f"Exported three synthetic source-contract examples to {sys.argv[1]}")
