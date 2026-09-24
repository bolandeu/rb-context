from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import requests
from tavily.errors import InvalidAPIKeyError, UsageLimitExceededError

from rb_context.core import services
from rb_context.core.errors import AuthRequired, InvalidArguments, ProviderError
from rb_context.core.models import SearchHit
from rb_context.providers import BraveProvider, ExaProvider, SearchProvider, TavilyProvider

from .test_cli import init, invoke, invoke_json

# --- exa ---------------------------------------------------------------------


class _FakeExa:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result, self.error, self.kwargs = result, error, {}

    def search(self, query, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def test_exa_maps_highlights_to_snippet_and_passes_mode() -> None:
    result = SimpleNamespace(
        results=[
            SimpleNamespace(
                url="https://www.example.com/a",
                title="A",
                highlights=["one", "two"],
                published_date="2026-01-01",
                score=0.9,
            ),
            SimpleNamespace(url="https://b.org/", title=None, highlights=None, published_date=None, score=None),
        ]
    )
    client = _FakeExa(result)
    hits = ExaProvider(client).search("q", limit=2, mode="deep")  # ty: ignore[invalid-argument-type]
    assert client.kwargs == {"num_results": 2, "type": "deep", "contents": {"highlights": True}}
    assert hits[0].domain == "example.com"
    assert hits[0].snippet == "one … two"
    assert hits[1].position == 2
    assert hits[1].title == ""
    assert hits[1].snippet == ""


@pytest.mark.parametrize(
    ("error", "expected", "status"),
    [
        (ValueError("Request failed with status code 401: bad key"), AuthRequired, None),
        (ValueError("Request failed with status code 500: boom"), ProviderError, 500),
        (ValueError("something odd"), ProviderError, None),
        (requests.ConnectionError("down"), ProviderError, None),
    ],
)
def test_exa_errors_become_cli_errors(error: Exception, expected: type[Exception], status: int | None) -> None:
    with pytest.raises(expected) as exc_info:
        ExaProvider(_FakeExa(error=error)).search("q", limit=1)  # ty: ignore[invalid-argument-type]
    if expected is ProviderError:
        assert getattr(exc_info.value, "status", None) == status


# --- tavily ------------------------------------------------------------------


def test_tavily_maps_content_to_snippet_and_passes_mode() -> None:
    client = _FakeExa(
        {"results": [{"url": "https://t.dev/x", "title": "T", "content": "ctx", "score": 0.5, "published_date": None}]}
    )
    hits = TavilyProvider(client).search("q", limit=3, mode="advanced")  # ty: ignore[invalid-argument-type]
    assert client.kwargs == {"max_results": 3, "search_depth": "advanced"}
    assert hits == [
        SearchHit(
            provider="tavily",
            query="q",
            position=1,
            url="https://t.dev/x",
            domain="t.dev",
            title="T",
            snippet="ctx",
            score=0.5,
        )
    ]


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError("server error", response=response)


@pytest.mark.parametrize(
    ("error", "expected", "status"),
    [
        (InvalidAPIKeyError("bad"), AuthRequired, None),
        (UsageLimitExceededError("limit"), ProviderError, None),
        (_http_error(502), ProviderError, 502),
    ],
)
def test_tavily_errors_become_cli_errors(error: Exception, expected: type[Exception], status: int | None) -> None:
    with pytest.raises(expected) as exc_info:
        TavilyProvider(_FakeExa(error=error)).search("q", limit=1)  # ty: ignore[invalid-argument-type]
    if expected is ProviderError:
        assert getattr(exc_info.value, "status", None) == status


# --- brave -------------------------------------------------------------------


def _brave(handler) -> BraveProvider:
    provider = BraveProvider(api_key="k")
    provider.transport = httpx.MockTransport(handler)
    provider.retries = 0
    return provider


def test_brave_strips_html_and_joins_extra_snippets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "k"
        assert request.url.params["count"] == "20"  # capped
        body = {
            "web": {
                "results": [
                    {
                        "url": "https://brave.com/x",
                        "title": "<strong>B</strong>",
                        "description": "a &amp; <strong>b</strong>",
                        "extra_snippets": ["more"],
                        "page_age": "2026-02-02",
                    }
                ]
            }
        }
        return httpx.Response(200, json=body)

    [hit] = _brave(handler).search("q", limit=50)
    assert (hit.title, hit.snippet, hit.published) == ("B", "a & b … more", "2026-02-02")


def test_brave_no_web_block_is_empty_not_error() -> None:
    assert _brave(lambda request: httpx.Response(200, json={})).search("q", limit=5) == []


def test_brave_401_is_auth_required() -> None:
    with pytest.raises(AuthRequired):
        _brave(lambda request: httpx.Response(401)).search("q", limit=5)


# --- credentials -------------------------------------------------------------


@pytest.mark.parametrize("cls", [ExaProvider, TavilyProvider, BraveProvider])
def test_provider_without_key_is_auth_required(cls: type, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rb_context.credentials.manager.get_secret", lambda provider, field="api_key": None)
    with pytest.raises(AuthRequired):
        cls()


def test_provider_reads_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rb_context.credentials.manager.keyring.get_password", lambda service, user: None)
    monkeypatch.setenv("CONTEXT_BRAVE_API_KEY", "from-env")
    assert BraveProvider().auth_headers()["X-Subscription-Token"] == "from-env"


# --- services.search ---------------------------------------------------------


class _Fake(SearchProvider):
    name = "fake"
    modes = ("m1",)

    def __init__(self, name: str, error: Exception | None = None) -> None:
        self._name, self._error = name, error
        self.modes_seen: list[str | None] = []

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        self.modes_seen.append(mode)
        if self._error:
            raise self._error
        return [SearchHit(provider=self._name, query=query, position=1, url="https://x.io", domain="x.io", title="x")]


def _factory(errors: Mapping[str, Exception]):
    return lambda name: _Fake(name, errors.get(name))


def test_search_queries_every_provider_for_every_query() -> None:
    hits, runs = services.search(["a", "b"], providers=["exa", "brave"], limit=5, factory=_factory({}))
    assert {(h.query, h.provider) for h in hits} == {("a", "exa"), ("a", "brave"), ("b", "exa"), ("b", "brave")}
    assert all(r.ok and r.count == 1 for r in runs)


def test_search_one_failed_provider_does_not_fail_the_rest() -> None:
    hits, runs = services.search(
        ["a"], providers=["exa", "brave"], limit=5, factory=_factory({"brave": AuthRequired("brave")})
    )
    assert [h.provider for h in hits] == ["exa"]
    failed = next(r for r in runs if not r.ok)
    assert failed.provider == "brave"
    assert failed.error is not None
    assert failed.error["code"] == "AUTH_REQUIRED"


def test_search_all_failed_with_one_error_reraises_it() -> None:
    with pytest.raises(AuthRequired):
        services.search(["a"], providers=["exa"], limit=5, factory=_factory({"exa": AuthRequired("exa")}))


def test_search_all_failed_with_different_errors_is_provider_error() -> None:
    errors = {"exa": AuthRequired("exa"), "brave": ProviderError("brave", "down")}
    with pytest.raises(ProviderError) as exc_info:
        services.search(["a"], providers=["exa", "brave"], limit=5, factory=_factory(errors))
    assert "exa" in exc_info.value.message
    assert "down" in exc_info.value.message


def test_search_passes_mode_only_to_its_provider() -> None:
    made: dict[str, _Fake] = {}

    def factory(name: str) -> _Fake:
        made[name] = _Fake(name)
        return made[name]

    services.search(["a"], providers=["exa", "brave"], limit=5, modes={"exa": "deep"}, factory=factory)
    assert made["exa"].modes_seen == ["deep"]
    assert made["brave"].modes_seen == [None]


def test_search_rejects_unknown_mode() -> None:
    with pytest.raises(InvalidArguments):
        services.search(["a"], providers=["exa"], limit=5, modes={"exa": "turbo"}, factory=_factory({}))


def test_resolve_providers_explicit_dedupes_and_validates(tmp_path: Path) -> None:
    assert services.resolve_providers("exa, brave,exa", tmp_path) == ["exa", "brave"]
    with pytest.raises(InvalidArguments):
        services.resolve_providers("exa,google", tmp_path)


def test_resolve_providers_uses_project_config_then_default(tmp_path: Path) -> None:
    assert services.resolve_providers(None, tmp_path) == ["exa", "tavily", "brave"]
    init(tmp_path)
    invoke("--project", str(tmp_path), "config", "set", "providers", "tavily")
    assert services.resolve_providers(None, tmp_path) == ["tavily"]


# --- context search ----------------------------------------------------------


@pytest.fixture
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> dict[str, Exception]:
    """Подменить реальные провайдеры: ключ словаря → этот провайдер падает с ошибкой."""
    errors: dict[str, Exception] = {}
    real = services.provider_class

    def fake_class(name: str):
        cls = real(name)
        return type(
            cls.__name__,
            (_Fake,),
            {"modes": cls.modes, "__init__": lambda self: _Fake.__init__(self, name, errors.get(name))},
        )

    monkeypatch.setattr(services, "provider_class", fake_class)
    return errors


def test_search_command_json_contract(tmp_path: Path, fake_providers: dict) -> None:
    fake_providers["tavily"] = ProviderError("tavily", "down")
    code, payload = invoke_json("--project", str(tmp_path), "search", "q", "-p", "exa,tavily", "--exa-mode", "fast")
    assert code == 0
    assert payload["count"] == 1
    assert payload["results"][0]["provider"] == "exa"
    assert {s["provider"]: s["ok"] for s in payload["sources"]} == {"exa": True, "tavily": False}


def test_search_command_human_output_is_markdown(tmp_path: Path, fake_providers: dict) -> None:
    fake_providers["brave"] = ProviderError("brave", "down")
    result = invoke("--project", str(tmp_path), "search", "q", "-p", "exa,brave")
    assert result.exit_code == 0
    assert "## x\nhttps://x.io · exa #1" in result.stdout
    assert "down" in result.stderr


def test_search_command_all_failed_exits_with_error(tmp_path: Path, fake_providers: dict) -> None:
    fake_providers["exa"] = AuthRequired("exa")
    code, payload = invoke_json("--project", str(tmp_path), "search", "q", "-p", "exa")
    assert code == 3
    assert payload["error"]["action"] == "Run 'context auth login --provider exa'."


def test_search_command_bad_mode_is_invalid_arguments(tmp_path: Path, fake_providers: dict) -> None:
    code, payload = invoke_json("--project", str(tmp_path), "search", "q", "-p", "tavily", "--tavily-mode", "deep")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"
