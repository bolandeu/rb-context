from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services
from ..core.models import ProviderRun, SearchHit
from ..providers import (
    ExaProvider,
    GitHubProvider,
    SerpProvider,
    TavilyProvider,
    WikipediaProvider,
    providers_help,
)


def _render(hits: list[SearchHit], runs: list[ProviderRun]) -> None:
    """Человеку — markdown, который можно сразу вставить в контекст LLM."""
    for run in runs:
        if run.error:
            output.human.err_console.print(f"[yellow]{run.provider} ('{run.query}'): {run.error['message']}[/yellow]")
    for hit in hits:
        # typer.echo, не rich: rich переносит строки по ширине терминала и ломает URL и код.
        source = f"{hit.provider}/{hit.engine}" if hit.engine else hit.provider
        typer.echo(f"## {hit.title or hit.url}\n{hit.url} · {source} #{hit.position}\n\n{hit.snippet}\n")


@output.guard
def search(
    ctx: typer.Context,
    queries: list[str] = typer.Argument(..., help="Один или несколько поисковых запросов."),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-p",
        help="Кого опросить: один (-p exa), несколько через запятую (-p exa,serp) или все (-p all); "
        "выбранные опрашиваются параллельно, и каждый тратит свой лимит. "
        f"Доступны: {providers_help()}. По умолчанию — `providers` из конфига проекта, иначе exa.",
    ),
    limit: int = typer.Option(
        10, "--limit", "-n", min=1, max=100, help="Результатов с каждого провайдера (brave, wikipedia ≤ 20)."
    ),
    exa_mode: str | None = typer.Option(
        None, "--exa-mode", help=f"Режим Exa: {', '.join(ExaProvider.modes)}. По умолчанию auto."
    ),
    tavily_mode: str | None = typer.Option(
        None, "--tavily-mode", help=f"Режим Tavily: {', '.join(TavilyProvider.modes)}. По умолчанию basic."
    ),
    serp_engine: str | None = typer.Option(
        None,
        "--serp-engine",
        help=f"Поисковик для serp: {', '.join(SerpProvider.modes)} или оба через запятую. По умолчанию yandex.",
    ),
    github_mode: str | None = typer.Option(
        None,
        "--github-mode",
        help=f"Что искать на GitHub: {', '.join(GitHubProvider.modes)} (code — только с токеном). "
        "По умолчанию repositories.",
    ),
    wikipedia_lang: str | None = typer.Option(
        None, "--wikipedia-lang", help=f"Раздел Википедии: {', '.join(WikipediaProvider.modes)}. По умолчанию ru."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Веб-поиск для контекста LLM: опрашивает выбранных провайдеров параллельно.

    Без -p — только провайдер по умолчанию (exa или `providers` проекта):
    каждый опрошенный тратит свой лимит, поэтому всех сразу — только явно, -p all.

    Результаты не смешиваются и не дедуплицируются: у каждого своя позиция
    и пометка provider (у serp ещё engine — yandex/google). Упавший
    провайдер не мешает остальным — его ошибка в `sources[].error` (человеку —
    предупреждение в stderr). Не ответил никто — exit 5 (PROVIDER_ERROR,
    QUOTA_EXHAUSTED — исчерпан бесплатный лимит, платный тариф не подключается)
    или 3 (AUTH_REQUIRED).

    snippet — текст-контекст провайдера: exa — хайлайты страницы, tavily —
    выжимка content, brave — описание и доп. сниппеты, serp — сниппет из
    выдачи Яндекса/Google (нужен установленный CLI serp ≥ 0.7.2 со своими
    ключами; нет или старше — DEPENDENCY_TOO_OLD в `sources[].error`),
    hackernews — очки, комментарии, текст и ссылка на обсуждение, github —
    описание и звёзды репозитория / текст issue / фрагменты кода, wikipedia —
    вводный абзац статьи.

    Без ключа: hackernews, wikipedia; github — токен необязателен
    (CONTEXT_GITHUB_API_KEY, связка ключей или GITHUB_TOKEN), без него лимит
    10 поисков в минуту и нет --github-mode code (AUTH_REQUIRED).

    --json: {"ok": true, "count": N, "results": [{provider, engine, query,
    position, url, domain, title, snippet, published, score}, ...], "sources":
    [{provider, query, ok, count, error, billable_requests, cost,
    cost_currency, cost_source, would_cost, would_cost_unit}, ...],
    "billable_requests_total": N, "cost_total": X}. Без --json — markdown в stdout.

    Стоимость — на каждый вызов провайдера (sources[]). exa, tavily, brave —
    только бесплатные лимиты: cost 0, cost_source "free_tier", billable_requests
    — потраченные запросы лимита (упавший вызов — 0); would_cost — сколько вызов
    стоил бы по словам провайдера (exa — USD из costDollars, tavily — credits,
    brave — null), в cost не входит. hackernews, wikipedia — бесплатно и без
    лимита: cost 0, billable_requests 0; github — cost 0, billable_requests 1
    (минутный лимит API; кончился — QUOTA_EXHAUSTED). serp — платный: cost, cost_source
    ("price_table", "provider", "cache" — 0) и billable_requests из конверта
    serp. cost — в cost_currency "RUB"; cost_total — сумма cost всех вызовов,
    null, если стоимость хоть одного неизвестна (serp упал или не отдал
    стоимость — предупреждение в stderr) или не в рублях.

    \b
    Example: {cli} search "rag chunking strategies"            # только exa
             {cli} search "запрос" -p tavily                   # только tavily
             {cli} search "запрос" -p exa,serp -n 5            # два провайдера
             {cli} search "запрос" -p all                      # все
             {cli} search "купить диван" -p serp --serp-engine google
             {cli} search "купить диван" -p serp --serp-engine yandex,google
             {cli} search "sqlite wal" -p hackernews,github,wikipedia --wikipedia-lang en
             {cli} search "typer callback" -p github --github-mode issues
             {cli} search "сравнение векторных БД" -p exa --exa-mode deep
    """
    providers = services.resolve_providers(provider, Path(ctx.obj.get("project") or Path.cwd()))
    output.vecho(ctx, f"Провайдеры: {', '.join(providers)}")
    requested = {
        "exa": exa_mode,
        "tavily": tavily_mode,
        "serp": serp_engine,
        "github": github_mode,
        "wikipedia": wikipedia_lang,
    }
    modes = {name: mode for name, mode in requested.items() if name in providers}
    hits, runs = services.search(queries, providers=providers, limit=limit, modes=modes)
    cost_total, billable_total = services.cost_totals(runs)
    for name in dict.fromkeys(run.provider for run in runs if run.cost is None):
        typer.echo(f"Предупреждение: стоимость вызова {name} неизвестна — cost и cost_total null.", err=True)
    output.emit_success(
        ctx,
        {
            "count": len(hits),
            "results": [hit.model_dump() for hit in hits],
            "sources": [run.model_dump() for run in runs],
            "billable_requests_total": billable_total,
            "cost_total": cost_total,
        },
        render_human=lambda _: _render(hits, runs),
    )
