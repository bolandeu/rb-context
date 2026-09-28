# Changelog

All notable changes to this project are documented here. Versions follow
[SemVer](https://semver.org/) (while at `0.x`, a minor bump may break).

Don't edit this file between releases: each change adds a fragment to
`changelog.d/` (`uv run towncrier create +<slug>.<type>.md -c "..."`, type
one of added/changed/deprecated/removed/fixed/security), and
`scripts/release.py` assembles them into a new section below the marker.

<!-- towncrier release notes start -->

## [0.2.2] - 2026-09-28

### Changed

- Шаблон cli-generator v1.2.10: внешний CLI serp объявлен в [[tool.rb.external]]; `context doctor` показывает проверку `external:serp`, подсказка установки serp — `uv tool install "rb-serp @ git+…@vX.Y.Z" --force`.


## [0.2.1] - 2026-09-28

### Changed

- Шаблон cli-generator v1.2.8: `auth status --check` ограничивает проверку 10 с таймаутом запроса самого провайдера (exa, brave, tavily — одна попытка), без фонового потока; подсказка при отсутствующем или старом serp — готовая команда `uv tool install --reinstall` с тегом.


## [0.2.0] - 2026-09-27

### Changed

- Провайдер `serp` требует CLI serp ≥ 0.4.0 (читает `auth status --json` в форме §8: `ok` и `credentials[].status`); нет serp или он старше — ошибка `DEPENDENCY_TOO_OLD` (exit 1) с командой установки/обновления вместо `PROVIDER_ERROR`.
- Шаблон cli-generator v1.2.0 и стандарт релизов: версия из git-тега, changelog из фрагментов, единый гейт `scripts/release.py --check`, контракт справки (`Example:` у каждой команды, снапшоты). **Ломающее:** `context auth status` теперь отдаёт отчёт §8 (`tool`, `version`, `checked_at`, `credentials[]` со `status`) вместо `{provider, authenticated}`, `--provider` необязателен, `--check` проверяет ключи вызовом API; exit 3, если не в порядке exa или неверен любой ключ (tavily и brave необязательны). Провайдеры создаются без ключа — ключ читается при первом запросе.


## [0.1.0] - 2026-09-27

### Added

- Каркас из шаблона cli-generator: пакет `rb-context`, команда `context`.
- `context search`: параллельный опрос Exa (SDK `exa-py`, хайлайты), Tavily (SDK
  `tavily-python`) и Brave (REST) с результатами в общем виде и `sources` по провайдерам;
  упавший провайдер не ломает ответ.
- Режимы поиска `--exa-mode` и `--tavily-mode`.
- `providers` в конфиге проекта — кого опрашивать без `--provider`.
- `auth login|logout|status --provider exa|tavily|brave`, `doctor` проверяет ключ каждого.
- Ошибка `QUOTA_EXCEEDED` (exit 5), когда у провайдера кончился баланс или лимит тарифа
  (Exa 402, Tavily 432/433, Brave 402 / 429 `QUOTA_LIMITED`); видна в `sources[].error`,
  а при отказе всех — в `error.errors` по каждому провайдеру.
- Провайдер `serp`: выдача Яндекса/Google со сниппетами через установленный CLI `serp`
  (`serp snippets --json`, без зависимости от `rb-serp`), `--serp-engine yandex|google|yandex,google` (по умолчанию yandex).

### Changed

- Без `--provider` опрашивается один провайдер (`exa`), а не все — чтобы не тратить лимиты;
  все сразу — `-p all` (в том числе в `providers` конфига проекта).
