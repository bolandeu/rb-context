from __future__ import annotations

import re

import requests
from exa_py import Exa

from ..core.errors import AuthRequired, ProviderError, QuotaExceeded
from ..core.models import SearchHit, extract_domain
from .base import SearchProvider

# exa-py сообщает о HTTP-ошибке только текстом: ValueError("Request failed with status code 401: ...").
_STATUS_RE = re.compile(r"status code (\d{3})")
# 402 — кончились кредиты или бюджет ключа/команды (NO_MORE_CREDITS, API_KEY_BUDGET_EXCEEDED,
# TEAM_BUDGET_EXCEEDED), https://exa.ai/docs/reference/error-codes. 429 — только частота запросов.
_QUOTA_TAG_RE = re.compile(r"NO_MORE_CREDITS|[A-Z_]*BUDGET_EXCEEDED")


class ExaProvider(SearchProvider):
    """Exa через официальный SDK `exa-py`; сниппет — хайлайты страницы."""

    name = "exa"
    summary = "Exa — нейропоиск, хайлайты страниц"
    modes = ("auto", "fast", "instant", "deep-lite", "deep", "deep-reasoning")

    def __init__(self, client: Exa | None = None) -> None:
        self._client = client or Exa(api_key=self.require_api_key())

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        try:
            response = self._client.search(query, num_results=limit, type=mode, contents={"highlights": True})
        except ValueError as exc:
            match = _STATUS_RE.search(str(exc))
            status = int(match.group(1)) if match else None
            if status in (401, 403):
                raise AuthRequired(self.name) from exc
            if status == 402:
                tag = _QUOTA_TAG_RE.search(str(exc))
                raise QuotaExceeded(self.name, f"HTTP 402 {tag.group(0) if tag else ''}".strip(), status=402) from exc
            raise ProviderError(self.name, str(exc)[:300], status=status) from exc
        except requests.RequestException as exc:
            raise ProviderError(self.name, f"{type(exc).__name__}: {exc}"[:300]) from exc
        return [
            SearchHit(
                provider=self.name,
                query=query,
                position=position,
                url=result.url,
                domain=extract_domain(result.url),
                title=result.title or "",
                snippet=" … ".join(result.highlights or []),
                published=result.published_date,
                score=result.score,
            )
            for position, result in enumerate(response.results, start=1)
        ]
