"""Data guard (070 plan 2.1 S-adatőr, 071): a personal-data and key guard before commit and push.

Only code and codebase documentation may reach GitHub; personal data, keys, real documents and internal working
documents may not. The data guard looks at the **new lines** going into git (on commit, `git diff --cached`; on push,
the changes of the commits to be pushed) and stops the operation if it finds data of a real shape. It does not
re-check existing lines, so an old, tolerated value does not block an unrelated commit; the whole tree is checked by
`scan` (and the test).

- **Real shape** = passes the check: the check digit of the Hungarian tax number and the EU VAT number
  (`jav/taxid.py`), the IBAN's mod-97, the two check digits of a domestic bank account number. A value with a wrong
  check digit cannot be real, so it does not stop anything. Foreign tax numbers, email addresses and phone numbers
  cannot be checked this way: they have an allow list.
- **Exception** (`configs/data_guard.json` `allow`): a fictitious or public company value, in readable form.
- **Tolerated own data** (`known`): a real value that stays until the next prompt change, per the 069 decision; only
  as sha256 and only in the named files; anywhere else it stops the operation.
- **Denied term** (`deny`): the owner's company name, the user name and the like; matched by the sha256 of word
  fragments, so that the list itself does not carry them.
- **Key:** known key shapes, and the secret values of the local `.env` verbatim (the output shows only the variable
  name).
- **Path:** internal working documents (`jav/doc_scope.py`), `.env`, the local data folders, document and image
  files, binary files.
- **On push**, the old history carrying personal data and internal working documents is also forbidden (the 069 / 070
  archive branches).

Entry point for the hooks: `python -m jav.data_guard pre-commit | pre-push <remote> [url] | scan | install`.
The hooks: `scripts/githooks/` (`core.hooksPath`; installation: `python -m jav.cli hooks-install`).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any

from jav import cfg, doc_scope, taxid, validators
from jav.config import PROJECT_ROOT

HOOKS_DIR = "scripts/githooks"
ZERO_SHA = "0" * 40

KIND_LABELS = {
    "hu_tax_id": "adószám",
    "eu_vat": "külföldi adószám",
    "iban": "IBAN",
    "bank_account": "bankszámlaszám",
    "email": "e-mail-cím",
    "phone": "telefonszám",
    "api_key": "kulcs",
    "env_secret": ".env-titok",
    "deny_term": "tiltott kifejezés",
    "internal_doc": "belső munkaanyag",
    "blocked_path": "tiltott útvonal",
    "blocked_file": "tiltott fájltípus",
    "binary_file": "bináris fájl",
    "forbidden_history": "tiltott történet",
}

_VALUE_KINDS = frozenset({"hu_tax_id", "eu_vat", "iban", "bank_account", "email", "phone", "api_key", "env_secret",
                          "deny_term"})
_PATH_KINDS = frozenset({"internal_doc", "blocked_path", "blocked_file", "binary_file"})
_TOKEN = re.compile(r"\w+")
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_ENV_SECRET_NAME = re.compile(r"(?i)key|token|secret|passw|pwd")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class DataGuardError(RuntimeError):
    """The git command did not run (not a git repository, missing commit)."""


@dataclass(frozen=True)
class Finding:
    path: str
    line: int  # 0: the whole file or the whole pushed branch
    kind: str
    shown: str  # masked value or explanation; never the real value
    known: bool = False  # tolerated own data in the named file: a notice, it does not stop the operation

    def describe(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        tail = " (tűrt ismert érték)" if self.known else ""
        return f"  {where}  {KIND_LABELS.get(self.kind, self.kind)}  {self.shown}{tail}"


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if not f.known]


# --- normalisation and checking ------------------------------------------------------------------------------------


def normalize(kind: str, value: str) -> str:
    """Uniform form for the allow list and the fingerprint."""
    v = value.strip()
    if kind in ("hu_tax_id", "eu_vat"):
        t = taxid.recognize(v)
        return t.canonical if t else re.sub(r"[\s.\-]", "", v).upper()
    if kind == "iban":
        return re.sub(r"\s", "", v).upper()
    if kind == "bank_account":
        return re.sub(r"\D", "", v)
    if kind == "email":
        return v.lower()
    if kind == "phone":
        d = re.sub(r"\D", "", v)
        for prefix in ("0036", "06"):
            if d.startswith(prefix):
                return "36" + d[len(prefix):]
        return d
    return v


def value_hash(kind: str, value: str) -> str:
    """The fingerprint of a tolerated value (an entry of the `known` list)."""
    return hashlib.sha256(normalize(kind, value).encode("utf-8")).hexdigest()


def deny_entry(term: str, why: str = "") -> dict[str, Any]:
    """A `deny` list entry for a term: the sha256 and length of its lower-case form (for the word-fragment search)."""
    t = term.lower()
    return {"sha256": hashlib.sha256(t.encode("utf-8")).hexdigest(), "len": len(t), "why": why}


def _real_hu_tax(value: str) -> bool:
    t = taxid.recognize(value)
    return t is not None and t.country == "HU" and taxid.hu_check(t)[0]


def _real_eu_vat(value: str) -> bool:
    t = taxid.recognize(value)
    return t is not None and t.country != "HU" and sum(c.isdigit() for c in t.canonical) >= 7


def _real_iban(value: str) -> bool:
    return validators.iban_check(value).code == "iban.ok"


def _real_account(value: str) -> bool:
    return validators.hu_account_check_digits_ok(re.sub(r"\D", "", value))  # 075: one rule with the validator


_REAL = {"hu_tax_id": _real_hu_tax, "eu_vat": _real_eu_vat, "iban": _real_iban, "bank_account": _real_account}


def _mask(kind: str, value: str) -> str:
    if kind == "email":
        local, _, domain = value.partition("@")
        name, _, tld = domain.rpartition(".")
        return f"{local[:1]}***@{name[:1]}***.{tld}"
    if kind == "api_key":
        return value[:4] + "***"
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


# --- configuration -------------------------------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    """A copy of `configs/data_guard.json` (the caller may modify it without corrupting the cache)."""
    import copy

    return copy.deepcopy(cfg.load("data_guard"))


def read_env_secrets(env_file: Path) -> dict[str, str]:
    """The secret values of `.env` (key, token, password; at least 12 characters). Missing file: empty."""
    if not env_file.is_file():
        return {}
    out: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ENV_LINE.match(line)
        if not m or line.lstrip().startswith("#"):
            continue
        name, value = m.group(1), m.group(2).strip().strip("'\"")
        if _ENV_SECRET_NAME.search(name) and len(value) >= 12:
            out[name] = value
    return out


class Guard:
    """The patterns, exceptions and denials from one configuration; the search runs per line and per path."""

    def __init__(self, conf: dict[str, Any], *, env_secrets: dict[str, str]) -> None:
        self.conf = conf
        self.patterns = {k: re.compile(v) for k, v in conf["patterns"].items()}
        self.key_patterns = [re.compile(p) for p in conf["api_key_patterns"]]
        self.allow = {k: {normalize(k, v) for v in vals} for k, vals in conf.get("allow", {}).items()}
        self.email_domains = {d.lower() for d in conf.get("email_domains_ok", [])}
        self.email_tlds = {t.lower() for t in conf.get("email_reserved_tlds", [])}
        self.deny = {e["sha256"] for e in conf.get("deny", [])}
        self.deny_lengths = sorted({int(e["len"]) for e in conf.get("deny", [])})
        self.known: dict[str, list[str]] = {}
        for k in conf.get("known", []):
            self.known.setdefault(k["sha256"], []).extend(k["paths"])
        self.env_secrets = env_secrets
        self._token_deny: dict[str, frozenset[str]] = {}

    def _deny_in_token(self, token: str) -> frozenset[str]:
        """The fingerprints of the denied terms occurring in the word (anywhere, also run together); computed once per
        word."""
        hit = self._token_deny.get(token)
        if hit is None:
            digests = {hashlib.sha256(token[i:i + n].encode("utf-8")).hexdigest()
                       for n in self.deny_lengths for i in range(len(token) - n + 1)}
            hit = self._token_deny[token] = frozenset(digests & self.deny)
        return hit

    # --- content ---

    def _is_known(self, digest: str, path: str) -> bool:
        return any(fnmatchcase(path, p) for p in self.known.get(digest, []))

    def _email_ok(self, value: str) -> bool:
        domain = value.rpartition("@")[2].lower()
        if domain.rpartition(".")[2] in self.email_tlds:
            return True
        return any(domain == d or domain.endswith("." + d) for d in self.email_domains)

    def _finding(self, path: str, line: int, kind: str, value: str) -> Finding:
        known = self._is_known(value_hash(kind, value), path)
        return Finding(path, line, kind, _mask(kind, value), known)

    def scan_line(self, path: str, line: int, text: str) -> list[Finding]:
        out: list[Finding] = []
        for kind, pat in self.patterns.items():
            for m in pat.finditer(text):
                value = m.group(0)
                if normalize(kind, value) in self.allow.get(kind, set()):
                    continue
                if kind in _REAL and not _REAL[kind](value):
                    continue
                if kind == "email" and self._email_ok(value):
                    continue
                out.append(self._finding(path, line, kind, value))
        for pat in self.key_patterns:
            out.extend(Finding(path, line, "api_key", _mask("api_key", m.group(0))) for m in pat.finditer(text))
        for name, secret in self.env_secrets.items():
            if secret in text:
                out.append(Finding(path, line, "env_secret", f"(a .env {name} értéke)"))
        if self.deny:
            hits: set[str] = set()
            for token in set(_TOKEN.findall(text.lower())):
                hits |= self._deny_in_token(token)
            out.extend(Finding(path, line, "deny_term", f"(tiltott kifejezés {d[:8]})", self._is_known(d, path))
                       for d in sorted(hits))
        return out

    # --- path ---

    def check_path(self, path: str) -> Finding | None:
        p = PurePosixPath(path.replace("\\", "/"))
        rel = p.as_posix()
        if any(fnmatchcase(rel, a) for a in self.conf.get("allowed_paths", [])):
            return None
        if doc_scope.is_internal(rel):
            return Finding(rel, 0, "internal_doc", "a belső munkaanyag helyben marad (070)")
        for pattern in self.conf.get("blocked_paths", []):
            if (pattern.endswith("/") and rel.startswith(pattern)) or fnmatchcase(rel, pattern) \
                    or fnmatchcase(p.name, pattern):
                return Finding(rel, 0, "blocked_path", f"minta: {pattern}")
        if p.suffix.lower() in self.conf.get("blocked_extensions", []):
            return Finding(rel, 0, "blocked_file", f"{p.suffix.lower()}: irat, kép vagy adattár nem kerülhet a gitbe")
        return None

    def binary_allowed(self, path: str) -> bool:
        return any(fnmatchcase(path, a) for a in self.conf.get("allowed_binary", []))


def load_guard(root: Path = PROJECT_ROOT) -> Guard:
    return Guard(load_config(), env_secrets=read_env_secrets(root / ".env"))


# --- git ------------------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True)
    if check and proc.returncode != 0:
        raise DataGuardError(f"git {' '.join(args[:2])}: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """The added lines of a unified diff: (path, line number in the new file, text)."""
    path: str | None = None
    lineno = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        if raw.startswith("diff --git "):
            path = None
            continue
        m = _HUNK.match(raw)
        if m:
            lineno = int(m.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            yield path, lineno, raw[1:]
            lineno += 1
        elif raw.startswith(" "):
            lineno += 1


def _numstat_binaries(out: bytes) -> list[str]:
    """The binary files from the `--numstat -z` output ("-  -  path")."""
    paths = []
    for rec in out.decode("utf-8", "replace").split("\0"):
        parts = rec.split("\t")
        if len(parts) == 3 and parts[0] == "-" and parts[1] == "-" and parts[2]:
            paths.append(parts[2])
    return paths


def _scan_change(root: Path, guard: Guard, diff_args: list[str]) -> list[Finding]:
    """Checks one change (the files going into git and their new lines); `diff_args` is the `git diff`/`diff-tree`
    call. 075 (repeated security audit, S05): without rename detection, so a renamed or copied file shows as a new
    file and its whole content is checked under the new path (a pure rename used to have no added line)."""
    diff_args = [*diff_args, "--no-renames"]
    found: list[Finding] = []
    names = _git(root, *diff_args, "--name-only", "-z", "--diff-filter=ACMR").stdout
    for name in filter(None, names.decode("utf-8", "replace").split("\0")):
        f = guard.check_path(name)
        if f is not None:
            found.append(f)
    blocked = {f.path for f in found}
    for name in _numstat_binaries(_git(root, *diff_args, "--numstat", "-z", "--diff-filter=ACMR").stdout):
        if name not in blocked and not guard.binary_allowed(name):
            found.append(Finding(name, 0, "binary_file", "bináris fájl csak kivétellistával kerülhet a gitbe"))
    diff = _git(root, *diff_args, "-p", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR").stdout
    for path, line, text in added_lines(diff.decode("utf-8", "replace")):
        found.extend(guard.scan_line(path, line, text))
    return found


def check_staged(root: Path, guard: Guard) -> list[Finding]:
    """Before a commit: the files and new lines going into the commit."""
    return _scan_change(root, guard, ["diff", "--cached"])


def _dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, str]] = set()
    out = []
    for f in findings:
        key = (f.path, f.kind, f.shown)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def check_push(root: Path, guard: Guard, ref_lines: Iterable[str], remote: str = "origin") -> list[Finding]:
    """Before a push (the git `pre-push` input, line by line): forbidden history, then the commits not yet pushed."""
    roots = []
    for ref in guard.conf.get("forbidden_history", []):
        proc = _git(root, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}", check=False)
        if proc.returncode == 0:
            roots.append(proc.stdout.decode().strip())
    found: list[Finding] = []
    for line in ref_lines:
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO_SHA:
            continue
        local_ref, local_sha, _remote_ref, remote_sha = parts
        if any(_git(root, "merge-base", "--is-ancestor", r, local_sha, check=False).returncode == 0 for r in roots):
            found.append(Finding(local_ref, 0, "forbidden_history",
                                 "a régi (069 / 070 előtti) történetre épül: személyes adat, belső munkaanyag"))
            continue
        revs = [local_sha, "--not", f"--remotes={remote}"] + ([] if remote_sha == ZERO_SHA else [remote_sha])
        commits = _git(root, "rev-list", *revs).stdout.decode().split()
        for c in commits:
            found.extend(_scan_change(root, guard, ["diff-tree", "-r", "--root", "-m", "--first-parent", c]))
    return _dedupe(found)


def scan_tracked(root: Path, guard: Guard) -> list[Finding]:
    """Checks the whole tracked tree (the content that reaches GitHub)."""
    found: list[Finding] = []
    names = _git(root, "ls-files", "-z").stdout.decode("utf-8", "replace").split("\0")
    for name in filter(None, names):
        f = guard.check_path(name)
        if f is not None:
            found.append(f)
            continue
        p = root / name
        if not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data:
            if not guard.binary_allowed(name):
                found.append(Finding(name, 0, "binary_file", "bináris fájl csak kivétellistával kerülhet a gitbe"))
            continue
        for i, text in enumerate(data.decode("utf-8", "replace").splitlines(), start=1):
            found.extend(guard.scan_line(name, i, text))
    return found


# --- hooks ----------------------------------------------------------------------------------------------------------


def hooks_installed(root: Path = PROJECT_ROOT) -> bool:
    proc = _git(root, "config", "--get", "core.hooksPath", check=False)
    return proc.returncode == 0 and proc.stdout.decode().strip() == HOOKS_DIR


def install_hooks(root: Path = PROJECT_ROOT) -> str:
    """Enables the versioned hooks in this working tree (`core.hooksPath`); `.git/hooks` no longer runs after this."""
    _git(root, "config", "core.hooksPath", HOOKS_DIR)
    return f"core.hooksPath = {HOOKS_DIR}: a commit és a feltöltés előtt az adatőr fut"


def report(findings: list[Finding], action: str) -> str:
    stop = blocking(findings)
    lines = []
    if stop:
        lines.append(f"adatőr: {len(stop)} megállító találat - {action} nem történt meg")
        lines.extend(f.describe() for f in stop)
        kinds = {f.kind for f in stop}
        if kinds & _VALUE_KINDS:
            lines.append("Tartalom: ha kitalált érték, vedd fel a configs/data_guard.json `allow` listájára "
                         "(verziólépéssel); ha valódi adat vagy kulcs, cseréld kitaláltra.")
        if kinds & _PATH_KINDS:
            lines.append("Fájl: vedd ki a commitból: `git restore --staged <fájl>` (a belső munkaanyag helyben marad).")
        if "forbidden_history" in kinds:
            lines.append("Történet: ez az ág vagy címke a régi történetre épül, nem tölthető fel.")
        lines.append("Leírás: docs/guides/DEVELOPMENT.md §1. A horog megkerülése (--no-verify) tilos.")
    tolerated = [f for f in findings if f.known]
    if tolerated:
        lines.append(f"adatőr: {len(tolerated)} tűrt ismert érték "
                     "(configs/data_guard.json `known`: a 069-es döntés szerint maradó saját adat)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "scan"
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.decode().strip())
    if cmd == "install":
        print(install_hooks(root))
        return 0
    guard = load_guard(root)
    if cmd == "pre-commit":
        findings, action = check_staged(root, guard), "a commit"
    elif cmd == "pre-push":
        remote = args[1] if len(args) > 1 else "origin"
        findings, action = check_push(root, guard, sys.stdin.read().splitlines(), remote), "a feltöltés"
    elif cmd == "scan":
        findings, action = scan_tracked(root, guard), "a kiadás"
        if not findings:
            print("adatőr: a verziókövetett fájlokban nincs találat")
    else:
        print(f"ismeretlen parancs: {cmd} (pre-commit | pre-push <remote> | scan | install)", file=sys.stderr)
        return 2
    text = report(findings, action)
    if text:
        print(text, file=sys.stderr if blocking(findings) else sys.stdout)
    return 1 if blocking(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["HOOKS_DIR", "DataGuardError", "Finding", "Guard", "added_lines", "blocking", "check_push", "deny_entry",
           "check_staged", "hooks_installed", "install_hooks", "load_config", "load_guard", "main", "normalize",
           "read_env_secrets", "report", "scan_tracked", "value_hash"]
