"""Típus-csomag (type pack): egy dokumentumtípus adatpont-kinyerésének MINDEN típus-specifikus adata egy JSON-ban
(`configs/types/<típus>.json`, `cfg.load("type:<típus>")`), a kód pedig típus-független mechanizmus.

Mit tartalmaz a csomag (a régi 10_AIFLOW_V4 `types/<key>/` pack tükre, adatként):
- `fields`: a fejléc-mezők sorrendben, mindegyikhez a FAJTA (`name`, `tax_id`, `date`, `money`, `iban`, `currency`,
  `country`, `invoice_number`, `address`, `text`, `number`) - a fajta dönti el a normalizálást, az összehasonlítást
  (golden), a jelölt-fajtát (S-kar) és az evidencia-illesztést (G-kar);
- `scored_fields` / `informational_fields` (a régi `_compare_contract` és `rules.json non_scored_fields`),
  `required` (rules.json), `high_stakes` (policy), `validators` (rules.json `named` + `fields` formátum-szabályok);
- `prompt_file` + `schema_file` (a régi prompt.md és schema.json verbatim, `jav/prompts/`), ebből épül a G-kar
  kimeneti modellje (`llm_model()`: a JSON-sémából Pydantic-modell, `extra="forbid"`);
- `select_callsite` / `verify_callsite`: a Jev-hívási helyek beállításfájljai; `candidate_profile`: a jelöltkeresők
  regex-készlete (`hu` = a magyar számla eddigi viselkedése bitre azonosan, `intl` = nemzetközi bővítés, `utility` = a
  magyar közmű-számlák OCR-tűrő készlete);
- `text_labels` (2026-09-20, közmű-kör): a szabad szöveges mezők (`text` fajta) címkéi a dokumentumon (regex-lista
  mezőnként) - a címkés szöveg-kereső (`candidates.find_labelled_text`) ebből ad jelölteket, a Jev választ;
- `extends` (2026-09-20): alap-csomag (`configs/types/_base/<név>.json`, pl. a régi `_shared/utility_bill_hu`), amelynek
  mezői, listái, validátorai és séma-fájlja a gyermek elé kerülnek (a régi `extends` szemantikája: base + child); az
  alap-csomag önmagában nem futtatható típus (nincs promptja), a `keys()` nem listázza.

Új típus = új JSON (+ prompt, séma, két hívási-hely fájl) - Python-kód nélkül, ha a fajták elegendők.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from jav import cfg
from jav.config import PROMPTS_DIR

KINDS = ("name", "tax_id", "date", "money", "iban", "currency", "country", "invoice_number", "address", "text", "number",
         "boolean", "list")  # 047: igen/nem mező; tételes lista (a tétel-mezők fajtája a `list_fields`-ben)
CANDIDATE_KIND_OF = {  # mező-fajta -> jelölt-fajta (S-kar); ami nincs itt, azt nem jelöltből választjuk (Choice-lista vagy nincs)
    "name": "name", "tax_id": "tax_id", "date": "date", "money": "money", "iban": "iban", "invoice_number": "invoice_number", "address": "address",
    "number": "quantity",  # mennyiség (kWh, m3, MJ, mérőállás): a mértékegységes / mérő-címkés sorok számai (candidates.find_quantities)
}
DEFAULT_KEY = "invoice_hu"
BASE_PREFIX = "_base/"


class TypePack(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    version: str
    document: str
    golden_type_key: str
    candidate_profile: str = "hu"
    prompt_file: str
    schema_file: str
    base_schema_file: str | None = None  # az alap-csomag sémája (a mezők eleje), ha `extends`
    extends: str | None = None
    select_callsite: str | None  # None: nincs S-kar (047: a régi típusokból átalakított csomagok, csak G-kar)
    verify_callsite: str
    arms: tuple[str, ...] = ("S", "G")  # a csomaggal futtatható karok
    default_arm: str | None = None  # 053 T3: a csomag ajánlott útja, ha a recept automatikus kart kér (közmű: G, mert tételt is ad)
    parent: str | None = None  # 047: a durva felismerési kategória (configs/doc_types.json), amelyen belül ez a részletes típus
    auto_detect: bool = True  # 047: a felismerés választhatja-e (a régiben is függő típusok: nem)
    detect: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # 047: a régi detect.json kulcsszavai (required_any, supporting, excluders)
    fields: dict[str, str]  # mező -> fajta (sorrend = a séma sorrendje)
    scored_fields: tuple[str, ...]
    informational_fields: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    high_stakes: tuple[str, ...] = ()
    validators: tuple[dict[str, Any], ...] = ()
    text_labels: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # `text` fajtájú mező -> címke-regexek (jelöltkereső)
    list_fields: dict[str, dict[str, str]] = Field(default_factory=dict)  # 047: `list` mező -> tétel-mező -> fajta ({"*": fajta}: egyszerű lista)
    enums: dict[str, tuple[Any, ...]] = Field(default_factory=dict)  # 047: `mező` / `mező[].tétel-mező` -> megengedett értékek
    config_hash: str

    # --- mezőlisták fajta szerint --------------------------------------------------------

    @property
    def header_fields(self) -> tuple[str, ...]:
        """A skalár (egy értékű) mezők: ezekre van jelölt, ellenőrzés, forráshely és mezőjavítás."""
        return tuple(f for f, k in self.fields.items() if k != "list")

    @property
    def record_fields(self) -> tuple[str, ...]:
        """Minden mező a séma sorrendjében, a tételes listákkal együtt (a mentett `datapoints` kulcsai)."""
        return tuple(self.fields)

    def normalize(self, data: dict[str, Any]) -> tuple[Any, list[str]]:
        """Generatív kivonat -> normalizált rekord a csomag fajtái, tétel-leírásai és felsorolt értékei szerint."""
        from jav.models import record_from_llm

        return record_from_llm(data, self.fields, list_fields=self.list_fields, enums={k: list(v) for k, v in self.enums.items()})

    def kind(self, field: str) -> str:
        return self.fields.get(field, "text")

    def of_kind(self, *kinds: str) -> tuple[str, ...]:
        return tuple(f for f, k in self.fields.items() if k in kinds)

    @property
    def money_fields(self) -> tuple[str, ...]:
        return self.of_kind("money")

    @property
    def date_fields(self) -> tuple[str, ...]:
        return self.of_kind("date")

    @property
    def tax_id_fields(self) -> tuple[str, ...]:
        return self.of_kind("tax_id")

    @property
    def strict_scored(self) -> tuple[str, ...]:
        """Pontozott, de nem csak informatív mezők (a régi szerződés: az IBAN és a címek nem számítanak a pontosságba)."""
        return tuple(f for f in self.scored_fields if f not in self.informational_fields)

    @property
    def is_default(self) -> bool:
        return self.key == DEFAULT_KEY

    # --- séma / prompt ---------------------------------------------------------------------

    @property
    def schema_files(self) -> tuple[str, ...]:
        return ((self.base_schema_file,) if self.base_schema_file else ()) + (self.schema_file,)

    def schema(self) -> dict[str, Any]:
        """A régi séma (alap + gyermek összefésülve: a `properties` az alap sorrendjével kezdve, a `required` unió)."""
        return _merged_schema(self.schema_files)

    def llm_model(self) -> type[BaseModel]:
        """A G-kar kimeneti modellje. A magyar számlánál a kézzel írt `InvoiceLLM` (a régi séma 1:1 tükre, tesztek
        hivatkozzák); más típusnál a régi schema.json-ból (alap + gyermek) generált modell (`extra="forbid"`, minden mező nullable)."""
        if self.is_default:
            from jav.models import InvoiceLLM

            return InvoiceLLM
        return _model_from_schema(self.key, self.schema_files)


def _read_schema(name: str) -> dict[str, Any]:
    return json.loads((PROMPTS_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _merged_schema(files: tuple[str, ...]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for name in files:
        s = _read_schema(name)
        for k, v in s.get("properties", {}).items():
            props.setdefault(k, v)
        for k in s.get("required", []):
            if k not in required:
                required.append(k)
    return {"type": "object", "additionalProperties": False, "properties": props, "required": required}


def _py_type(prop: dict[str, Any], name: str, owner: str) -> Any:
    types = prop.get("type", ["string", "null"])
    if isinstance(types, str):
        types = [types]
    if "array" in types:
        item_schema = prop.get("items", {})
        item_model = _sub_model(f"{owner}_{name}_item", item_schema)
        return list[item_model]  # type: ignore[valid-type]
    base = [t for t in types if t != "null"]
    t = base[0] if base else "string"
    return {"string": str, "number": float, "integer": int, "boolean": bool}.get(t, str) | None  # type: ignore[return-value]


def _sub_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for prop_name, prop in schema.get("properties", {}).items():
        fields[prop_name] = (_py_type(prop, prop_name, name), Field(default=None, description=prop.get("description")))
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


@lru_cache(maxsize=None)
def _model_from_schema(key: str, schema_files: tuple[str, ...]) -> type[BaseModel]:
    schema = _merged_schema(schema_files)
    fields: dict[str, Any] = {}
    for prop_name, prop in schema["properties"].items():
        if prop.get("type") == "array":
            fields[prop_name] = (_py_type(prop, prop_name, f"LLM_{key}"), Field(default_factory=list, description=prop.get("description")))
        else:
            fields[prop_name] = (_py_type(prop, prop_name, f"LLM_{key}"), Field(default=None, description=prop.get("description")))
    model = create_model(f"LLM_{key}", __config__=ConfigDict(extra="forbid"), **fields)
    model.__doc__ = f"{key} kivonata a régi schema.json-ból generálva ({', '.join(schema_files)}); minden mező nullable, pénz decimális string ponttal, dátum ISO."
    return model


def _dedup(*lists: list[Any]) -> tuple[Any, ...]:
    out: list[Any] = []
    for lst in lists:
        for x in lst:
            if x not in out:
                out.append(x)
    return tuple(out)


@lru_cache(maxsize=None)
def get(key: str = DEFAULT_KEY) -> TypePack:
    """A típus-csomag betöltve és ellenőrizve (`FileNotFoundError`, ha nincs ilyen típus-csomag). `extends` esetén az
    alap-csomag mezői / listái / validátorai / sémája a gyermek elé fésülve; a `config_hash` mindkettőt fedi."""
    data = cfg.load(f"type:{key}")
    extends = data.get("extends")
    base: dict[str, Any] = cfg.load(f"type:{BASE_PREFIX}{extends}") if extends else {}
    fields = {**dict(base.get("fields", {})), **dict(data["fields"])}
    bad = [f"{f}:{k}" for f, k in fields.items() if k not in KINDS]
    if bad:
        raise ValueError(f"ismeretlen mező-fajta a(z) {key} típus-csomagban: {bad}")
    lists = {name: _dedup(list(base.get(name, [])), list(data.get(name, []))) for name in ("scored_fields", "informational_fields", "required", "high_stakes")}
    for name, lst in lists.items():
        unknown = [f for f in lst if f not in fields]
        if unknown:
            raise ValueError(f"{key}.{name}: nem a csomag mezője: {unknown}")
    validators = _dedup([dict(v) for v in base.get("validators", ())], [dict(v) for v in data.get("validators", ())])
    text_labels = {**{f: tuple(v) for f, v in base.get("text_labels", {}).items()}, **{f: tuple(v) for f, v in data.get("text_labels", {}).items()}}
    unknown_labels = [f for f in text_labels if fields.get(f) != "text"]
    if unknown_labels:
        raise ValueError(f"{key}.text_labels: csak `text` fajtájú mezőhöz adható címke: {unknown_labels}")
    list_fields = {**{f: dict(v) for f, v in base.get("list_fields", {}).items()}, **{f: dict(v) for f, v in data.get("list_fields", {}).items()}}
    bad_lists = [f for f in list_fields if fields.get(f) != "list"] + [f for f, k in fields.items() if k == "list" and f not in list_fields]
    bad_items = [f"{f}.{sub}:{k}" for f, v in list_fields.items() for sub, k in v.items() if k in ("list",) or k not in KINDS]
    if bad_lists or bad_items:
        raise ValueError(f"{key}.list_fields: a `list` mezők és a tétel-leírások nem egyeznek: {bad_lists + bad_items}")
    enums = {**{f: tuple(v) for f, v in base.get("enums", {}).items()}, **{f: tuple(v) for f, v in data.get("enums", {}).items()}}
    bad_enums = [e for e in enums if e.split("[")[0] not in fields]
    if bad_enums:
        raise ValueError(f"{key}.enums: nem a csomag mezője: {bad_enums}")
    inherit = lambda name, default=None: data.get(name, base.get(name, default))  # noqa: E731
    arms = tuple(inherit("arms", ["S", "G"]))
    default_arm = inherit("default_arm")
    if default_arm is not None and default_arm not in arms:
        raise ValueError(f"{key}.default_arm: {default_arm} nem a csomag kara ({', '.join(arms)})")
    # 067 (066 Á18): az azonosító a típus-JSON(ok) mellett a G-kar utasítás- és sémafájljainak tartalmát is fedi
    type_names = [f"type:{key}", *([f"type:{BASE_PREFIX}{extends}"] if extends else [])]
    prompt_files = [data["prompt_file"], *([base["schema_file"]] if base.get("schema_file") else []), data["schema_file"]]
    return TypePack(
        key=key,
        version=str(data["meta"]["version"]),
        document=inherit("document"),
        golden_type_key=data.get("golden_type_key", key),
        candidate_profile=inherit("candidate_profile", "hu"),
        prompt_file=data["prompt_file"],
        schema_file=data["schema_file"],
        base_schema_file=base.get("schema_file"),
        extends=extends,
        select_callsite=inherit("select_callsite"),
        verify_callsite=inherit("verify_callsite"),
        arms=arms,
        default_arm=default_arm,
        parent=inherit("parent"),
        auto_detect=bool(inherit("auto_detect", True)),
        detect={k: tuple(v) for k, v in dict(inherit("detect", {})).items()},
        fields=fields,
        scored_fields=lists["scored_fields"],
        informational_fields=lists["informational_fields"],
        required=lists["required"],
        high_stakes=lists["high_stakes"],
        validators=validators,
        text_labels=text_labels,
        list_fields=list_fields,
        enums=enums,
        config_hash=cfg.combine(cfg.config_hash(*type_names), *(cfg.file_digest(PROMPTS_DIR / f) for f in prompt_files)),
    )


def keys() -> list[str]:
    return [n.split(":", 1)[1] for n in cfg.all_names() if n.startswith("type:") and not n.split(":", 1)[1].startswith(BASE_PREFIX)]


def catalog_hash() -> str:
    """067 (066 Á18): az összes típuscsomag együttes azonosítója (a részletes típus kérdésének opciói a csomagok leírásai)."""
    return cfg.combine(*(get(k).config_hash for k in sorted(keys())))


def resolve_arm(doc_type: str, preferred: str) -> str:
    """A típus tényleges útja: a kért kar, ha a csomag támogatja; különben a csomag első kara (047: a régi típusokból
    átalakított csomagok csak G-karral futnak). `auto` (053 T3): a csomag ajánlott útja (`default_arm`), ennek híján az
    első kara. A feldolgozó (`runtime/worker.arm_for`) és a futás keretfoglalása (`work.run_budget`, 065) közös szabálya."""
    pack = get(doc_type)
    if preferred == "auto":
        return pack.default_arm or pack.arms[0]
    return preferred if preferred in pack.arms else pack.arms[0]


def reload() -> None:
    get.cache_clear()
    _model_from_schema.cache_clear()
    _merged_schema.cache_clear()


__all__ = ["KINDS", "CANDIDATE_KIND_OF", "DEFAULT_KEY", "BASE_PREFIX", "TypePack", "get", "keys", "resolve_arm", "reload"]
