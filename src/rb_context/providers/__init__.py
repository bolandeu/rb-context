"""Поисковые провайдеры: один модуль на внешний сервис, все регистрируются в `PROVIDERS`.

Новый провайдер: подкласс `SearchProvider` в своём модуле + строка в
`PROVIDERS`. Дальше он доступен по имени в `context search --provider`,
`context auth login --provider` и в `providers` конфига проекта. Сервис с
официальным SDK оборачивается им (exa, tavily), без SDK — `HttpProvider`
(brave); в обоих случаях наружу только `ProviderError` / `AuthRequired`.
"""

from __future__ import annotations

from ..core.errors import InvalidArguments
from .base import SearchProvider
from .brave import BraveProvider
from .exa import ExaProvider
from .http import HttpProvider
from .tavily import TavilyProvider

PROVIDERS: dict[str, type[SearchProvider]] = {
    ExaProvider.name: ExaProvider,
    TavilyProvider.name: TavilyProvider,
    BraveProvider.name: BraveProvider,
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
    "HttpProvider",
    "SearchProvider",
    "TavilyProvider",
    "provider_class",
    "providers_help",
]
