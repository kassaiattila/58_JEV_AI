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
import re
import sys
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    # 203: the SDK and its HTTP library are loaded when a client is built, not with the package. Every module of the
    # application imports this one, the isolated reader process too, which then spent about 0.5 s of its 1.1 s start
    # loading network code it must not use.
    from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # 208: jav/core/config.py

# 231 (stage E, E2; the owner's decisions of 2026-10-29): the start-up description. `JAV_START` names a JSON file that
# says where this installation's configs (`configs`), writable data (`data`: the store, the runs, the caches, the
# inbox, the logs) and keys (`env`) are, and which installation its store belongs to (`installation`); a relative path
# is read from the file's folder. Without it everything stays under the program's folder, as before. It is read when
# this module is first imported, before any config is read; a description that cannot be read, names an unknown key or
# a data folder that does not exist stops the start (`StartError`), so a typo never starts an empty installation.
START_ENV = "JAV_START"
_START_KEYS = ("configs", "data", "env", "installation")
_INSTALLATION = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


class StartError(RuntimeError):
    """The start-up description cannot be used (unreadable, an unknown key, a data folder that does not exist)."""


def _start_description() -> dict[str, Any]:
    named = os.environ.get(START_ENV)
    if not named:
        return {}
    path = Path(named)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StartError(f"the start-up description {path} cannot be read: {exc}") from exc
    if not isinstance(data, dict) or (unknown := sorted(set(data) - set(_START_KEYS))):
        raise StartError(f"the start-up description {path} names unknown keys: {unknown if isinstance(data, dict) else data!r}")
    out: dict[str, Any] = {}
    for key in ("configs", "data", "env"):
        if key in data:
            out[key] = (path.parent / str(data[key])).resolve()
    if "installation" in data:
        if not isinstance(data["installation"], str) or not _INSTALLATION.fullmatch(data["installation"]):
            raise StartError(f"the installation in {path} is 3 to 64 lowercase letters, digits and hyphens")
        out["installation"] = data["installation"]
    for key in ("configs", "data"):
        if key in out and not out[key].is_dir():
            raise StartError(f"the {key} folder of the start-up description does not exist: {out[key]}")
    return out


_START = _start_description()
CONFIG_ROOT: Path = _START.get("configs", PROJECT_ROOT / "configs")  # E2: the rule files, registries and prompts
DATA_ROOT: Path = _START.get("data", PROJECT_ROOT)  # E2: everything the installation writes
INSTALLATION_ID: str | None = _START.get("installation")  # E2: the store's own installation (None: not checked)
ENV_FILE: Path = _START.get("env", PROJECT_ROOT / ".env")
# 227 (plan R3c): a secret of `.env` or the environment, by its name and length; the data guard and the operations
# log mask these (`read_env_secrets`)
ENV_SECRET_NAME = re.compile(r"(?i)key|token|secret|passw|pwd")
ENV_SECRET_MIN_LEN = 12
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
PROMPTS_DIR = CONFIG_ROOT / "prompts"  # 209 (R2b): the instructions sent to a model are config data
# 231 (F, D4): the interface's Hungarian dictionary, which the service's labels are displayed with too (jav/core/display.py)
UI_HUNGARIAN = PROJECT_ROOT / "ui" / "src" / "i18n" / "hu-native.json"
UI_ENGLISH = PROJECT_ROOT / "ui" / "src" / "i18n" / "en-native.json"
RUNS_DIR = DATA_ROOT / "runs"
CACHE_DIR = RUNS_DIR / "cache"  # JEV request-hash cache
STORE_PATH = DATA_ROOT / "store" / "jav.sqlite"  # durable store (git-ignored, PII)
INBOX_ROOT = DATA_ROOT / "inbox"  # E2: the downloaded emails
LOG_DIR = RUNS_DIR / "logs"  # E2: the long-running processes' rotating logs

# The golden set and the sample PDFs stay in the legacy project; we only reference them.
# Location: the JAV_LEGACY_ROOT environment variable (or the .env); default: the `10_AIFLOW_V4` folder next to this
# repository (076: no machine path in the code).
load_dotenv(ENV_FILE, override=False)
LEGACY_ROOT_ENV = "JAV_LEGACY_ROOT"
DEFAULT_OLD_PROJECT_ROOT = PROJECT_ROOT.parent / "10_AIFLOW_V4"
OLD_PROJECT_ROOT = Path(os.environ.get(LEGACY_ROOT_ENV) or DEFAULT_OLD_PROJECT_ROOT)
OLD_DATA_ROOT = OLD_PROJECT_ROOT / "data"
# 048 T2: the Outlook script and the project root we give it: this way the attachments and the "already read" list land
# in our own git-ignored inbox folder, not in the (read-only) legacy project. 148: the script is ported from the legacy
# project (it reads the Sent Items folder too; an unknown folder is an error).
OUTLOOK_BRIDGE_SCRIPT = PROJECT_ROOT / "scripts" / "outlook_bridge.ps1"
BRIDGE_ROOT = INBOX_ROOT / ".bridge"
BRIDGE_DATA_ROOT = BRIDGE_ROOT / "data"
GOLDEN_MANIFEST = OLD_PROJECT_ROOT / "flows" / "doc-extract-bare" / "golden" / "manifest.json"
GOLDEN_EXPECTED_DIR = OLD_DATA_ROOT / "golden" / "doc-extract-bare"

