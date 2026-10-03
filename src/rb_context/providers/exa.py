from __future__ import annotations

import functools
import re
from collections.abc import Iterator
from contextlib import contextmanager

import requests
from exa_py import Exa

from ..core.errors import AuthRequired, ProviderError, QuotaExceeded
from ..core.models import CallCost, SearchHit, extract_domain
from .base import Health, SearchProvider
from .http import PROBE_TIMEOUT

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
        self._given = client  # None — клиент с ключом создаётся при первом запросе

    @functools.cached_property
    def _client(self) -> Exa:
        return self._given or Exa(api_key=self.require_api_key())

    @contextmanager
    def _errors(self) -> Iterator[None]:
        """Ошибки exa-py → AuthRequired / QuotaExceeded / ProviderError."""
        try:
            yield
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

    def health_check(self) -> Health:
        """`POST /search` без запроса: ключ проверяется до тела, ответ 400 — ключ принят, поиск не тарифицируется.

        Бесплатного чтения у Exa нет (Research API закрыт — 410, Websets — только Pro).
        Опора на порядок проверок недокументирована: если Exa начнёт валидировать
        тело раньше ключа, неверный ключ тоже даст 400 — поэтому 400 засчитывается
        только с текстом о невалидном теле.
        """
        try:
            with self._errors():
                self._probe_search()
        except QuotaExceeded as exc:
            return Health(status="quota_exhausted", message=exc.message)
        except ProviderError as exc:
            if exc.status == 400 and "Invalid request body" in exc.message:
                return Health()
            raise
        return Health()

    def _probe_search(self) -> None:
        """Тот же `POST /search`, что шлёт SDK, но одной попыткой за `PROBE_TIMEOUT`: exa-py таймаут не ставит.

        Ошибку поднимает в виде exa-py (`ValueError` с кодом), чтобы её разобрал `_errors`.
        """
        client = self._client
        response = requests.post(
            f"{client.base_url}/search", json={"numResults": 1}, headers=client.headers, timeout=PROBE_TIMEOUT
        )
        if response.status_code >= 400:
            raise ValueError(f"Request failed with status code {response.status_code}: {response.text}")

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        with self._errors():
            response = self._client.search(query, num_results=limit, type=mode, contents={"highlights": True})
        # Только бесплатный лимит: cost 0, а costDollars из ответа — «сколько стоило бы».
        cost_dollars = getattr(response, "cost_dollars", None)
        would_cost = getattr(cost_dollars, "total", None)
        self.last_cost = CallCost(
            billable_requests=1, would_cost=would_cost, would_cost_unit="USD" if would_cost is not None else None
        )
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
