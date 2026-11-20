"""Ключ и прокси из локальной базы 9router (`--source 9router`).

Сама база — забота `rb_ninerouter` (пакет живёт отдельно: чужая 0.x-схема, приватный репозиторий, никуда не
публикуется). Здесь только перевод его ответа в наше: ключ для `api_key_override` и прокси для поля провайдера,
плюс ошибки этого CLI вместо `SchemaDrift`/`LookupError`.

Импорт через `importlib`: пакета может не быть на машине, и тогда это аргумент, а не падение при старте CLI.
"""

from __future__ import annotations

import importlib

from ..core.errors import InvalidArguments


def binding(service: str, *, key: str | None = None, rotation: str | None = None) -> tuple[str, str | None]:
    """(ключ, прокси) для сервиса: конкретный `--key`, иначе выбор по схеме 9router (или `--rotation`)."""
    try:
        router = importlib.import_module("rb_ninerouter")
    except ModuleNotFoundError:  # пакет не установлен: источник недоступен, но CLI работает
        raise InvalidArguments("--source 9router needs the rb-9router package installed (tools/rb-9router)") from None

    schema_drift = router.SchemaDrift
    try:
        if key is not None:
            known = router.bindings(service)
            found = [b for b in known if b.name == key]
            if not found:
                names = ", ".join(b.name for b in known) or "none"
                raise InvalidArguments(f"9router has no key '{key}' for {service} (known: {names}).")
            chosen = found[0]
        else:
            chosen = router.pick(service, rotation=rotation)
    except schema_drift as exc:  # база другой версии: читать её наугад нельзя
        raise InvalidArguments(f"9router database is not readable: {exc}") from exc
    except LookupError as exc:  # ни одного живого ключа у сервиса
        raise InvalidArguments(f"{exc}. Fix it in 9router or use --source env.") from exc
    return chosen.reveal(), chosen.proxy
