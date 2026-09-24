from __future__ import annotations

import requests
from tavily import TavilyClient
from tavily.errors import ForbiddenError, InvalidAPIKeyError, MissingAPIKeyError

from ..core.errors import AuthRequired, ProviderError
from ..core.models import SearchHit, extract_domain
from .base import SearchProvider


class TavilyProvider(SearchProvider):
    """Tavily через официальный SDK `tavily-python`; сниппет — выжимка `content`."""

    name = "tavily"
    summary = "Tavily — поиск с выжимкой контента под LLM"
    modes = ("basic", "advanced", "fast", "ultra-fast")

    def __init__(self, client: TavilyClient | None = None) -> None:
        self._client = client or TavilyClient(api_key=self.require_api_key())

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        try:
            response = self._client.search(query, max_results=limit, search_depth=mode)  # ty: ignore[invalid-argument-type]
        except (InvalidAPIKeyError, ForbiddenError, MissingAPIKeyError) as exc:
            raise AuthRequired(self.name) from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            raise ProviderError(self.name, str(exc)[:300], status=status) from exc
        except (requests.RequestException, Exception) as exc:
            # UsageLimitExceededError, BadRequestError, TimeoutError SDK и сетевые сбои.
            raise ProviderError(self.name, f"{type(exc).__name__}: {exc}"[:300]) from exc
        return [
            SearchHit(
                provider=self.name,
                query=query,
                position=position,
                url=item["url"],
                domain=extract_domain(item["url"]),
                title=item.get("title") or "",
                snippet=item.get("content") or "",
                published=item.get("published_date"),
                score=item.get("score"),
            )
            for position, item in enumerate(response.get("results", []), start=1)
        ]
