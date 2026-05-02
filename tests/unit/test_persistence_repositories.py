from __future__ import annotations

import unittest

from jobindex_scraper.models import CategoryRecord
from jobindex_scraper.persistence.repositories import CategoryRepository, JobRepository


class _FakeCursor:
    def __init__(self, fetchone_results: list[object | None]) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fetchone_results = list(fetchone_results)
        self.closed = False

    def execute(self, sql: str, params: tuple[object, ...] | None = None):
        self.executed.append((sql, tuple(params or ())))
        return self

    def fetchone(self):
        if not self.fetchone_results:
            return None
        return self.fetchone_results.pop(0)

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


class RepositoryTests(unittest.TestCase):
    def test_category_upsert_inserts_missing_row(self) -> None:
        cursor = _FakeCursor([None, (7,)])
        repository = CategoryRepository(_FakeConnection(cursor))

        category_id = repository.upsert_category(
            CategoryRecord(
                category_key="subid_1",
                category_name="subid_1",
                listing_url="https://www.jobindex.dk/jobsoegning?subid=1",
            )
        )

        self.assertEqual(category_id, 7)
        self.assertEqual(len(cursor.executed), 3)
        self.assertIn("INSERT INTO categories", cursor.executed[1][0])
        self.assertTrue(cursor.closed)

    def test_job_upsert_returns_new_when_url_is_missing(self) -> None:
        cursor = _FakeCursor([None, (101,)])
        repository = JobRepository(_FakeConnection(cursor))

        result = repository.upsert_listing_job(
            canonical_job_url="https://www.jobindex.dk/jobannonce/a",
            source_host="www.jobindex.dk",
            listing_hash="hash-a",
        )

        self.assertEqual(result.job_id, 101)
        self.assertEqual(result.state, "new")
        self.assertIn("INSERT INTO jobs", cursor.executed[1][0])
        self.assertTrue(cursor.closed)

    def test_job_upsert_returns_changed_when_hash_differs(self) -> None:
        cursor = _FakeCursor([(101, "old-hash")])
        repository = JobRepository(_FakeConnection(cursor))

        result = repository.upsert_listing_job(
            canonical_job_url="https://www.jobindex.dk/jobannonce/a",
            source_host="www.jobindex.dk",
            listing_hash="new-hash",
        )

        self.assertEqual(result.job_id, 101)
        self.assertEqual(result.state, "changed")
        self.assertIn("UPDATE jobs", cursor.executed[1][0])
        self.assertIn("current_listing_hash", cursor.executed[1][0])

    def test_job_upsert_returns_unchanged_when_hash_matches(self) -> None:
        cursor = _FakeCursor([(101, "same-hash")])
        repository = JobRepository(_FakeConnection(cursor))

        result = repository.upsert_listing_job(
            canonical_job_url="https://www.jobindex.dk/jobannonce/a",
            source_host="www.jobindex.dk",
            listing_hash="same-hash",
        )

        self.assertEqual(result.job_id, 101)
        self.assertEqual(result.state, "unchanged")
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("SET last_seen_at = SYSUTCDATETIME()", cursor.executed[1][0])


if __name__ == "__main__":
    unittest.main()