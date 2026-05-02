from __future__ import annotations

from datetime import datetime, timezone
import unittest
from uuid import uuid4

from jobindex_scraper.models import CategoryRecord, ExtractedDetail
from jobindex_scraper.persistence.repositories import (
    CategoryRepository,
    JobImageRepository,
    JobRepository,
    SnapshotRepository,
)


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
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("INSERT INTO categories", cursor.executed[1][0])
        self.assertIn("OUTPUT INSERTED.category_id", cursor.executed[1][0])
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
        self.assertIn("OUTPUT INSERTED.job_id", cursor.executed[1][0])
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

    def test_job_image_upsert_inserts_missing_row(self) -> None:
        cursor = _FakeCursor([None, (901,)])
        repository = JobImageRepository(_FakeConnection(cursor))

        job_image_id = repository.upsert_image(
            job_id=101,
            image_role="banner",
            source_url="https://www.jobindex.dk/img/banner.png",
            content_type="image/png",
            image_bytes=b"banner-bytes",
        )

        self.assertEqual(job_image_id, 901)
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("INSERT INTO job_images", cursor.executed[1][0])
        self.assertIn("OUTPUT INSERTED.job_image_id", cursor.executed[1][0])

    def test_snapshot_upsert_includes_image_ids_on_insert(self) -> None:
        cursor = _FakeCursor([None, (501,)])
        repository = SnapshotRepository(_FakeConnection(cursor))
        extracted_detail = ExtractedDetail(
            scrape_run_id=uuid4(),
            job_id=101,
            canonical_job_url="https://example.com/jobs/1",
            source_host="example.com",
            listing_hash="a" * 64,
            detail_html_hash="b" * 64,
            job_title_raw="Senior Platform Engineer",
            job_title_normalized="Senior Platform Engineer",
            company_name_raw="Example Company",
            company_name_normalized="Example Company",
            company_url_raw="https://example.com",
            company_url_normalized="https://example.com",
            location_raw="Odense",
            location_normalized="Odense",
            published_raw="2026-05-02T09:00:00+02:00",
            published_utc=datetime.now(timezone.utc),
            banner_image_url_raw="/img/banner.png",
            footer_image_url_raw="https://cdn.example.com/footer.png",
            job_description_raw="Build data products",
            job_description_clean="Build data products",
            description_text_hash="c" * 64,
            field_provenance={"job_description_clean": "detail_page"},
            extraction_warnings=[],
            detail_refresh_reason="new",
        )

        job_snapshot_id = repository.upsert_snapshot(
            extracted_detail=extracted_detail,
            extraction_version="2026.05.02",
            banner_image_id=701,
            footer_image_id=702,
        )

        self.assertEqual(job_snapshot_id, 501)
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("INSERT INTO job_snapshots", cursor.executed[1][0])
        self.assertIn("banner_image_id", cursor.executed[1][0])
        self.assertIn("footer_image_id", cursor.executed[1][0])
        self.assertEqual(cursor.executed[1][1][-4:-2], (701, 702))


if __name__ == "__main__":
    unittest.main()