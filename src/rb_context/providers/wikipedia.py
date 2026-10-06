from __future__ import annotations

from ..core.models import SearchHit, extract_domain
from .base import Health, SearchProvider
from .http import HttpProvider

# С `exintro` MediaWiki отдаёт вводные абзацы не больше чем для 20 страниц за запрос.
MAX_PAGES = 20
EXTRACT_CHARS = 700


class WikipediaProvider(HttpProvider, SearchProvider):
    """Википедия через MediaWiki API: поиск статей, сниппет — вводный абзац. Режим — язык раздела."""

    name = "wikipedia"
    summary = "Википедия — определения и факты (ru, en), без ключа"
    modes = ("ru", "en")  # первый — по умолчанию
    base_url = "https://ru.wikipedia.org"
    needs_api_key = False
    credential_fields = ()
    required = False

    @classmethod
    def check(cls) -> tuple[bool, str | None]:
        return True, None  # ключа нет — проверять нечего

    def _api(self, lang: str) -> str:
        return f"https://{lang}.wikipedia.org/w/api.php"

    def health_check(self) -> Health:
        """`meta=siteinfo` — открытое чтение, ничего не тратит."""
        self.probe(self._api(self.modes[0]), params={"action": "query", "meta": "siteinfo", "format": "json"})
        return Health()

    def search(self, query: str, *, limit: int, mode: str | None = None) -> list[SearchHit]:
        data = self.get_json(
            self._api(mode or self.modes[0]),
            action="query",
            generator="search",
            gsrsearch=query,
            gsrlimit=min(limit, MAX_PAGES),
            prop="extracts|info",
            exintro=1,
            explaintext=1,
            exchars=EXTRACT_CHARS,
            exlimit="max",
            inprop="url",
            format="json",
            formatversion=2,
        )
        pages = sorted((data.get("query") or {}).get("pages") or [], key=lambda page: page.get("index", 0))
        return [
            SearchHit(
                provider=self.name,
                query=query,
                position=position,
                url=page["fullurl"],
                domain=extract_domain(page["fullurl"]),
                title=page.get("title") or "",
                snippet=(page.get("extract") or "").strip(),
                published=page.get("touched"),
            )
            for position, page in enumerate(pages, start=1)
        ]
