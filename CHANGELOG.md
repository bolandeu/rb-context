# Changelog

All notable changes to this project are documented here. The format is
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/). `scripts/release.py` moves the Unreleased
section under a new version heading — add entries here as you go, don't
write them at release time.

## [Unreleased]

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
  (`serp snippets --json`, без зависимости от `rb-serp`), `--serp-engine yandex|google` (по умолчанию yandex).

### Changed

- Без `--provider` опрашивается один провайдер (`exa`), а не все — чтобы не тратить лимиты;
  все сразу — `-p all` (в том числе в `providers` конфига проекта).
