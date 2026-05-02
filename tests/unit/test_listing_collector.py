from __future__ import annotations

import unittest

from requests import HTTPError

from jobindex_scraper.config import Settings
from jobindex_scraper.listing.collector import JobindexListingCollector
from jobindex_scraper.models import CategoryRecord


class _FakeResponse:
    def __init__(self, status_code: int, url: str, text: str = "") -> None:
        self.status_code = status_code
        self.url = url
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} Client Error", response=self)


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, timeout: float):
        self.calls.append((url, timeout))
        return self.responses.pop(0)


class ListingCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            user_agent="test-agent",
            http_timeout_seconds=20.0,
            log_level="INFO",
            database_url=None,
            extraction_version="test",
        )
        self.category = CategoryRecord(
            category_key="subid_5",
            category_name="subid_5",
            listing_url="https://www.jobindex.dk/jobsoegning?subid=5",
        )

    def test_collect_pages_returns_empty_list_for_missing_category(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    status_code=404,
                    url="https://www.jobindex.dk/jobsoegning?subid=5",
                )
            ]
        )
        collector = JobindexListingCollector(settings=self.settings, session=session)

        page_results = collector.collect_pages(category=self.category, max_pages=3)

        self.assertEqual(page_results, [])
        self.assertEqual(
            session.calls,
            [("https://www.jobindex.dk/jobsoegning?subid=5", 20.0)],
        )

    def test_collect_pages_reraises_non_404_http_errors(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    status_code=500,
                    url="https://www.jobindex.dk/jobsoegning?subid=5",
                )
            ]
        )
        collector = JobindexListingCollector(settings=self.settings, session=session)

        with self.assertRaises(HTTPError):
            collector.collect_pages(category=self.category, max_pages=1)


if __name__ == "__main__":
    unittest.main()