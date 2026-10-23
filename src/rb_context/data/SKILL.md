---
name: context
description: Веб-поиск как контекст для LLM через CLI `context` — провайдеры Exa, Tavily, Brave и выдача Яндекса/Google (через CLI serp); каждый результат с URL, заголовком и текстом-сниппетом (хайлайты Exa, выжимка Tavily, описание Brave, сниппет выдачи). Использовать, когда задаче нужны свежие данные из интернета, источники по теме или ответ, которого нет в знаниях модели (web search, research, найти в интернете, актуальная информация). Здесь — установка, --json, коды выхода, ключи.
---

# context

Всё про конкретные команды есть в самом CLI: `context` без аргументов —
версия и список команд, `context <команда> --help` — подробности и примеры.
Этот документ — только то, чего `--help` не скажет. Если CLI запускать
можно, а файлы читать нельзя, этот же текст печатает `context --ai`.

## Установка (если `context --version` не работает)

```bash
uv tool install rb-context --index https://homeserver.tailee01ab.ts.net:3000/api/packages/bolandeu/pypi/simple
```

From the git tag instead:

```bash
uv tool install "rb-context @ git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/context.git@vX.Y.Z"
```

Replace `vX.Y.Z` with the latest release tag (install from a tag, never a
branch: [the Standard](https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md), Install).

Одинаково на macOS, Linux и Windows; обновление — `uv tool upgrade rb-context`.
Из исходников не запускать, если не просили разрабатывать сам CLI.

## Правила

- **`--json` у каждой команды.** Разбирать stdout, не человеческий вывод.
  stdout — только данные, stderr — диагностика.
- **Каждый опрошенный провайдер тратит свой лимит.** Без `-p` опрашивается
  один — `exa` (или `providers` из конфига проекта). Нужен другой — `-p tavily`,
  несколько — `-p exa,serp`, все — `-p all`, только если задаче правда нужны все.
  Выдача Яндекса/Google — `-p serp` (Яндекс; Google — `--serp-engine google`, оба — `yandex,google`).
  Бесплатно и без ключа: `-p hackernews` (обсуждения), `-p wikipedia` (определения;
  `--wikipedia-lang en`), `-p github` (репозитории; `--github-mode issues|code`, code — только с токеном).
- **Выбранные опрашиваются параллельно.** Упавший провайдер не ломает
  ответ: `ok: true`, а его ошибка — в `sources[].error`. Проверяй `sources`,
  если результатов меньше, чем ждал.
- **Проект необязателен.** Свой набор по умолчанию — `context init
  --non-interactive`, затем `context config set providers exa,serp`.
- **serp — отдельный CLI.** `rb-serp` не зависимость context: провайдер `serp`
  вызывает установленную команду `serp` не старше 0.7.2. Нет или старая —
  ошибка `DEPENDENCY_TOO_OLD` с командой установки/обновления в `action`; ключи serp — `serp auth login`, не `context auth login`.
- **`--non-interactive`** на всём, что может спросить: вместо зависания —
  структурированная ошибка.
- **Ключи** — в связке ключей ОС или env `CONTEXT_<PROVIDER>_API_KEY`
  (`CONTEXT_EXA_API_KEY`, `CONTEXT_TAVILY_API_KEY`, `CONTEXT_BRAVE_API_KEY`;
  у serp — свои, см. выше),
  никогда в аргументах или конфиге. Проверка — `context auth status --check --json`
  (откуда каждый ключ и работает ли, без значений; exit 3 — не в порядке exa
  или неверен любой; tavily и brave необязательны) или `context doctor --json`;
  никогда не проси пользователя вставить ключ в командную строку.
- **Стоимость.** Exa, Tavily, Brave — бесплатные месячные лимиты: каждый
  запрос тратит лимит (`sources[].billable_requests`), cost 0
  (`cost_source: "free_tier"`); serp платный (рубли, `cost_total`). Глубокие
  режимы (`--exa-mode deep*`, `--tavily-mode advanced`) тратят больше — только
  когда обычный поиск не дал нужного. `auth status --check` с brave тратит
  1 запрос его лимита — не запускать по расписанию.
- **`doctor --json`** первым, если что-то не так: версия, проект, настройки,
  готовность ключей и внешние программы.
- **`describe --json`** — весь CLI одним документом OpenCLI (команды, опции,
  exit-коды, env, данные): голый документ, без конверта `{"ok": ...}`.

## Ошибки

Конверт ошибки: `{"ok": false, "error": {"code", "message", "action"}}`.
Порядок чтения: код выхода → `error.code` → `error.action` (конкретная следующая команда).

    0  ok (в том числе, если часть провайдеров упала — см. sources)
    1  общая (UNEXPECTED — баг: повторить с --verbose и сообщить)
    2  неверные аргументы (неизвестный провайдер, режим не того провайдера)
    3  нужен ключ          → context auth login --provider <имя>
    4  проект не инициализирован → context init
    5  сбой провайдера (все опрошенные не ответили):
         PROVIDER_ERROR  — сеть / сервис / частота запросов → повторить позже
         QUOTA_EXHAUSTED — исчерпан бесплатный лимит → НЕ повторять, сказать пользователю
    6  CLI старее, чем требует проект → uv tool upgrade rb-context

Если не ответил никто из нескольких провайдеров, в `error.errors` — ошибка
каждого (`provider`, `code`, `message`). При частичном отказе (exit 0) те же
ошибки — в `sources[].error`: `QUOTA_EXHAUSTED` там значит, что лимит этого
провайдера исчерпан и он будет отказывать до нового периода лимита — сообщи
пользователю и не включай его в следующие запросы (`-p` без него).

Автоматически повторять имеет смысл только `PROVIDER_ERROR` (exit 5).
