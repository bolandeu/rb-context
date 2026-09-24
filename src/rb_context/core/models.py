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


class ProviderRun(BaseModel):
    """Итог одного провайдера по одному запросу: сколько нашёл или почему упал."""

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
