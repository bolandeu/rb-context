from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services
from ..core.models import ProviderRun, SearchHit
from ..providers import ExaProvider, TavilyProvider, providers_help


def _render(hits: list[SearchHit], runs: list[ProviderRun]) -> None:
    """Человеку — markdown, который можно сразу вставить в контекст LLM."""
    for run in runs:
        if run.error:
            output.human.err_console.print(f"[yellow]{run.provider} ('{run.query}'): {run.error['message']}[/yellow]")
    for hit in hits:
        # typer.echo, не rich: rich переносит строки по ширине терминала и ломает URL и код.
        typer.echo(f"## {hit.title or hit.url}\n{hit.url} · {hit.provider} #{hit.position}\n\n{hit.snippet}\n")


@output.guard
def search(
    ctx: typer.Context,
    queries: list[str] = typer.Argument(..., help="Один или несколько поисковых запросов."),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-p",
        help=f"Кого опросить, через запятую; опрашиваются все сразу. Доступны: {providers_help()}. "
        "По умолчанию — `providers` из конфига проекта, иначе все.",
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
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Веб-поиск для контекста LLM: опрашивает всех выбранных провайдеров параллельно.

    Результаты не смешиваются и не дедуплицируются: у каждого своя позиция
    и пометка provider. Упавший провайдер не мешает остальным — его ошибка
    в `sources[].error` (человеку — предупреждение в stderr). Не ответил
    никто — PROVIDER_ERROR (exit 5) или AUTH_REQUIRED (exit 3).

    snippet — текст-контекст провайдера: exa — хайлайты страницы, tavily —
    выжимка content, brave — описание и доп. сниппеты.

    --json: {"ok": true, "count": N, "results": [{provider, query, position,
    url, domain, title, snippet, published, score}, ...], "sources":
    [{provider, query, ok, count, error}, ...]}. Без --json — markdown в stdout.

    \b
    Примеры:
      context search "rag chunking strategies"
      context search "запрос" -p exa,tavily -n 5
      context search "сравнение векторных БД" -p exa --exa-mode deep
      context search "news about uv" -p tavily --tavily-mode advanced --json
    """
    providers = services.resolve_providers(provider, Path(ctx.obj.get("project") or Path.cwd()))
    output.vecho(ctx, f"Провайдеры: {', '.join(providers)}")
    modes = {name: mode for name, mode in (("exa", exa_mode), ("tavily", tavily_mode)) if name in providers}
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
