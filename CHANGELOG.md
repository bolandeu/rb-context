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
