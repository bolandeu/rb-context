# context

Веб-поиск как контекст для LLM через провайдеров [Exa](https://exa.ai),
[Tavily](https://tavily.com), [Brave Search](https://brave.com/search/api/), выдачу
Яндекса/Google через CLI [`serp`](https://github.com/bolandeu/serp) и бесплатные источники без ключа:
Hacker News, GitHub и Википедия.
Выбранные провайдеры опрашиваются параллельно, результаты приходят в общем
виде (URL, заголовок, сниппет-контекст) с пометкой, откуда каждый.
Python-пакет — `rb-context` (импорт `rb_context`), команда в терминале — `context`.

## Установка

```bash
```

Из git-тега:

```bash
uv tool install "rb-context @ git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/context.git@vX.Y.Z"
```

Вместо `vX.Y.Z` — последний тег релиза. Одинаково на macOS, Linux и Windows; обновление —
`uv tool upgrade rb-context`.

## Ключи

Ключи хранятся в связке ключей ОС (keychain), не в файлах проекта:

```bash
context auth login -p exa       # спросит API-ключ
context auth login -p tavily
context auth login -p brave
context doctor                  # версия, проект, какие ключи есть
context auth status --check     # каждый ключ: откуда и работает ли (exit 3 — проблема)
```

Без keychain (CI, headless Linux) — переменные `CONTEXT_EXA_API_KEY`,
`CONTEXT_TAVILY_API_KEY`, `CONTEXT_BRAVE_API_KEY` (их же читает
`auth login --non-interactive`).

У провайдера `serp` своих ключей в context нет: его доступы (XML River / XMLStock)
хранит и проверяет сам `serp` — `serp auth login`. `context doctor` спрашивает у него
`serp auth status`. В `context auth status` serp не входит; exa — обязательный,
tavily и brave — необязательные (без ключа не ошибка).

## Использование

```bash
context search "rag chunking strategies"                  # только exa (по умолчанию)
context search "запрос" -p tavily                         # один конкретный
context search "запрос" -p exa,serp -n 5                  # несколько, по 5 результатов
context search "запрос" -p all                            # все
context search "купить диван" -p serp                     # выдача Яндекса
context search "купить диван" -p serp --serp-engine google
context search "купить диван" -p serp --serp-engine yandex,google  # оба
context search "сравнение векторных БД" -p exa --exa-mode deep
context search "news about uv" --json                     # для агентов
context search "sqlite wal" -p hackernews,github,wikipedia --wikipedia-lang en  # бесплатные
context search "typer callback" -p github --github-mode issues

# ключи и прокси из локальной базы 9router (пакет rb-9router, не публикуется)
context search "запрос" -p exa --source 9router            # ключ + прокси + схема из 9router
context search "запрос" -p exa --source 9router --key netparadox   # конкретное подключение
context search "запрос" -p exa --source 9router --rotation least-used
context search "запрос" -p brave --proxy socks5://u:p@host:1080    # прокси для этого запуска
```

**Источник ключа.** По умолчанию ключ берётся из окружения и keychain (`--source env`, он же
умолчание). `--source 9router` берёт ключ из локальной базы 9router, а вместе с ним — прокси,
привязанный к этому ключу, и схему ротации из настроек 9router (`providerStrategies`).
`--key <имя>` выбирает конкретное подключение вместо схемы, `--rotation` перебивает схему,
`--proxy` перебивает прокси ключа. Живых ключей нет — ошибка аргументов, молчаливого отката
на окружение нет.

**Лимиты.** Каждый опрошенный провайдер тратит свой лимит, поэтому без `-p` опрашивается
только один — `exa`, а все сразу — только явно, `-p all`. Свой набор по умолчанию для
проекта: `context init`, затем `context config set providers exa,serp` (`all` — все).
Упавший провайдер не мешает остальным: его ошибка в `sources[].error`. Exa, Tavily и Brave —
только бесплатные лимиты: исчерпан — `QUOTA_EXHAUSTED` («лимит исчерпан»), на платный тариф
context не переходит.

**Стоимость** (`--json`): у каждого вызова в `sources[]` — `billable_requests`, `cost`,
`cost_currency` (RUB), `cost_source`, `would_cost`/`would_cost_unit`; в конверте `cost_total` и
`billable_requests_total`. Exa/Tavily/Brave — `cost_source: "free_tier"`, cost 0; что вызов стоил
бы по словам провайдера — `would_cost` (Exa `costDollars` в USD, Tavily — кредиты, Brave — null),
в cost не входит. serp платный — его cost и `cost_source` берутся из конверта serp; не отдал
(`serp snippets` пока без стоимости) — cost и `cost_total` null с предупреждением в stderr.
Проверка ключа Brave (`auth status --check`) — поиск `count=1`, тратит 1 запрос лимита
(бесплатной у Brave нет): не запускать по расписанию.

Режимы: `--exa-mode` (auto, fast, instant, deep-lite, deep, deep-reasoning),
`--tavily-mode` (basic, advanced, fast, ultra-fast), `--serp-engine` (yandex, google или оба —
`yandex,google`; по умолчанию yandex), `--github-mode` (repositories, issues, code — code только
с токеном), `--wikipedia-lang` (ru, en). У Brave и Hacker News режимов нет.

**Бесплатные источники.** `hackernews` (API поиска Algolia) и `wikipedia` (MediaWiki API) —
без ключа и без лимита: cost 0, `billable_requests` 0. `github` — REST search; токен
необязателен (`context auth login -p github`, `CONTEXT_GITHUB_API_KEY` или `GITHUB_TOKEN`): без
него 10 поисков в минуту вместо 30 и нет поиска по коду. Кончился минутный лимит —
`QUOTA_EXHAUSTED`.

## Почему такие библиотеки

| Провайдер | Как подключён | Почему |
| --- | --- | --- |
| Exa | официальный SDK [`exa-py`](https://github.com/exa-labs/exa-py) | поддерживается Exa, типы ответа; сниппет — `highlights` (рекомендация Exa для LLM-контекста) |
| Tavily | официальный SDK [`tavily-python`](https://github.com/tavily-ai/tavily-python) | поддерживается Tavily, свои классы ошибок (ключ / лимит) |
| Brave | REST через `providers/http.py` (`HttpProvider` на httpx) | официального Python SDK нет; сторонние обёртки ничего не дают поверх одного GET |
| Hacker News, GitHub, Википедия | REST через `HttpProvider` | открытые API (Algolia, GitHub REST, MediaWiki); SDK ради одного GET не нужен |
| serp (Яндекс/Google) | вызов установленного CLI `serp snippets --json` (subprocess) | **пакет `rb-serp` в зависимостях нет, и это намеренно** — см. ниже |

**Почему serp — через CLI, а не библиотекой `rb-serp`.** `--json` у serp — его стабильный
контракт для агентов (конверт, коды ошибок), ключи XML River / XMLStock остаются в serp и
не дублируются, версии двух пакетов не связаны. Импорт `rb-serp` потребовал бы зависимость
от приватного git-репозитория в `uv.lock` (CI её не скачает) и синхронных релизов.
Цена — serp должен быть установлен отдельно, не старше 0.7.2 (`MIN_SERP` в
`providers/serp.py`, проверяется по `serp --version`):
`uv tool install "git+https://github.com/bolandeu/serp.git"`; без него или со старым провайдер
`serp` отвечает `DEPENDENCY_TOO_OLD` с командой установки/обновления в `action`, остальные работают.

Отвергнуто: LangChain / LlamaIndex tools для этих сервисов — тяжёлая зависимость
ради трёх вызовов, и ошибки всё равно пришлось бы переводить в коды CLI. Исключения
SDK переводятся в `AuthRequired` / `ProviderError` в самих модулях `providers/`,
выше них никто не видит вендорских ошибок.

## Разработка

```bash
uv sync
uv run context --help
# гейт перед коммитом — `gate check` на этой машине (команда — `[publish] gate_command`
# в `.agents/antagor/antagor.toml`); workflow его не гоняет
uv run pytest --snapshot-update     # после правки справки команды; смотреть tests/snapshots/help/
```

Гейт: `uv lock --check`, ruff (с правилами безопасности `S`), ty, pytest с порогом
покрытия, снапшоты `--help`, форма `auth status`, контракты потребителей, сборка и установка
колеса во временный venv; `osv-scanner` и `gitleaks`, если они установлены.

Новый провайдер: модуль в `src/rb_context/providers/` с подклассом `SearchProvider`
(`name`, `required`, `search`, `health_check`) и строка в `PROVIDERS` (`providers/__init__.py`).

## Релиз

Версия — git-тег `vX.Y.Z`, строки `version =` в `pyproject.toml` нет. Релиз делает
`antagor publish` (гейт, `CHANGELOG.md`, тег, push); `CHANGELOG.md` руками не правится.

## Архитектура

Проект следует архитектуре шаблона `cli-generator`:

- `src/rb_context/commands/` — только разбор аргументов.
- `src/rb_context/core/` — сервисы, модели, ошибки.
- `src/rb_context/providers/` — Exa, Tavily, Brave, serp.
- `src/rb_context/credentials/` — ключи: связка ключей ОС и env.
- `src/rb_context/output/` — человеческий вывод и `--json`.

Памятка для агентов — `src/rb_context/data/SKILL.md`: `context skill install`
ставит её в AI-инструмент, `context --ai` печатает.
