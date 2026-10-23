"""160 (review T-1): a test never reads or writes the real OCR cache (`runs/ocr/`: recognised text of real documents,
personal data). Two tests lived from it: on a clean copy of the repository they failed, and on this machine they
added files to it. The shared test set-up points the cache at a temporary folder."""

from jav import ocr
from jav.core.config import PROJECT_ROOT


def test_the_ocr_cache_is_a_temporary_folder_during_tests():
    assert not ocr.CACHE_DIR.resolve().is_relative_to(PROJECT_ROOT.resolve())


def test_each_test_gets_an_empty_ocr_cache():
    assert not ocr.CACHE_DIR.exists() or not any(ocr.CACHE_DIR.iterdir())
    ocr.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (ocr.CACHE_DIR / "left-by-a-test.json").write_text("{}", encoding="utf-8")
