"""OCR-lánc (BACKLOG 7, B5): szöveg nélküli PDF -> oldalkép -> tesseract szó-dobozok -> a közös sor- / cella-építő.

Újrahasznosítás (CLAUDE.md §3): a régi sidecar (`10_AIFLOW_V4/sidecar/app/providers/tesseract_ocr.py`) mintája - PDF
oldalképre (ott pdf2image + poppler, itt pypdfium2, ami már a venvben van), tesseract `image_to_data` (itt a CLI TSV-je:
ugyanaz a táblázat, szó-szintű bizalommal), a szó-bizalom átlaga minőségjelnek. Ami új: a szó-dobozokból ugyanaz a
sor- és cella-rekonstrukció készül, mint a szövegréteges PDF-nél (`jav/pdf.py: build_layout`), ezért a jelöltkeresők, a
Jev-state és az ellenőrző kérdések forrástól függetlenül működnek. A magyar + angol nyelvcsomag a régi sidecar
Docker-képéből jött (`tools/tessdata`, tessdata_fast).

Motor (configs/ocr.json `engine`): `auto` = natív tesseract, ha van (a gépen telepített 5.4; ~7-10 s / oldal), különben
a régi sidecar-kép `docker run`-nal (ugyanaz a parancs a konténerben; a gépen ~30× lassabb, mert a Docker-VM sok más
konténerrel osztozik) - ha egyik sincs, `OcrUnavailableError` (a flow `needs_ocr` terminálisba megy, nem dől el).

Lemez-gyorsítótár `runs/ocr/<doc sha256>_<konfig-hash>_<tesseract-verzió>.json` (PII, mint a Jev-cache): a golden-futás
másodszor OCR nélkül fut, a determinizmus-mérés az OCR-t nem ismétli (az OCR determinisztikus; a Jev-t mérjük).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from jav import cfg, pdf as pdfmod
from jav.config import PROJECT_ROOT
from jav.models import LineLayout
from jav.pdf import PdfText, build_layout, text_layer_ok

_CFG = cfg.load("ocr")
CONFIG_HASH = cfg.config_hash("ocr")
_TESS = _CFG["tesseract"]
DPI: int = int(_CFG["dpi"])
CACHE_DIR = PROJECT_ROOT / _CFG["cache_dir"]
LOW_CONF_WORD: float = float(_CFG["quality"]["low_conf_word"])
_TSV_LEVEL_WORD = "5"


class OcrUnavailableError(RuntimeError):
    """Nincs futtatható OCR-motor (se natív tesseract, se a Docker-kép)."""


class PageTooLarge(OcrUnavailableError):
    """067: egy oldal képe a felismerés felbontásán a `configs/service.json` `input_limits.max_page_megapixels` korlátja
    fölött lenne; a folyamat teendőt ad (`ocr:unavailable:PageTooLarge`), oldalkép nem készül."""


# --- motorok -----------------------------------------------------------------------------------


def _expand(p: str) -> str:
    return os.path.expandvars(p.replace("%LOCALAPPDATA%", os.environ.get("LOCALAPPDATA", "")))


@lru_cache(maxsize=1)
def native_exe() -> str | None:
    """A natív tesseract elérési útja a konfig jelöltjei közül (PATH, majd a szokásos Windows-helyek), vagy None."""
    for cand in _TESS["exe_candidates"]:
        cand = _expand(cand)
        found = shutil.which(cand) if os.sep not in cand and "/" not in cand else (cand if Path(cand).exists() else None)
        if found:
            return found
    return None


@lru_cache(maxsize=1)
def docker_available() -> bool:
    if _CFG["engine"] == "native" or not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", _CFG["docker"]["image"]], capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


ENGINE_ENV = "JAV_OCR_ENGINE"  # futás-idejű felülírás (native / docker / azure_di) - méréshez, a konfig marad az alap


@lru_cache(maxsize=None)
def engine(want: str | None = None) -> str:
    """`native` | `docker` | `azure_di`, a kért motor (paraméter > env > konfig `engine`: auto / native / docker / azure_di)
    és az elérhetőség szerint; hiba, ha egyik sem megy. Az `azure_di` FIZETŐS: `auto` sosem választja."""
    want = want or os.environ.get(ENGINE_ENV) or _CFG["engine"]
    if want == "azure_di":
        return "azure_di"
    if want in ("auto", "native") and native_exe():
        return "native"
    if want in ("auto", "docker") and docker_available():
        return "docker"
    raise OcrUnavailableError(
        f"nincs OCR-motor ({want}): natív tesseract ({', '.join(_TESS['exe_candidates'])}) és a Docker-kép ({_CFG['docker']['image']}) sem elérhető"
    )


@lru_cache(maxsize=None)
def engine_version(eng: str) -> str:
    """A motor verziósora (a gyorsítótár-kulcs része: más bináris / modell más eredményt adhat)."""
    if eng == "azure_di":
        return "azure_di prebuilt-read"
    if eng == "native":
        out = subprocess.run([native_exe(), "--version"], capture_output=True, text=True, timeout=30)
    else:
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "tesseract", _CFG["docker"]["image"], "--version"], capture_output=True, text=True, timeout=120)
    first = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()
    return (first[0] if first else "tesseract ?").strip()


# --- Azure Document Intelligence a régi sidecar-on át ------------------------------------------------


def azure_words(path: Path, *, run_id: str = "jav-ocr") -> tuple[list[list[dict[str, Any]]], list[float], dict[str, Any]]:
    """A régi sidecar `/parse` (chain: azure_di) + az általa mentett evidence-fájl szó-dobozai pontban (inch × 72), a
    bizalom 0-100 skálán (a tesseracttal egyező jelek). A PDF a sidecar `/data` mountja alatt kell legyen."""
    import json as _json
    import urllib.request

    az = _CFG["azure_di"]
    data_root = Path(az["data_root"])
    try:
        rel = path.resolve().relative_to(data_root.resolve())
    except ValueError as exc:
        raise OcrUnavailableError(f"azure_di: a PDF nincs a sidecar adat-mappája alatt ({data_root}): {path}") from exc
    container_path = f"{az['container_root']}/{rel.as_posix()}"
    body = _json.dumps({"path": container_path, "chain": ["azure_di"], "ai_run_id": run_id}).encode("utf-8")
    req = urllib.request.Request(f"{az['sidecar_url']}/parse", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=float(az["timeout_s"])) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise OcrUnavailableError(f"azure_di: a sidecar nem válaszolt ({az['sidecar_url']}): {exc}") from exc
    if result.get("provider_used") != "azure_di" or not result.get("evidence_ref"):
        raise OcrUnavailableError(f"azure_di: nem futott le (provider={result.get('provider_used')}, chain={result.get('fallback_chain')})")
    evidence = _json.loads((data_root / result["evidence_ref"]["path"]).read_text(encoding="utf-8"))
    return azure_evidence_words(evidence)


def azure_evidence_words(evidence: dict[str, Any]) -> tuple[list[list[dict[str, Any]]], list[float], dict[str, Any]]:
    pages: list[list[dict[str, Any]]] = []
    confs: list[float] = []
    for page in evidence["pages"]:
        scale = 72.0 if page.get("unit") == "inch" else 1.0
        words: list[dict[str, Any]] = []
        for w in page["words"]:
            poly = w.get("polygon") or []
            text = pdfmod.normalize_dashes((w.get("content") or "").strip())  # 066 Á33
            if len(poly) < 8 or not text:
                continue
            xs, ys = poly[0::2], poly[1::2]
            conf = float(w["confidence"]) * 100 if w.get("confidence") is not None else -1.0
            words.append({"text": text, "x0": min(xs) * scale, "x1": max(xs) * scale, "top": min(ys) * scale, "bottom": max(ys) * scale, "conf": conf})
            if conf >= 0:
                confs.append(conf)
        pages.append(words)
    meta = {"model_id": evidence.get("model_id"), "api_version": evidence.get("api_version")}
    return pages, confs, meta


def _tesseract_args(psm: int | None = None) -> list[str]:
    return ["-l", _TESS["lang"], "--psm", str(psm if psm is not None else _TESS["psm"]), "--oem", str(_TESS["oem"]),
            "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"]


def _run_tesseract(png: Path, out_base: Path, *, psm: int | None = None, eng: str = "native") -> str:
    """Egy oldalkép OCR-je; visszatér a TSV szövegével. Natív: `--tessdata-dir tools/tessdata`; Docker: a képben lévő tessdata."""
    timeout = float(_TESS["timeout_s"])
    if eng == "native":
        tessdata = PROJECT_ROOT / _TESS["tessdata_dir"]
        cmd = [native_exe(), str(png), str(out_base), "--tessdata-dir", str(tessdata), *_tesseract_args(psm)]
    else:
        work = png.parent
        cmd = ["docker", "run", "--rm", "-v", f"{work}:/work", "--entrypoint", "tesseract", _CFG["docker"]["image"],
               f"/work/{png.name}", f"/work/{out_base.name}", *_tesseract_args(psm)]
        timeout *= 20  # a VM-ben nagyságrenddel lassabb
    subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)
    return Path(str(out_base) + ".tsv").read_text(encoding="utf-8")


# --- oldalképek -------------------------------------------------------------------------------


def render_pages(path: str | Path, out_dir: Path, *, dpi: int = DPI, max_pages: int | None = None) -> list[Path]:
    """PDF -> oldalképek (PNG) pypdfium2-vel (poppler nélkül). Szürke, `dpi` felbontás; legfeljebb `max_pages` oldal."""
    import pypdfium2 as pdfium

    from jav.page_image import PDFIUM_LOCK  # 063: a PDFium nem szálbiztos

    max_pages = max_pages or int(_CFG["max_pages"])
    max_mp = pdfmod.input_limits().max_page_megapixels
    out: list[Path] = []
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(path))
        try:
            for i in range(min(len(doc), max_pages)):  # előbb minden oldal mérete: túl nagy oldalnál egy kép se készüljön
                w, h = doc[i].get_size()
                if pdfmod.fit_scale(w, h, scale=dpi / 72.0, max_megapixels=max_mp) < dpi / 72.0:
                    raise PageTooLarge(f"page {i + 1} ({w:.0f} x {h:.0f} pt) is over {max_mp:g} MP at {dpi} dpi")
            for i in range(min(len(doc), max_pages)):
                page = doc[i]
                bitmap = page.render(scale=dpi / 72.0, grayscale=bool(_CFG.get("grayscale", True)))
                img = bitmap.to_pil()
                p = out_dir / f"p-{i + 1}.png"
                img.save(p)
                out.append(p)
                page.close()
        finally:
            doc.close()
    return out


def page_sizes(path: str | Path) -> list[tuple[float, float]]:
    """Az oldalak mérete pontban (pypdfium2), a szóréteg normalizálásához; bármely OCR-motornál ugyanaz a vonatkoztatás."""
    import pypdfium2 as pdfium

    from jav.page_image import PDFIUM_LOCK  # 063: a PDFium nem szálbiztos

    with PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError:
            return []  # nem olvasható PDF (pl. képfájl vagy sérült): szóréteg nem lesz, az OCR-eredmény ettől még érvényes
        try:
            return [tuple(float(v) for v in doc[i].get_size()) for i in range(len(doc))]
        finally:
            doc.close()


# --- TSV -> szó-dobozok (pontban) ----------------------------------------------------------------


def parse_tsv(tsv_text: str, *, dpi: int = DPI) -> tuple[list[dict[str, Any]], list[float]]:
    """A tesseract TSV szó-sorai (`level` 5) -> `{text, x0, x1, top, bottom, conf}` pontban (72 / dpi), és a bizalmak."""
    scale = 72.0 / dpi
    words: list[dict[str, Any]] = []
    confs: list[float] = []
    for r in csv.DictReader(io.StringIO(tsv_text), delimiter="\t", quoting=csv.QUOTE_NONE):
        if r.get("level") != _TSV_LEVEL_WORD:
            continue
        text = pdfmod.normalize_dashes((r.get("text") or "").strip())  # 066 Á33
        if not text:
            continue
        try:
            left, top, width, height, conf = int(r["left"]), int(r["top"]), int(r["width"]), int(r["height"]), float(r["conf"])
        except (KeyError, ValueError):
            continue
        words.append({"text": text, "x0": left * scale, "x1": (left + width) * scale, "top": top * scale, "bottom": (top + height) * scale, "conf": conf})
        if conf >= 0:
            confs.append(conf)
    return words, confs


def _y_tolerance(pages: list[list[dict[str, Any]]]) -> float:
    heights = [w["bottom"] - w["top"] for page in pages for w in page if w["bottom"] > w["top"]]
    if not heights:
        return 3.0
    return max(3.0, 0.45 * statistics.median(heights))  # ferde szkennelés: a sor-küszöb a betűmagasság közel fele


# --- gyorsítótár + belépési pont -----------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_key(path: Path, eng: str) -> str:
    ver = engine_version(eng).replace(" ", "_").replace("/", "_")[:40]
    return f"{_sha256(path)}_{CONFIG_HASH}_{ver}"


def _to_pdftext(path: Path, data: dict[str, Any], *, cached: bool) -> PdfText:
    layout = [LineLayout.model_validate(ln) for ln in data["layout"]]
    lines = [ln.text for ln in layout]
    text = "\n".join(lines)
    ok = text_layer_ok(text)
    signals = {**data["signals"], "cached": cached, "engine": data["engine"], "engine_version": data["engine_version"], "config_hash": CONFIG_HASH}
    # 045: a régi gyorsítótár-fájlokban nincs szó- és oldalméret-adat; ekkor a szóréteg üres (nincs keret), a sorok ugyanazok
    return PdfText(path=str(path), text=text, lines=lines, layout=layout, page_count=data["page_count"], has_text_layer=False,
                   text_source="ocr" if ok else None, ocr=signals, words=data.get("words") or [],
                   page_sizes=[tuple(s) for s in data.get("page_sizes") or []])


def ocr_pdf(
    path: str | Path, *, page_count: int | None = None, use_cache: bool = True, psm: int | None = None, engine_name: str | None = None
) -> PdfText:
    """Egy PDF OCR-je: gyorsítótárból, ha van; különben oldalképek + tesseract oldalanként (vagy Azure DI a sidecar-on át) +
    közös elrendezés-építés. `has_text_layer` marad False (tény), `text_source="ocr"`, ha a felismert szöveg használható;
    az `ocr` szótár a minőségjelek. A motor a gyorsítótár-kulcs része: motorváltás = új OCR."""
    path = Path(path)
    eng = engine(engine_name)  # OcrUnavailableError, ha nincs motor
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(path, eng) + (f"_psm{psm}" if psm is not None and eng != "azure_di" else "")
    cache_file = CACHE_DIR / f"{key}.json"
    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if not cached.get("words") and eng != "azure_di":
            cached = _backfill_words(path, cached, cache_file, psm=psm, eng=eng)
        return _to_pdftext(path, cached, cached=True)

    t0 = time.perf_counter()
    extra: dict[str, Any] = {}
    if eng == "azure_di":
        pages, all_conf, extra = azure_words(path)
        n_pages = len(pages)
    else:
        with tempfile.TemporaryDirectory(prefix="jav_ocr_") as tmp:
            tmp_dir = Path(tmp)
            pngs = render_pages(path, tmp_dir)
            pages = []
            all_conf = []
            for png in pngs:
                tsv = _run_tesseract(png, tmp_dir / png.stem, psm=psm, eng=eng)
                words, confs = parse_tsv(tsv)
                pages.append(words)
                all_conf.extend(confs)
        n_pages = len(pngs)
    layout = build_layout(pages, y_tol=_y_tolerance(pages))
    n_words = sum(len(p) for p in pages)
    signals = {
        "mean_conf": round(statistics.mean(all_conf) / 100.0, 4) if all_conf else 0.0,
        "low_conf_ratio": round(sum(1 for c in all_conf if c < LOW_CONF_WORD) / len(all_conf), 4) if all_conf else 1.0,
        "words": n_words,
        "pages_ocr": n_pages,
        "dpi": DPI if eng != "azure_di" else None,
        "psm": (psm if psm is not None else int(_TESS["psm"])) if eng != "azure_di" else None,
        "seconds": round(time.perf_counter() - t0, 2),
        **extra,
    }
    data = {
        "path": str(path), "page_count": page_count if page_count is not None else n_pages, "engine": eng,
        "engine_version": engine_version(eng), "config_hash": CONFIG_HASH, "signals": signals,
        "layout": [ln.model_dump() for ln in layout],
        "words": pages,  # 045: szókeretek pontban, a sorszámmal (build_layout adja) — a szóréteghez
        "page_sizes": page_sizes(path),
    }
    if use_cache:
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return _to_pdftext(path, data, cached=False)


def _backfill_words(path: Path, cached: dict[str, Any], cache_file: Path, *, psm: int | None, eng: str) -> dict[str, Any]:
    """048: a 045 előtti gyorsítótár-bejegyzésben nincs szó- és oldalméret-adat, ezért az ilyen iratnak nem volt szórétege
    (nincs keret, a felületen nincs lapozás a mezőkhöz). A helyi motor ingyenes és determinisztikus: újrafuttatjuk, és a
    szóadatot CSAK akkor írjuk a bejegyzésbe, ha az újraolvasott sorok betűre egyeznek a tároltakkal — így a szöveg (és
    vele a korábbi JEV-kérések gyorsítótár-kulcsa) nem változik. Eltérésnél a bejegyzés változatlan marad."""
    fresh = ocr_pdf(path, page_count=cached.get("page_count"), use_cache=False, psm=psm, engine_name=eng)
    if fresh.lines != [ln["text"] for ln in cached["layout"]]:
        return cached
    cached = {**cached, "words": fresh.words, "page_sizes": [list(s) for s in fresh.page_sizes], "words_backfilled": True}
    cache_file.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    return cached


ESCALATION: dict[str, Any] = dict(_CFG.get("escalation", {}))


def ocr_with_escalation(path: str | Path, *, page_count: int | None = None, use_cache: bool = True) -> tuple[PdfText, bool]:
    """A flow OCR-lépése: az alap motor (auto / env), és ha az eredmény a policy `ocr.escalate_*` küszöbei szerint gyenge és
    az eszkaláció be van kapcsolva (configs/ocr.json), a pontosabb, fizetős motor (`azure_di`) szövege megy tovább.
    Visszatér: (PdfText, eszkalált-e). Ha az eszkaláció nem elérhető (sidecar / mount), a helyi eredmény marad."""
    from jav.policy import ocr_should_escalate

    first = ocr_pdf(path, page_count=page_count, use_cache=use_cache)
    if os.environ.get(ENGINE_ENV) or not ESCALATION.get("enabled") or first.ocr is None or first.ocr.get("engine") == ESCALATION.get("engine"):
        return first, False
    if not ocr_should_escalate(first.ocr.get("mean_conf"), first.ocr.get("low_conf_ratio")):
        return first, False
    try:
        second = ocr_pdf(path, page_count=page_count, use_cache=use_cache, engine_name=ESCALATION["engine"])
    except OcrUnavailableError:
        return first, False
    if second.ocr and (second.ocr.get("mean_conf") or 0) >= (first.ocr.get("mean_conf") or 0):
        second.ocr["escalated_from"] = first.ocr.get("engine")
        if not second.words and first.words:
            # 049: a régi Azure-gyorsítótárban nincs szóadat (újrahívása fizetős). A szöveg az Azure-é marad, a szóréteg
            # (keretek, lapozás a mezőhöz) a helyi OCR szóhelyeiből épül; ami ott nem található, keret nélkül marad.
            second.words, second.page_sizes = first.words, first.page_sizes
            second.ocr["words_from"] = first.ocr.get("engine")
        return second, True
    return first, False


def status() -> dict[str, Any]:
    """Admin / preflight: melyik motor, verzió, nyelvcsomag, gyorsítótár-méret."""
    out: dict[str, Any] = {"config_version": cfg.version("ocr"), "config_hash": CONFIG_HASH, "native_exe": native_exe(), "docker_image": _CFG["docker"]["image"],
                           "azure_sidecar": _CFG["azure_di"]["sidecar_url"], "engine_env": os.environ.get(ENGINE_ENV)}
    try:
        out["engine"] = engine()
        out["engine_version"] = engine_version(out["engine"])
    except OcrUnavailableError as exc:
        out["engine"] = None
        out["error"] = str(exc)
    tessdata = PROJECT_ROOT / _TESS["tessdata_dir"]
    out["tessdata"] = sorted(p.stem for p in tessdata.glob("*.traineddata")) if tessdata.exists() else []
    out["cache_files"] = len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0
    return out


if __name__ == "__main__":  # gyors kézi próba: python -m jav.ocr <pdf>
    r = ocr_pdf(sys.argv[1], use_cache=False)
    print(json.dumps(r.ocr, ensure_ascii=False))
    print("\n".join(r.lines[:80]))
