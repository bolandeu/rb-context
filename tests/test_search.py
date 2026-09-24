from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import requests
from tavily.errors import ForbiddenError, InvalidAPIKeyError, UsageLimitExceededError

from rb_context.core import services
from rb_context.core.errors import AuthRequired, InvalidArguments, ProviderError, QuotaExceeded
from rb_context.core.models import SearchHit
from rb_context.providers import BraveProvider, ExaProvider, SearchProvider, SerpProvider, TavilyProvider
from rb_context.providers import serp as serp_module

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
        (ValueError('Request failed with status code 402: {"tag":"NO_MORE_CREDITS"}'), QuotaExceeded, 402),
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


def test_resolve_providers_all_means_every_provider(tmp_path: Path) -> None:
    assert services.resolve_providers("all", tmp_path) == ["exa", "tavily", "brave", "serp"]


def test_resolve_providers_uses_project_config_then_default(tmp_path: Path) -> None:
    assert services.resolve_providers(None, tmp_path) == ["exa"]
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


# --- исчерпан баланс / лимит тарифа -----------------------------------------


def test_exa_402_names_the_quota_tag() -> None:
    error = ValueError('Request failed with status code 402: {"tag":"TEAM_BUDGET_EXCEEDED"}')
    with pytest.raises(QuotaExceeded) as exc_info:
        ExaProvider(_FakeExa(error=error)).search("q", limit=1)  # ty: ignore[invalid-argument-type]
    assert exc_info.value.code == "QUOTA_EXCEEDED"
    assert "TEAM_BUDGET_EXCEEDED" in exc_info.value.message
    assert "повтор не поможет" in (exc_info.value.action or "")


@pytest.mark.parametrize(("status", "expected"), [(432, QuotaExceeded), (433, QuotaExceeded), (403, AuthRequired)])
def test_tavily_forbidden_is_quota_only_for_432_433(status: int, expected: type[Exception]) -> None:
    provider = TavilyProvider(_FakeExa(error=ForbiddenError("limit")))  # ty: ignore[invalid-argument-type]
    response = requests.Response()
    response.status_code = status
    provider._remember_status(response)  # так его вызывает хук requests-сессии SDK
    with pytest.raises(expected):
        provider.search("q", limit=1)


def test_tavily_real_client_gets_status_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rb_context.credentials.manager.get_secret", lambda provider, field="api_key": "k")
    provider = TavilyProvider()
    session = provider._client.session
    assert provider._remember_status in session.hooks["response"]
    assert session.headers["Authorization"] == "Bearer k"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, {"error": {"code": "QUOTA_LIMITED"}}, QuotaExceeded),
        (402, {}, QuotaExceeded),
        (429, {"error": {"code": "RATE_LIMITED"}}, ProviderError),
    ],
)
def test_brave_quota_vs_rate_limit(status: int, body: dict, expected: type[Exception]) -> None:
    with pytest.raises(expected) as exc_info:
        _brave(lambda request: httpx.Response(status, json=body)).search("q", limit=1)
    assert (getattr(exc_info.value, "code", None) == "QUOTA_EXCEEDED") is (expected is QuotaExceeded)


def test_all_failed_envelope_lists_each_provider_error(tmp_path: Path, fake_providers: dict) -> None:
    fake_providers["exa"] = QuotaExceeded("exa", "HTTP 402 NO_MORE_CREDITS", status=402)
    fake_providers["tavily"] = QuotaExceeded("tavily", "HTTP 432", status=432)
    code, payload = invoke_json("--project", str(tmp_path), "search", "q", "-p", "exa,tavily")
    assert code == 5
    assert [e["code"] for e in payload["error"]["errors"]] == ["QUOTA_EXCEEDED", "QUOTA_EXCEEDED"]
    assert {e["provider"] for e in payload["error"]["errors"]} == {"exa", "tavily"}


def test_partial_quota_is_visible_in_sources(tmp_path: Path, fake_providers: dict) -> None:
    fake_providers["exa"] = QuotaExceeded("exa", "HTTP 402", status=402)
    code, payload = invoke_json("--project", str(tmp_path), "search", "q", "-p", "exa,brave")
    assert code == 0
    [failed] = [src for src in payload["sources"] if not src["ok"]]
    assert failed["error"]["code"] == "QUOTA_EXCEEDED"


# --- serp (через установленный CLI) -----------------------------------------


