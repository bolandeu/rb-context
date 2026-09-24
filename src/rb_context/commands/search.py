from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services
from ..core.models import ProviderRun, SearchHit
from ..providers import ExaProvider, SerpProvider, TavilyProvider, providers_help


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
        10, "--limit", "-n", min=1, max=100, help="Результатов с каждого провайдера (brave ≤ 20)."
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
    QUOTA_EXCEEDED) или 3 (AUTH_REQUIRED).

    snippet — текст-контекст провайдера: exa — хайлайты страницы, tavily —
    выжимка content, brave — описание и доп. сниппеты, serp — сниппет из
    выдачи Яндекса/Google (нужен установленный CLI serp со своими ключами).

    --json: {"ok": true, "count": N, "results": [{provider, engine, query,
    position, url, domain, title, snippet, published, score}, ...], "sources":
    [{provider, query, ok, count, error}, ...]}. Без --json — markdown в stdout.

    \b
    Примеры:
      context search "rag chunking strategies"            # только exa
      context search "запрос" -p tavily                   # только tavily
      context search "запрос" -p exa,serp -n 5            # два провайдера
      context search "запрос" -p all                      # все
      context search "купить диван" -p serp --serp-engine google
      context search "купить диван" -p serp --serp-engine yandex,google
      context search "сравнение векторных БД" -p exa --exa-mode deep
    """
    providers = services.resolve_providers(provider, Path(ctx.obj.get("project") or Path.cwd()))
    output.vecho(ctx, f"Провайдеры: {', '.join(providers)}")
    requested = {"exa": exa_mode, "tavily": tavily_mode, "serp": serp_engine}
    modes = {name: mode for name, mode in requested.items() if name in providers}
    hits, runs = services.search(queries, providers=providers, limit=limit, modes=modes)
    output.emit_success(
        ctx,
        {
            "count": len(hits),
            "results": [hit.model_dump() for hit in hits],
            "sources": [run.model_dump() for run in runs],
        },
        render_human=lambda _: _render(hits, runs),
    )
