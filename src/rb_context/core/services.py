"""Project services: find the project folder, read and write its config file, and the check that the installed CLI is
new enough for it.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tomli_w
from packaging.version import Version

from ..providers import PROVIDERS, SearchProvider, provider_class
from .errors import AllProvidersFailed, CliError, CliTooOld, InvalidArguments, ProjectNotInitialized
from .models import COST_CURRENCY, DEFAULT_PROVIDERS, ProjectConfig, ProviderRun, SearchHit
from .version import cli_name, installed_version

# Папка проекта — по имени команды (.context), а не пакета (.rb_context, как в
# шаблоне): так она называлась до переименования пакета в rb_context.
PROJECT_DIR_NAME = f".{cli_name()}"
CONFIG_FILE_NAME = "config.toml"


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_DIR_NAME).is_dir():
            return candidate
    return None


def require_project_root(start: Path) -> Path:
    root = find_project_root(start)
    if root is None:
        raise ProjectNotInitialized(str(start))
    return root


def config_path(project_root: Path) -> Path:
    return project_root / PROJECT_DIR_NAME / CONFIG_FILE_NAME


def check_cli_compat(config: ProjectConfig) -> None:
    """Raise CliTooOld if this installed CLI is older than the project's `cli.min_version`.

    A project outlives any single CLI release; this is how it refuses to be
    driven by a CLI that predates a config field or command it relies on.
    Skipped for an uninstalled (bare source) run, which has no version, and
    for a build without a `v*` tag in reach (uv-dynamic-versioning's
    `0.0.0` fallback) — a dev checkout, not a release older than anything.
    """
    installed = installed_version()
    if installed is None or Version(installed).release == (0, 0, 0):
        return
    if Version(installed) < Version(config.cli.min_version):
        raise CliTooOld(installed, config.cli.min_version)


def load_config(project_root: Path, *, check_compat: bool = True) -> ProjectConfig:
    """Load and validate the project config, enforcing `cli.min_version` by default.

    Only `doctor` passes `check_compat=False` — it reports the mismatch as
    one of its checks instead of failing on it.
    """
    data = tomllib.loads(config_path(project_root).read_text())
    config = ProjectConfig.model_validate(data)
    if check_compat:
        check_cli_compat(config)
    return config


def save_config(project_root: Path, config: ProjectConfig) -> None:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(config.model_dump()))


def init_project(project_root: Path, name: str) -> ProjectConfig:
    config = ProjectConfig(name=name)
    save_config(project_root, config)
    return config


def resolve_providers(explicit: str | None, start: Path) -> list[str]:
    """Кого опрашивать: --provider "a,b" → `providers` проекта → `DEFAULT_PROVIDERS`; `all` — всех."""
    if explicit:
        names = [name.strip() for name in explicit.split(",") if name.strip()]
    else:
        root = find_project_root(start)
        names = load_config(root).providers if root is not None else list(DEFAULT_PROVIDERS)
    if "all" in names:
        return list(PROVIDERS)
    for name in names:
        provider_class(name)  # неизвестное имя → INVALID_ARGUMENTS до любых запросов
    return list(dict.fromkeys(names))


def check_modes(modes: dict[str, str | None]) -> None:
    """Режим поиска должен быть из `modes` своего провайдера."""
    for name, mode in modes.items():
        if mode is None:
            continue
        cls = provider_class(name)
        parts = [part.strip() for part in mode.split(",")] if cls.multi_mode else [mode]
        for part in parts:
            if part not in cls.modes:
                raise InvalidArguments(f"Режим '{part}' не поддерживается {name}. Доступны: {', '.join(cls.modes)}.")


def _default_factory(name: str) -> SearchProvider:
    return provider_class(name)()


def cost_totals(runs: list[ProviderRun]) -> tuple[float | None, int]:
    """`cost_total` (в `COST_CURRENCY`) и `billable_requests_total` по всем вызовам.

    Стоимость неизвестна хоть у одного вызова — итог None. Курсов context не знает:
    ненулевая сумма в другой валюте тоже делает итог None (нули — не мешают).
    """
    billable = sum(run.billable_requests for run in runs)
    total = 0.0
    for run in runs:
        if run.cost is None or (run.cost and run.cost_currency != COST_CURRENCY):
            return None, billable
        total += run.cost
    return round(total, 6), billable


def search(
    queries: list[str],
    *,
    providers: list[str],
    limit: int,
    modes: dict[str, str | None] | None = None,
    factory: Callable[[str], SearchProvider] = _default_factory,
) -> tuple[list[SearchHit], list[ProviderRun]]:
    """Опросить все `providers` по всем `queries` параллельно.

    Упавший провайдер не мешает остальным: его ошибка попадает в
    `ProviderRun.error`. Ошибка поднимается, только если не ответил никто —
    одна как есть, несколько — `AllProvidersFailed` со списком `errors`.
    `factory` — тестовый шов вместо реальных провайдеров.
    """
    modes = modes or {}
    check_modes(modes)
    tasks = [(query, name) for query in queries for name in providers]

    def run(task: tuple[str, str]) -> tuple[list[SearchHit], ProviderRun, CliError | None]:
        query, name = task
        provider: SearchProvider | None = None
        try:
            provider = factory(name)
            hits = provider.search(query, limit=limit, mode=modes.get(name))
        except CliError as exc:
            cost = (provider or provider_class(name)).last_cost.model_dump()
            return [], ProviderRun(provider=name, query=query, ok=False, error=exc.to_dict(), **cost), exc
        cost = provider.last_cost.model_dump()
        return hits, ProviderRun(provider=name, query=query, ok=True, count=len(hits), **cost), None

    hits: list[SearchHit] = []
    runs: list[ProviderRun] = []
    errors: list[CliError] = []
    with ThreadPoolExecutor(max_workers=min(len(tasks), 8) or 1) as pool:
        for task_hits, task_run, error in pool.map(run, tasks):
            hits.extend(task_hits)
            runs.append(task_run)
            if error is not None:
                errors.append(error)

    if runs and len(errors) == len(runs):
        if len({(e.code, e.message) for e in errors}) == 1:
            raise errors[0]
        raise AllProvidersFailed(errors)
    return hits, runs
