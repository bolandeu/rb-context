from __future__ import annotations

import importlib
from datetime import UTC, datetime

import typer

from .. import output, providers
from ..core.errors import InvalidArguments
from ..core.version import DEV_VERSION, cli_name, installed_version, module_exists

# `auth status` exists in every CLI (tools/docs/standard-release.md §8); a CLI
# generated without credentials (no credentials/ package, no commands/login.py)
# reports an empty `credentials` list and exits 0. Detected at runtime so this
# file needs no template logic — same approach as doctor.py.
_PACKAGE_NAME = __name__.split(".")[0]
_HAS_CREDENTIALS = module_exists(f"{_PACKAGE_NAME}.credentials.manager")

app = output.group("Ключи провайдеров (связка ключей ОС или env CONTEXT_<PROVIDER>_API_KEY).")


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
    (`serp auth status`) and isn't listed (`--provider serp` is a usage error).
    --check is free for exa (an empty /search request, rejected before billing)
    and tavily (/usage, with the remaining credits as `quota`); brave has no free
    call, so it makes one search.
    Exits 0 when every required provider is ok/unchecked (an optional one may be
    missing), 3 when any required provider has a problem or any credential is
    invalid/expired, 2 on a usage error. The --json shape is a cross-tool contract:
    `tool`, `version`, `checked_at`, `credentials[]` with `provider`, `required`,
    `fields`, `source`, `source_ref`, `status`, `expires_at`, `quota`, `message`.

    Example: {cli} auth status --check --json
    """
    tool, version = cli_name(), installed_version() or DEV_VERSION
    if not _HAS_CREDENTIALS:
        if provider is not None:
            raise InvalidArguments(f"Unknown provider '{provider}' ({tool} stores no credentials).")
        checked_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        payload = {"tool": tool, "version": version, "checked_at": checked_at, "credentials": []}
        output.emit_report(ctx, payload, lambda _: output.human.echo(f"{tool} stores no credentials."), None)
        return
    health = importlib.import_module(f"{_PACKAGE_NAME}.credentials.health")
    # Провайдер без ключей context (serp хранит свои сам) — такая же ошибка, как неизвестный.
    with_keys = [cls for cls in providers.all_providers() if cls.credential_fields]
    if provider is not None and not health.select(with_keys, provider):
        raise InvalidArguments(f"Unknown provider '{provider}' (known: {', '.join(cls.name for cls in with_keys)}).")
    payload, problem = health.status(tool, version, check=check, only=provider)
    output.emit_report(ctx, payload, health.render, problem)


if module_exists(f"{_PACKAGE_NAME}.commands.login"):
    _login = importlib.import_module(f"{_PACKAGE_NAME}.commands.login")
    app.command("login")(_login.login)
    app.command("logout")(_login.logout)
