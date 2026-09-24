# context

Веб-поиск как контекст для LLM через провайдеров [Exa](https://exa.ai),
[Tavily](https://tavily.com) и [Brave Search](https://brave.com/search/api/).
Выбранные провайдеры опрашиваются параллельно, результаты приходят в общем
виде (URL, заголовок, сниппет-контекст) с пометкой, откуда каждый.
Python-пакет — `rb-context` (импорт `rb_context`), команда в терминале — `context`.

## Установка

```bash
uv tool install "git+https://github.com/bolandeu/context.git"
```

Одинаково на macOS, Linux и Windows; обновление — `uv tool upgrade rb-context`,
конкретная версия — `...context.git@v0.2.0`.

**Репозиторий приватный.** `uv` ходит в git так же, как `git clone`. Если установка
падает с ошибкой авторизации — один раз `gh auth login` (или `gh auth setup-git`, если
`gh` залогинен через `--with-token`), либо SSH-вариант:

```bash
uv tool install "git+ssh://git@github.com/bolandeu/context.git"
```

## Ключи

Ключи хранятся в связке ключей ОС (keychain), не в файлах проекта:

```bash
context auth login -p exa       # спросит API-ключ
context auth login -p tavily
context auth login -p brave
context doctor                  # версия, проект, какие ключи есть
```

Без keychain (CI, headless Linux) — переменные `CONTEXT_EXA_API_KEY`,
`CONTEXT_TAVILY_API_KEY`, `CONTEXT_BRAVE_API_KEY` (их же читает
`auth login --non-interactive`).

## Использование

```bash
context search "rag chunking strategies"                  # все провайдеры
context search "запрос" -p exa,tavily -n 5                # только эти, по 5 результатов
context search "сравнение векторных БД" -p exa --exa-mode deep
context search "news about uv" --json                     # для агентов
```

Без проекта опрашиваются все провайдеры. В проекте (`context init`) — список из
`providers` в `.context/config.toml` (`context config set providers exa,tavily`).
Упавший провайдер не мешает остальным: его ошибка в `sources[].error`.

Режимы поиска: `--exa-mode` (auto, fast, instant, deep-lite, deep, deep-reasoning) и
`--tavily-mode` (basic, advanced, fast, ultra-fast). У Brave режимов нет.

## Почему такие библиотеки

| Провайдер | Как подключён | Почему |
| --- | --- | --- |
| Exa | официальный SDK [`exa-py`](https://github.com/exa-labs/exa-py) | поддерживается Exa, типы ответа; сниппет — `highlights` (рекомендация Exa для LLM-контекста) |
| Tavily | официальный SDK [`tavily-python`](https://github.com/tavily-ai/tavily-python) | поддерживается Tavily, свои классы ошибок (ключ / лимит) |
| Brave | REST через `providers/http.py` (`HttpProvider` на httpx) | официального Python SDK нет; сторонние обёртки ничего не дают поверх одного GET |

Отвергнуто: LangChain / LlamaIndex tools для этих сервисов — тяжёлая зависимость
ради трёх вызовов, и ошибки всё равно пришлось бы переводить в коды CLI. Исключения
SDK переводятся в `AuthRequired` / `ProviderError` в самих модулях `providers/`,
выше них никто не видит вендорских ошибок.

## Разработка

```bash
uv sync
uv run context --help
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
scripts/install_hooks.sh  # pre-commit предупреждает об устаревших docstring команд (это их --help)
```

Новый провайдер: модуль в `src/rb_context/providers/` с подклассом `SearchProvider`
и строка в `PROVIDERS` (`providers/__init__.py`).

## Релиз

```bash
uv run scripts/release.py patch   # или minor / major
```

Поднимает версию в `pyproject.toml`, датирует `## [Unreleased]` в `CHANGELOG.md`,
коммитит, ставит тег `v<version>` и пушит.

## Архитектура

Проект следует архитектуре шаблона `cli-generator`:

- `src/rb_context/commands/` — только разбор аргументов.
- `src/rb_context/core/` — сервисы, модели, ошибки.
- `src/rb_context/providers/` — Exa, Tavily, Brave.
- `src/rb_context/credentials/` — ключи: связка ключей ОС и env.
- `src/rb_context/output/` — человеческий вывод и `--json`.

Памятка для агентов — `src/rb_context/data/SKILL.md`: `context skill install`
ставит её в AI-инструмент, `context --ai` печатает.
