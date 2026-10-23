"""Path checks by their text alone, made before anything resolves or opens a path that arrived from outside.

On Windows, resolving a network path (`\\\\host\\share\\...`, `//host/share/...`) or a path relative to another drive's
current folder (`Q:file`, possibly a mapped network drive) already contacts the host: an outgoing SMB connection,
which can leak the Windows sign-in hash. So an email's attachment name (153, review C6) and a mail bridge path (167,
review S-1) are checked here first, by text, without touching the file system.
"""

from __future__ import annotations

from pathlib import PureWindowsPath

_SEPARATORS = ("\\", "/")


def reaches_another_host(text: str) -> bool:
    """Resolving this path could contact another host: it starts with two separators in any mix (a network or device
    path), or it names a drive without a root folder."""
    if text[:1] in _SEPARATORS and text[1:2] in _SEPARATORS:
        return True
    path = PureWindowsPath(text)
    return bool(path.drive) and not path.root


def plain_relative(text: str) -> bool:
    """A path that stays below the folder it is joined to, by its text: not empty, no leading separator, no drive or
    other colon, and no empty or `..` segment (either separator counts)."""
    if not text or text[0] in _SEPARATORS or ":" in text:
        return False
    return all(part not in ("", "..") for part in text.replace("\\", "/").split("/"))


__all__ = ["plain_relative", "reaches_another_host"]
