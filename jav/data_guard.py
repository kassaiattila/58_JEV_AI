"""Adatőr (070 terv 2.1 S-adatőr, 071): commit és feltöltés előtti személyesadat- és kulcsőr.

A GitHubra csak kód és kódtári leírás kerülhet; személyes adat, kulcs, valódi irat és belső munkaanyag nem. Az adatőr a
gitbe kerülő **új sorokat** nézi (commitnál a `git diff --cached`, feltöltésnél a feltöltendő commitok változásai), és
megállítja a műveletet, ha valódi alakú adatot talál. A meglévő sorokat nem nézi újra, ezért egy régi, tűrt érték
nem akaszt meg egy független commitot; a teljes fát a `scan` (és a teszt) nézi át.

- **Valódi alak** = átmegy az ellenőrzésen: a magyar adószám és közösségi adószám ellenőrzőszáma (`jav/taxid.py`), az
  IBAN mod-97-e, a hazai bankszámlaszám két ellenőrzőszáma. A hibás ellenőrzőszámú érték nem lehet valódi, ezért nem
  állít meg. A külföldi adószám, az e-mail-cím és a telefonszám nem ellenőrizhető így: ezekre kivétellista van.
- **Kivétel** (`configs/data_guard.json` `allow`): kitalált vagy nyilvános céges érték, olvashatóan.
- **Tűrt saját adat** (`known`): a 069-es döntés szerint a következő utasítás-módosításig maradó valódi érték, csak
  sha256-tal és csak a megnevezett fájlokban; máshol megállít.
- **Tiltott kifejezés** (`deny`): a saját cég neve, a felhasználónév és hasonló; a szórészletek sha256-ával egyeztetve,
  hogy a lista maga ne hordozza őket.
- **Kulcs:** ismert kulcs-alakok, és a helyi `.env` titkos értékei szó szerint (a kiírásban csak a változó neve).
- **Útvonal:** belső munkaanyag (`jav/doc_scope.py`), `.env`, a helyi adatmappák, irat- és képfájlok, bináris fájl.
- **Feltöltésnél** a régi, személyes adatot és belső munkaanyagot hordozó történet is tiltott (a 069 / 070 archív ágak).

Belépési pont a horgoknak: `python -m jav.data_guard pre-commit | pre-push <remote> [url] | scan | install`.
A horgok: `scripts/githooks/` (`core.hooksPath`; telepítés: `python -m jav.cli hooks-install`).
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

_TOKEN = re.compile(r"\w+")
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_ENV_SECRET_NAME = re.compile(r"(?i)key|token|secret|passw|pwd")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class DataGuardError(RuntimeError):
    """A git-parancs nem futott le (nem git-tár, hiányzó commit)."""


@dataclass(frozen=True)
class Finding:
    path: str
    line: int  # 0: a fájl vagy a feltöltött ág egésze
    kind: str
    shown: str  # maszkolt érték vagy magyarázat; a valódi érték soha
    known: bool = False  # tűrt saját adat a megnevezett fájlban: jelzés, nem állít meg

    def describe(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        tail = " (tűrt ismert érték)" if self.known else ""
        return f"  {where}  {KIND_LABELS.get(self.kind, self.kind)}  {self.shown}{tail}"


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if not f.known]


# --- normalizálás és ellenőrzés ------------------------------------------------------------------------------------


def normalize(kind: str, value: str) -> str:
    """Egységes alak a kivétellistához és az ujjlenyomathoz."""
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
    """A tűrt érték ujjlenyomata (a `known` lista eleme)."""
    return hashlib.sha256(normalize(kind, value).encode("utf-8")).hexdigest()


def deny_entry(term: str, why: str = "") -> dict[str, Any]:
    """A `deny` lista eleme egy kifejezésre: kisbetűs alakjának sha256-a és hossza (a szórészlet-kereséshez)."""
    t = term.lower()
    return {"sha256": hashlib.sha256(t.encode("utf-8")).hexdigest(), "len": len(t), "why": why}


def _cdv_ok(digits: str) -> bool:
    """Hazai bankszámlaszám-csoport ellenőrzőszáma: 9-7-3-1 súlyok, az összeg 10-zel osztható."""
    return sum(int(d) * (9, 7, 3, 1)[i % 4] for i, d in enumerate(digits)) % 10 == 0


def _real_hu_tax(value: str) -> bool:
    t = taxid.recognize(value)
    return t is not None and t.country == "HU" and taxid.hu_check(t)[0]


def _real_eu_vat(value: str) -> bool:
    t = taxid.recognize(value)
    return t is not None and t.country != "HU" and sum(c.isdigit() for c in t.canonical) >= 7


def _real_iban(value: str) -> bool:
    return validators.iban_check(value).code == "iban.ok"


def _real_account(value: str) -> bool:
    d = re.sub(r"\D", "", value)
    return len(d) in (16, 24) and _cdv_ok(d[:8]) and _cdv_ok(d[8:])


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


# --- beállítás -----------------------------------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    """A `configs/data_guard.json` másolata (a hívó módosíthatja, a gyorsítótárat nem rontja el)."""
    import copy

    return copy.deepcopy(cfg.load("data_guard"))


def read_env_secrets(env_file: Path) -> dict[str, str]:
    """A `.env` titkos értékei (kulcs, token, jelszó; legalább 12 karakter). Hiányzó fájl: üres."""
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
    """A minták, kivételek és tiltások egy beállításból; a keresés soronként és útvonalanként."""

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
        """A szóban (bárhol, egybeírt alakban is) előforduló tiltott kifejezések ujjlenyomatai; szavanként egyszer számolva."""
        hit = self._token_deny.get(token)
        if hit is None:
            digests = {hashlib.sha256(token[i:i + n].encode("utf-8")).hexdigest()
                       for n in self.deny_lengths for i in range(len(token) - n + 1)}
            hit = self._token_deny[token] = frozenset(digests & self.deny)
        return hit

    # --- tartalom ---

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

    # --- útvonal ---

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
    """Egységes (unified) diff hozzáadott sorai: (útvonal, sorszám az új fájlban, szöveg)."""
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
    """`--numstat -z` kimenetéből a bináris fájlok („-  -  útvonal”)."""
    paths = []
    for rec in out.decode("utf-8", "replace").split("\0"):
        parts = rec.split("\t")
        if len(parts) == 3 and parts[0] == "-" and parts[1] == "-" and parts[2]:
            paths.append(parts[2])
    return paths


def _scan_change(root: Path, guard: Guard, diff_args: list[str]) -> list[Finding]:
    """Egy változás (a gitbe kerülő fájlok és új soraik) átnézése; a `diff_args` a `git diff`/`diff-tree` hívás."""
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
    """Commit előtt: a commitba kerülő fájlok és új sorok."""
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
    """Feltöltés előtt (a git `pre-push` bemenete soronként): tiltott történet, majd a még fel nem töltött commitok."""
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
    """A teljes verziókövetett fa (a GitHubra kerülő tartalom) átnézése."""
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


# --- horgok ---------------------------------------------------------------------------------------------------------


def hooks_installed(root: Path = PROJECT_ROOT) -> bool:
    proc = _git(root, "config", "--get", "core.hooksPath", check=False)
    return proc.returncode == 0 and proc.stdout.decode().strip() == HOOKS_DIR


def install_hooks(root: Path = PROJECT_ROOT) -> str:
    """A verziózott horgok bekapcsolása ebben a munkafában (`core.hooksPath`); a `.git/hooks` ezután nem fut."""
    _git(root, "config", "core.hooksPath", HOOKS_DIR)
    return f"core.hooksPath = {HOOKS_DIR}: a commit és a feltöltés előtt az adatőr fut"


def report(findings: list[Finding], action: str) -> str:
    stop = blocking(findings)
    lines = []
    if stop:
        lines.append(f"adatőr: {len(stop)} megállító találat - {action} nem történt meg")
        lines.extend(f.describe() for f in stop)
        lines.append("Kitalált érték: vedd fel a configs/data_guard.json `allow` listájára (verziólépéssel). "
                     "Valódi adat: cseréld kitaláltra. Belső munkaanyag vagy tiltott fájl: "
                     "`git restore --staged <fájl>`. Leírás: docs/guides/DEVELOPMENT.md §1.")
    tolerated = [f for f in findings if f.known]
    if tolerated:
        lines.append(f"adatőr: {len(tolerated)} tűrt ismert érték (configs/data_guard.json `known`: a 069-es döntés szerint maradó saját adat)")
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
