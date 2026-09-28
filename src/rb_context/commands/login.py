"""`auth login` / `auth logout` — only in CLIs generated with credentials (include_auth).

`commands/auth.py` registers these into the `auth` group when this module
exists; `auth status` is there in every CLI (tools/docs/standard-release.md §8).
"""

from __future__ import annotations

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..credentials import manager as credentials
from ..providers import provider_class, providers_help

ProviderOption = typer.Option(..., "--provider", "-p", help=f"Провайдер. Доступны: {providers_help()}.")


def _require_api_key_provider(provider: str) -> None:
    if not provider_class(provider).needs_api_key:
        raise InvalidArguments(f"Ключи {provider} хранит сам {provider}: '{provider} auth login'.")


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

    Example: {cli} auth login --provider exa
    """
    _require_api_key_provider(provider)
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


@output.guard
def logout(
    ctx: typer.Context,
    provider: str = ProviderOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить API-ключ провайдера из связки ключей ОС.

    Example: {cli} auth logout --provider exa
    """
    _require_api_key_provider(provider)
    credentials.delete_secret(provider)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Removed credential for '{d['provider']}'."),
    )
