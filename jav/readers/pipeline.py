"""Standalone reader delivery for local experiments, without application storage.

Files and decoded email attachments enter the same bounded parser. Outputs are
immutable local artifacts; this module is not a second work queue or JAV store.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

from .contracts import (
    ChildInventory, EvidenceRef, Issue, ParsedDocument, ParseAttempt, Protections,
    ReadLimits, SourceBundle, SourceManifest, SourceObject, SourceOccurrence,
    canonical_bytes, read_bundle, verify_evidence,
)
from .isolation import run
from .limits import DEFAULT_LIMITS, ReadFailure, limited
from .native import evidence_view


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def implementation_version() -> str:
    sources = {p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")}
    packages = {}
    for name in ("openpyxl", "python-docx", "lxml", "defusedxml", "Pillow", "pydantic"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "missing"
    return "native-1:" + digest(json_bytes({"sources": sources, "packages": packages}))


def bounded_file(path: Path, bound: int) -> bytes:
    """Verify the opened Windows handle as well as the proposed path."""
    absolute = path.absolute()
    if absolute.is_symlink() or absolute.resolve() != absolute:
        raise ReadFailure("excluded", "excluded", "Symbolic links and redirected input paths are excluded")
    with absolute.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ReadFailure("excluded", "excluded", "Input is not a regular file")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            import msvcrt
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            method = kernel.GetFinalPathNameByHandleW
            method.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            method.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            count = method(msvcrt.get_osfhandle(stream.fileno()), buffer, len(buffer), 0)
            if not count or count >= len(buffer):
                raise ReadFailure("excluded", "protection_unavailable", "Could not verify opened input path")
            final = buffer.value
            if final.startswith("\\\\?\\UNC\\"):
                final = "\\\\" + final[8:]
            elif final.startswith("\\\\?\\"):
                final = final[4:]
            if Path(final) != absolute:
                raise ReadFailure("excluded", "excluded", "Opened input path changed during acquisition")
        limited(os.fstat(stream.fileno()).st_size > bound, "Input byte limit exceeded")
        data = stream.read(bound + 1)
    limited(len(data) > bound, "Input grew beyond the byte limit")
    return data


@dataclass
class Delivery:
    bundle: SourceBundle
    objects: dict[str, bytes] = field(repr=False)
    evidence: dict[str, bytes] = field(repr=False)
    texts: dict[str, bytes] = field(default_factory=dict, repr=False)
    reading_invocations: dict[str, int] = field(default_factory=dict)

    def select(self, root_ids: set[str]) -> Delivery:
        """Select complete source trees for a bounded experiment, without rereading."""
        roots = {o.occurrence_id for o in self.bundle.manifest.occurrences if o.parent_id is None}
        if not root_ids or not root_ids <= roots:
            raise ValueError("Selection must name existing root occurrences")
        selected = set(root_ids)
        for _ in range(16):
            selected.update(o.occurrence_id for o in self.bundle.manifest.occurrences if o.parent_id in selected)
        occurrences = tuple(o for o in self.bundle.manifest.occurrences if o.occurrence_id in selected)
        hashes = {o.object_sha256 for o in occurrences if o.object_sha256}
        results = tuple(r for r in self.bundle.results if r.attempt.occurrence_id in selected)
        evidence = {r.raw_evidence.sha256: self.evidence[r.raw_evidence.sha256] for r in results if r.raw_evidence}
        text_keys = {e.locator.text_sha256 for r in results for e in r.elements if e.locator.kind == "text"}
        bundle = SourceBundle(manifest=SourceManifest(
            objects=tuple(o for o in self.bundle.manifest.objects if o.sha256 in hashes), occurrences=occurrences,
            inventories=tuple(i for i in self.bundle.manifest.inventories if i.occurrence_id in selected)), results=results)
        result = Delivery(bundle, {h: self.objects[h] for h in hashes}, evidence, {h: self.texts[h] for h in text_keys})
        result.verify()
        return result

    def verify(self):
        for namespace in (self.objects, self.evidence, self.texts):
            if any(digest(data) != key for key, data in namespace.items()):
                raise ValueError("Artifact content does not match its address")
        for item in self.bundle.manifest.objects:
            if item.sha256 not in self.objects or len(self.objects[item.sha256]) != item.byte_size:
                raise ValueError("Missing or wrong-size original object")
        for result in self.bundle.results:
            ref = result.raw_evidence
            if ref:
                verify_evidence(ref, self.objects[ref.source_sha256], self.evidence[ref.sha256])
                raw = json.loads(self.evidence[ref.sha256])
                if (raw["elements"] != [e.model_dump(mode="json") for e in result.elements]
                        or raw["issues"] != [i.model_dump(mode="json") for i in result.issues]
                        or raw["status"] != result.status):
                    raise ValueError("Structured reading differs from its frozen evidence")
                children = [o for o in self.bundle.manifest.occurrences if o.parent_id == result.attempt.occurrence_id]
                if len(children) != len(raw["children"]):
                    raise ValueError("Child inventory differs from its frozen evidence")
                for child, recorded in zip(children, raw["children"], strict=True):
                    expected_sha = recorded.get("sha256")
                    if expected_sha is None and "data" in recorded:
                        expected_sha = digest(base64.b64decode(recorded["data"], validate=True))
                    if child.object_sha256 != expected_sha or child.original_name != recorded["name"]:
                        raise ValueError("Child occurrence differs from its frozen evidence")
            for element in result.elements:
                if element.locator.kind == "text":
                    loc = element.locator
                    text = self.texts[loc.text_sha256].decode("utf-8")
                    if text[loc.start:loc.end] != element.text:
                        raise ValueError("Text locator no longer identifies its exact value")

    def save(self, destination: Path):
        """Create once. Failure leaves no published bundle, and never replaces one."""
        self.verify()
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=False)
        for name, items in (("objects", self.objects), ("evidence", self.evidence), ("texts", self.texts)):
            folder = destination / name
            folder.mkdir()
            for key, content in items.items():
                with (folder / key).open("xb") as output:
                    output.write(content)
        payload = canonical_bytes(self.bundle)
        read_bundle(payload)
        with (destination / "bundle.json").open("xb") as output:
            output.write(payload)

    @classmethod
    def load(cls, destination: Path):
        destination = Path(destination)
        bundle = read_bundle(bounded_file(destination / "bundle.json", 2_000_000))
        # Only content-addressed references in the validated envelope are read.
        object_sizes = {item.sha256: item.byte_size for item in bundle.manifest.objects}
        if (any(size > DEFAULT_LIMITS.input_bytes for size in object_sizes.values())
                or sum(object_sizes.values()) > DEFAULT_LIMITS.expanded_bytes):
            raise ValueError("Saved delivery exceeds the local artifact loading bounds")
        evidence_sizes = {r.raw_evidence.sha256: r.raw_evidence.byte_size for r in bundle.results if r.raw_evidence}
        text_keys = {e.locator.text_sha256 for r in bundle.results for e in r.elements if e.locator.kind == "text"}
        objects = {key: bounded_file(destination / "objects" / key, size) for key, size in object_sizes.items()}
        evidence = {key: bounded_file(destination / "evidence" / key, size) for key, size in evidence_sizes.items()}
        texts = {key: bounded_file(destination / "texts" / key, 400_000) for key in text_keys}
        delivery = cls(bundle, objects, evidence, texts)
        delivery.verify()
        return delivery


def read_files(paths: list[Path], *, limits: ReadLimits = DEFAULT_LIMITS) -> Delivery:
    inputs = []
    for selected in map(Path, paths):
        if selected.is_dir() and not selected.is_symlink():
            for parent, directories, files in os.walk(selected, followlinks=False):
                for name in sorted(directories):
                    path = Path(parent, name)
                    if path.is_symlink() or path.resolve() != path.absolute():
                        inputs.append(path)
                        directories.remove(name)
                inputs.extend(Path(parent, name) for name in sorted(files))
                limited(len(inputs) > 500, "Folder inventory exceeds the 500-file experiment limit")
        else:
            inputs.append(selected)
    if not inputs:
        raise ValueError("No input files were offered")
    limited(len(inputs) > 500, "Input inventory exceeds the experiment limit")
    version = implementation_version()
    source_version = "intake:" + uuid4().hex
    objects, object_models, evidence, texts, invocations, cache = {}, {}, {}, {}, {}, {}
    occurrences, inventories, results = [], [], []
    total_bytes = 0
    total_elements = 0

    def append(name, data, *, parent=None, role="document", depth=0, missing=None):
        nonlocal total_bytes, total_elements
        limited(len(occurrences) >= 900, "Source tree occurrence limit exceeded")
        oid = f"o{len(occurrences)}"
        if missing:
            occurrences.append(SourceOccurrence(occurrence_id=oid, parent_id=parent, source_version=source_version,
                original_name=name[:512] or "unnamed", role="email" if name.lower().endswith(".eml") else role,
                acquisition="missing" if missing.code == "download_missing" else "excluded",
                issues=(Issue(stage="acquisition", code=missing.code, message=str(missing)[:512]),)))
            if name.lower().endswith(".eml"):
                inventories.append(ChildInventory(occurrence_id=oid, completeness="unknown", expected_children=None,
                    issues=(Issue(stage="acquisition", code="inventory_unknown", message="Email could not be acquired"),)))
            return
        total_bytes += len(data)
        limited(total_bytes > limits.expanded_bytes, "Whole source tree byte limit exceeded")
        content_sha = digest(data)
        objects[content_sha] = data
        occurrences.append(SourceOccurrence(occurrence_id=oid, parent_id=parent, source_version=source_version,
            original_name=name[:512] or "unnamed", role="email" if name.lower().endswith(".eml") else role,
            acquisition="received", object_sha256=content_sha))
        failure = None
        key = (content_sha, Path(name).suffix.lower())
        response = cache.get(key)
        if response is None:
            try:
                if depth >= limits.source_tree_depth:
                    raise ReadFailure("resource_limited", "resource_limit", "Source tree depth limit exceeded")
                invocations[content_sha] = invocations.get(content_sha, 0) + 1
                response = run(data, name, limits)
                cache[key] = response
            except ReadFailure as exc:
                failure = exc
        mime = response["mime"] if response else "application/octet-stream"
        object_models[content_sha] = SourceObject(sha256=content_sha, byte_size=len(data), detected_mime=mime)
        attempt = ParseAttempt(attempt_id=f"read:{oid}", occurrence_id=oid, source_sha256=content_sha,
            parser_name=response["parser"] if response else "native-unavailable", parser_version=version,
            config_sha256=limits.digest(), models_sha256=digest(b"no-models"), execution="reader", limits=limits,
            protections=Protections(**dict.fromkeys(("network", "paths", "active_content", "expansion", "cells",
                                                     "pixels", "time", "memory"), "enforced" if response else "not_executed")))
        if failure:
            results.append(ParsedDocument(attempt=attempt, status=failure.status,
                issues=(Issue(stage="reading", code=failure.code, message=str(failure)[:512]),)))
            if name.lower().endswith(".eml"):
                inventories.append(ChildInventory(occurrence_id=oid, completeness="unknown", expected_children=None,
                    issues=(Issue(stage="acquisition", code="inventory_unknown", message="Email reading did not establish attachment count"),)))
            return
        raw = json_bytes(evidence_view(response))
        raw_sha = digest(raw)
        evidence[raw_sha] = raw
        ref = EvidenceRef(sha256=raw_sha, byte_size=len(raw), source_sha256=content_sha,
                          reader_key=attempt.reader_key(), media_type="application/json")
        payload = {"attempt": attempt.model_dump(mode="json"), "status": response["status"],
                   "elements": response["elements"], "issues": response["issues"], "raw_evidence": ref.model_dump(mode="json")}
        result = ParsedDocument.model_validate_json(json_bytes(payload))
        total_elements += len(result.elements)
        limited(total_elements > limits.visited_cells, "Whole source tree element limit exceeded")
        results.append(result)
        texts.update({key: text.encode("utf-8") for key, text in response["texts"].items()})
        children = response["children"]
        if children or name.lower().endswith(".eml"):
            unknown = any("MIME" in i.message for i in result.issues)
            inventories.append(ChildInventory(occurrence_id=oid, completeness="unknown" if unknown else "complete",
                expected_children=None if unknown else len(children), issues=(Issue(stage="acquisition", code="inventory_unknown",
                    message="MIME defects prevent proving the original attachment denominator"),) if unknown else ()))
        for child in children:
            absent = ReadFailure("corrupt", "download_missing", "No decoded attachment bytes") if child.get("missing") else None
            decoded = b"" if absent else base64.b64decode(child["data"], validate=True)
            if not absent and (digest(decoded) != child["sha256"] or len(decoded) != child["byte_size"]):
                raise ValueError("Decoded child differs from its frozen structural evidence")
            append(child["name"], decoded,
                   parent=oid, role=child["role"], depth=depth + 1, missing=absent)

    for path in inputs:
        try:
            data = bounded_file(path, limits.input_bytes)
        except (OSError, ReadFailure) as exc:
            failure = exc if isinstance(exc, ReadFailure) else ReadFailure("corrupt", "download_missing", "Input could not be acquired")
            append(path.name, b"", missing=failure)
        else:
            append(path.name, data)
    bundle = SourceBundle(manifest=SourceManifest(objects=tuple(object_models.values()), occurrences=tuple(occurrences),
                                                  inventories=tuple(inventories)), results=tuple(results))
    read_bundle(canonical_bytes(bundle))
    delivery = Delivery(bundle, objects, evidence, texts, invocations)
    delivery.verify()
    return delivery
