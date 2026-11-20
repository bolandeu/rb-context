from __future__ import annotations

import json
import os
import subprocess

from ..core import deps
from ..core.errors import AuthRequired, CliError, ProviderError
from ..core.models import COST_CURRENCY, CallCost, SearchHit
from .base import Health, SearchProvider

# 0.7.2 — стоимость в конверте --json (cost, cost_source, billable_requests и итоги, T175).
MIN_SERP = "0.7.2"
_REPO = "https://github.com/bolandeu/serp"
# serp сам повторяет сбойные страницы до 10 раз; дольше ждать нет смысла.
_TIMEOUT = 300


# Если страницы разного происхождения — общий источник по худшему: неизвестно > цена > провайдер > кэш.
_SOURCE_RANK = {"cache": 0, "provider": 1, "price_table": 2}


def _envelope_cost(payload: dict) -> CallCost:
    """Стоимость вызова serp из его конверта: `cost_total`, `billable_requests_total`, `sources[]`.

    Конверт без `cost_total` (`serp snippets` 0.7.2 стоимость ещё не отдаёт) — cost
    неизвестна (None), а платными считаются страницы не из кэша.
    """
    sources = payload.get("sources") or []
    if "cost_total" not in payload:
        return CallCost(
            billable_requests=sum(1 for row in sources if not row.get("from_cache")), cost=None, cost_source=None
        )
    kinds = [row.get("cost_source") for row in sources]
    cost_source = None if None in kinds or not kinds else max(kinds, key=lambda kind: _SOURCE_RANK.get(kind, 3))
    currencies = {row.get("cost_currency") for row in sources} - {None}
    return CallCost(
        billable_requests=payload.get("billable_requests_total") or 0,
        cost=payload["cost_total"],
        cost_currency=currencies.pop() if len(currencies) == 1 else COST_CURRENCY,
        cost_source=cost_source if payload["cost_total"] is not None else None,
    )


def _exe() -> str:
    return deps.require_cli("serp", MIN_SERP, install_url=_REPO)


def _run_json(args: list[str], proxy: str | None = None) -> dict:
    """Запустить `serp ... --json` и вернуть конверт; вывод не JSON — ProviderError.

    `proxy` уходит в окружение subprocess: свой флаг serp прокси не знает, а `requests` внутри него
    читает `HTTPS_PROXY`/`HTTP_PROXY`.
    """
    env = {**os.environ, "HTTPS_PROXY": proxy, "HTTP_PROXY": proxy} if proxy else None
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный argv, без shell
            [_exe(), *args, "--json"], capture_output=True, text=True, timeout=_TIMEOUT, check=False, env=env
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError("serp", f"нет ответа за {_TIMEOUT} с") from exc
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise ProviderError("serp", f"не JSON (exit {proc.returncode}): {proc.stderr.strip()[-300:]}") from exc


class SerpProvider(SearchProvider):
    """Выдача Яндекса/Google со сниппетами через установленный CLI `serp` (`serp snippets --json`).

    Ключи XML River / XMLStock хранит и проверяет сам serp — у context своих нет,
    поэтому в отчёт `context auth status` serp не входит (`credential_fields = ()`):
    его ключи — в `serp auth status`.
    """

    name = "serp"
    summary = "Яндекс/Google — выдача и сниппеты через CLI serp"
    modes = ("yandex", "google")  # первый — по умолчанию
    multi_mode = True
    needs_api_key = False
    credential_fields = ()
    # Платный: стоимость отдаёт serp; пока его ответа нет (упал, не установлен) — неизвестна.
    last_cost = CallCost(cost=None, cost_source=None)

    @classmethod
    def check(cls) -> tuple[bool, str | None]:
        try:
            payload = _run_json(["auth", "status"])
        except CliError as exc:
            return False, exc.action or exc.message
        if payload.get("ok"):
            return True, None
        bad = [c["provider"] for c in payload.get("credentials", []) if c.get("status") not in ("ok", "unchecked")]
        detail = f"serp: {', '.join(bad)} — " if bad else ""
        return False, detail + ((payload.get("error") or {}).get("action") or "run 'serp auth status'")

    def health_check(self) -> Health:
        """Ключей у context для serp нет — проверять нечего (их проверяет `serp auth status --check`)."""
        return Health()

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        top = min(100, max(10, -(-limit // 10) * 10))  # serp берёт выдачу страницами по 10
        engines = {part.strip() for part in (mode or self.modes[0]).split(",")}
        engine = "both" if len(engines) > 1 else engines.pop()  # оба поисковика serp просит одним вызовом
        payload = _run_json(["snippets", query, "--engine", engine, "--top", str(top)], proxy=self.proxy)
        if not payload.get("ok"):
            error = payload.get("error") or {}
            if error.get("code") == "AUTH_REQUIRED":
                exc = AuthRequired(self.name)
                exc.action = error.get("action") or "Run 'serp auth login'."
                raise exc
            raise ProviderError(self.name, error.get("message", "неизвестная ошибка"), action=error.get("action"))
        self.last_cost = _envelope_cost(payload)
        return [
            SearchHit(
                provider=self.name,
                engine=row["searchengine"],
                query=query,
                position=row["serp_position"],
                url=row["url"],
                domain=row["domain"],
                title=row["title"],
                snippet=row.get("snippet") or "",
                published=row.get("pubdate") or None,
            )
            for row in payload.get("results", [])
            if row["serp_position"] <= limit  # позиции у каждого поисковика свои, с 1
        ]
