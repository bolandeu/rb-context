from __future__ import annotations

from .._distribution import DIST_NAME
from .version import cli_name

# The real command (may differ from the package name) for `action` hints;
# `uv tool upgrade` takes the distribution name, which is the package's.
_CLI = cli_name()
_DIST = DIST_NAME


class CliError(Exception):
    """Base error for all expected, user-facing CLI failures.

    Every raise carries a stable `code`, a human `message`, an optional
    `action` telling the caller (human or agent) how to recover, and the
    process exit code to use. Only named, expected failure modes get a
    subclass here; anything else that escapes a command is turned into an
    `UNEXPECTED` envelope by `output.guard`, so `--json` callers always get
    JSON back.
    """

    def __init__(self, code: str, message: str, *, action: str | None = None, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code

    def to_dict(self) -> dict:
        payload: dict = {"code": self.code, "message": self.message}
        if self.action:
            payload["action"] = self.action
        return payload


class ProjectNotInitialized(CliError):
    def __init__(self, path: str) -> None:
        super().__init__(
            "PROJECT_NOT_INITIALIZED",
            f"No project found at or above '{path}'.",
            action=f"Run '{_CLI} init' in the project directory.",
            exit_code=4,
        )


class AuthRequired(CliError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            "AUTH_REQUIRED",
            f"Authentication is required for provider '{provider}'.",
            action=f"Run '{_CLI} auth login --provider {provider}'.",
            exit_code=3,
        )


class CredentialsUnhealthy(CliError):
    def __init__(self, problems: dict[str, str]) -> None:
        listed = ", ".join(f"{provider} ({status})" for provider, status in problems.items())
        super().__init__(
            "CREDENTIALS_UNHEALTHY",
            f"{len(problems)} credential(s) need attention: {listed}.",
            action=f"See each entry's `message`; store a credential with '{_CLI} auth login --provider <name>'.",
            exit_code=3,
        )


class DependencyTooOld(CliError):
    """Another CLI this one calls is missing or older than required (core/deps.py).

    `dist` is its distribution name — what `uv tool` knows it by (`rb-serp`
    for the `serp` command, standard §10). With `install_url` the action is a
    pinned, runnable install; without it, what to install and no fake URL.
    """

    def __init__(
        self,
        name: str,
        installed: str | None,
        required: str | None,
        *,
        install_url: str | None = None,
        dist: str | None = None,
    ) -> None:
        dist = dist or name
        found = "is not installed" if installed is None else f"is {installed}"
        need = f"{name} >= {required}" if required else name
        if install_url:
            repo = install_url.removesuffix(".git")
            tag = f"v{required}" if required else "<latest release tag>"
            action = f"Run 'uv tool install \"{dist} @ git+{repo}.git@{tag}\" --force', then retry."
        elif installed is not None:
            action = f"Run 'uv tool upgrade {dist}', then retry."
        else:
            action = f"Install {need} (distribution {dist}; see its README for the install command), then retry."
        super().__init__(
            "DEPENDENCY_TOO_OLD",
            f"'{name}' {found}; {_CLI} needs {need}.",
            action=action,
            exit_code=1,
        )


class InvalidArguments(CliError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_ARGUMENTS", message, exit_code=2)


class CredentialStoreUnavailable(CliError):
    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(
            "CREDENTIAL_STORE_UNAVAILABLE",
            f"Could not access the OS credential store for provider '{provider}': {reason}",
            action="Set the credential via an environment variable instead of 'auth login' (see 'auth login --help').",
            exit_code=1,
        )


class ProviderError(CliError):
    """An external service failed: network, timeout, HTTP 5xx/429, malformed response.

    `status` is the HTTP status when there was one. Raised by
    `providers.HttpProvider` after its retries are exhausted — commands and
    services normally don't construct this themselves.
    """

    def __init__(self, provider: str, message: str, *, status: int | None = None, action: str | None = None) -> None:
        super().__init__(
            "PROVIDER_ERROR",
            f"Provider '{provider}': {message}",
            action=action or "Retry later; if it keeps failing, check the provider's status page.",
            exit_code=5,
        )
        self.provider = provider
        self.status = status

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["provider"] = self.provider
        if self.status is not None:
            payload["status"] = self.status
        return payload


class QuotaExceeded(ProviderError):
    """Кончился баланс или лимит тарифа провайдера: повтор не поможет, нужен человек."""

    def __init__(self, provider: str, detail: str, *, status: int | None = None) -> None:
        super().__init__(
            provider,
            f"закончился баланс или лимит тарифа ({detail})",
            status=status,
            action=f"Пополнить баланс или поднять лимит в кабинете {provider}; повтор не поможет.",
        )
        self.code = "QUOTA_EXCEEDED"


class AllProvidersFailed(ProviderError):
    """Не ответил ни один провайдер; `errors` — ошибка каждого, как в `sources[].error`."""

    def __init__(self, errors: list[CliError]) -> None:
        summary = "; ".join(dict.fromkeys(e.message for e in errors))
        super().__init__("all", f"не ответил ни один провайдер — {summary}"[:1000])
        self.errors = [e.to_dict() for e in errors]

    def to_dict(self) -> dict:
        return {**super().to_dict(), "errors": self.errors}


class CliTooOld(CliError):
    def __init__(self, installed: str, required: str) -> None:
        super().__init__(
            "CLI_TOO_OLD",
            f"This project requires {_CLI} >= {required}, but {installed} is installed.",
            action=f"Run 'uv tool upgrade {_DIST}' (or lower cli.min_version in the project's config.toml).",
            exit_code=6,
        )


class Aborted(CliError):
    def __init__(self, description: str) -> None:
        super().__init__("ABORTED", f"{description}: aborted by user.", exit_code=1)
