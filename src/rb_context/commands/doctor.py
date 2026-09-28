from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import deps, services
from ..core.errors import CliTooOld, InvalidArguments
from ..core.models import DEFAULT_PROVIDERS, ProjectConfig
from ..core.version import DEV_VERSION, installed_version
from ..credentials import manager as credentials
from ..providers import provider_class


def _auth_checks(providers: list[str]) -> list[dict]:
    backend = credentials.store_backend()
    checks: list[dict] = [
        {
            "name": "credential_store",
            "ok": backend is not None,
            "detail": backend or "no usable OS keychain backend; credentials must come from environment variables",
        }
    ]
    for provider in providers:
        try:
            ok, detail = provider_class(provider).check()
        except InvalidArguments as exc:
            ok, detail = False, exc.message
        checks.append({"name": f"credential:{provider}", "ok": ok, "detail": detail})
    return checks


@output.guard
def doctor(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Диагностика: версия, проект, настройки, связка ключей, ключи провайдеров, внешние CLI (serp).

    Always exits 0 — the report itself is the result; `healthy` says
    whether every check passed.

    Example: {cli} doctor --json
    """
    checks: list[dict] = [{"name": "python", "ok": True}]
    checks.append({"name": "cli_version", "ok": True, "detail": installed_version() or DEV_VERSION})

    start = Path(ctx.obj.get("project") or Path.cwd())
    output.vecho(ctx, f"Searching for a project root starting at: {start}")
    root = services.find_project_root(start)
    checks.append({"name": "project", "ok": root is not None, "detail": str(root) if root else None})

    config: ProjectConfig | None = None
    if root is not None:
        try:
            config = services.load_config(root, check_compat=False)
            checks.append({"name": "config", "ok": True})
        except Exception as exc:
            checks.append({"name": "config", "ok": False, "detail": str(exc)})
    if config is not None:
        try:
            services.check_cli_compat(config)
            checks.append({"name": "cli_compat", "ok": True, "detail": f"project requires >= {config.cli.min_version}"})
        except CliTooOld as exc:
            checks.append({"name": "cli_compat", "ok": False, "detail": exc.message})

    checks.extend(_auth_checks(config.providers if config else list(DEFAULT_PROVIDERS)))
    checks.extend(deps.doctor_checks())  # [[tool.rb.external]] in pyproject.toml

    all_ok = all(check["ok"] for check in checks)
    output.emit_success(
        ctx, {"healthy": all_ok, "checks": checks}, render_human=lambda data: output.human.render_doctor(data["checks"])
    )