@pytest.fixture
def fake_serp(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Подменить `serp ... --json`: `state["payload"]` — что он напечатает, `state["argv"]` — с чем вызван."""
    state: dict = {"payload": {"ok": True, "results": []}, "stdout": None, "argv": None}
    monkeypatch.setattr(serp_module.shutil, "which", lambda name: "/bin/serp")

    def fake_run(argv, **kwargs):
        state["argv"] = argv
        stdout = state["stdout"] if state["stdout"] is not None else json.dumps(state["payload"])
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="boom")

    monkeypatch.setattr(serp_module.subprocess, "run", fake_run)
    return state


def _row(engine: str, position: int) -> dict:
    return {
        "serp_position": position,
        "searchengine": engine,
        "url": f"https://{engine}.ru/{position}",
        "domain": f"{engine}.ru",
        "title": "T",
        "snippet": "S",
        "pubdate": "",
    }


def test_serp_rounds_top_to_pages_and_cuts_per_engine(fake_serp: dict) -> None:
    fake_serp["payload"] = {"ok": True, "results": [_row(e, p) for e in ("yandex", "google") for p in (1, 2, 3)]}
    hits = SerpProvider().search("q", limit=2, mode="both")
    assert fake_serp["argv"] == ["/bin/serp", "snippets", "q", "--engine", "both", "--top", "10", "--json"]
    assert [(h.engine, h.position) for h in hits] == [("yandex", 1), ("yandex", 2), ("google", 1), ("google", 2)]
    assert hits[0].provider == "serp"
    assert hits[0].published is None


def test_serp_default_engine_is_yandex(fake_serp: dict) -> None:
    SerpProvider().search("q", limit=15)
    assert fake_serp["argv"][3:7] == ["--engine", "yandex", "--top", "20"]


def test_serp_auth_error_keeps_serp_action(fake_serp: dict) -> None:
    fake_serp["payload"] = {
        "ok": False,
        "error": {"code": "AUTH_REQUIRED", "message": "m", "action": "Run 'serp auth login --provider xmlriver'."},
    }
    with pytest.raises(AuthRequired) as exc_info:
        SerpProvider().search("q", limit=1)
    assert exc_info.value.action == "Run 'serp auth login --provider xmlriver'."


def test_serp_other_error_is_provider_error(fake_serp: dict) -> None:
    fake_serp["payload"] = {"ok": False, "error": {"code": "PROVIDER_ERROR", "message": "xmlriver down"}}
    with pytest.raises(ProviderError, match="xmlriver down"):
        SerpProvider().search("q", limit=1)


def test_serp_non_json_output_is_provider_error(fake_serp: dict) -> None:
    fake_serp["stdout"] = "Traceback"
    with pytest.raises(ProviderError, match="boom"):
        SerpProvider().search("q", limit=1)


def test_serp_timeout_is_provider_error(fake_serp: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(serp_module.subprocess, "run", slow)
    with pytest.raises(ProviderError, match="нет ответа"):
        SerpProvider().search("q", limit=1)


def test_serp_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serp_module.shutil, "which", lambda name: None)
    with pytest.raises(ProviderError) as exc_info:
        SerpProvider().search("q", limit=1)
    assert "uv tool install" in (exc_info.value.action or "")
    ok, detail = SerpProvider.check()
    assert not ok
    assert "uv tool install" in (detail or "")


@pytest.mark.parametrize(("authenticated", "ok"), [(True, True), (False, False)])
def test_serp_check_asks_serp_itself(fake_serp: dict, authenticated: bool, ok: bool) -> None:
    fake_serp["payload"] = {"ok": True, "authenticated": authenticated}
    assert SerpProvider.check()[0] is ok
    assert fake_serp["argv"] == ["/bin/serp", "auth", "status", "--json"]


def test_auth_login_for_serp_points_to_serp(fake_serp: dict) -> None:
    code, payload = invoke_json("auth", "login", "-p", "serp", "--non-interactive")
    assert code == 2
    assert "serp auth login" in payload["error"]["message"]


def test_human_output_shows_serp_engine(tmp_path: Path, fake_serp: dict) -> None:
    fake_serp["payload"] = {"ok": True, "results": [_row("google", 1)]}
    result = invoke("--project", str(tmp_path), "search", "q", "-p", "serp", "--serp-engine", "google")
    assert result.exit_code == 0
    assert "https://google.ru/1 · serp/google #1" in result.stdout
