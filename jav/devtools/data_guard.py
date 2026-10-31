"""Data guard (070 plan 2.1 S-adatőr, 071): a personal-data and key guard before commit and push.

Only code and codebase documentation may reach GitHub; personal data, keys, real documents and internal working
documents may not. The data guard looks at the **new lines** going into git (on commit, `git diff --cached`; on push,
the changes of the commits to be pushed) and stops the operation if it finds data of a real shape. It does not
re-check existing lines, so an old, tolerated value does not block an unrelated commit; the whole tree is checked by
`scan` (and the test).

- **Real shape** = passes the check: the check digit of the Hungarian tax number and the EU VAT number
  (`jav/core/taxid.py`), the IBAN's mod-97, the two check digits of a domestic bank account number. A value with a wrong
  check digit cannot be real, so it does not stop anything. Foreign tax numbers, email addresses and phone numbers
  cannot be checked this way: they have an allow list.
- **Exception** (`configs/data_guard.json` `allow`): a fictitious or public company value, in readable form.
- **Tolerated known value** (`known`): a value accepted for the time being; only as sha256 and only in the named
  files; anywhere else it stops the operation.
- **Denied term** (`deny`): the owner's company name, the user name and the like; matched by the sha256 of word
  fragments, so that the list itself does not carry them.
- **Key:** known key shapes (also a literal value assigned to one of the project's key variables), and the secret
  values of the checkout's, the main checkout's and the installation's `.env` verbatim (the output shows only the
  variable name; 265: a linked worktree has no `.env` of its own). Without any `.env` a note says so.
- **Path:** internal working documents (`jav/core/doc_scope.py`), `.env`, the local data folders, document and image
  files, binary files.
- **On push**, a branch or tag built on a history listed under `forbidden_history` is also refused.

Entry point for the hooks: `python -m jav.devtools.data_guard pre-commit | pre-push <remote> [url] | scan | install`.
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

from jav.ai import validators
from jav.core import card_numbers, cfg, doc_scope, taxid
from jav.core.config import ENV_FILE, PROJECT_ROOT, read_env_secrets  # 227: the core's; named here as before

HOOKS_DIR = "scripts/githooks"
ZERO_SHA = "0" * 40

KIND_LABELS = {
    "hu_tax_id": "Hungarian tax number",
    "eu_vat": "foreign tax number",
    "iban": "IBAN",
    "bank_account": "bank account number",
    "email": "email address",
    "phone": "phone number",
    "card_number": "card number",  # 153 (review C2)
    "api_key": "kulcs",
    "env_secret": ".env-titok",
    "deny_term": "forbidden phrase",
    "internal_doc": "internal working document",
    "blocked_path": "blocked path",
    "blocked_file": "blocked file type",
    "binary_file": "binary file",
    "forbidden_history": "forbidden history",
}

_VALUE_KINDS = frozenset({"hu_tax_id", "eu_vat", "iban", "bank_account", "email", "phone", "card_number", "api_key",
                          "env_secret", "deny_term"})
_PATH_KINDS = frozenset({"internal_doc", "blocked_path", "blocked_file", "binary_file"})
_TOKEN = re.compile(r"\w+")
_HUNK = re.compile(r"^@@ -\d+(?:,(?P<old>\d+))? \+(?P<start>\d+)(?:,(?P<new>\d+))? @@")


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
        tail = " (a tolerated known value)" if self.known else ""
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
    if kind in ("bank_account", "card_number"):
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
    """A `deny` list entry for a term: the sha256 and length of its lower-case form (for the word-fragment search). 265
    (code review TOOL-10): one word of letters and digits only: the search looks inside words, so a term with a space
    or a point never matched; such a term is refused (give its words one by one)."""
    t = term.lower().strip()
    if not t or not _TOKEN.fullmatch(t):
        raise DataGuardError(f"a denied term is one word of letters and digits (got {len(t)} characters); give its words one by one")
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


def _real_card(value: str) -> bool:
    """153 (review C2): a payment card number (a scheme's first digit and a right check digit, `jav/core/card_numbers.py`)."""
    return card_numbers.is_card_number(re.sub(r"\D", "", value))


_REAL = {"hu_tax_id": _real_hu_tax, "eu_vat": _real_eu_vat, "iban": _real_iban, "bank_account": _real_account,
         "card_number": _real_card}


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


class Guard:
    """The patterns, exceptions and denials from one configuration; the search runs per line and per path."""

    def __init__(self, conf: dict[str, Any], *, env_secrets: dict[str, str], env_sources: tuple[Path, ...] = ()) -> None:
        self.conf = conf
        self.env_sources = env_sources  # 265: the `.env` files the secret values were read from
        self.patterns = {k: re.compile(v) for k, v in conf["patterns"].items()}
        self.patterns["card_number"] = card_numbers.CARD  # 167 (review S-3): the masking's own pattern, not a copy
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
                out.append(Finding(path, line, "env_secret", f"(the value of .env {name})"))
        if self.deny:
            hits: set[str] = set()
            for token in set(_TOKEN.findall(text.lower())):
                hits |= self._deny_in_token(token)
            out.extend(Finding(path, line, "deny_term", f"(forbidden phrase {d[:8]})", self._is_known(d, path))
                       for d in sorted(hits))
        return out

    # --- path ---

    def check_path(self, path: str) -> Finding | None:
        p = PurePosixPath(path.replace("\\", "/"))
        rel = p.as_posix()
        if any(fnmatchcase(rel, a) for a in self.conf.get("allowed_paths", [])):
            return None
        if doc_scope.is_internal(rel):
            return Finding(rel, 0, "internal_doc", "the internal working documents stay local (070)")
        for pattern in self.conf.get("blocked_paths", []):
            if (pattern.endswith("/") and rel.startswith(pattern)) or fnmatchcase(rel, pattern) \
                    or fnmatchcase(p.name, pattern):
                return Finding(rel, 0, "blocked_path", f"minta: {pattern}")
        if p.suffix.lower() in self.conf.get("blocked_extensions", []):
            return Finding(rel, 0, "blocked_file", f"{p.suffix.lower()}: a document, an image or a store cannot go into git")
        return None

    def binary_allowed(self, path: str) -> bool:
        return any(fnmatchcase(path, a) for a in self.conf.get("allowed_binary", []))


def _main_checkout(root: Path) -> Path | None:
    """The main checkout of the repository `root` belongs to (the folder holding the shared `.git`), or None."""
    proc = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    if proc.returncode != 0:
        return None
    common = Path(proc.stdout.decode("utf-8", "replace").strip())
    return common.parent if common.name == ".git" else None


def env_files(root: Path) -> list[Path]:
    """265 (code review SEC-01): the `.env` files whose secret values the guard looks for, each once: the checkout's
    own, the main checkout's (a linked worktree has none, the keys stay in the main folder) and the installation's
    (`config.ENV_FILE`). Before 265 only the first was read, so the check was silently off in every worktree."""
    main = _main_checkout(root)
    out: list[Path] = []
    for candidate in (root / ".env", main / ".env" if main else None, ENV_FILE):
        if candidate is not None and candidate.is_file() and all(candidate.resolve() != p.resolve() for p in out):
            out.append(candidate)
    return out


def load_guard(root: Path = PROJECT_ROOT) -> Guard:
    files = env_files(root)
    env_secrets: dict[str, str] = {}
    for env_file in files:
        for name, value in read_env_secrets(env_file).items():
            env_secrets[name if env_secrets.get(name, value) == value else f"{name} ({env_file})"] = value
    return Guard(load_config(), env_secrets=env_secrets, env_sources=tuple(files))


def env_note(guard: Guard) -> str | None:
    """265: a non-blocking note when no `.env` was found, so a skipped check of the keys' values is visible."""
    if guard.env_sources:
        return None
    return ("data guard: no .env found (the checkout's, the main checkout's or the installation's); "
            "the keys' values are not checked, only their known shapes")


# --- git ------------------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True)
    if check and proc.returncode != 0:
        raise DataGuardError(f"git {' '.join(args[:2])}: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """The added lines of a unified diff: (path, line number in the new file, text). 265 (code review TOOL-10): inside
    a hunk its counted lines are content, so an added line whose text starts with "++ " is never read as the next
    file's header (an added "++ /dev/null" used to switch the check off for the rest of the file)."""
    path: str | None = None
    lineno = old_left = new_left = 0
    for raw in diff.splitlines():
        if old_left > 0 or new_left > 0:  # inside a hunk
            if raw.startswith("\\"):
                continue  # "\ No newline at end of file"
            if raw.startswith("+"):
                if path is not None:
                    yield path, lineno, raw[1:]
                lineno += 1
                new_left -= 1
            elif raw.startswith("-"):
                old_left -= 1
            else:
                lineno += 1
                old_left, new_left = old_left - 1, new_left - 1
            continue
        if raw.startswith("+++ "):
            target = raw[4:]
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        if raw.startswith("diff --git "):
            path = None
            continue
        m = _HUNK.match(raw)
        if m:
            lineno = int(m.group("start"))
            old_left = 1 if m.group("old") is None else int(m.group("old"))
            new_left = 1 if m.group("new") is None else int(m.group("new"))


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
    names = _git(root, *diff_args, "--name-only", "-z", "--diff-filter=ACMRT").stdout  # 265 (TOOL-10): T too
    for name in filter(None, names.decode("utf-8", "replace").split("\0")):
        f = guard.check_path(name)
        if f is not None:
            found.append(f)
    blocked = {f.path for f in found}
    for name in _numstat_binaries(_git(root, *diff_args, "--numstat", "-z", "--diff-filter=ACMRT").stdout):
        if name not in blocked and not guard.binary_allowed(name):
            found.append(Finding(name, 0, "binary_file", "a binary file goes into git only on the exception list"))
    diff = _git(root, *diff_args, "-p", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMRT").stdout
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


def unresolved_history(root: Path, guard: Guard) -> list[str]:
    """265 (code review SEC-03): the `forbidden_history` entries this clone cannot resolve (a tag deleted here): the
    guard cannot keep their history out, so the push says so."""
    return [ref for ref in guard.conf.get("forbidden_history", [])
            if _git(root, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}", check=False).returncode != 0]


def _push_refs(guard: Guard, lines: list[list[str]]) -> list[Finding]:
    """265 (code review SEC-03; CLAUDE.md 2.3): what a push may carry (`push` in configs/data_guard.json): `main`, the
    release tags and one stage branch; never an archive branch, another tag, a ref that is no branch or tag, or the
    deletion of `main` or a tag (a stage branch may be deleted). The hook does not see the command line, so `--all`,
    `--tags` and `--mirror` are refused by the refs they bring (several branches, an old tag, the remote-tracking refs)."""
    rules = guard.conf.get("push") or {}
    found: list[Finding] = []
    branches = []
    for _local_ref, local_sha, remote_ref, _remote_sha in lines:
        if not remote_ref.startswith(("refs/heads/", "refs/tags/")):
            found.append(Finding(remote_ref, 0, "push_ref", "only a branch or a tag goes to GitHub"))
        elif local_sha == ZERO_SHA:
            if remote_ref in rules.get("main", []) or remote_ref.startswith("refs/tags/"):
                found.append(Finding(remote_ref, 0, "push_ref", "a push never deletes main or a tag"))
        elif any(fnmatchcase(remote_ref, p) for p in rules.get("deny", [])):
            found.append(Finding(remote_ref, 0, "push_ref", "this branch or tag stays local (configs/data_guard.json push.deny)"))
        elif remote_ref.startswith("refs/tags/"):
            if not any(fnmatchcase(remote_ref, p) for p in rules.get("tags", [])):
                found.append(Finding(remote_ref, 0, "push_ref", "only a release tag goes to GitHub (push.tags)"))
        elif remote_ref.startswith("refs/heads/") and remote_ref not in rules.get("main", []):
            branches.append(remote_ref)
    if len(branches) > int(rules.get("stage_branches", 1)):
        found += [Finding(ref, 0, "push_ref", "one stage branch at a time (a push of every branch is refused)")
                  for ref in branches]
    return found


def check_push(root: Path, guard: Guard, ref_lines: Iterable[str], remote: str = "origin") -> list[Finding]:
    """Before a push (the git `pre-push` input, line by line): the refs it carries (265), forbidden history, then the
    commits not yet pushed."""
    roots = []
    for ref in guard.conf.get("forbidden_history", []):
        proc = _git(root, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}", check=False)
        if proc.returncode == 0:
            roots.append(proc.stdout.decode().strip())
    lines = [parts for parts in (line.split() for line in ref_lines) if len(parts) == 4]
    found: list[Finding] = _push_refs(guard, lines)
    for parts in lines:
        if parts[1] == ZERO_SHA:
            continue
        local_ref, local_sha, _remote_ref, remote_sha = parts
        if any(_git(root, "merge-base", "--is-ancestor", r, local_sha, check=False).returncode == 0 for r in roots):
            found.append(Finding(local_ref, 0, "forbidden_history",
                                 "built on a history listed under forbidden_history in configs/data_guard.json"))
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
                found.append(Finding(name, 0, "binary_file", "a binary file goes into git only on the exception list"))
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
    return f"core.hooksPath = {HOOKS_DIR}: the data guard runs before every commit and push"


def report(findings: list[Finding], action: str) -> str:
    stop = blocking(findings)
    lines = []
    if stop:
        lines.append(f"data guard: {len(stop)} blocking finding(s) - {action} did not happen")
        lines.extend(f.describe() for f in stop)
        kinds = {f.kind for f in stop}
        if kinds & _VALUE_KINDS:
            lines.append("Content: if it is an invented value, add it to the `allow` list of configs/data_guard.json "
                         "(with a version step); if it is real data or a key, replace it with an invented one.")
        if kinds & _PATH_KINDS:
            lines.append("File: take it out of the commit: `git restore --staged <file>` (the internal working documents stay local).")
        if "forbidden_history" in kinds:
            lines.append("History: this branch or tag is built on a forbidden history; it cannot be pushed.")
        lines.append("Description: docs/guides/DEVELOPMENT.md §1. Bypassing the hook (--no-verify) is forbidden.")
    tolerated = [f for f in findings if f.known]
    if tolerated:
        lines.append(f"data guard: {len(tolerated)} tolerated known value(s) "
                     "(configs/data_guard.json `known`)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "scan"
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.decode().strip())
    if cmd == "install":
        print(install_hooks(root))
        return 0
    guard = load_guard(root)
    if cmd in ("pre-commit", "pre-push", "scan") and (note := env_note(guard)):
        print(note, file=sys.stderr)
    if cmd == "pre-commit":
        findings, action = check_staged(root, guard), "a commit"
    elif cmd == "pre-push":
        remote = args[1] if len(args) > 1 else "origin"
        for ref in unresolved_history(root, guard):  # 265 (code review SEC-03): never silently
            print(f"data guard: the forbidden_history entry {ref!r} does not resolve here; its history is not checked",
                  file=sys.stderr)
        findings, action = check_push(root, guard, sys.stdin.read().splitlines(), remote), "the push"
    elif cmd == "scan":
        findings, action = scan_tracked(root, guard), "the release"
        if not findings:
            print("data guard: no finding in the tracked files")
    else:
        print(f"unknown command: {cmd} (pre-commit | pre-push <remote> | scan | install)", file=sys.stderr)
        return 2
    text = report(findings, action)
    if text:
        print(text, file=sys.stderr if blocking(findings) else sys.stdout)
    return 1 if blocking(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["HOOKS_DIR", "DataGuardError", "Finding", "Guard", "added_lines", "blocking", "check_push", "deny_entry",
           "check_staged", "env_files", "env_note", "hooks_installed", "install_hooks", "load_config", "load_guard",
           "main", "normalize",
           "read_env_secrets", "report", "scan_tracked", "value_hash"]
