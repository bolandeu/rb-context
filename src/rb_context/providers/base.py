from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..core.errors import AuthRequired
from ..core.models import SearchHit
from ..core.version import CLI_NAME
from ..credentials import manager as credentials


class SearchProvider(ABC):
    """Интерфейс поискового провайдера: запрос → список `SearchHit`.

    Подкласс задаёт `name` (ключ в реестре `providers.PROVIDERS` и имя
    credential в keychain), `summary` (строка для --help) и реализует
    `search`. Сбои сервиса — только `ProviderError` / `AuthRequired`:
    исключения SDK наружу не выходят.
    """

    name: ClassVar[str]
    summary: ClassVar[str] = ""
    # Режимы поиска сервиса (`--<name>-mode`); пусто — режимов нет.
    modes: ClassVar[tuple[str, ...]] = ()
    # True — можно несколько режимов через запятую (serp: yandex,google).
    multi_mode: ClassVar[bool] = False
    # False — ключи хранит не context (serp держит их сам), `auth login` к нему не относится.
    needs_api_key: ClassVar[bool] = True

    @classmethod
    def check(cls) -> tuple[bool, str | None]:
        """Готов ли провайдер к работе и что сделать, если нет — для doctor и auth status."""
        if cls.load_api_key():
            return True, None
        return False, f"run '{CLI_NAME} auth login --provider {cls.name}'"

    @classmethod
    def load_api_key(cls) -> str | None:
        """Ключ из CONTEXT_<PROVIDER>_API_KEY или связки ключей ОС."""
        return credentials.get_secret(cls.name)

    @classmethod
    def require_api_key(cls) -> str:
        api_key = cls.load_api_key()
        if not api_key:
            raise AuthRequired(cls.name)
        return api_key

    @abstractmethod
    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        """До `limit` результатов по запросу; `mode` — один из `modes` или None (по умолчанию сервиса).

        Пустой ответ — не ошибка.
        """
        ...
