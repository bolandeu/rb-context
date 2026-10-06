from __future__ import annotations

import html
import re

from ..core.models import SearchHit, extract_domain
from .base import Health, SearchProvider
from .http import HttpProvider

_TAG_RE = re.compile(r"<[^>]+>")
_ITEM_URL = "https://news.ycombinator.com/item?id="
# Algolia отдаёт до 1000 на страницу; больше сотни context не просит.
MAX_HITS = 100
SNIPPET_CHARS = 500


class HackerNewsProvider(HttpProvider, SearchProvider):
    """Hacker News через открытое API поиска Algolia: истории (ссылки и Ask/Show HN), без ключа и лимитов."""

    name = "hackernews"
    summary = "Hacker News — обсуждения и ссылки про технологии, без ключа"
    base_url = "https://hn.algolia.com/api/v1"
    needs_api_key = False
    credential_fields = ()
    required = False

    @classmethod
    def check(cls) -> tuple[bool, str | None]:
        return True, None  # ключа нет — проверять нечего

    def health_check(self) -> Health:
        """Поиск с `hitsPerPage=1`: у Algolia API открытое, запрос ничего не тратит."""
        self.probe("/search", params={"query": "test", "hitsPerPage": 1})
        return Health()

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        data = self.get_json("/search", query=query, tags="story", hitsPerPage=min(limit, MAX_HITS))
        hits = []
        for position, item in enumerate(data.get("hits") or [], start=1):
            discussion = f"{_ITEM_URL}{item['objectID']}"
            url = item.get("url") or discussion  # у Ask HN своей ссылки нет — сама страница обсуждения
            text = html.unescape(_TAG_RE.sub(" ", item.get("story_text") or "")).strip()
            parts = [
                f"{item.get('points') or 0} points, {item.get('num_comments') or 0} comments",
                text[:SNIPPET_CHARS],
            ]
            if url != discussion:
                parts.append(f"Обсуждение: {discussion}")
            hits.append(
                SearchHit(
                    provider=self.name,
                    query=query,
                    position=position,
                    url=url,
                    domain=extract_domain(url),
                    title=item.get("title") or "",
                    snippet=" · ".join(part for part in parts if part),
                    published=item.get("created_at"),
                    score=item.get("points"),
                )
            )
        return hits
