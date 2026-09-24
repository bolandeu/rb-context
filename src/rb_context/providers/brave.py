from __future__ import annotations

import html
import re

from ..core.models import SearchHit, extract_domain
from .base import SearchProvider
from .http import HttpProvider

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

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or self.require_api_key()

    def auth_headers(self) -> dict[str, str]:
        return {"X-Subscription-Token": self._api_key, "Accept": "application/json"}

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        data = self.get_json("/web/search", q=query, count=min(limit, MAX_COUNT), extra_snippets="true")
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
