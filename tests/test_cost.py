"""Учёт платных вызовов в `search --json` (T175): cost, cost_source, billable_requests, would_cost."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import requests
from tavily.errors import ForbiddenError

from rb_context.core import services
from rb_context.core.errors import ProviderError, QuotaExceeded
from rb_context.core.models import CallCost, ProviderRun, SearchHit
from rb_context.providers import BraveProvider, ExaProvider, Quota, SearchProvider, SerpProvider, TavilyProvider
from rb_context.providers import serp as serp_module

from .test_cli import init, invoke, invoke_json
from .test_search import _brave, _FakeExa

FREE = {"cost": 0.0, "cost_currency": "RUB", "cost_source": "free_tier"}


def _cost_fields(cost: CallCost) -> dict:
    return cost.model_dump()


# --- бесплатные лимиты: exa, tavily, brave ------------------------------------


def test_exa_call_is_free_tier_and_keeps_cost_dollars_as_would_cost() -> None:
    result = SimpleNamespace(results=[], cost_dollars=SimpleNamespace(total=0.005))
    provider = ExaProvider(_FakeExa(result))  # ty: ignore[invalid-argument-type]
    provider.search("q", limit=1)
    assert _cost_fields(provider.last_cost) == {
        **FREE,
        "billable_requests": 1,
        "would_cost": 0.005,
        "would_cost_unit": "USD",
    }


def test_exa_without_cost_dollars_has_no_would_cost() -> None:
    provider = ExaProvider(_FakeExa(SimpleNamespace(results=[])))  # ty: ignore[invalid-argument-type]
    provider.search("q", limit=1)
    assert (provider.last_cost.would_cost, provider.last_cost.would_cost_unit) == (None, None)
    assert provider.last_cost.billable_requests == 1


def test_tavily_asks_for_usage_and_keeps_credits_as_would_cost() -> None:
    client = _FakeExa({"results": [], "usage": {"credits": 2}})
    provider = TavilyProvider(client)  # ty: ignore[invalid-argument-type]
    provider.search("q", limit=3)
    assert client.kwargs["include_usage"] is True
    assert _cost_fields(provider.last_cost) == {
        **FREE,
        "billable_requests": 1,
        "would_cost": 2,
        "would_cost_unit": "credits",
    }


def test_brave_call_is_free_tier_without_would_cost() -> None:
    provider = _brave(lambda request: httpx.Response(200, json={}))
    provider.search("q", limit=1)
    assert _cost_fields(provider.last_cost) == {
        **FREE,
        "billable_requests": 1,
        "would_cost": None,
        "would_cost_unit": None,
    }


# --- лимит исчерпан → QUOTA_EXHAUSTED, без перехода на платное ------------------


def _assert_exhausted(exc: QuotaExceeded, provider: str) -> None:
    assert exc.code == "QUOTA_EXHAUSTED"
    assert "лимит исчерпан" in exc.message
    assert exc.exit_code == 5
    assert exc.to_dict()["provider"] == provider


def test_exa_out_of_credits_is_quota_exhausted() -> None:
    error = ValueError('Request failed with status code 402: {"tag":"NO_MORE_CREDITS"}')
    with pytest.raises(QuotaExceeded) as exc_info:
        ExaProvider(_FakeExa(error=error)).search("q", limit=1)  # ty: ignore[invalid-argument-type]
    _assert_exhausted(exc_info.value, "exa")
    assert "NO_MORE_CREDITS" in exc_info.value.message


@pytest.mark.parametrize("status", [432, 433])
def test_tavily_plan_limit_is_quota_exhausted(status: int) -> None:
    provider = TavilyProvider(_FakeExa(error=ForbiddenError("limit")))  # ty: ignore[invalid-argument-type]
    response = requests.Response()
    response.status_code = status
    provider._remember_status(response)
    with pytest.raises(QuotaExceeded) as exc_info:
        provider.search("q", limit=1)
    _assert_exhausted(exc_info.value, "tavily")


@pytest.mark.parametrize(("status", "body"), [(429, {"error": {"code": "QUOTA_LIMITED"}}), (402, {})])
def test_brave_quota_is_quota_exhausted(status: int, body: dict) -> None:
    with pytest.raises(QuotaExceeded) as exc_info:
        _brave(lambda request: httpx.Response(status, json=body)).search("q", limit=1)
    _assert_exhausted(exc_info.value, "brave")


def test_quota_exhausted_action_does_not_offer_a_paid_plan() -> None:
    action = QuotaExceeded("exa", "HTTP 402").action or ""
    assert "бесплатн" in action
    assert "Пополнить" not in action


def test_failed_free_call_is_not_counted() -> None:
    provider = ExaProvider(_FakeExa(error=ValueError("Request failed with status code 402: NO_MORE_CREDITS")))  # ty: ignore[invalid-argument-type]
    with pytest.raises(QuotaExceeded):
        provider.search("q", limit=1)
    assert _cost_fields(provider.last_cost) == {
        **FREE,
        "billable_requests": 0,
        "would_cost": None,
        "would_cost_unit": None,
    }


# --- serp: стоимость из его конверта ------------------------------------------


@pytest.fixture
def fake_serp(monkeypatch: pytest.MonkeyPatch) -> dict:
    state: dict = {"payload": {"ok": True, "results": []}}
    monkeypatch.setattr(serp_module.deps, "require_cli", lambda name, version, **kwargs: "/bin/serp")

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(state["payload"]), stderr="")

    monkeypatch.setattr(serp_module.subprocess, "run", fake_run)
    return state


def _serp_source(cost: float | None, source: str | None, billable: int, *, cache: bool = False) -> dict:
    return {
        "query": "q",
        "engine": "yandex",
        "page": 1,
        "provider": "xmlriver",
        "from_cache": cache,
        "complete": True,
        "billable_requests": billable,
        "cost": cost,
        "cost_currency": "RUB",
        "cost_source": source,
    }


def test_serp_cost_comes_from_its_envelope(fake_serp: dict) -> None:
    fake_serp["payload"] = {
        "ok": True,
        "results": [],
        "sources": [_serp_source(0.5, "price_table", 1), _serp_source(1.0, "price_table", 2)],
        "billable_requests_total": 3,
        "cost_total": 1.5,
    }
    provider = SerpProvider()
    provider.search("q", limit=20)
    assert _cost_fields(provider.last_cost) == {
        "billable_requests": 3,
        "cost": 1.5,
        "cost_currency": "RUB",
        "cost_source": "price_table",
        "would_cost": None,
        "would_cost_unit": None,
    }


def test_serp_from_cache_is_free(fake_serp: dict) -> None:
    fake_serp["payload"] = {
        "ok": True,
        "results": [],
        "sources": [_serp_source(0.0, "cache", 0, cache=True)],
        "billable_requests_total": 0,
        "cost_total": 0.0,
    }
    provider = SerpProvider()
    provider.search("q", limit=10)
    assert (provider.last_cost.cost, provider.last_cost.cost_source, provider.last_cost.billable_requests) == (
        0.0,
        "cache",
        0,
    )


def test_serp_without_price_is_null_cost(fake_serp: dict) -> None:
    fake_serp["payload"] = {
        "ok": True,
        "results": [],
        "sources": [_serp_source(None, None, 1)],
        "billable_requests_total": 1,
        "cost_total": None,
    }
    provider = SerpProvider()
    provider.search("q", limit=10)
    assert (provider.last_cost.cost, provider.last_cost.cost_source, provider.last_cost.billable_requests) == (
        None,
        None,
        1,
    )


def test_serp_envelope_without_cost_is_unknown_cost(fake_serp: dict) -> None:
    """`serp snippets` 0.7.2 стоимость не отдаёт: cost null, оплаченные страницы — те, что не из кэша."""
    fake_serp["payload"] = {
        "ok": True,
        "results": [],
        "sources": [
            {"query": "q", "engine": "yandex", "page": 1, "provider": "xmlriver", "from_cache": False},
            {"query": "q", "engine": "yandex", "page": 2, "provider": "xmlriver", "from_cache": True},
        ],
    }
    provider = SerpProvider()
    provider.search("q", limit=20)
    assert (provider.last_cost.cost, provider.last_cost.cost_source, provider.last_cost.billable_requests) == (
        None,
        None,
        1,
    )


def test_serp_failure_cost_is_unknown(fake_serp: dict) -> None:
    fake_serp["payload"] = {"ok": False, "error": {"code": "PROVIDER_ERROR", "message": "down"}}
    provider = SerpProvider()
    with pytest.raises(ProviderError):
        provider.search("q", limit=10)
    assert (provider.last_cost.cost, provider.last_cost.cost_source) == (None, None)


def test_min_serp_is_0_7_2_in_code_and_registry() -> None:
    assert serp_module.MIN_SERP == "0.7.2"
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    [serp] = [dep for dep in pyproject["tool"]["rb"]["external"] if dep["name"] == "serp"]
    assert serp["min_version"] == "0.7.2"


# --- services: стоимость на каждый вызов и итог --------------------------------


class _Priced(SearchProvider):
    name = "priced"

    def __init__(self, name: str, cost: CallCost | None, error: Exception | None = None) -> None:
        self._name, self._cost, self._error = name, cost, error

    def health_check(self):  # pragma: no cover — не нужен в этих тестах
        raise NotImplementedError

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        if self._error:
            raise self._error
        if self._cost is not None:
            self.last_cost = self._cost
        return [SearchHit(provider=self._name, query=query, position=1, url="https://x.io", domain="x.io", title="x")]


def test_every_run_carries_its_cost() -> None:
    costs = {
        "exa": CallCost(billable_requests=1, would_cost=0.005, would_cost_unit="USD"),
        "serp": CallCost(billable_requests=2, cost=1.5, cost_source="price_table"),
    }
    _, runs = services.search(
        ["a"], providers=["exa", "serp"], limit=5, factory=lambda name: _Priced(name, costs[name])
    )
    by_name = {run.provider: run for run in runs}
    assert (by_name["exa"].cost, by_name["exa"].cost_source, by_name["exa"].would_cost) == (0.0, "free_tier", 0.005)
    assert (by_name["serp"].cost, by_name["serp"].billable_requests) == (1.5, 2)


def test_failed_run_costs_nothing_on_a_free_tier() -> None:
    _, runs = services.search(
        ["a"],
        providers=["exa", "brave"],
        limit=5,
        factory=lambda name: _Priced(name, None, ProviderError(name, "down") if name == "brave" else None),
    )
    failed = next(run for run in runs if not run.ok)
    assert (failed.billable_requests, failed.cost, failed.cost_source) == (0, 0.0, "free_tier")


def _run(cost: float | None, billable: int, currency: str = "RUB", source: str | None = "price_table") -> ProviderRun:
    return ProviderRun(
        provider="p",
        query="q",
        ok=True,
        billable_requests=billable,
        cost=cost,
        cost_currency=currency,
        cost_source=source,
    )


def test_totals_sum_cost_and_billable_requests() -> None:
    assert services.cost_totals([_run(0.0, 1, source="free_tier"), _run(1.5, 2), _run(0.25, 1)]) == (1.75, 4)


def test_total_cost_is_null_when_any_cost_is_unknown() -> None:
    assert services.cost_totals([_run(1.5, 2), _run(None, 1, source=None)]) == (None, 3)


def test_total_cost_is_null_for_a_foreign_currency() -> None:
    """Курсов context не знает: ненулевая сумма не в RUB — итог null, а не смесь валют."""
    assert services.cost_totals([_run(1.5, 2), _run(0.1, 1, currency="USD")]) == (None, 3)
    assert services.cost_totals([_run(1.5, 2), _run(0.0, 1, currency="USD")]) == (1.5, 3)


# --- context search --json ----------------------------------------------------


@pytest.fixture
def priced_providers(monkeypatch: pytest.MonkeyPatch) -> dict[str, CallCost]:
    costs: dict[str, CallCost] = {}
    real = services.provider_class

    def fake_class(name: str):
        cls = real(name)
        return type(
            cls.__name__,
            (_Priced,),
            {"modes": cls.modes, "__init__": lambda self: _Priced.__init__(self, name, costs.get(name))},
        )

    monkeypatch.setattr(services, "provider_class", fake_class)
    return costs


def test_search_json_has_cost_per_source_and_totals(tmp_path: Path, priced_providers: dict) -> None:
    priced_providers["exa"] = CallCost(billable_requests=1, would_cost=0.005, would_cost_unit="USD")
    priced_providers["serp"] = CallCost(billable_requests=2, cost=1.5, cost_source="price_table")
    code, payload = invoke_json("--project", str(tmp_path), "search", "q", "-p", "exa,serp")
    assert code == 0
    assert payload["cost_total"] == 1.5
    assert payload["billable_requests_total"] == 3
    exa = next(s for s in payload["sources"] if s["provider"] == "exa")
    assert {k: exa[k] for k in (*FREE, "billable_requests", "would_cost", "would_cost_unit")} == {
        **FREE,
        "billable_requests": 1,
        "would_cost": 0.005,
        "would_cost_unit": "USD",
    }


def test_search_warns_when_cost_is_unknown(tmp_path: Path, priced_providers: dict) -> None:
    priced_providers["serp"] = CallCost(billable_requests=1, cost=None, cost_source=None)
    result = invoke("--project", str(tmp_path), "search", "q", "-p", "serp", "--json")
    assert json.loads(result.stdout)["cost_total"] is None
    assert "serp" in result.stderr and "cost" in result.stderr


# --- brave: проверка ключа тратит лимит ----------------------------------------


def test_brave_health_check_reports_monthly_quota_from_headers() -> None:
    headers = {"X-RateLimit-Limit": "1, 2000", "X-RateLimit-Remaining": "0, 1500"}
    health = _brave(lambda request: httpx.Response(200, json={}, headers=headers)).health_check()
    assert health.status == "ok"
    assert health.quota == Quota(remaining=1500, limit=2000, unit="requests")
    assert "1 запрос" in (health.message or "")


def test_brave_health_check_is_marked_as_billable() -> None:
    assert BraveProvider.health_check_spends_quota is True
    assert ExaProvider.health_check_spends_quota is False
    assert TavilyProvider.health_check_spends_quota is False


def test_doctor_flags_brave_check_spending_the_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_BRAVE_API_KEY", "k")
    init(tmp_path)
    invoke("--project", str(tmp_path), "config", "set", "providers", "brave")
    code, payload = invoke_json("--project", str(tmp_path), "doctor")
    assert code == 0
    [check] = [c for c in payload["checks"] if c["name"] == "credential:brave"]
    assert check["ok"] is True
    assert "лимит" in (check["detail"] or "")
