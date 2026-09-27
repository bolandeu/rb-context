from __future__ import annotations

import json
import subprocess

from ..core import deps
from ..core.errors import AuthRequired, CliError, DependencyTooOld, ProviderError
from ..core.models import SearchHit
from .base import Health, SearchProvider

# 0.4.0 — `auth status --json` в форме §8 стандарта (ok + credentials[].status).
MIN_SERP = "0.4.0"
_REPO = "git+https://github.com/bolandeu/serp.git"
# serp сам повторяет сбойные страницы до 10 раз; дольше ждать нет смысла.
_TIMEOUT = 300


def _exe() -> str:
    try:
        return deps.require_cli("serp", MIN_SERP)
    except DependencyTooOld as exc:
        if "not installed" in exc.message:
            exc.action = f"Run 'uv tool install \"{_REPO}@v{MIN_SERP}\"', then retry."
        raise


def _run_json(args: list[str]) -> dict:
    """Запустить `serp ... --json` и вернуть конверт; вывод не JSON — ProviderError."""
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный argv, без shell
            [_exe(), *args, "--json"], capture_output=True, text=True, timeout=_TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError("serp", f"нет ответа за {_TIMEOUT} с") from exc
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise ProviderError("serp", f"не JSON (exit {proc.returncode}): {proc.stderr.strip()[-300:]}") from exc


class SerpProvider(SearchProvider):
    """Выдача Яндекса/Google со сниппетами через установленный CLI `serp` (`serp snippets --json`).

    Ключи XML River / XMLStock хранит и проверяет сам serp — у context своих нет,
    поэтому в отчёт `context auth status` serp не входит (`credential_fields = ()`):
    его ключи — в `serp auth status`.
    """

    name = "serp"
    summary = "Яндекс/Google — выдача и сниппеты через CLI serp"
    modes = ("yandex", "google")  # первый — по умолчанию
    multi_mode = True
    needs_api_key = False
    credential_fields = ()

    @classmethod
    def check(cls) -> tuple[bool, str | None]:
        try:
            payload = _run_json(["auth", "status"])
        except CliError as exc:
            return False, exc.action or exc.message
        if payload.get("ok"):
            return True, None
        bad = [c["provider"] for c in payload.get("credentials", []) if c.get("status") not in ("ok", "unchecked")]
        detail = f"serp: {', '.join(bad)} — " if bad else ""
        return False, detail + ((payload.get("error") or {}).get("action") or "run 'serp auth status'")

    def health_check(self) -> Health:
        """Ключей у context для serp нет — проверять нечего (их проверяет `serp auth status --check`)."""
        return Health()

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        top = min(100, max(10, -(-limit // 10) * 10))  # serp берёт выдачу страницами по 10
        engines = {part.strip() for part in (mode or self.modes[0]).split(",")}
        engine = "both" if len(engines) > 1 else engines.pop()  # оба поисковика serp просит одним вызовом
        payload = _run_json(["snippets", query, "--engine", engine, "--top", str(top)])
        if not payload.get("ok"):
            error = payload.get("error") or {}
            if error.get("code") == "AUTH_REQUIRED":
                exc = AuthRequired(self.name)
                exc.action = error.get("action") or "Run 'serp auth login'."
                raise exc
            raise ProviderError(self.name, error.get("message", "неизвестная ошибка"), action=error.get("action"))
        return [
            SearchHit(
                provider=self.name,
                engine=row["searchengine"],
                query=query,
                position=row["serp_position"],
                url=row["url"],
                domain=row["domain"],
                title=row["title"],
                snippet=row.get("snippet") or "",
                published=row.get("pubdate") or None,
            )
            for row in payload.get("results", [])
            if row["serp_position"] <= limit  # позиции у каждого поисковика свои, с 1
        ]