# The project's own name first, then the SDK's default variable.
API_KEY_ENV_VARS = ("TypeSafeJAV_API_KEY", "TYPESAFE_API_KEY")
OPENAI_KEY_ENV_VAR = "OPENAI_API_KEY"
# 121: Azure Document Intelligence, called directly (jav/documents/azure_di.py); without them the legacy sidecar is used
AZURE_DI_ENV_VARS = ("AZURE_DI_ENDPOINT", "AZURE_DI_KEY")

# Model administration: configs/models.json (config as data; read with json directly, as jav.core.cfg imports this module).
MODELS_CONFIG = CONFIG_ROOT / "models.json"
_MODELS = json.loads(MODELS_CONFIG.read_text(encoding="utf-8"))
MODELS_VERSION: str = _MODELS["meta"]["version"]
JEV_MODEL: str = _MODELS["jev"]["model"]
OPENAI_MODEL: str = _MODELS["openai"]["model"]
JEV_TIMEOUT_S: float = float(_MODELS["jev"]["timeout_s"])  # SDK default 10 s is too short for 20-40 question fan-outs
JEV_CACHE_VERSION: int = int(_MODELS["jev"].get("cache_version", 1))
JEV_ALIAS_TTL_H: float = float(_MODELS["jev"].get("alias_ttl_hours", 24))  # how long an alias resolution stays valid
JEV_WATCH_ALIAS: str = _MODELS["jev"].get("watch_alias", "jev-latest")  # 200: the provider's moving name, only looked at
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


def read_env_secrets(env_file: Path) -> dict[str, str]:
    """The secret values of `.env` (key, token, password; at least 12 characters). Missing file: empty. 227 (plan
    R3c): here, so the operations log needs no developer tool (until then the data guard's)."""
    if not env_file.is_file():
        return {}
    out: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ENV_LINE.match(line)
        if not m or line.lstrip().startswith("#"):
            continue
        name, value = m.group(1), m.group(2).strip().strip("'\"")
        if ENV_SECRET_NAME.search(name) and len(value) >= ENV_SECRET_MIN_LEN:
            out[name] = value
    return out


def openai_price(model: str) -> tuple[float, float]:
    """(input, output) USD / 1M tokens; `UnpricedModelError` for a model without a price."""
    try:
        return OPENAI_USD_PER_MTOK[model]
    except KeyError:
        raise UnpricedModelError(f"no price for {model!r} in configs/models.json openai.usd_per_mtok") from None


def openai_priced_model(*, requested: str, actual: str | None) -> str | None:
    """167 (review AI-12): the model whose configured price an answer is charged at: the answering model's own, else
    the requested model's (a dated snapshot such as `gpt-5.4-mini-2026-03-17`, or any name without a price of its
    own); None when neither has a price."""
    for model in (actual, requested):
        if model and model in OPENAI_USD_PER_MTOK:
            return model
    return None


def openai_cost(usage: Any, *, requested: str, actual: str | None) -> Decimal | None:
    """167 (review AI-12): the USD cost of one OpenAI answer, the one price rule of every caller: tokens × the price of
    `openai_priced_model`, exact in Decimal, rounded to 0.000001 USD. None is an unknown cost: no configured price, or
    a usage that reports nothing (no usage object, or a Pydantic AI usage without values). The ledger then records no
    cost, and the call log keeps the call's reserved maximum committed (`jav/core/calls.py`)."""
    model = openai_priced_model(requested=requested, actual=actual)
    if model is None or usage is None or (hasattr(usage, "has_values") and not usage.has_values()):
        return None
    price_in, price_out = (Decimal(str(p)) for p in OPENAI_USD_PER_MTOK[model])
    exact = (Decimal(usage.input_tokens or 0) * price_in + Decimal(usage.output_tokens or 0) * price_out) / Decimal(1_000_000)
    return exact.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


