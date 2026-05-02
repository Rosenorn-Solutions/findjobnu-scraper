from __future__ import annotations

from datetime import datetime, timezone
import unittest
from uuid import uuid4

from jobindex_scraper.config import Settings
from jobindex_scraper.models import (
    DetailExtractionFailure,
    DetailExtractionPersistenceResult,
    DetailFetchResult,
    ExtractedDetail,
    JobUpsertResult,
    ListingObservation,
    ScrapeRunRecord,
)
from jobindex_scraper.persistence.ddl import read_init_sql
from jobindex_scraper.persistence.pool import PersistenceConfigurationError
from jobindex_scraper.persistence.writer import PersistenceWriter


class _FakeConnection:
    def __init__(self) -> None:
        self.commit_count = 0
        self.closed = False
        self.rollback_count = 0

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.closed = True


class _FakeRunRepository:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str | None]] = []
        self.finished: list[tuple[object, str, str | None]] = []

    def create_run(
        self,
        extraction_version: str,
        config_fingerprint: str,
        notes: str | None = None,
    ) -> ScrapeRunRecord:
        self.created.append((extraction_version, config_fingerprint, notes))
        return ScrapeRunRecord(
            scrape_run_id=uuid4(),
            started_at=datetime.now(timezone.utc),
            status="running",
            extraction_version=extraction_version,
        )

    def finish_run(self, scrape_run_id: object, status: str, notes: str | None = None) -> None:
        self.finished.append((scrape_run_id, status, notes))


class _UnusedRepository:
    def __init__(self) -> None:
        self.calls = 0

    def record_event(self, *args, **kwargs) -> None:
        self.calls += 1


class _FakeJobRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.detail_calls: list[tuple[int, int | None]] = []
        self.snapshot_calls: list[tuple[int, int]] = []
        self.results = [
            JobUpsertResult(job_id=101, state="new"),
            JobUpsertResult(job_id=102, state="unchanged"),
            JobUpsertResult(job_id=103, state="changed"),
        ]

    def upsert_listing_job(
        self,
        canonical_job_url: str,
        source_host: str,
        listing_hash: str,
    ) -> JobUpsertResult:
        self.calls.append((canonical_job_url, source_host, listing_hash))
        return self.results.pop(0)

    def record_detail_fetch_outcome(self, job_id: int, http_status: int | None) -> None:
        self.detail_calls.append((job_id, http_status))

    def set_current_snapshot(self, job_id: int, job_snapshot_id: int) -> None:
        self.snapshot_calls.append((job_id, job_snapshot_id))


class _FakeJobCategoryRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def link_job_category(self, job_id: int, category_id: int) -> None:
        self.calls.append((job_id, category_id))


class _FakeObservationRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[object, int, int, ListingObservation]] = []

    def record_observation(
        self,
        scrape_run_id: object,
        job_id: int,
        category_id: int,
        observation: ListingObservation,
    ) -> None:
        self.calls.append((scrape_run_id, job_id, category_id, observation))


class _FakeEventRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_event(
        self,
        scrape_run_id: object,
        stage: str,
        event: str,
        status: str,
        canonical_job_url: str | None = None,
        source_host: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.calls.append(
            {
                "scrape_run_id": scrape_run_id,
                "stage": stage,
                "event": event,
                "status": status,
                "canonical_job_url": canonical_job_url,
                "source_host": source_host,
                "details": details,
            }
        )


class _FakeSnapshotRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[ExtractedDetail, str]] = []
        self._next_snapshot_id = 500

    def upsert_snapshot(self, extracted_detail: ExtractedDetail, extraction_version: str) -> int:
        self.calls.append((extracted_detail, extraction_version))
        self._next_snapshot_id += 1
        return self._next_snapshot_id


