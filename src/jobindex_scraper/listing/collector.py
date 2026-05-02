from __future__ import annotations

import logging

from requests import HTTPError, Session

from ..config import Settings
from ..http.client import build_session
from ..models import CategoryRecord, ListingPageResult
from .jobindex_parser import parse_jobindex_listing_page


logger = logging.getLogger(__name__)


class JobindexListingCollector:
    def __init__(self, settings: Settings, session: Session | None = None) -> None:
        self.settings = settings
        self.session = session or build_session(settings)

    def collect_pages(self, category: CategoryRecord, max_pages: int = 1) -> list[ListingPageResult]:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        page_results: list[ListingPageResult] = []
        next_page_url = category.listing_url
        visited_urls: set[str] = set()

        for _ in range(max_pages):
            if next_page_url in visited_urls:
                break

            visited_urls.add(next_page_url)
            response = self.session.get(next_page_url, timeout=self.settings.http_timeout_seconds)
            try:
                response.raise_for_status()
            except HTTPError:
                if response.status_code == 404:
                    logger.warning(
                        "Skipping unavailable Jobindex category page %s for %s",
                        next_page_url,
                        category.category_key,
                    )
                    break
                raise

            page_result = parse_jobindex_listing_page(
                html_content=response.text,
                category=category,
                page_url=response.url,
            )
            logger.info(
                "Collected %s listing observations from %s",
                len(page_result.observations),
                response.url,
            )
            page_results.append(page_result)

            if not page_result.next_page_url:
                break
            next_page_url = page_result.next_page_url

        return page_results
