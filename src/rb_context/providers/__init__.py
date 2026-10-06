"""Поисковые провайдеры: один модуль на внешний сервис, все регистрируются в `PROVIDERS`.

Новый провайдер: подкласс `SearchProvider` в своём модуле + строка в
`PROVIDERS`. Дальше он доступен по имени в `context search --provider`,
`context auth login --provider` и в `providers` конфига проекта. Сервис с
официальным SDK оборачивается им (exa, tavily), без SDK — `HttpProvider`
(brave, hackernews, github, wikipedia), CLI — subprocess с его `--json` (serp); во всех случаях наружу
только `ProviderError` / `AuthRequired`.

Каждый провайдер реализует `health_check()` — это то, что проверяет
`context auth status --check` (см. `base.Provider`).
"""

from __future__ import annotations

from ..core.errors import InvalidArguments
from .base import Health, Provider, Quota, SearchProvider, all_providers
from .brave import BraveProvider
from .exa import ExaProvider
from .github import GitHubProvider
from .hackernews import HackerNewsProvider
from .http import HttpProvider
from .serp import SerpProvider
from .tavily import TavilyProvider
from .wikipedia import WikipediaProvider

PROVIDERS: dict[str, type[SearchProvider]] = {
    ExaProvider.name: ExaProvider,
    TavilyProvider.name: TavilyProvider,
    BraveProvider.name: BraveProvider,
    SerpProvider.name: SerpProvider,
    HackerNewsProvider.name: HackerNewsProvider,
    GitHubProvider.name: GitHubProvider,
    WikipediaProvider.name: WikipediaProvider,
}


def providers_help() -> str:
    """Список провайдеров для --help: `exa (Exa — ...); ...`."""
    return "; ".join(f"{name} ({cls.summary})" if cls.summary else name for name, cls in PROVIDERS.items())


def provider_class(name: str) -> type[SearchProvider]:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise InvalidArguments(f"Неизвестный провайдер '{name}'. Доступны: {', '.join(PROVIDERS)}.") from None


__all__ = [
    "PROVIDERS",
    "BraveProvider",
    "ExaProvider",
    "GitHubProvider",
    "HackerNewsProvider",
    "Health",
    "HttpProvider",
    "Provider",
    "Quota",
    "SearchProvider",
    "SerpProvider",
    "TavilyProvider",
    "WikipediaProvider",
    "all_providers",
    "provider_class",
    "providers_help",
]
