"""Language guard (073, plan N-angol): everything that reaches GitHub is written in English.

The owner decided on 2026-09-30 that code, comments, messages and codebase documents are English; Hungarian stays only
where it is data (document vocabulary printed on Hungarian invoices, UI translation files, synthetic test documents).
While the existing Hungarian text is being converted, this guard works as a ratchet:

- it counts the lines containing Hungarian letters in every tracked text file;
- a file may not have more such lines than its entry in the baseline (`configs/lang_guard.json`), and a file without
  an entry may not have any;
- `lang-guard --update` lowers the baseline after a conversion step; raising an entry needs an explicit
  `--accept <path>` (document vocabulary or test data), so the diff of the config shows every accepted file.

Lines are detected by accented Hungarian letters only; an unaccented Hungarian word ("Receptek") is not caught.

`same_python_code()` checks that two versions of a Python file differ only in comments and docstrings. It verifies
comment-only translation commits (`lang-guard --same-code <rev>`).
"""

from __future__ import annotations

import ast
import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_REL = "configs/lang_guard.json"
HUNGARIAN = re.compile(r"[áéíóöőúüűÁÉÍÓÖŐÚÜŰ]")


class LangGuardError(RuntimeError):
    """The guard cannot run (no git, unreadable config)."""


@dataclass(frozen=True)
class Guard:
    version: str
    allow: tuple[str, ...]
    baseline: dict[str, int] = field(default_factory=dict)

    def allowed(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.allow)


@dataclass(frozen=True)
class Excess:
    path: str
    lines: int
    limit: int


def load_guard(root: Path) -> Guard:
    try:
        data = json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LangGuardError(f"{CONFIG_REL}: {e}") from e
    return Guard(version=data["meta"]["version"], allow=tuple(data.get("allow", [])),
                 baseline={k: int(v) for k, v in data.get("baseline", {}).items()})


def hungarian_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if HUNGARIAN.search(line))


def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise LangGuardError(f"git ls-files: {e}") from e
    return [p for p in out.decode("utf-8").split("\0") if p]


def scan(root: Path, guard: Guard) -> dict[str, int]:
    """Hungarian line count of every tracked, non-allowed text file that has at least one such line."""
    counts: dict[str, int] = {}
    for rel in tracked_files(root):
        if guard.allowed(rel):
            continue
        try:
            raw = (root / rel).read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or deleted in the working tree
        if b"\0" in raw:
            continue
        n = hungarian_lines(text)
        if n:
            counts[rel] = n
    return counts


def excess(counts: dict[str, int], guard: Guard) -> list[Excess]:
    return [Excess(p, n, guard.baseline.get(p, 0)) for p, n in sorted(counts.items()) if n > guard.baseline.get(p, 0)]


def lowered_baseline(counts: dict[str, int], guard: Guard, accept: tuple[str, ...] = ()) -> dict[str, int]:
    """The new baseline after a conversion step: every entry drops to the current count (zeros disappear); a file in
    `accept` is raised to its current count."""
    out: dict[str, int] = {}
    for path in sorted(set(guard.baseline) | set(accept)):
        now = counts.get(path, 0)
        new = now if path in accept else min(now, guard.baseline.get(path, 0))
        if new:
            out[path] = new
    return out


def write_baseline(root: Path, baseline: dict[str, int]) -> None:
    path = root / CONFIG_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    data["baseline"] = dict(sorted(baseline.items()))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def same_python_code(old: str, new: str) -> bool:
    """True if the two sources parse to the same syntax tree once comments and docstrings are ignored."""
    try:
        a, b = (_strip_docstrings(ast.parse(src)) for src in (old, new))
    except SyntaxError:
        return False
    return ast.dump(a, include_attributes=False) == ast.dump(b, include_attributes=False)


def changed_python_code(root: Path, rev: str) -> list[str]:
    """Tracked .py files whose code (not only comments or docstrings) differs from revision `rev`."""
    try:
        names = subprocess.run(["git", "diff", "--name-only", rev, "--", "*.py"], cwd=root, capture_output=True,
                               check=True, text=True, encoding="utf-8").stdout.split()
    except (OSError, subprocess.CalledProcessError) as e:
        raise LangGuardError(f"git diff {rev}: {e}") from e
    changed = []
    for rel in names:
        new_path = root / rel
        old = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=root, capture_output=True)
        if old.returncode != 0 or not new_path.is_file():
            changed.append(rel)  # added or deleted file
            continue
        if not same_python_code(old.stdout.decode("utf-8"), new_path.read_text(encoding="utf-8")):
            changed.append(rel)
    return changed
