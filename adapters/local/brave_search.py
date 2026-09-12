"""Brave Web Search adapter with a fixed endpoint and bounded responses."""

import asyncio
import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import ValidationError

from youth_compass.domain.errors import WebSearchError
from youth_compass.ports import WebSearchRequest, WebSearchResult

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_MAX_RESPONSE_BYTES = 1_000_000


class BraveWebSearchProvider:
    """Query Brave's independent web index; never fetch result URLs."""

    def __init__(self, api_key: str, *, timeout_seconds: float = 10.0) -> None:
        if not api_key.strip():
            raise ValueError("Brave Search API key must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("web-search timeout must be positive")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchResult, ...]:
        return await asyncio.to_thread(self._search_sync, request)

    def _search_sync(self, request: WebSearchRequest) -> tuple[WebSearchResult, ...]:
        params: dict[str, str | int] = {
            "q": request.query,
            "count": request.count,
            "text_decorations": "false",
            "result_filter": "web",
        }
        if request.country:
            params["country"] = request.country
        if request.search_lang:
            params["search_lang"] = request.search_lang
        if request.freshness:
            params["freshness"] = request.freshness
        http_request = Request(
            f"{_ENDPOINT}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self._api_key,
                "User-Agent": "YouthCompass/0.1",
            },
        )
        try:
            # The request URL is assembled from the fixed HTTPS endpoint above.
            with urlopen(http_request, timeout=self._timeout_seconds) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise WebSearchError("Brave Web Search request failed") from exc
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise WebSearchError("Brave Web Search response exceeded the size limit")
        try:
            raw = json.loads(payload)
            items = raw.get("web", {}).get("results", [])
            if not isinstance(items, list):
                raise TypeError("web.results is not a list")
            results: list[WebSearchResult] = []
            seen_urls: set[str] = set()
            for item in items[: request.count]:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                title = item.get("title")
                if not isinstance(url, str) or not isinstance(title, str) or url in seen_urls:
                    continue
                published_at = _parse_datetime(item.get("page_age"))
                result = WebSearchResult(
                    title=title.strip(),
                    url=url,
                    description=str(item.get("description") or "").strip(),
                    published_at=published_at,
                )
                results.append(result)
                seen_urls.add(url)
            return tuple(results)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
            raise WebSearchError("Brave Web Search returned an invalid response") from exc


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
