"""Бесплатные источники: hackernews, github, wikipedia (HTTP подменён MockTransport)."""

from __future__ import annotations

import json
from typing import TypeVar

import httpx
import pytest

from rb_context.core.errors import AuthRequired, QuotaExceeded
from rb_context.providers import GitHubProvider, HackerNewsProvider, HttpProvider, Quota, WikipediaProvider

P = TypeVar("P", bound=HttpProvider)


def _mock(provider: P, handler) -> P:
    provider.transport = httpx.MockTransport(handler)
    provider.retries = 0
    return provider


# --- hackernews --------------------------------------------------------------


def test_hackernews_maps_story_and_links_discussion() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "objectID": "1",
                        "title": "SQLite WAL",
                        "url": "https://www.sqlite.org/wal.html",
                        "points": 120,
                        "num_comments": 40,
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    {"objectID": "2", "title": "Ask HN: x?", "url": None, "story_text": "<p>Why &amp; how</p>"},
                ]
            },
        )

    first, ask = _mock(HackerNewsProvider(), handler).search("wal", limit=500)
    assert seen == {"query": "wal", "tags": "story", "hitsPerPage": "100"}
    assert (first.url, first.domain, first.score) == ("https://www.sqlite.org/wal.html", "sqlite.org", 120)
    assert first.snippet == "120 points, 40 comments · Обсуждение: https://news.ycombinator.com/item?id=1"
    assert ask.url == "https://news.ycombinator.com/item?id=2"
    assert ask.snippet == "0 points, 0 comments · Why & how"
    assert ask.position == 2


def test_hackernews_needs_no_key() -> None:
    assert HackerNewsProvider.check() == (True, None)
    assert HackerNewsProvider.credential_fields == ()
    assert HackerNewsProvider.last_cost.billable_requests == 0


# --- wikipedia ---------------------------------------------------------------


def test_wikipedia_orders_by_index_and_uses_language() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        pages = [
            {"index": 2, "title": "B", "fullurl": "https://en.wikipedia.org/wiki/B", "extract": "b "},
            {"index": 1, "title": "A", "fullurl": "https://en.wikipedia.org/wiki/A", "extract": "a"},
        ]
        return httpx.Response(200, json={"query": {"pages": pages}})

    hits = _mock(WikipediaProvider(), handler).search("x", limit=50, mode="en")
    assert seen[0].host == "en.wikipedia.org"
    assert seen[0].params["gsrlimit"] == "20"
    assert [(h.position, h.title, h.snippet) for h in hits] == [(1, "A", "a"), (2, "B", "b")]


def test_wikipedia_default_is_russian_and_no_results_is_empty() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"batchcomplete": True})

    assert _mock(WikipediaProvider(), handler).search("x", limit=5) == []
    assert seen[0].host == "ru.wikipedia.org"


# --- github ------------------------------------------------------------------


def _github(handler, token: str | None = "t") -> GitHubProvider:  # noqa: S107 — фальшивый токен
    provider = GitHubProvider(api_key=token)
    if token is None:
        provider._token = lambda: None  # ty: ignore[invalid-assignment]
    return _mock(provider, handler)


def test_github_repositories_with_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = {
            "html_url": "https://github.com/a/b",
            "full_name": "a/b",
            "description": "Tool",
            "stargazers_count": 5,
            "language": "Python",
            "topics": ["cli"],
            "pushed_at": "2026-09-01T00:00:00Z",
            "score": 1.0,
        }
        return httpx.Response(200, json={"items": [item]})

    provider = _github(handler)
    [hit] = provider.search("tool", limit=3)
    assert seen[0].url.path == "/search/repositories"
    assert seen[0].headers["Authorization"] == "Bearer t"
    assert (hit.title, hit.snippet, hit.domain) == ("a/b", "Tool · ★ 5, Python, cli", "github.com")
    assert provider.last_cost.billable_requests == 1


def test_github_issues_title_has_repo() -> None:
    item = {
        "html_url": "https://github.com/a/b/issues/1",
        "repository_url": "https://api.github.com/repos/a/b",
        "title": "Bug",
        "body": "text",
    }
    [hit] = _github(lambda request: httpx.Response(200, json={"items": [item]})).search("q", limit=1, mode="issues")
    assert (hit.title, hit.snippet) == ("a/b: Bug", "text")


def test_github_code_joins_text_matches() -> None:
    seen: list[httpx.Request] = []
    item = {
        "html_url": "https://github.com/a/b/blob/main/x.py",
        "path": "x.py",
        "repository": {"full_name": "a/b"},
        "text_matches": [{"fragment": "one"}, {"fragment": "two"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": [item]})

    [hit] = _github(handler).search("q", limit=1, mode="code")
    assert seen[0].headers["Accept"] == "application/vnd.github.text-match+json"
    assert (hit.title, hit.snippet) == ("a/b: x.py", "one\n…\ntwo")


def test_github_code_without_token_is_auth_required() -> None:
    with pytest.raises(AuthRequired):
        _github(lambda request: httpx.Response(200, json={}), token=None).search("q", limit=1, mode="code")


def test_github_anonymous_search_sends_no_authorization() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": []})

    assert _github(handler, token=None).search("q", limit=1) == []
    assert "Authorization" not in seen[0].headers


def _rate_limited(search_status: int, remaining: int):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rate_limit":
            return httpx.Response(200, json={"resources": {"search": {"remaining": remaining, "limit": 30}}})
        return httpx.Response(search_status, json={"message": "API rate limit exceeded"})

    return handler


@pytest.mark.parametrize("status", [403, 429])
def test_github_rate_limit_is_quota_exhausted(status: int) -> None:
    with pytest.raises(QuotaExceeded) as exc_info:
        _github(_rate_limited(status, 0)).search("q", limit=1)
    assert exc_info.value.code == "QUOTA_EXHAUSTED"


def test_github_403_with_quota_left_is_auth_required() -> None:
    with pytest.raises(AuthRequired):
        _github(_rate_limited(403, 10)).search("q", limit=1)


def test_github_health_check_reports_search_quota() -> None:
    health = _github(_rate_limited(200, 7)).health_check()
    assert health.status == "ok"
    assert health.quota == Quota(remaining=7, limit=30, unit="requests/min")


def test_github_reads_github_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXT_GITHUB_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert GitHubProvider().auth_headers()["Authorization"] == "Bearer from-env"


def test_auth_login_rejects_keyless_provider() -> None:
    from typer.testing import CliRunner

    from rb_context.cli import app

    result = CliRunner().invoke(app, ["auth", "login", "-p", "wikipedia", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["message"] == "Провайдеру wikipedia ключ не нужен."
