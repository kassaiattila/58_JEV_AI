"""The OCR cache key covers only the settings that can change the recognised text (076).

A path, a time limit, a note or a version record in `configs/ocr.json` used to be part of the key, so removing a
machine-specific path would have made every scanned document go through OCR again (with escalation, paid Azure pages
too). The key now covers the output settings only, and the existing cache is moved to the new key once, only if the
older config reads the same.
"""

import copy

import pytest

from jav import ocr


def _conf():
    return copy.deepcopy(ocr._CFG)


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["meta"].update(version="9.9.9"),
        lambda c: c["azure_di"].update(data_root="D:/elsewhere/data", sidecar_url="http://127.0.0.1:9999", timeout_s=5),
        lambda c: c["tesseract"].update(timeout_s=1, exe_candidates=["x.exe"]),
        lambda c: c["escalation"].update(enabled=False),
        lambda c: c["docker"].update(note="another note"),
        lambda c: c.update(cache_dir="elsewhere/ocr"),
    ],
)
def test_settings_that_do_not_change_the_text_leave_the_key_alone(change):
    c = _conf()
    change(c)
    assert ocr.output_hash(c) == ocr.CACHE_HASH


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.update(dpi=200),
        lambda c: c.update(grayscale=not c["grayscale"]),
        lambda c: c.update(max_pages=c["max_pages"] + 1),
        lambda c: c["tesseract"].update(lang="eng"),
        lambda c: c["tesseract"].update(psm=6),
        lambda c: c["tesseract"].update(tessdata_dir="tools/tessdata_best"),
        lambda c: c["quality"].update(low_conf_word=50),
    ],
)
def test_settings_that_change_the_text_change_the_key(change):
    c = _conf()
    change(c)
    assert ocr.output_hash(c) != ocr.CACHE_HASH


def _old_whole_hash(conf):
    import hashlib

    from jav import cfg

    return hashlib.sha256(("ocr" + cfg.canonical(conf)).encode("utf-8")).hexdigest()[: cfg.HASH_LEN]


def test_rekey_moves_the_old_cache_once_and_never_overwrites(tmp_path):
    old = _conf()
    old["meta"]["version"] = "1.0.0"
    old["azure_di"]["data_root"] = "C:/somewhere/legacy/data"
    whole = _old_whole_hash(old)
    sha = "a" * 64
    (tmp_path / f"{sha}_{whole}_tesseract_5.4.0.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"{sha}_{whole}_tesseract_5.4.0_psm6.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"{'b' * 64}_{whole}_azure_di.json").write_text('{"old": 1}', encoding="utf-8")
    (tmp_path / f"{'b' * 64}_{ocr.CACHE_HASH}_azure_di.json").write_text('{"new": 1}', encoding="utf-8")  # already there
    (tmp_path / f"{'c' * 64}_0123456789abcdef_tesseract_5.4.0.json").write_text("{}", encoding="utf-8")  # another config

    assert ocr.rekey_cache(old, tmp_path) == 2
    assert (tmp_path / f"{sha}_{ocr.CACHE_HASH}_tesseract_5.4.0.json").exists()
    assert (tmp_path / f"{sha}_{ocr.CACHE_HASH}_tesseract_5.4.0_psm6.json").exists()
    assert (tmp_path / f"{'b' * 64}_{ocr.CACHE_HASH}_azure_di.json").read_text(encoding="utf-8") == '{"new": 1}'
    assert (tmp_path / f"{'c' * 64}_0123456789abcdef_tesseract_5.4.0.json").exists()
    assert ocr.rekey_cache(old, tmp_path) == 0


def test_rekey_refuses_a_config_that_reads_differently(tmp_path):
    old = _conf()
    old["dpi"] = 200
    (tmp_path / f"{'a' * 64}_{_old_whole_hash(old)}_tesseract_5.4.0.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        ocr.rekey_cache(old, tmp_path)
    assert len(list(tmp_path.iterdir())) == 1
