"""Explicit local command; no automatic mailbox or model calls."""
import argparse
import json
from pathlib import Path

from .pipeline import read_files


def main():
    parser = argparse.ArgumentParser(description="Read local files into frozen, source-bound experimental artifacts")
    parser.add_argument("inputs", nargs="+", type=Path, help="Files or folders; input content stays local")
    parser.add_argument("--output", type=Path, required=True, help="New directory for original bytes, evidence and bundle.json")
    args = parser.parse_args()
    delivery = read_files(args.inputs)
    delivery.save(args.output)
    print(json.dumps({"output": str(args.output), "occurrences": len(delivery.bundle.manifest.occurrences),
                      "readings": len(delivery.bundle.results), "provider_calls": 0,
                      "statuses": [result.status for result in delivery.bundle.results]}))


if __name__ == "__main__":
    main()
