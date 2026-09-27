from __future__ import annotations

import typer
from rich.markup import escape

from .. import output, providers
from ..core.errors import CredentialsUnhealthy, InvalidArguments
from ..core.version import CLI_NAME, DEV_VERSION, installed_version
from ..credentials import health
from ..credentials import manager as credentials
from ..providers import provider_class, providers_help

app = output.group("Ключи провайдеров (связка ключей ОС или env CONTEXT_<PROVIDER>_API_KEY).")

ProviderOption = typer.Option(..., "--provider", "-p", help=f"Провайдер. Доступны: {providers_help()}.")


def _require_api_key_provider(provider: str) -> None:
    if not provider_class(provider).needs_api_key:
        raise InvalidArguments(f"Ключи {provider} хранит сам {provider}: '{provider} auth login'.")


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


@app.command("logout")
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


@app.command("status")
@output.guard
def auth_status(
    ctx: typer.Context,
    check: bool = typer.Option(
        False, "--check", help="Also make one cheap read-only call per provider (10 s timeout) to prove each works."
    ),
    provider: str | None = typer.Option(
        None, "--provider", "-p", help="Report only this provider (default: all with keys: exa, tavily, brave)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Report every provider's credential: where it comes from and whether it works. Never prints values.

    Without --check only presence is reported (status `unchecked` or `missing`).
    exa is required, tavily and brave are optional; serp keeps its own keys
    (`serp auth status`) and isn't listed. --check is free for exa (an empty
    /search request, rejected before billing) and tavily (/usage, with the
    remaining credits as `quota`); brave has no free call, so it makes one search.
    Exits 0 when every required provider is ok/unchecked (an optional one may be
    missing), 3 when any required provider has a problem or any credential is
    invalid/expired, 2 on a usage error. The --json shape is a cross-tool contract:
    `tool`, `version`, `checked_at`, `credentials[]` with `provider`, `required`,
    `fields`, `source`, `source_ref`, `status`, `expires_at`, `quota`, `message`.

    Example: {cli} auth status --check --json
    """
    known = providers.all_providers()
    selected = health.select(known, provider)
    if provider is not None and not any(cls.credential_fields for cls in selected):
        names = ", ".join(cls.name for cls in known if cls.credential_fields) or "none"
        raise InvalidArguments(f"Unknown provider '{provider}' (known: {names}).")
    payload = health.report(CLI_NAME, installed_version() or DEV_VERSION, selected, check=check, only=provider)
    problems = {entry["provider"]: entry["status"] for entry in payload["credentials"] if health.is_problem(entry)}
    output.emit_report(ctx, payload, _render_status, CredentialsUnhealthy(problems) if problems else None)


def _render_status(payload: dict) -> None:
    if not payload["credentials"]:
        output.human.echo("No providers with credentials.")
    for entry in payload["credentials"]:
        mark = {"ok": "[green]✓[/green]", "unchecked": "[dim]·[/dim]"}.get(entry["status"], "[red]✗[/red]")
        optional = "" if entry["required"] else " (optional)"
        detail = f" — {entry['message']}" if entry["message"] else ""
        expires = f", expires {entry['expires_at']}" if entry["expires_at"] else ""
        line = f"{entry['provider']}{optional}: {entry['status']} ({entry['source']}: {entry['source_ref']}){expires}{detail}"
        output.human.echo(f"{mark} {escape(line)}")
