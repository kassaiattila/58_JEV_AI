"""The native recogniser's language packs: whether the ones the OCR settings need are in place, and fetching them.

A fresh installation has none: they are large binaries, so git ignores them. `configs/ocr.json`
`tesseract.language_packs` names the published release they come from and the SHA-256 of each file, so every machine
recognises with the same models the measurements were made with. `fetch` keeps a downloaded file only when its
fingerprint matches, and it never replaces a different file someone has put there; `state` reports both cases.
"""

from __future__ import annotations

import os
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any

from jav.core import cfg
from jav.core.digest import file_sha256

FETCH_TIMEOUT_S = 120
SUFFIX = ".traineddata"

Opener = Callable[..., IO[bytes]]


class LanguagePackError(RuntimeError):
    """The language-pack settings cannot be used (no pinned files, or a source that is not an https address)."""


@dataclass(frozen=True)
class FetchOutcome:
    """One pinned file after `fetch`: `in_place` (it was already there and matches), `fetched` (downloaded and checked),
    `kept_different` (a file with another fingerprint is there and was left alone) or `failed` (`detail` says why)."""

    name: str
    outcome: str
    detail: str = ""


def _settings() -> dict[str, Any]:
    return cfg.load("ocr")["tesseract"]


def pinned() -> dict[str, str]:
    """Language name -> the SHA-256 of its file, as configured."""
    files = (_settings().get("language_packs") or {}).get("files") or {}
    return {str(name): str(sha).lower() for name, sha in files.items()}


def required() -> list[str]:
    """The languages the recognition is asked for (`tesseract.lang`, e.g. `hun+eng`)."""
    return [lang for lang in str(_settings()["lang"]).split("+") if lang]


def _path(folder: Path, name: str) -> Path:
    return folder / f"{name}{SUFFIX}"


def missing(folder: Path) -> list[str]:
    """The required languages without a file in `folder`."""
    return [lang for lang in required() if not _path(folder, lang).is_file()]


def state(folder: Path) -> dict[str, Any]:
    """The folder, the language files found in it, the required ones missing, and the pinned ones whose file differs
    from its fingerprint."""
    present = sorted(p.name[: -len(SUFFIX)] for p in folder.glob(f"*{SUFFIX}")) if folder.is_dir() else []
    differs = [name for name, sha in pinned().items()
               if _path(folder, name).is_file() and file_sha256(_path(folder, name)) != sha]
    return {"folder": str(folder), "present": present, "missing": missing(folder), "differs": differs}


def _source(name: str) -> str:
    template = str((_settings().get("language_packs") or {}).get("source") or "")
    if not template.startswith("https://") or "{name}" not in template:
        raise LanguagePackError(f"configs/ocr.json tesseract.language_packs.source must be an https address with "
                                f"{{name}} in it, not {template!r}")
    return template.format(name=name)


def _download(url: str, target: Path, opener: Opener) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "jav-ocr-language-packs"})
    with opener(request, timeout=FETCH_TIMEOUT_S) as response, open(target, "wb") as out:
        while chunk := response.read(1 << 16):
            out.write(chunk)


def fetch(folder: Path, *, opener: Opener = urllib.request.urlopen) -> list[FetchOutcome]:
    """Put every pinned language file that is missing into `folder`: each is downloaded beside its final name and
    renamed only after its SHA-256 matched. A file already there is checked, never overwritten."""
    files = pinned()
    if not files:
        raise LanguagePackError("configs/ocr.json names no pinned language packs (tesseract.language_packs.files)")
    folder.mkdir(parents=True, exist_ok=True)
    outcomes: list[FetchOutcome] = []
    for name, sha in files.items():
        target = _path(folder, name)
        if target.is_file():
            if file_sha256(target) == sha:
                outcomes.append(FetchOutcome(name, "in_place"))
            else:
                outcomes.append(FetchOutcome(name, "kept_different",
                                             "another file is there; delete it to fetch the pinned one"))
            continue
        url = _source(name)
        handle, tmp_name = tempfile.mkstemp(prefix=f".{name}-", suffix=".part", dir=folder)
        os.close(handle)
        tmp = Path(tmp_name)
        try:
            _download(url, tmp, opener)
            got = file_sha256(tmp)
            if got != sha:
                outcomes.append(FetchOutcome(name, "failed", f"the download's SHA-256 is {got[:12]}..., not the pinned "
                                                             f"{sha[:12]}...; nothing was kept"))
                continue
            os.replace(tmp, target)
            outcomes.append(FetchOutcome(name, "fetched", url))
        except OSError as exc:  # urllib's URLError and HTTPError are OSErrors too
            outcomes.append(FetchOutcome(name, "failed", f"{type(exc).__name__}: {exc}"))
        finally:
            tmp.unlink(missing_ok=True)
    return outcomes


def as_dicts(outcomes: list[FetchOutcome]) -> list[dict[str, str]]:
    return [asdict(o) for o in outcomes]
