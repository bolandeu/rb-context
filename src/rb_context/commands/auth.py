from __future__ import annotations

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..credentials import manager as credentials
from ..providers import provider_class, providers_help

app = output.group("Ключи провайдеров (связка ключей ОС или env CONTEXT_<PROVIDER>_API_KEY).")

ProviderOption = typer.Option(..., "--provider", "-p", help=f"Провайдер. Доступны: {providers_help()}.")


@app.command("login")
@output.guard
def login(
    ctx: typer.Context,
    provider: str = ProviderOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сохранить API-ключ провайдера в связку ключей ОС.

    Ключ берётся из CONTEXT_<PROVIDER>_API_KEY (например CONTEXT_EXA_API_KEY),
    если переменная задана, иначе спрашивается. С --non-interactive и без
    переменной — ошибка, а не вопрос.
    """
    provider_class(provider)
    secret = credentials.read_secret_from_env(provider)
    if secret is None:
        if ctx.obj.get("non_interactive") or non_interactive:
            raise InvalidArguments(
                f"No credential found in environment for provider '{provider}' and --non-interactive was set."
            )
        secret = typer.prompt(f"Enter API key for '{provider}'", hide_input=True)
    credentials.store_secret(provider, secret)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Stored credential for '{d['provider']}'."),
    )


@app.command("logout")
@output.guard
def logout(
    ctx: typer.Context,
    provider: str = ProviderOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить API-ключ провайдера из связки ключей ОС."""
    provider_class(provider)
    credentials.delete_secret(provider)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Removed credential for '{d['provider']}'."),
    )


@app.command("status")
@output.guard
def auth_status(
    ctx: typer.Context,
    provider: str = ProviderOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Проверить, есть ли ключ провайдера (в env или связке ключей)."""
    authenticated = provider_class(provider).load_api_key() is not None
    output.emit_success(
        ctx,
        {"provider": provider, "authenticated": authenticated},
        render_human=lambda d: output.human.echo(
            f"{'Authenticated' if d['authenticated'] else 'Not authenticated'} for '{d['provider']}'."
        ),
    )
