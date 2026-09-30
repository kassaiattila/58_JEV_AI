"""071 S-adatőr (070 plan 2.1): the pre-commit and pre-push guard against personal data and keys (`jav/data_guard.py`).

This file deliberately contains no real-looking value: the tests compute the check-digit samples at run time and
assemble the email addresses and keys from pieces. This way the test itself passes the data guard.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from jav import data_guard, taxid

ROOT = Path(__file__).resolve().parents[1]
AT = "@"


# --- made-up but real-looking values (computed at run time) -------------------------------------------------------


def _hu_tax(seed7: str, vat: str = "2", county: str = "42") -> str:
    s = sum(int(d) * w for d, w in zip(seed7, taxid.HU_WEIGHTS))
    return f"{seed7}{(10 - s % 10) % 10}-{vat}-{county}"


def _cdv(seed: str) -> str:
    s = sum(int(d) * (9, 7, 3, 1)[i % 4] for i, d in enumerate(seed))
    return seed + str((10 - s % 10) % 10)


def _hu_account(a7: str, b15: str) -> str:
    return f"{_cdv(a7)}-{_cdv(b15)[:8]}-{_cdv(b15)[8:]}"


def _iban(country: str, bban: str) -> str:
    num = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{country}{98 - int(num) % 97:02d}{bban}"


def _bad_check(value: str) -> str:
    """Corrupts the first digit (after any letter prefix), so the check digit no longer matches."""
    i = next(k for k, c in enumerate(value) if c.isdigit())
    return value[:i] + str((int(value[i]) + 1) % 10) + value[i + 1:]


@pytest.fixture()
def guard():
    return data_guard.Guard(data_guard.load_config(), env_secrets={})


def _kinds(findings):
    return [f.kind for f in findings]


# --- content patterns ----------------------------------------------------------------------------------------------


def test_valid_hu_tax_id_is_flagged_invalid_is_not(guard):
    good = _hu_tax("1357924")
    assert taxid.hu_check(taxid.recognize(good))[0]
    assert _kinds(guard.scan_line("a.py", 1, f"Adószám: {good}")) == ["hu_tax_id"]
    assert guard.scan_line("a.py", 1, f"Adószám: {_bad_check(good)}") == []


def test_hu_eu_vat_uses_the_same_check_digit(guard):
    eu = "HU" + _hu_tax("2468135")[:8]
    assert _kinds(guard.scan_line("a.py", 1, f"VAT: {eu}")) == ["hu_tax_id"]
    assert guard.scan_line("a.py", 1, f"VAT: {_bad_check(eu)}") == []


def test_foreign_vat_is_flagged_unless_allowlisted(guard):
    vat = "DE" + "2" * 4 + "31" + "579"
    assert _kinds(guard.scan_line("a.py", 1, f"USt-IdNr. {vat}")) == ["eu_vat"]
    conf = data_guard.load_config()
    conf["allow"]["eu_vat"] = [*conf["allow"].get("eu_vat", []), vat]
    assert data_guard.Guard(conf, env_secrets={}).scan_line("a.py", 1, f"USt-IdNr. {vat}") == []


def test_iban_needs_a_valid_mod97(guard):
    iban = _iban("HU", _hu_account("1177301", "611110180000000").replace("-", ""))
    assert _kinds(guard.scan_line("a.py", 1, f"IBAN: {iban}")) == ["iban"]
    spaced = " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))
    assert _kinds(guard.scan_line("a.py", 1, f"IBAN: {spaced}")) == ["iban"]
    assert guard.scan_line("a.py", 1, f"IBAN: {iban[:-1]}{(int(iban[-1]) + 1) % 10}") == []


def test_hu_domestic_account_needs_valid_check_digits(guard):
    acct = _hu_account("1210002", "846813570000000")
    assert _kinds(guard.scan_line("a.py", 1, f"Számlaszám: {acct}")) == ["bank_account"]
    assert guard.scan_line("a.py", 1, f"Számlaszám: {_bad_check(acct)}") == []


def test_email_real_domain_flagged_reserved_and_fictional_domains_pass(guard):
    real = "valaki" + AT + "gmail" + ".com"
    assert _kinds(guard.scan_line("a.py", 1, f"to: {real}")) == ["email"]
    for ok in ("a" + AT + "example.com", "b" + AT + "sub.example.org", "c" + AT + "mail.test",
               "d" + AT + "minta.hu", "e" + AT + "x.invalid"):
        assert guard.scan_line("a.py", 1, f"to: {ok}") == [], ok


def test_hu_phone_flagged_unless_allowlisted(guard):
    phone = "+36 30 " + "987 65" + "43"
    assert _kinds(guard.scan_line("a.py", 1, f"Tel.: {phone}")) == ["phone"]
    conf = data_guard.load_config()
    conf["allow"]["phone"] = [*conf["allow"].get("phone", []), phone]
    assert data_guard.Guard(conf, env_secrets={}).scan_line("a.py", 1, f"tel {phone.replace(' ', '')}") == []


def test_phone_pattern_ignores_digits_inside_hashes(guard):
    digest = "0654422130e950bef5251168ca63f08bbe456705ad8b493a756c8ffdf5392418"
    assert guard.scan_line("a.json", 1, f'"schema.json": "{digest}"') == []


def test_api_key_shapes(guard):
    for key in ("sk-" + "proj-" + "Ab1" * 12, "gh" + "p_" + "x9Y" * 13, "AK" + "IA" + "ABCDEFGH23456789",
                "-----BEGIN " + "PRIVATE KEY-----"):
        assert _kinds(guard.scan_line("a.py", 1, f"key = '{key}'")) == ["api_key"], key


def test_env_secret_value_is_flagged_without_showing_it():
    secret = "ts" + "_live_" + "Q7w" * 8
    g = data_guard.Guard(data_guard.load_config(), env_secrets={"TypeSafeJAV_API_KEY": secret})
    found = g.scan_line("x.md", 3, f"kulcs: {secret}")
    assert _kinds(found) == ["env_secret"]
    assert secret not in found[0].shown and "TypeSafeJAV_API_KEY" in found[0].shown


def test_deny_terms_are_matched_by_hash_only_also_inside_words():
    conf = data_guard.load_config()
    entry = data_guard.deny_entry("Titkoscég")
    assert entry["sha256"] == hashlib.sha256("titkoscég".encode()).hexdigest() and entry["len"] == 9
    conf["deny"] = [*conf.get("deny", []), entry]
    g = data_guard.Guard(conf, env_secrets={})
    found = g.scan_line("t.py", 7, "Szállító: TITKOSCÉG Kft.")
    assert _kinds(found) == ["deny_term"] and "titkoscég" not in found[0].shown.lower()
    assert _kinds(g.scan_line("t.py", 8, 'összeragadt: "TitkoscégKft." és titkoscég.hu')) == ["deny_term"]
    assert g.scan_line("t.py", 9, "Szállító: Titkos Cég Kft.") == []


def test_known_values_are_tolerated_only_where_they_already_are():
    """Own data kept under the 069 decision: a warning in the named files, a stop anywhere else."""
    good = _hu_tax("9753102")
    conf = data_guard.load_config()
    conf["known"] = [*conf.get("known", []), {"sha256": data_guard.value_hash("hu_tax_id", good),
                                              "paths": ["a.py"], "until": "teszt"}]
    g = data_guard.Guard(conf, env_secrets={})
    found = g.scan_line("a.py", 1, good)
    assert [(f.kind, f.known) for f in found] == [("hu_tax_id", True)]
    assert data_guard.blocking(found) == []
    assert [(f.kind, f.known) for f in g.scan_line("b.py", 1, good)] == [("hu_tax_id", False)]


def test_known_deny_term_in_its_file():
    conf = data_guard.load_config()
    entry = data_guard.deny_entry("titkoscég")
    conf["deny"] = [*conf.get("deny", []), entry]
    conf["known"] = [*conf.get("known", []), {"sha256": entry["sha256"], "paths": ["configs/x.json"], "until": "teszt"}]
    g = data_guard.Guard(conf, env_secrets={})
    assert data_guard.blocking(g.scan_line("configs/x.json", 2, "Titkoscég Zrt.")) == []
    assert _kinds(data_guard.blocking(g.scan_line("tests/y.py", 2, "Titkoscég Zrt."))) == ["deny_term"]


def test_masking_hides_the_middle(guard):
    good = _hu_tax("1357924")
    shown = guard.scan_line("a.py", 1, good)[0].shown
    assert good not in shown and shown.startswith(good[:2]) and "*" in shown


# --- path rules ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("rel", ["docs/handoffs/071-x.md", "docs/BACKLOG.md", ".env", ".env.local", "store/jav.sqlite",
                                 "runs/x.jsonl", "inbox/a/b/message.json", "tests/fixtures/szamla.pdf", "a/b.eml",
                                 "ui/public/kep.png", "export.xlsx"])
def test_blocked_paths(guard, rel):
    assert guard.check_path(rel) is not None


@pytest.mark.parametrize("rel", [".env.example", "jav/data_guard.py", "docs/GLOSSARY.md", "configs/data_guard.json",
                                 "scripts/githooks/pre-commit", "ui/src/App.tsx"])
def test_allowed_paths(guard, rel):
    assert guard.check_path(rel) is None


# --- diff and git --------------------------------------------------------------------------------------------------


def test_added_lines_parses_unified_diff():
    diff = "\n".join([
        "diff --git a/x.py b/x.py", "index 1..2 100644", "--- a/x.py", "+++ b/x.py", "@@ -3,0 +4,2 @@",
        "+uj sor", "+masik", "diff --git a/y.md b/y.md", "new file mode 100644", "--- /dev/null", "+++ b/y.md",
        "@@ -0,0 +1 @@", "+elso", "diff --git a/z.txt b/z.txt", "deleted file mode 100644", "--- a/z.txt",
        "+++ /dev/null", "@@ -1 +0,0 @@", "-torolt",
    ])
    assert list(data_guard.added_lines(diff)) == [("x.py", 4, "uj sor"), ("x.py", 5, "masik"), ("y.md", 1, "elso")]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t" + AT + "example.com")
    _git(tmp_path, "config", "user.name", "Teszt")
    _git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def test_check_staged_blocks_new_pii_but_not_existing_lines(repo, guard):
    good = _hu_tax("1357924")
    (repo / "a.py").write_text(f"x = '{good}'\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    assert _kinds(data_guard.check_staged(repo, guard)) == ["hu_tax_id"]
    _git(repo, "commit", "-q", "-m", "régi állapot")
    (repo / "a.py").write_text(f"x = '{good}'\ny = 1\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    assert data_guard.check_staged(repo, guard) == []


def test_check_staged_blocks_binary_and_internal_paths(repo, guard):
    (repo / "docs" / "handoffs").mkdir(parents=True)
    (repo / "docs" / "handoffs" / "001-x.md").write_text("belső\n", encoding="utf-8")
    (repo / "kep.bin").write_bytes(b"\x00\x01\x02")
    _git(repo, "add", "-f", ".")
    assert sorted(f.path for f in data_guard.check_staged(repo, guard)) == ["docs/handoffs/001-x.md", "kep.bin"]


def test_pre_push_blocks_forbidden_history_and_scans_new_commits(repo, guard):
    (repo / "a.txt").write_text("régi\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "régi")
    old = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "b.txt").write_text("tiszta\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "rá épül")
    head = _git(repo, "rev-parse", "HEAD").strip()
    zero = "0" * 40
    conf = data_guard.load_config()
    conf["forbidden_history"] = [old]
    g = data_guard.Guard(conf, env_secrets={})
    found = data_guard.check_push(repo, g, [f"refs/heads/main {head} refs/heads/main {zero}"])
    assert _kinds(found) == ["forbidden_history"]
    # new starting point: it does not build on the forbidden line, but its content is still scanned
    _git(repo, "checkout", "-q", "--orphan", "uj")
    (repo / "c.txt").write_text(f"tel {_hu_tax('2468135')}\n", encoding="utf-8")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-q", "-m", "új gyökér")
    new = _git(repo, "rev-parse", "HEAD").strip()
    found = data_guard.check_push(repo, g, [f"refs/heads/uj {new} refs/heads/uj {zero}"])
    assert sorted(_kinds(found)) == ["hu_tax_id"]
    # pushing a deletion: nothing to scan
    assert data_guard.check_push(repo, g, [f"(delete) {zero} refs/heads/regi {head}"]) == []


# --- the real repository and the installation ----------------------------------------------------------------------


def test_tracked_files_have_no_blocking_findings():
    """The done criterion (070 plan 5.): 0 blocking findings outside the allow list in the files that go to GitHub."""
    found = data_guard.blocking(data_guard.scan_tracked(ROOT, data_guard.load_guard(ROOT)))
    assert [f"{f.path}:{f.line} {f.kind} {f.shown}" for f in found] == []


def test_install_hooks_sets_hooks_path(repo):
    assert not data_guard.hooks_installed(repo)
    data_guard.install_hooks(repo)
    assert data_guard.hooks_installed(repo)
    assert _git(repo, "config", "--get", "core.hooksPath").strip() == data_guard.HOOKS_DIR


def test_report_gives_only_the_matching_advice():
    value = data_guard.Finding("a.py", 1, "hu_tax_id", "13***42")
    path = data_guard.Finding("docs/BACKLOG.md", 0, "internal_doc", "belső")
    history = data_guard.Finding("refs/heads/regi", 0, "forbidden_history", "régi")
    text = data_guard.report([value], "a commit")
    assert "allow" in text and "restore" not in text and "History" not in text
    text = data_guard.report([path, history], "a feltöltés")
    assert "allow" not in text and "restore" in text and "History" in text
    known = data_guard.Finding("a.py", 1, "hu_tax_id", "13***42", known=True)
    assert "megállító" not in data_guard.report([known], "a commit")


def test_preflight_flags_missing_hooks_and_blocking_findings(monkeypatch):
    from jav import preflight

    monkeypatch.setattr(data_guard, "scan_tracked", lambda root, guard: [])
    monkeypatch.setattr(data_guard, "hooks_installed", lambda root: False)
    ok, msg = preflight.data_guard_status()
    assert not ok and "hooks-install" in msg
    monkeypatch.setattr(data_guard, "hooks_installed", lambda root: True)
    assert preflight.data_guard_status()[0]
    stop = data_guard.Finding("x.py", 3, "hu_tax_id", "12***42")
    monkeypatch.setattr(data_guard, "scan_tracked", lambda root, guard: [stop])
    ok, msg = preflight.data_guard_status()
    assert not ok and "1 megállító" in msg and "data-guard" in msg


def test_versioned_hooks_exist_and_call_the_guard():
    for name, arg in (("pre-commit", "pre-commit"), ("pre-push", "pre-push")):
        text = (ROOT / data_guard.HOOKS_DIR / name).read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh") and f"jav.data_guard {arg}" in text and "\r" not in text
