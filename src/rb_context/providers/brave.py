from __future__ import annotations

import html
import re

from ..core.errors import ProviderError, QuotaExceeded
from ..core.models import SearchHit, extract_domain
from .base import Health, SearchProvider
from .http import PROBE_TIMEOUT, HttpProvider

_TAG_RE = re.compile(r"<[^>]+>")
# Brave отдаёт не больше 20 результатов на запрос.
MAX_COUNT = 20


def _plain(text: str) -> str:
    """Описание Brave приходит с <strong>-подсветкой и HTML-сущностями."""
    return html.unescape(_TAG_RE.sub("", text))


class BraveProvider(HttpProvider, SearchProvider):
    """Brave Search API (официального Python SDK нет — REST через `HttpProvider`)."""

    name = "brave"
    summary = "Brave — независимый веб-индекс, описание и доп. сниппеты"
    base_url = "https://api.search.brave.com/res/v1"
    required = False  # context работает и без Brave

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key  # None — ключ читается при первом запросе

    def auth_headers(self) -> dict[str, str]:
        return {"X-Subscription-Token": self._api_key or self.require_api_key(), "Accept": "application/json"}

    @classmethod
    def for_health_check(cls, target: str | None = None) -> BraveProvider:
        # Проверка идёт через обычный search(): одна попытка и таймаут проверки (стандарт §8).
        provider = cls()
        provider.target = target
        provider.retries, provider.timeout = 0, PROBE_TIMEOUT
        return provider

    def health_check(self) -> Health:
        """Поиск с `count=1`: бесплатного эндпоинта у Brave нет, это самый дешёвый запрос."""
        try:
            self.search("test", limit=1)
        except QuotaExceeded as exc:
            return Health(status="quota_exhausted", message=exc.message)
        return Health()

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        try:
            data = self.get_json("/web/search", q=query, count=min(limit, MAX_COUNT), extra_snippets="true")
        except ProviderError as exc:
            # Исчерпан месячный лимит: 429 с кодом QUOTA_LIMITED в теле (просто частота — RATE_LIMITED) или 402.
            if exc.status == 402 or "QUOTA_LIMITED" in exc.message:
                raise QuotaExceeded(self.name, f"HTTP {exc.status} QUOTA_LIMITED", status=exc.status) from exc
            raise
        results = (data.get("web") or {}).get("results") or []
        return [
            SearchHit(
                provider=self.name,
                query=query,
                position=position,
                url=item["url"],
                domain=extract_domain(item["url"]),
                title=_plain(item.get("title") or ""),
                snippet=" … ".join(
                    _plain(s) for s in [item.get("description") or "", *item.get("extra_snippets", [])] if s
                ),
                published=item.get("page_age"),
            )
            for position, item in enumerate(results, start=1)
        ]
