# context

Веб-поиск как контекст для LLM через провайдеров [Exa](https://exa.ai),
[Tavily](https://tavily.com), [Brave Search](https://brave.com/search/api/) и выдачу
Яндекса/Google через CLI [`serp`](https://github.com/bolandeu/serp).
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

У провайдера `serp` своих ключей в context нет: его доступы (XML River / XMLStock)
хранит и проверяет сам `serp` — `serp auth login`. `context doctor` спрашивает у него
`serp auth status`.

## Использование

```bash
context search "rag chunking strategies"                  # только exa (по умолчанию)
context search "запрос" -p tavily                         # один конкретный
context search "запрос" -p exa,serp -n 5                  # несколько, по 5 результатов
context search "запрос" -p all                            # все
context search "купить диван" -p serp --serp-engine both  # Яндекс и Google
context search "сравнение векторных БД" -p exa --exa-mode deep
context search "news about uv" --json                     # для агентов
```

**Лимиты.** Каждый опрошенный провайдер тратит свой лимит, поэтому без `-p` опрашивается
только один — `exa`, а все сразу — только явно, `-p all`. Свой набор по умолчанию для
проекта: `context init`, затем `context config set providers exa,serp` (`all` — все).
Упавший провайдер не мешает остальным: его ошибка в `sources[].error`; кончился баланс —
`QUOTA_EXCEEDED`.

Режимы: `--exa-mode` (auto, fast, instant, deep-lite, deep, deep-reasoning),
`--tavily-mode` (basic, advanced, fast, ultra-fast), `--serp-engine` (yandex, google, both;
по умолчанию yandex). У Brave режимов нет.

## Почему такие библиотеки

| Провайдер | Как подключён | Почему |
| --- | --- | --- |
| Exa | официальный SDK [`exa-py`](https://github.com/exa-labs/exa-py) | поддерживается Exa, типы ответа; сниппет — `highlights` (рекомендация Exa для LLM-контекста) |
| Tavily | официальный SDK [`tavily-python`](https://github.com/tavily-ai/tavily-python) | поддерживается Tavily, свои классы ошибок (ключ / лимит) |
| Brave | REST через `providers/http.py` (`HttpProvider` на httpx) | официального Python SDK нет; сторонние обёртки ничего не дают поверх одного GET |
| serp (Яндекс/Google) | вызов установленного CLI `serp snippets --json` (subprocess) | **пакет `rb-serp` в зависимостях нет, и это намеренно** — см. ниже |

**Почему serp — через CLI, а не библиотекой `rb-serp`.** `--json` у serp — его стабильный
контракт для агентов (конверт, коды ошибок), ключи XML River / XMLStock остаются в serp и
не дублируются, версии двух пакетов не связаны. Импорт `rb-serp` потребовал бы зависимость
от приватного git-репозитория в `uv.lock` (CI её не скачает) и синхронных релизов.
Цена — serp должен быть установлен отдельно:
`uv tool install "git+https://github.com/bolandeu/serp.git"`; без него провайдер `serp`
отвечает `PROVIDER_ERROR` с этой командой в `action`, остальные работают.
Сниппеты при этом пишутся в журнал serp, и `serp ... --cache` потом отдаст их бесплатно.

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
- `src/rb_context/providers/` — Exa, Tavily, Brave, serp.
- `src/rb_context/credentials/` — ключи: связка ключей ОС и env.
- `src/rb_context/output/` — человеческий вывод и `--json`.

Памятка для агентов — `src/rb_context/data/SKILL.md`: `context skill install`
ставит её в AI-инструмент, `context --ai` печатает.
