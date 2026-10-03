"""Explicit bounds and conservative package inspection for native readers."""
from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
import stat
import zipfile

from .contracts import ReadLimits

DEFAULT_LIMITS = ReadLimits(
    input_bytes=8_000_000, expanded_bytes=32_000_000, archive_entries=1000,
    expansion_ratio=200, visited_cells=4000, image_pixels=20_000_000,
    output_bytes=2_000_000, wall_seconds=20, memory_bytes=768_000_000,
    source_tree_depth=8,
)


class ReadFailure(ValueError):
    def __init__(self, status: str, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def limited(condition: bool, message: str) -> None:
    if condition:
        raise ReadFailure("resource_limited", "resource_limit", message)


def xml(data: bytes):
    """DTD and entity processing are never part of the input language."""
    from defusedxml import ElementTree
    return ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def inspect_package(data: bytes, limits: ReadLimits) -> dict[str, bytes]:
    """Inspect ZIP/XML metadata; Office interpretation remains in libraries.

    No package member is extracted to a filesystem path. Active parts and external
    relationships reject the entire reading, with an explicit exclusion reason.
    """
    parts = {}
    expanded = 0
    with zipfile.ZipFile(BytesIO(data)) as package:
        entries = package.infolist()
        limited(len(entries) > limits.archive_entries, "Archive entry limit exceeded")
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                    or ":" in name or "\x00" in name or name in parts
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ReadFailure("excluded", "excluded", "Unsafe or duplicate archive member")
            if entry.flag_bits & 1:
                raise ReadFailure("password_required", "password_required", "Encrypted archive member")
            expanded += entry.file_size
            limited(expanded > limits.expanded_bytes, "Expanded archive byte limit exceeded")
            limited(entry.file_size > max(1, entry.compress_size) * limits.expansion_ratio,
                    "Archive expansion ratio limit exceeded")
            with package.open(entry) as stream:
                content = stream.read(min(entry.file_size + 1, limits.expanded_bytes + 1))
            limited(len(content) != entry.file_size, "Archive size differs from its directory")
            lower = name.lower()
            if any(term in lower for term in ("vbaproject", "/activex/", "/embeddings/", "/externallinks/")):
                raise ReadFailure("excluded", "excluded", "Active or embedded executable Office content")
            if lower.endswith((".xml", ".rels")):
                root = xml(content)
                if lower.endswith(".rels") and any(
                        node.attrib.get("TargetMode", "").lower() == "external" for node in root.iter()):
                    raise ReadFailure("excluded", "excluded", "External Office relationship is not followed")
            parts[name] = content
    return parts
