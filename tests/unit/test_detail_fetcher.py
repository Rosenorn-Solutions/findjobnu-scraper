from __future__ import annotations

from types import SimpleNamespace
import unittest
from uuid import uuid4

import requests

from jobindex_scraper.config import Settings
from jobindex_scraper.detail.fetcher import JobDetailFetcher
from jobindex_scraper.models import DetailFetchTask


class _FakeResponse:
    def __init__(self, url: str, status_code: int, content: bytes) -> None:
        self.url = url
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8")


class _FakeSession:
    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, timeout: float):
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class DetailFetcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            user_agent="test-agent",
            http_timeout_seconds=10.0,
            log_level="INFO",
            database_url=None,
            extraction_version="2026.05.02",
        )
        self.task = DetailFetchTask(
            scrape_run_id=uuid4(),
            job_id=101,
            canonical_job_url="https://example.com/job/123",
            source_host="example.com",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Example Job",
            company_name_raw="Example Company",
            company_url_raw=None,
            location_raw="Odense",
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="a" * 64,
            detail_refresh_reason="new",
        )

    def test_fetch_task_hashes_successful_response(self) -> None:
        response = _FakeResponse(
            url="https://example.com/job/123",
            status_code=200,
            content=b"<html>detail body</html>",
        )
        session = _FakeSession(response=response)
        fetcher = JobDetailFetcher(settings=self.settings, session=session)

        result = fetcher.fetch_task(self.task)

        self.assertEqual(session.calls, [(self.task.canonical_job_url, 10.0)])
        self.assertEqual(result.http_status, 200)
        self.assertIsNone(result.error_message)
        self.assertEqual(result.html_content, "<html>detail body</html>")
        self.assertEqual(
            result.detail_html_hash,
            "eb7c157d4f4b91add6cdf88d3f770b8a26048cd6468018191c1c1fffbe76ab43",
        )

    def test_fetch_task_records_request_failure(self) -> None:
        session = _FakeSession(error=requests.RequestException("connection dropped"))
        fetcher = JobDetailFetcher(settings=self.settings, session=session)

        result = fetcher.fetch_task(self.task)

        self.assertIsNone(result.http_status)
        self.assertIsNone(result.detail_html_hash)
        self.assertIsNone(result.html_content)
        self.assertEqual(result.error_message, "connection dropped")


if __name__ == "__main__":
    unittest.main()