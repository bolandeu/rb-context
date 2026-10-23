"""The pydantic models of the project's config file."""

from __future__ import annotations

import urllib.parse

from pydantic import BaseModel, Field, field_validator


class SearchHit(BaseModel):
    """Один результат поиска в общем для всех провайдеров виде.

    `snippet` — текст, который провайдер отдал как контекст: у Exa — хайлайты,
    у Tavily — выжимка `content`, у Brave — описание и доп. сниппеты.
    """

    provider: str
    query: str
    position: int
    # Поисковик, из выдачи которого результат (только у serp: yandex / google).
    engine: str | None = None
    url: str
    domain: str
    title: str
    snippet: str = ""
    published: str | None = None
    score: float | None = None


# Валюта стоимости платных вызовов (serp — рубли); бесплатные лимиты — 0 в той же валюте.
COST_CURRENCY = "RUB"


class CallCost(BaseModel):
    """Стоимость одного вызова провайдера (общая схема T175, как у serp и wordstat).

    billable_requests — сколько запросов ушло в счёт тарифа или бесплатного лимита.
    cost_source: "free_tier" — бесплатный лимит (cost 0, платный тариф не подключён),
    "price_table" / "provider" / "cache" — как их отдал serp, None — стоимость неизвестна
    (cost None). would_cost — сколько вызов стоил бы по словам самого провайдера, в
    would_cost_unit (exa — "USD", tavily — "credits"); в cost не входит.
    """

    billable_requests: int = 0
    cost: float | None = 0.0
    cost_currency: str = COST_CURRENCY
    cost_source: str | None = "free_tier"
    would_cost: float | None = None
    would_cost_unit: str | None = None


class ProviderRun(CallCost):
    """Итог одного провайдера по одному запросу: сколько нашёл или почему упал и во что обошёлся."""

    provider: str
    query: str
    ok: bool
    count: int = 0
    error: dict | None = None


def extract_domain(url: str) -> str:
    """Домен из URL без `www.`."""
    return urllib.parse.urlparse(url).netloc.removeprefix("www.")


# Без --provider и без проекта — один провайдер: каждый запрос тратит лимит у каждого опрошенного.
DEFAULT_PROVIDERS = ["exa"]


class CliCompat(BaseModel):
    min_version: str = "0.1.0"


class ProjectConfig(BaseModel):
    version: int = 1
    name: str
    # Кого `search` опрашивает без --provider (`all` — всех).
    providers: list[str] = Field(default_factory=lambda: list(DEFAULT_PROVIDERS))
    cli: CliCompat = Field(default_factory=CliCompat)

    @field_validator("providers", mode="before")
    @classmethod
    def split_providers(cls, v: object) -> object:
        # `config set providers "a,b"` приходит строкой.
        if isinstance(v, str):
            return [name.strip() for name in v.split(",") if name.strip()]
        return v
