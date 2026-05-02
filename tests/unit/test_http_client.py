from __future__ import annotations

import unittest

from jobindex_scraper.config import Settings
from jobindex_scraper.http.client import build_session


class HttpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            user_agent="test-agent",
            http_timeout_seconds=20.0,
            log_level="INFO",
            database_url=None,
            extraction_version="test",
        )

    def test_build_session_disables_transport_retries_when_requested(self) -> None:
        session = build_session(self.settings, retry_transport_errors=False)

        retry = session.adapters["https://"].max_retries
        self.assertEqual(retry.connect, 0)
        self.assertEqual(retry.read, 0)
        self.assertEqual(retry.other, 0)
        self.assertEqual(retry.status, 3)
        self.assertEqual(retry.total, 3)

    def test_build_session_keeps_transport_retries_enabled_by_default(self) -> None:
        session = build_session(self.settings)

        retry = session.adapters["https://"].max_retries
        self.assertEqual(retry.connect, 3)
        self.assertEqual(retry.read, 3)
        self.assertEqual(retry.other, 3)
        self.assertEqual(retry.status, 3)
        self.assertEqual(retry.total, 3)


if __name__ == "__main__":
    unittest.main()