from __future__ import annotations

from typing import ClassVar

from ..core.errors import AuthRequired, ProviderError, QuotaExceeded
from ..core.models import CallCost, SearchHit, extract_domain
from .base import Health, Quota, SearchProvider
from .http import HttpProvider

MAX_PER_PAGE = 100
SNIPPET_CHARS = 500
_TEXT_MATCH = "application/vnd.github.text-match+json"
_ENDPOINTS = {"repositories": "/search/repositories", "issues": "/search/issues", "code": "/search/code"}


class GitHubProvider(HttpProvider, SearchProvider):
    """GitHub REST search: репозитории, issues/PR и код (код — только с токеном).

    Токен необязателен: без него репозитории и issues ищутся с урезанным лимитом
    (10 запросов в минуту вместо 30). Читается из CONTEXT_GITHUB_API_KEY, связки
    ключей ОС или GITHUB_TOKEN.
    """

    name = "github"
    summary = "GitHub — репозитории, issues и код, токен необязателен"
    modes = ("repositories", "issues", "code")  # первый — по умолчанию
    base_url = "https://api.github.com"
    required = False
    legacy_env: ClassVar[dict[str, str]] = {"api_key": "GITHUB_TOKEN"}

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key  # None — токен читается при первом запросе

    @classmethod
    def check(cls) -> tuple[bool, str | None]:
        return True, None  # работает и без токена (кроме кода)

    def _token(self) -> str | None:
        return self._api_key or (self.credential() or {}).get("api_key")

    def auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def health_check(self) -> Health:
        """`GET /rate_limit` — не расходует лимит; в ответе остаток лимита поиска в минуту."""
        search = (self.probe("/rate_limit").json().get("resources") or {}).get("search") or {}
        remaining, limit = search.get("remaining"), search.get("limit")
        if remaining is None:
            return Health()
        exhausted = remaining == 0
        return Health(
            status="quota_exhausted" if exhausted else "ok",
            quota=Quota(remaining=remaining, limit=limit, unit="requests/min"),
            message="лимит поиска в минуту исчерпан" if exhausted else None,
        )

    def _search_exhausted(self) -> bool:
        """403 без токена или с токеном — это либо плохой токен, либо кончившийся лимит: смотрим остаток."""
        try:
            resources = self.client.get("/rate_limit", timeout=10.0).json().get("resources") or {}
        except Exception:
            return False
        return (resources.get("search") or {}).get("remaining") == 0

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        mode = mode or self.modes[0]
        if mode == "code" and not self._token():
            raise AuthRequired(self.name)  # поиск по коду GitHub отдаёт только с токеном
        headers = {"Accept": _TEXT_MATCH} if mode == "code" else {}
        try:
            response = self.request(
                "GET",
                _ENDPOINTS[mode],
                params={"q": query, "per_page": min(limit, MAX_PER_PAGE)},
                headers=headers,
            )
        except AuthRequired:
            if self._search_exhausted():
                raise QuotaExceeded(self.name, "HTTP 403 rate limit", status=403) from None
            raise
        except ProviderError as exc:
            if exc.status == 429:
                raise QuotaExceeded(self.name, "HTTP 429 rate limit", status=429) from exc
            raise
        self.last_cost = CallCost(billable_requests=1)  # только лимит API; платного тарифа нет
        items = response.json().get("items") or []
        return [self._hit(mode, query, position, item) for position, item in enumerate(items, start=1)]

    def _hit(self, mode: str, query: str, position: int, item: dict) -> SearchHit:
        url = item["html_url"]
        if mode == "repositories":
            facts = [f"★ {item.get('stargazers_count', 0)}", item.get("language"), *(item.get("topics") or [])]
            title = item["full_name"]
            snippet = " · ".join(
                str(fact) for fact in [item.get("description"), ", ".join(map(str, facts[:6]))] if fact
            )
            published = item.get("pushed_at")
        elif mode == "issues":
            repo = item["repository_url"].removeprefix(f"{self.base_url}/repos/")
            title = f"{repo}: {item['title']}"
            snippet = (item.get("body") or "")[:SNIPPET_CHARS].strip()
            published = item.get("created_at")
        else:
            title = f"{item['repository']['full_name']}: {item['path']}"
            snippet = "\n…\n".join(match["fragment"] for match in item.get("text_matches") or [])
            published = None
        return SearchHit(
            provider=self.name,
            query=query,
            position=position,
            url=url,
            domain=extract_domain(url),
            title=title,
            snippet=snippet,
            published=published,
            score=item.get("score"),
        )