OPENAI_SETTINGS: dict = {"reasoning_effort": _MODELS["openai"].get("reasoning_effort", "none"), "temperature": float(_MODELS["openai"].get("temperature", 0.0)),
                         "retries": int(_MODELS["openai"].get("retries", 2)),
                         # 075 (S02): the OpenAI client's own transport retries are paid requests the reservation must
                         # count; 0 = none (the work queue repeats a failed item instead)
                         "sdk_max_retries": int(_MODELS["openai"].get("sdk_max_retries", 0))}
TRACKER_PROJECTS: dict[str, str] = dict(_MODELS.get("burr", {}).get("tracker_projects", {}))
# 075: Azure DI (through the legacy sidecar) is priced per page for the reservation and the call log
AZURE_DI_MODEL: str = _MODELS.get("azure_di", {}).get("model", "prebuilt-read")
AZURE_USD_PER_PAGE: Decimal = Decimal(str(_MODELS.get("azure_di", {}).get("usd_per_page", "0.0015")))

# override=False: a real environment variable that is already set wins over the .env
# (CI / production supplies the key there, not from a file).
load_dotenv(ENV_FILE, override=False)


class MissingAPIKeyError(RuntimeError):
    """A required API key is not set."""


def _env_hint() -> str:
    return f"\n.env looked for: {ENV_FILE}" + ("  (it does not exist)" if not ENV_FILE.exists() else "") + "\nSample: .env.example"


def get_api_key() -> str:
    """Returns the TypeSafe API key, or raises a descriptive error.

    On Windows environment variable names are case-insensitive anyway, but the
    lookup is made explicit so that it works the same way on Linux/macOS.
    """
    for name in API_KEY_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()

    raise MissingAPIKeyError("No TypeSafe API key. Expected variables: " + ", ".join(API_KEY_ENV_VARS) + _env_hint())


def get_openai_key() -> str:
    """Returns the OpenAI key (G path), or raises a descriptive error."""
    value = os.environ.get(OPENAI_KEY_ENV_VAR)
    if value and value.strip():
        return value.strip()
    raise MissingAPIKeyError(f"No OpenAI API key. Expected variable: {OPENAI_KEY_ENV_VAR}" + _env_hint())


def build_retry_policy() -> RetryPolicy:
    """Configured backoff and HTTP status retries, with no blind transport retries after a possible send.

    The SDK groups connection failures with broken reads, and all timeouts together. Only a transport cause proving
    that nothing was sent may retry; a lost response must reach the durable call log as an uncertain outcome.
    """
    import httpx2
    from typesafe_sdk import RetryPolicy

    def not_sent(error: BaseException) -> bool:
        cause = error.__cause__
        return isinstance(cause, (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout))

    settings = {k: v for k, v in JEV_RETRY.items() if not k.startswith("_")}
    settings.update(api_connection_error=False, api_timeout_error=False, predicate=not_sent)
    return RetryPolicy(**settings)


def guard_sdk_logging() -> bool:
    """`TYPESAFE_LOG_LEVEL=debug|info` also logs the request body (the document text, PII). This is allowed only with
    explicit permission (`JAV_ALLOW_SDK_DEBUG=1`); otherwise the level is raised to WARNING. True if it intervened."""
    level = (os.environ.get(SDK_LOG_LEVEL_ENV) or "").strip().lower()
    if level not in ("debug", "info") or os.environ.get(SDK_DEBUG_ALLOW_ENV, "").strip() == "1":
        return False
    logging.getLogger("typesafe_sdk").setLevel(logging.WARNING)
    print(f"[jav] {SDK_LOG_LEVEL_ENV}={level} ignored (personal data in the log); to allow it: {SDK_DEBUG_ALLOW_ENV}=1", file=sys.stderr)
    return True


def openai_chat_model():
    """The Pydantic AI chat model of the configured OpenAI model, with the client's own retries set explicitly
    (`sdk_max_retries` in configs/models.json, 075), so that every physical request is one the reservation counted."""
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    client = AsyncOpenAI(api_key=get_openai_key(), max_retries=OPENAI_SETTINGS["sdk_max_retries"])
    return OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(openai_client=client))


def make_client(**kwargs: object) -> TypeSafeClient:
    """Synchronous TypeSafe client with the project key, the models.json RetryPolicy and log protection.

    Use it as a context manager:
        with make_client() as client:
            client.system_one(...)
    """
    from typesafe_sdk import TypeSafeClient

    guard_sdk_logging()
    kwargs.setdefault("api_key", get_api_key())
    kwargs.setdefault("timeout", JEV_TIMEOUT_S)
    kwargs.setdefault("retry", build_retry_policy())
    return TypeSafeClient(**kwargs)  # type: ignore[arg-type]


def make_async_client(**kwargs: object) -> AsyncTypeSafeClient:
    """Asynchronous TypeSafe client with the project key."""
    from typesafe_sdk import AsyncTypeSafeClient

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
