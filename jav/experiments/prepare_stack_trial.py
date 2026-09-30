"""Deterministic, issuer-disjoint trial sample from approved sources.

Local reading only; the selection is fixed before any model answer is seen.
"""
import hashlib
import json
from pathlib import Path

from jav.config import PROJECT_ROOT
from jav.pdf import read_pdf

# 066 Á13: the selection (file names of real documents) and the local folder structure must not go into git; it lives
# under `runs/`, which git excludes: {"root": ..., "roots": {category: relative folder},
# "selection": [[category, file name, group, split], ...]}.
LOCAL_SELECTION = PROJECT_ROOT / "runs/20260921_stack_trial/selection_local.json"
CATEGORIES = ("business", "bank", "household")


def _local() -> dict:
    if not LOCAL_SELECTION.is_file():
        raise SystemExit(f"hiányzik a helyi kiválasztás (gitben nincs, 066 Á13): {LOCAL_SELECTION}")
    return json.loads(LOCAL_SELECTION.read_text(encoding="utf-8"))


def roots() -> dict[str, Path]:
    """The source folders per category (from the local selection file)."""
    d = _local()
    return {k: Path(d["root"]) / v for k, v in d["roots"].items()}


def selection() -> list[tuple[str, str, str, str]]:
    """The fixed, issuer-disjoint sample: (category, file name, group, development / evaluation split)."""
    return [tuple(x) for x in _local()["selection"]]


def main():
    out = PROJECT_ROOT / "runs/20260921_stack_trial"
    out.mkdir(parents=True, exist_ok=True)
    manifest_file = out / "sample.json"
    if manifest_file.exists():
        raise SystemExit("A rögzített mintát nem írjuk felül")
    inventory = []
    for category, root in roots().items():
        for path in sorted(root.rglob("*.pdf")):
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                inventory.append(dict(category=category, path=str(path), sha256=digest))
            except OSError as exc:
                inventory.append(dict(category=category, path=str(path), error=type(exc).__name__))
    (out / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    cases = []
    texts = []
    for i, (category, name, group, split) in enumerate(selection(), 1):
        matches = [x for x in inventory if x["category"] == category and Path(x["path"]).name == name]
        if len(matches) != 1:
            raise ValueError((name, len(matches)))
        row = {**matches[0], "case_id": f"real-{i:02d}", "group": group, "split": split,
               "prior_exposure": "existing_corpus" if category == "business" else "not_checked"}
        pdf = read_pdf(row["path"])
        row.update(page_count=pdf.page_count, text_source=pdf.text_source, text_chars=len(pdf.text))
        cases.append(row)
        texts.append({"case_id": row["case_id"], "text": pdf.text})
        print(row["case_id"], category, group, pdf.page_count, pdf.text_source, len(pdf.text), flush=True)
    assert len({c["sha256"] for c in cases}) == len(cases)
    assert not ({c["group"] for c in cases if c["split"] == "development"} &
                {c["group"] for c in cases if c["split"] == "evaluation"})
    manifest_file.write_text(json.dumps({"cases": cases, "selection": "purposive issuer-disjoint pilot; not population-random",
        "labels": "pending source-based assessment before live calls"}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "source_texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8")
    print("inventory", len(inventory), "unique", len({r.get("sha256") for r in inventory if "sha256" in r}))


if __name__ == "__main__":
    main()
