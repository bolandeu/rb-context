"""`--source 9router`: ключ и прокси из локальной базы 9router, без её HTTP-API."""

from __future__ import annotations

import sys
import types
from collections.abc import Callable

import pytest

from rb_context.core import services
from rb_context.core.errors import InvalidArguments
from rb_context.credentials import ninerouter


class FakeRouter(types.ModuleType):
    """A module with the three attributes `ninerouter.binding` reaches for, declared so the checker sees them."""

    SchemaDrift: type[Exception]
    bindings: Callable[..., list]
    pick: Callable[..., object]


@pytest.fixture
def fake_router(monkeypatch: pytest.MonkeyPatch) -> FakeRouter:
    """Stand-in for `rb_ninerouter`: two keys for exa, the first one already dead."""
    module = FakeRouter("rb_ninerouter")

    class SchemaDrift(RuntimeError):
        pass

    class Binding:
        def __init__(self, name: str, key: str, proxy: str | None = None) -> None:
            self.name, self._key, self.proxy = name, key, proxy

        def reveal(self) -> str:
            return self._key

    keys = [Binding("first", "k1"), Binding("second", "k2", "socks5://h:1")]
    module.SchemaDrift = SchemaDrift
    module.bindings = lambda service: keys
    module.pick = lambda service, rotation=None: keys[1]
    monkeypatch.setitem(sys.modules, "rb_ninerouter", module)
    return module


def test_binding_takes_the_key_and_the_proxy_of_the_picked_key(fake_router: types.ModuleType) -> None:
    assert ninerouter.binding("exa") == ("k2", "socks5://h:1")


def test_a_named_key_wins_over_the_scheme(fake_router: types.ModuleType) -> None:
    assert ninerouter.binding("exa", key="first") == ("k1", None)


def test_an_unknown_key_names_the_known_ones(fake_router: types.ModuleType) -> None:
    with pytest.raises(InvalidArguments, match="no key 'nope' for exa \\(known: first, second\\)"):
        ninerouter.binding("exa", key="nope")


def test_a_service_without_live_keys_is_an_arguments_error(fake_router: FakeRouter) -> None:
    def pick(service: str, rotation: str | None = None) -> None:
        raise LookupError(f"9router has no usable key for '{service}'")

    fake_router.pick = pick
    with pytest.raises(InvalidArguments, match="no usable key for 'exa'"):
        ninerouter.binding("exa")


def test_schema_drift_is_reported_as_our_error(fake_router: FakeRouter) -> None:
    def bindings(service: str) -> list:
        raise fake_router.SchemaDrift("schemaVersion '7'")

    fake_router.bindings = bindings
    with pytest.raises(InvalidArguments, match="not readable"):
        ninerouter.binding("exa", key="first")


def test_the_factory_attaches_the_binding_to_the_provider(fake_router: types.ModuleType) -> None:
    services.use_source("9router")
    try:
        provider = services._default_factory("exa")
    finally:
        services.use_source(None)
    assert (provider.api_key_override, provider.proxy) == ("k2", "socks5://h:1")


def test_an_explicit_proxy_wins_over_the_binding(fake_router: types.ModuleType) -> None:
    services.use_source("9router", proxy="http://127.0.0.1:8080")
    try:
        provider = services._default_factory("exa")
    finally:
        services.use_source(None)
    assert (provider.api_key_override, provider.proxy) == ("k2", "http://127.0.0.1:8080")


def test_an_unknown_source_is_refused() -> None:
    with pytest.raises(InvalidArguments, match="Неизвестный источник ключей"):
        services.use_source("keychain")


def test_the_store_is_the_default_source(fake_router: types.ModuleType) -> None:
    services.use_source(None)
    provider = services._default_factory("exa")
    assert (provider.api_key_override, provider.proxy) == (None, None)
    assert sys.modules["rb_ninerouter"].__name__ == "rb_ninerouter"  # untouched, just not consulted
