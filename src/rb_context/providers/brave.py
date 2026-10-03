from __future__ import annotations

import html
import re

import httpx

from ..core.errors import ProviderError, QuotaExceeded
from ..core.models import CallCost, SearchHit, extract_domain
from .base import Health, Quota, SearchProvider
from .http import PROBE_TIMEOUT, HttpProvider

_TAG_RE = re.compile(r"<[^>]+>")
# Brave отдаёт не больше 20 результатов на запрос.
MAX_COUNT = 20


def _monthly(header: str | None) -> int | None:
    """Месячное значение из `X-RateLimit-*`: «секунда, месяц», например `1, 2000`."""
    parts = [part.strip() for part in (header or "").split(",")]
    return int(parts[-1]) if parts[-1].isdigit() else None


def _plain(text: str) -> str:
    """Описание Brave приходит с <strong>-подсветкой и HTML-сущностями."""
    return html.unescape(_TAG_RE.sub("", text))


class BraveProvider(HttpProvider, SearchProvider):
    """Brave Search API (официального Python SDK нет — REST через `HttpProvider`)."""

    name = "brave"
    summary = "Brave — независимый веб-индекс, описание и доп. сниппеты"
    base_url = "https://api.search.brave.com/res/v1"
    required = False  # context работает и без Brave
    health_check_spends_quota = True

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
        """Поиск с `count=1` — тратит 1 запрос бесплатного лимита: бесплатного эндпоинта у Brave нет.

        Остаток месячного лимита — из заголовков `X-RateLimit-*` этого ответа.
        Поэтому `auth status --check` с brave не запускают по расписанию.
        """
        try:
            response = self._search_response("test", 1)
        except QuotaExceeded as exc:
            return Health(status="quota_exhausted", message=exc.message)
        remaining = _monthly(response.headers.get("X-RateLimit-Remaining"))
        limit = _monthly(response.headers.get("X-RateLimit-Limit"))
        return Health(
            quota=Quota(remaining=remaining, limit=limit) if remaining is not None or limit is not None else None,
            message="проверка — поиск count=1: тратит 1 запрос бесплатного лимита Brave",
        )

    def _search_response(self, query: str, count: int) -> httpx.Response:
        try:
            return self.request("GET", "/web/search", params={"q": query, "count": count, "extra_snippets": "true"})
        except ProviderError as exc:
            # Исчерпан месячный лимит: 429 с кодом QUOTA_LIMITED в теле (просто частота — RATE_LIMITED) или 402.
            if exc.status == 402 or "QUOTA_LIMITED" in exc.message:
                raise QuotaExceeded(self.name, f"HTTP {exc.status} QUOTA_LIMITED", status=exc.status) from exc
            raise

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        response = self._search_response(query, min(limit, MAX_COUNT))
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                self.name, "non-JSON response for GET /web/search", status=response.status_code
            ) from exc
        self.last_cost = CallCost(billable_requests=1)  # только бесплатный лимит; цену Brave не сообщает
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
