"""Configuration: .env loading, key resolution, paths, preconfigured clients.

By default the TypeSafe SDK reads the TYPESAFE_API_KEY environment variable, but in
this project the key is in the .env under the name TypeSafeJAV_API_KEY. So the key is
resolved here and passed to the client as an explicit api_key parameter - this way
there is no hidden dependency on which variable name happens to be set.
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
CACHE_DIR = RUNS_DIR / "cache"  # JEV request-hash cache
STORE_PATH = PROJECT_ROOT / "store" / "jav.sqlite"  # durable store (git-ignored, PII)

# The golden set and the sample PDFs stay in the legacy project; we only reference them.
# Location: the JAV_LEGACY_ROOT environment variable (or the .env); default: the dev machine's path (040, K0).
load_dotenv(ENV_FILE, override=False)
LEGACY_ROOT_ENV = "JAV_LEGACY_ROOT"
DEFAULT_OLD_PROJECT_ROOT = Path(r"C:\00_DEV_LOCAL\10_AIFLOW_V4")
OLD_PROJECT_ROOT = Path(os.environ.get(LEGACY_ROOT_ENV) or DEFAULT_OLD_PROJECT_ROOT)
OLD_DATA_ROOT = OLD_PROJECT_ROOT / "data"
# 048 T2: the legacy Outlook script (called unchanged) and the project root we give it: this way the attachments and the
# "already read" list land in our own git-ignored inbox folder, not in the (read-only) legacy project.
OUTLOOK_BRIDGE_SCRIPT = OLD_PROJECT_ROOT / "scripts" / "outlook_bridge.ps1"
BRIDGE_ROOT = PROJECT_ROOT / "inbox" / ".bridge"
BRIDGE_DATA_ROOT = BRIDGE_ROOT / "data"
GOLDEN_MANIFEST = OLD_PROJECT_ROOT / "flows" / "doc-extract-bare" / "golden" / "manifest.json"
GOLDEN_EXPECTED_DIR = OLD_DATA_ROOT / "golden" / "doc-extract-bare"

# The project's own name first, then the SDK's default variable.
API_KEY_ENV_VARS = ("TypeSafeJAV_API_KEY", "TYPESAFE_API_KEY")
OPENAI_KEY_ENV_VAR = "OPENAI_API_KEY"

# Model administration: configs/models.json (config as data; read with json directly, as jav.cfg imports this module).
MODELS_CONFIG = PROJECT_ROOT / "configs" / "models.json"
_MODELS = json.loads(MODELS_CONFIG.read_text(encoding="utf-8"))
MODELS_VERSION: str = _MODELS["meta"]["version"]
JEV_MODEL: str = _MODELS["jev"]["model"]
OPENAI_MODEL: str = _MODELS["openai"]["model"]
JEV_TIMEOUT_S: float = float(_MODELS["jev"]["timeout_s"])  # SDK default 10 s is too short for 20-40 question fan-outs
JEV_CACHE_VERSION: int = int(_MODELS["jev"].get("cache_version", 1))
JEV_ALIAS_TTL_H: float = float(_MODELS["jev"].get("alias_ttl_hours", 24))  # how long an alias resolution stays valid
JEV_RETRY: dict = dict(_MODELS["jev"].get("retry", {}))  # typesafe_sdk.RetryPolicy fields (data, not a constant)
SDK_LOG_LEVEL_ENV = "TYPESAFE_LOG_LEVEL"  # at debug level the SDK logs the request body (PII) too
SDK_DEBUG_ALLOW_ENV = "JAV_ALLOW_SDK_DEBUG"  # =1: debug log explicitly allowed (debugging, on PII-free data)
# Price list (data): docs.typesafe.ai/models - JEV: input tokens are billed, output is free;
# OpenAI: (input, output) USD / 1M tokens.
JEV_USD_PER_MTOK: float = float(_MODELS["jev"]["usd_per_mtok_input"])
OPENAI_USD_PER_MTOK: dict[str, tuple[float, float]] = {k: (float(v[0]), float(v[1])) for k, v in _MODELS["openai"]["usd_per_mtok"].items()}
class UnpricedModelError(RuntimeError):
    """067 (066 Á38): the model has no price in the `configs/models.json` `openai.usd_per_mtok` list. It is not called
    under a budget, because the cost reservation would see zero and the budget would not catch the spending."""


def openai_price(model: str) -> tuple[float, float]:
    """(input, output) USD / 1M tokens; `UnpricedModelError` for a model without a price."""
    try:
        return OPENAI_USD_PER_MTOK[model]
    except KeyError:
        raise UnpricedModelError(f"no price for {model!r} in configs/models.json openai.usd_per_mtok") from None


OPENAI_SETTINGS: dict = {"reasoning_effort": _MODELS["openai"].get("reasoning_effort", "none"), "temperature": float(_MODELS["openai"].get("temperature", 0.0)),
                         "retries": int(_MODELS["openai"].get("retries", 2))}
TRACKER_PROJECTS: dict[str, str] = dict(_MODELS.get("burr", {}).get("tracker_projects", {}))

# override=False: a real environment variable that is already set wins over the .env
# (CI / production supplies the key there, not from a file).
load_dotenv(ENV_FILE, override=False)


class MissingAPIKeyError(RuntimeError):
    """A required API key is not set."""


def _env_hint() -> str:
    return f"\nKeresett .env: {ENV_FILE}" + ("  (nem létezik)" if not ENV_FILE.exists() else "") + "\nMinta: .env.example"


def get_api_key() -> str:
    """Returns the TypeSafe API key, or raises a descriptive error.

    On Windows environment variable names are case-insensitive anyway, but the
    lookup is made explicit so that it works the same way on Linux/macOS.
    """
    for name in API_KEY_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()

    raise MissingAPIKeyError("Nincs TypeSafe API kulcs. Várt változók: " + ", ".join(API_KEY_ENV_VARS) + _env_hint())


def get_openai_key() -> str:
    """Returns the OpenAI key (G path), or raises a descriptive error."""
    value = os.environ.get(OPENAI_KEY_ENV_VAR)
    if value and value.strip():
        return value.strip()
    raise MissingAPIKeyError(f"Nincs OpenAI API kulcs. Várt változó: {OPENAI_KEY_ENV_VAR}" + _env_hint())


def build_retry_policy() -> RetryPolicy:
    """Explicit RetryPolicy from the `jev.retry` block of `configs/models.json` (429/5xx/timeout/connection are retried,
    `timeout` is the total allowance for one SDK call; the `Retry-After` header is honoured). Missing field = SDK
    default."""
    return RetryPolicy(**{k: v for k, v in JEV_RETRY.items() if not k.startswith("_")})  # `_note` = a note in the JSON


def guard_sdk_logging() -> bool:
    """`TYPESAFE_LOG_LEVEL=debug|info` also logs the request body (the document text, PII). This is allowed only with
    explicit permission (`JAV_ALLOW_SDK_DEBUG=1`); otherwise the level is raised to WARNING. True if it intervened."""
    level = (os.environ.get(SDK_LOG_LEVEL_ENV) or "").strip().lower()
    if level not in ("debug", "info") or os.environ.get(SDK_DEBUG_ALLOW_ENV, "").strip() == "1":
        return False
    logging.getLogger("typesafe_sdk").setLevel(logging.WARNING)
    print(f"[jav] {SDK_LOG_LEVEL_ENV}={level} figyelmen kívül hagyva (PII a naplóban); engedélyezés: {SDK_DEBUG_ALLOW_ENV}=1", file=sys.stderr)
    return True


def make_client(**kwargs: object) -> TypeSafeClient:
    """Synchronous TypeSafe client with the project key, the models.json RetryPolicy and log protection.

    Use it as a context manager:
        with make_client() as client:
            client.system_one(...)
    """
    guard_sdk_logging()
    kwargs.setdefault("api_key", get_api_key())
    kwargs.setdefault("timeout", JEV_TIMEOUT_S)
    kwargs.setdefault("retry", build_retry_policy())
    return TypeSafeClient(**kwargs)  # type: ignore[arg-type]


def make_async_client(**kwargs: object) -> AsyncTypeSafeClient:
    """Asynchronous TypeSafe client with the project key."""
    guard_sdk_logging()
    kwargs.setdefault("api_key", get_api_key())
    kwargs.setdefault("timeout", JEV_TIMEOUT_S)
    kwargs.setdefault("retry", build_retry_policy())
    return AsyncTypeSafeClient(**kwargs)  # type: ignore[arg-type]


def load_prompt(name: str = "invoice_hu_prompt.md") -> str:
    """The verbatim ported prompt, with the header comment (HTML comment) cut off."""
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    if text.startswith("<!--"):
        end = text.find("-->")
        if end != -1:
            text = text[end + 3 :]
    return text.strip()
