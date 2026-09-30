"""Konfiguráció: .env betöltés, kulcsfeloldás, útvonalak, előkonfigurált kliensek.

A TypeSafe SDK alapértelmezésben a TYPESAFE_API_KEY env-változót olvassa, ebben a
projektben viszont a kulcs TypeSafeJAV_API_KEY néven van a .env-ben. Ezért a kulcsot
itt oldjuk fel, és explicit api_key paraméterként adjuk át a kliensnek - így nincs
rejtett függés attól, melyik változónév van éppen beállítva.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
PROMPTS_DIR = PROJECT_ROOT / "jav" / "prompts"
RUNS_DIR = PROJECT_ROOT / "runs"
CACHE_DIR = RUNS_DIR / "cache"  # Jev kérés-hash cache
STORE_PATH = PROJECT_ROOT / "store" / "jav.sqlite"  # tartós adattár (git-ignorált, PII)

# A golden készlet és a minta-PDF-ek a régi projektben maradnak, csak hivatkozzuk őket.
# Helye a JAV_LEGACY_ROOT környezeti változóból (vagy a .env-ből) jön; alapérték a fejlesztői gép útvonala (040, K0).
load_dotenv(ENV_FILE, override=False)
LEGACY_ROOT_ENV = "JAV_LEGACY_ROOT"
DEFAULT_OLD_PROJECT_ROOT = Path(r"C:\00_DEV_LOCAL\10_AIFLOW_V4")
OLD_PROJECT_ROOT = Path(os.environ.get(LEGACY_ROOT_ENV) or DEFAULT_OLD_PROJECT_ROOT)
OLD_DATA_ROOT = OLD_PROJECT_ROOT / "data"
# 048 T2: a régi Outlook-szkript (változatlanul hívva) és a projektgyökér, amelyet neki adunk: így a csatolmányok és a
# „már beolvasva” lista a saját, git-ignorált bejövő mappánkba kerül, nem a (csak olvasható) régi projektbe.
OUTLOOK_BRIDGE_SCRIPT = OLD_PROJECT_ROOT / "scripts" / "outlook_bridge.ps1"
BRIDGE_ROOT = PROJECT_ROOT / "inbox" / ".bridge"
BRIDGE_DATA_ROOT = BRIDGE_ROOT / "data"
GOLDEN_MANIFEST = OLD_PROJECT_ROOT / "flows" / "doc-extract-bare" / "golden" / "manifest.json"
GOLDEN_EXPECTED_DIR = OLD_DATA_ROOT / "golden" / "doc-extract-bare"

# Elsőként a projekt saját neve, utána az SDK alapértelmezett változója.
API_KEY_ENV_VARS = ("TypeSafeJAV_API_KEY", "TYPESAFE_API_KEY")
OPENAI_KEY_ENV_VAR = "OPENAI_API_KEY"

# Modell-adminisztráció: configs/models.json (konfig mint adat; közvetlen json-olvasás, mert a jav.cfg ezt a modult importálja).
MODELS_CONFIG = PROJECT_ROOT / "configs" / "models.json"
_MODELS = json.loads(MODELS_CONFIG.read_text(encoding="utf-8"))
MODELS_VERSION: str = _MODELS["meta"]["version"]
JEV_MODEL: str = _MODELS["jev"]["model"]
OPENAI_MODEL: str = _MODELS["openai"]["model"]
JEV_TIMEOUT_S: float = float(_MODELS["jev"]["timeout_s"])  # az SDK alap 10 s-a kevés egy 20-40 kérdéses fan-outhoz
JEV_CACHE_VERSION: int = int(_MODELS["jev"].get("cache_version", 1))
JEV_ALIAS_TTL_H: float = float(_MODELS["jev"].get("alias_ttl_hours", 24))  # az alias -> konkrét verzió feloldás érvényessége
JEV_RETRY: dict = dict(_MODELS["jev"].get("retry", {}))  # typesafe_sdk.RetryPolicy mezői (adat, nem konstans)
SDK_LOG_LEVEL_ENV = "TYPESAFE_LOG_LEVEL"  # az SDK debug-szinten a kérés-body-t (PII) is naplózza
SDK_DEBUG_ALLOW_ENV = "JAV_ALLOW_SDK_DEBUG"  # =1: a debug-napló kifejezetten engedélyezve (hibakeresés, PII-mentes adaton)
# Árlista (adat): docs.typesafe.ai/models - Jev: input token fizetős, output ingyenes; OpenAI: (input, output) USD / 1M token.
JEV_USD_PER_MTOK: float = float(_MODELS["jev"]["usd_per_mtok_input"])
OPENAI_USD_PER_MTOK: dict[str, tuple[float, float]] = {k: (float(v[0]), float(v[1])) for k, v in _MODELS["openai"]["usd_per_mtok"].items()}
class UnpricedModelError(RuntimeError):
    """067 (066 Á38): a modellnek nincs ára a `configs/models.json` `openai.usd_per_mtok` listáján. Keret alatt nem hívjuk,
    mert a költségfoglalás nullának látná, és a keret nem fogná meg a költést."""


def openai_price(model: str) -> tuple[float, float]:
    """(input, output) USD / 1M token; ár nélküli modellnél `UnpricedModelError`."""
    try:
        return OPENAI_USD_PER_MTOK[model]
    except KeyError:
        raise UnpricedModelError(f"no price for {model!r} in configs/models.json openai.usd_per_mtok") from None


OPENAI_SETTINGS: dict = {"reasoning_effort": _MODELS["openai"].get("reasoning_effort", "none"), "temperature": float(_MODELS["openai"].get("temperature", 0.0)),
                         "retries": int(_MODELS["openai"].get("retries", 2))}
TRACKER_PROJECTS: dict[str, str] = dict(_MODELS.get("burr", {}).get("tracker_projects", {}))

# override=False: a már beállított valódi környezeti változó erősebb a .env-nél
# (CI / production ott adja meg a kulcsot, nem fájlból).
load_dotenv(ENV_FILE, override=False)


class MissingAPIKeyError(RuntimeError):
    """Egy szükséges API kulcs nincs beállítva."""


def _env_hint() -> str:
    return f"\nKeresett .env: {ENV_FILE}" + ("  (nem létezik)" if not ENV_FILE.exists() else "") + "\nMinta: .env.example"


def get_api_key() -> str:
    """Visszaadja a TypeSafe API kulcsot, vagy beszédes hibát dob.

    Windows alatt a környezeti változók nevei amúgy is kis-nagybetű függetlenek,
    de a keresést explicit tesszük, hogy Linux/macOS alatt is ugyanígy működjön.
    """
    for name in API_KEY_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()

    raise MissingAPIKeyError("Nincs TypeSafe API kulcs. Várt változók: " + ", ".join(API_KEY_ENV_VARS) + _env_hint())


def get_openai_key() -> str:
    """Visszaadja az OpenAI kulcsot (G-kar), vagy beszédes hibát dob."""
    value = os.environ.get(OPENAI_KEY_ENV_VAR)
    if value and value.strip():
        return value.strip()
    raise MissingAPIKeyError(f"Nincs OpenAI API kulcs. Várt változó: {OPENAI_KEY_ENV_VAR}" + _env_hint())


def build_retry_policy() -> RetryPolicy:
    """Explicit RetryPolicy a `configs/models.json` `jev.retry` blokkjából (429/5xx/időtúllépés/kapcsolat újrapróbálva,
    a `timeout` az egy SDK-hívásra jutó teljes keret; a `Retry-After` fejlécet tiszteli). Hiányzó mező = SDK-alap."""
    return RetryPolicy(**{k: v for k, v in JEV_RETRY.items() if not k.startswith("_")})  # `_note` = megjegyzés a JSON-ban


def guard_sdk_logging() -> bool:
    """`TYPESAFE_LOG_LEVEL=debug|info` a kérés-body-t (a dokumentum szövegét, PII) is naplózza. Ezt csak kifejezett
    engedéllyel (`JAV_ALLOW_SDK_DEBUG=1`) hagyjuk; különben WARNING-ra emeljük. Igaz, ha beavatkozott."""
    level = (os.environ.get(SDK_LOG_LEVEL_ENV) or "").strip().lower()
    if level not in ("debug", "info") or os.environ.get(SDK_DEBUG_ALLOW_ENV, "").strip() == "1":
        return False
    logging.getLogger("typesafe_sdk").setLevel(logging.WARNING)
    print(f"[jav] {SDK_LOG_LEVEL_ENV}={level} figyelmen kívül hagyva (PII a naplóban); engedélyezés: {SDK_DEBUG_ALLOW_ENV}=1", file=sys.stderr)
    return True


def make_client(**kwargs: object) -> TypeSafeClient:
    """Szinkron TypeSafe kliens a projekt kulcsával, a models.json RetryPolicy-jával és napló-védelemmel.

    Használat context managerként:
        with make_client() as client:
            client.system_one(...)
    """
    guard_sdk_logging()
    kwargs.setdefault("api_key", get_api_key())
    kwargs.setdefault("timeout", JEV_TIMEOUT_S)
    kwargs.setdefault("retry", build_retry_policy())
    return TypeSafeClient(**kwargs)  # type: ignore[arg-type]


def make_async_client(**kwargs: object) -> AsyncTypeSafeClient:
    """Aszinkron TypeSafe kliens a projekt kulcsával."""
    guard_sdk_logging()
    kwargs.setdefault("api_key", get_api_key())
    kwargs.setdefault("timeout", JEV_TIMEOUT_S)
    kwargs.setdefault("retry", build_retry_policy())
    return AsyncTypeSafeClient(**kwargs)  # type: ignore[arg-type]


def load_prompt(name: str = "invoice_hu_prompt.md") -> str:
    """A verbatim átemelt prompt, a fejléc-kommentet (HTML comment) levágva."""
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    if text.startswith("<!--"):
        end = text.find("-->")
        if end != -1:
            text = text[end + 3 :]
    return text.strip()