class PersistenceWriterTests(unittest.TestCase):
    def test_start_run_commits_and_uses_config_fingerprint(self) -> None:
        connection = _FakeConnection()
        run_repository = _FakeRunRepository()
        writer = PersistenceWriter(
            connection=connection,
            run_repository=run_repository,
            category_repository=_UnusedRepository(),
            job_repository=_UnusedRepository(),
            event_repository=_UnusedRepository(),
        )
        settings = Settings(
            user_agent="test-agent",
            http_timeout_seconds=10.0,
            log_level="INFO",
            database_url=(
                "Driver={ODBC Driver 18 for SQL Server};"
                "Server=localhost,1433;"
                "Database=test;Uid=sa;Pwd=secret;"
                "Encrypt=yes;TrustServerCertificate=yes;"
            ),
            extraction_version="2026.05.01",
        )

        scrape_run = writer.start_run(settings=settings)

        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(scrape_run.status, "running")
        self.assertEqual(len(run_repository.created), 1)
        self.assertEqual(run_repository.created[0][0], "2026.05.01")
        self.assertEqual(run_repository.created[0][1], settings.config_fingerprint())

    def test_persist_listing_observations_batches_job_and_observation_writes(self) -> None:
        connection = _FakeConnection()
        job_repository = _FakeJobRepository()
        job_category_repository = _FakeJobCategoryRepository()
        observation_repository = _FakeObservationRepository()
        writer = PersistenceWriter(
            connection=connection,
            run_repository=_FakeRunRepository(),
            category_repository=_UnusedRepository(),
            job_repository=job_repository,
            job_category_repository=job_category_repository,
            observation_repository=observation_repository,
            event_repository=_UnusedRepository(),
        )
        scrape_run_id = uuid4()
        observations = [
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=1,
                job_url_raw="/jobannonce/a",
                canonical_job_url="https://www.jobindex.dk/jobannonce/a",
                source_host="www.jobindex.dk",
                job_title_raw="Job A",
                company_name_raw="Company A",
                company_url_raw=None,
                location_raw="Odense",
                published_raw="2026-05-01T10:00:00+02:00",
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="hash-a",
            ),
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1&page=2",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=3,
                job_url_raw="/jobannonce/a",
                canonical_job_url="https://www.jobindex.dk/jobannonce/a",
                source_host="www.jobindex.dk",
                job_title_raw="Job A",
                company_name_raw="Company A",
                company_url_raw=None,
                location_raw="Odense",
                published_raw="2026-05-01T10:00:00+02:00",
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="hash-a-2",
            ),
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1&page=2",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=4,
                job_url_raw="/jobannonce/b",
                canonical_job_url="https://www.jobindex.dk/jobannonce/b",
                source_host="karnovgroupdenmark.teamtailor.com",
                job_title_raw="Job B",
                company_name_raw="Company B",
                company_url_raw="https://example.com/company-b",
                location_raw="Aarhus",
                published_raw=None,
                banner_image_url_raw="https://cdn.example.com/banner-b.png",
                footer_image_url_raw=None,
                listing_hash="hash-b",
            ),
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1&page=3",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=7,
                job_url_raw="/jobannonce/c",
                canonical_job_url="https://www.jobindex.dk/jobannonce/c",
                source_host="boards.greenhouse.io",
                job_title_raw="Job C",
                company_name_raw="Company C",
                company_url_raw=None,
                location_raw="Copenhagen",
                published_raw=None,
                banner_image_url_raw=None,
                footer_image_url_raw="https://cdn.example.com/footer-c.png",
                listing_hash="hash-c",
            ),
        ]

        result = writer.persist_listing_observations(
            scrape_run_id=scrape_run_id,
            category_id=7,
            observations=observations,
        )

        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(result.jobs_touched, 3)
        self.assertEqual(result.changed_jobs, 1)
        self.assertEqual(len(result.detail_tasks), 2)
        self.assertEqual(result.detail_tasks[0].canonical_job_url, "https://www.jobindex.dk/jobannonce/a")
        self.assertEqual(result.detail_tasks[0].detail_refresh_reason, "new")
        self.assertEqual(result.detail_tasks[1].canonical_job_url, "https://www.jobindex.dk/jobannonce/c")
        self.assertEqual(result.detail_tasks[1].detail_refresh_reason, "changed")
        self.assertEqual(result.new_jobs, 1)
        self.assertEqual(result.observations_written, 4)
        self.assertEqual(result.unchanged_jobs, 1)
        self.assertEqual(
            job_repository.calls,
            [
                ("https://www.jobindex.dk/jobannonce/a", "www.jobindex.dk", "hash-a"),
                (
                    "https://www.jobindex.dk/jobannonce/b",
                    "karnovgroupdenmark.teamtailor.com",
                    "hash-b",
                ),
                (
                    "https://www.jobindex.dk/jobannonce/c",
                    "boards.greenhouse.io",
                    "hash-c",
                ),
            ],
        )
        self.assertEqual(job_category_repository.calls, [(101, 7), (102, 7), (103, 7)])
        self.assertEqual(len(observation_repository.calls), 4)

    def test_persist_detail_fetch_results_updates_jobs_and_records_events(self) -> None:
        connection = _FakeConnection()
        job_repository = _FakeJobRepository()
        event_repository = _FakeEventRepository()
        writer = PersistenceWriter(
            connection=connection,
            run_repository=_FakeRunRepository(),
            category_repository=_UnusedRepository(),
            job_repository=job_repository,
            job_category_repository=_UnusedRepository(),
            observation_repository=_UnusedRepository(),
            event_repository=event_repository,
        )
        scrape_run_id = uuid4()
        results = [
            DetailFetchResult(
                scrape_run_id=scrape_run_id,
                job_id=101,
                canonical_job_url="https://www.jobindex.dk/jobannonce/a",
                source_host="www.jobindex.dk",
                response_url="https://www.jobindex.dk/jobannonce/a",
                http_status=200,
                fetched_at=datetime.now(timezone.utc),
                elapsed_ms=120,
                detail_html_hash="d" * 64,
                detail_refresh_reason="new",
                error_message=None,
                html_content="<html><body>ok</body></html>",
            ),
            DetailFetchResult(
                scrape_run_id=scrape_run_id,
                job_id=103,
                canonical_job_url="https://www.jobindex.dk/jobannonce/c",
                source_host="boards.greenhouse.io",
                response_url=None,
                http_status=None,
                fetched_at=datetime.now(timezone.utc),
                elapsed_ms=50,
                detail_html_hash=None,
                detail_refresh_reason="changed",
                error_message="connection dropped",
                html_content=None,
            ),
        ]

        result = writer.persist_detail_fetch_results(results)

        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(result.tasks_fetched, 2)
        self.assertEqual(result.fetch_succeeded, 1)
        self.assertEqual(result.fetch_failed, 1)
        self.assertEqual(job_repository.detail_calls, [(101, 200), (103, None)])
        self.assertEqual(len(event_repository.calls), 2)
        self.assertEqual(event_repository.calls[0]["event"], "detail_fetch_succeeded")
        self.assertEqual(event_repository.calls[1]["event"], "detail_fetch_failed")
        self.assertEqual(event_repository.calls[1]["status"], "error")

    def test_persist_extracted_details_writes_snapshot_and_updates_current_pointer(self) -> None:
        connection = _FakeConnection()
        job_repository = _FakeJobRepository()
        snapshot_repository = _FakeSnapshotRepository()
        event_repository = _FakeEventRepository()
        writer = PersistenceWriter(
            connection=connection,
            run_repository=_FakeRunRepository(),
            category_repository=_UnusedRepository(),
            job_repository=job_repository,
            job_category_repository=_UnusedRepository(),
            observation_repository=_UnusedRepository(),
            snapshot_repository=snapshot_repository,
            event_repository=event_repository,
        )
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
            job_description_raw="Build data products",
            job_description_clean="Build data products",
            description_text_hash="c" * 64,
            field_provenance={"job_description_clean": "detail_page"},
            extraction_warnings=[],
            detail_refresh_reason="new",
        )

        result = writer.persist_extracted_details(
            extracted_details=(extracted_detail,),
            extraction_version="2026.05.02",
        )

        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(result.snapshots_written, 1)
        self.assertEqual(result.extraction_failed, 0)
        self.assertEqual(len(snapshot_repository.calls), 1)
        self.assertEqual(snapshot_repository.calls[0][1], "2026.05.02")
        self.assertEqual(job_repository.snapshot_calls, [(101, 501)])
        self.assertEqual(event_repository.calls[0]["event"], "snapshot_written")

    def test_persist_extracted_details_records_failure_events(self) -> None:
        connection = _FakeConnection()
        event_repository = _FakeEventRepository()
        writer = PersistenceWriter(
            connection=connection,
            run_repository=_FakeRunRepository(),
            category_repository=_UnusedRepository(),
            job_repository=_FakeJobRepository(),
            job_category_repository=_UnusedRepository(),
            observation_repository=_UnusedRepository(),
            snapshot_repository=_FakeSnapshotRepository(),
            event_repository=event_repository,
        )
        failure = DetailExtractionFailure(
            scrape_run_id=uuid4(),
            job_id=101,
            canonical_job_url="https://example.com/jobs/1",
            source_host="example.com",
            detail_html_hash="f" * 64,
            detail_refresh_reason="new",
            error_message="Detail extraction produced no snapshot.",
        )

        result = writer.persist_extracted_details(
            extracted_details=(),
            extraction_version="2026.05.02",
            failures=(failure,),
        )

        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(result.snapshots_written, 0)
        self.assertEqual(result.extraction_failed, 1)
        self.assertEqual(len(event_repository.calls), 1)
        self.assertEqual(event_repository.calls[0]["event"], "detail_extract_failed")
        self.assertEqual(event_repository.calls[0]["status"], "warning")

    def test_rollback_calls_connection_rollback(self) -> None:
        connection = _FakeConnection()
        writer = PersistenceWriter(
            connection=connection,
            run_repository=_FakeRunRepository(),
            category_repository=_UnusedRepository(),
            job_repository=_UnusedRepository(),
            job_category_repository=_UnusedRepository(),
            observation_repository=_UnusedRepository(),
            event_repository=_UnusedRepository(),
        )

        writer.rollback()

        self.assertEqual(connection.rollback_count, 1)

    def test_finish_run_rejects_unknown_status(self) -> None:
        writer = PersistenceWriter(
            connection=_FakeConnection(),
            run_repository=_FakeRunRepository(),
            category_repository=_UnusedRepository(),
            job_repository=_UnusedRepository(),
            job_category_repository=_UnusedRepository(),
            observation_repository=_UnusedRepository(),
            event_repository=_UnusedRepository(),
        )

        with self.assertRaises(ValueError):
            writer.finish_run(scrape_run_id=uuid4(), status="unknown")

    def test_from_settings_requires_database_url(self) -> None:
        settings = Settings(
            user_agent="test-agent",
            http_timeout_seconds=10.0,
            log_level="INFO",
            database_url=None,
            extraction_version="2026.05.01",
        )

        with self.assertRaises(PersistenceConfigurationError):
            PersistenceWriter.from_settings(settings)

    def test_read_init_sql_contains_scrape_runs_table(self) -> None:
        ddl = read_init_sql()

        self.assertIn("CREATE TABLE scrape_runs", ddl)
        self.assertIn("CREATE TABLE categories", ddl)
        self.assertIn("current_listing_hash", ddl)
        self.assertIn("SYSUTCDATETIME", ddl)
        self.assertNotIn("ON CONFLICT", ddl)


if __name__ == "__main__":
    unittest.main()