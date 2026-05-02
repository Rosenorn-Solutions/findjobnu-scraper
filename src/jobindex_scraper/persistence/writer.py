from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

import requests

from ..catalog import JOBINDEX_BASE_URL
from ..config import Settings
from ..http.client import build_session
from ..models import (
    CategoryRecord,
    DetailExtractionFailure,
    DetailExtractionPersistenceResult,
    DetailFetchPersistenceResult,
    DetailFetchResult,
    DetailFetchTask,
    ExtractedDetail,
    JobUpsertResult,
    ListingObservation,
    ListingPersistenceResult,
    ScrapeRunRecord,
)
from .pool import PersistenceConfigurationError, connect
from .repositories import (
    CategoryRepository,
    EventRepository,
    JobCategoryRepository,
    JobImageRepository,
    JobRepository,
    ObservationRepository,
    RunRepository,
    SnapshotRepository,
)


_VALID_RUN_STATUSES = {"running", "completed", "failed", "cancelled"}


class PersistenceWriter:
    def __init__(
        self,
        connection: Any,
        run_repository: RunRepository | None = None,
        category_repository: CategoryRepository | None = None,
        job_repository: JobRepository | None = None,
        job_category_repository: JobCategoryRepository | None = None,
        observation_repository: ObservationRepository | None = None,
        snapshot_repository: SnapshotRepository | None = None,
        job_image_repository: JobImageRepository | None = None,
        event_repository: EventRepository | None = None,
        image_session: Any | None = None,
        image_timeout_seconds: float = 20.0,
    ) -> None:
        self.connection = connection
        self.run_repository = run_repository or RunRepository(connection)
        self.category_repository = category_repository or CategoryRepository(connection)
        self.job_repository = job_repository or JobRepository(connection)
        self.job_category_repository = job_category_repository or JobCategoryRepository(connection)
        self.observation_repository = observation_repository or ObservationRepository(connection)
        self.snapshot_repository = snapshot_repository or SnapshotRepository(connection)
        self.job_image_repository = job_image_repository or JobImageRepository(connection)
        self.event_repository = event_repository or EventRepository(connection)
        self.image_session = image_session
        self.image_timeout_seconds = image_timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "PersistenceWriter":
        if not settings.database_url:
            raise PersistenceConfigurationError(
                "JOBINDEX_SCRAPER_DATABASE_URL must be set when --record-run is used. Provide a SQL Server ODBC connection string or omit --record-run for stats-only runs such as --dump-referral-stats."
            )
        return cls(
            connection=connect(settings.database_url),
            image_session=build_session(settings, retry_transport_errors=False),
            image_timeout_seconds=settings.http_timeout_seconds,
        )

    def start_run(self, settings: Settings, notes: str | None = None) -> ScrapeRunRecord:
        scrape_run = self.run_repository.create_run(
            extraction_version=settings.extraction_version,
            config_fingerprint=settings.config_fingerprint(),
            notes=notes,
        )
        self.connection.commit()
        return scrape_run

    def finish_run(self, scrape_run_id: UUID, status: str, notes: str | None = None) -> None:
        if status not in _VALID_RUN_STATUSES:
            raise ValueError(f"Unsupported scrape run status: {status}")
        self.run_repository.finish_run(scrape_run_id=scrape_run_id, status=status, notes=notes)
        self.connection.commit()

    def ensure_category(self, category: CategoryRecord) -> int:
        category_id = self.category_repository.upsert_category(category)
        self.connection.commit()
        return category_id

    def touch_job(self, canonical_job_url: str, source_host: str) -> int:
        job_id = self.job_repository.touch_job(
            canonical_job_url=canonical_job_url,
            source_host=source_host,
        )
        self.connection.commit()
        return job_id

    def persist_listing_observations(
        self,
        scrape_run_id: UUID,
        category_id: int,
        observations: Sequence[ListingObservation],
    ) -> ListingPersistenceResult:
        if not observations:
            return ListingPersistenceResult(
                jobs_touched=0,
                changed_jobs=0,
                new_jobs=0,
                observations_written=0,
                unchanged_jobs=0,
                detail_tasks=(),
            )

        job_results_by_url: dict[str, JobUpsertResult] = {}
        detail_tasks: list[DetailFetchTask] = []
        linked_job_ids: set[int] = set()
        state_counts: Counter[str] = Counter()

        for observation in observations:
            job_result = job_results_by_url.get(observation.canonical_job_url)
            if job_result is None:
                job_result = self.job_repository.upsert_listing_job(
                    canonical_job_url=observation.canonical_job_url,
                    source_host=observation.source_host,
                    listing_hash=observation.listing_hash,
                )
                job_results_by_url[observation.canonical_job_url] = job_result
                state_counts[job_result.state] += 1
                if job_result.state in {"new", "changed"}:
                    detail_tasks.append(
                        _build_detail_fetch_task(
                            scrape_run_id=scrape_run_id,
                            job_id=job_result.job_id,
                            observation=observation,
                            detail_refresh_reason=job_result.state,
                        )
                    )

            job_id = job_result.job_id

            if job_id not in linked_job_ids:
                self.job_category_repository.link_job_category(job_id=job_id, category_id=category_id)
                linked_job_ids.add(job_id)

            self.observation_repository.record_observation(
                scrape_run_id=scrape_run_id,
                job_id=job_id,
                category_id=category_id,
                observation=observation,
            )

        self.connection.commit()
        return ListingPersistenceResult(
            jobs_touched=len(job_results_by_url),
            changed_jobs=state_counts["changed"],
            new_jobs=state_counts["new"],
            observations_written=len(observations),
            unchanged_jobs=state_counts["unchanged"],
            detail_tasks=tuple(detail_tasks),
        )

    def persist_detail_fetch_results(
        self,
        results: Sequence[DetailFetchResult],
    ) -> DetailFetchPersistenceResult:
        if not results:
            return DetailFetchPersistenceResult(
                fetch_failed=0,
                fetch_succeeded=0,
                tasks_fetched=0,
            )

        fetch_succeeded = 0
        fetch_failed = 0

        for result in results:
            self.job_repository.record_detail_fetch_outcome(
                job_id=result.job_id,
                http_status=result.http_status,
            )

            event_name = "detail_fetch_succeeded"
            event_status = "info"
            if not _is_success_status(result.http_status) or result.error_message:
                fetch_failed += 1
                event_name = "detail_fetch_failed"
                event_status = "warning" if result.http_status is not None else "error"
            else:
                fetch_succeeded += 1

            self.event_repository.record_event(
                scrape_run_id=result.scrape_run_id,
                stage="detail_fetch",
                event=event_name,
                status=event_status,
                canonical_job_url=result.canonical_job_url,
                source_host=result.source_host,
                details={
                    "detail_html_hash": result.detail_html_hash,
                    "detail_refresh_reason": result.detail_refresh_reason,
                    "elapsed_ms": result.elapsed_ms,
                    "error_message": result.error_message,
                    "fetched_at": result.fetched_at.isoformat(),
                    "http_status": result.http_status,
                    "response_url": result.response_url,
                },
            )

        self.connection.commit()
        return DetailFetchPersistenceResult(
            fetch_failed=fetch_failed,
            fetch_succeeded=fetch_succeeded,
            tasks_fetched=len(results),
        )

    def persist_extracted_details(
        self,
        extracted_details: Sequence[ExtractedDetail],
        extraction_version: str,
        failures: Sequence[DetailExtractionFailure] = (),
    ) -> DetailExtractionPersistenceResult:
        if not extracted_details and not failures:
            return DetailExtractionPersistenceResult(
                extraction_failed=0,
                snapshots_written=0,
            )

        extraction_failed = 0
        snapshots_written = 0

        for extracted_detail in extracted_details:
            banner_image_id, footer_image_id = self._persist_listing_images(extracted_detail)
            job_snapshot_id = self.snapshot_repository.upsert_snapshot(
                extracted_detail=extracted_detail,
                extraction_version=extraction_version,
                banner_image_id=banner_image_id,
                footer_image_id=footer_image_id,
            )
            self.job_repository.set_current_snapshot(
                job_id=extracted_detail.job_id,
                job_snapshot_id=job_snapshot_id,
            )
            self.event_repository.record_event(
                scrape_run_id=extracted_detail.scrape_run_id,
                stage="detail_extract",
                event="snapshot_written",
                status="info",
                canonical_job_url=extracted_detail.canonical_job_url,
                source_host=extracted_detail.source_host,
                details={
                    "banner_image_id": banner_image_id,
                    "description_text_hash": extracted_detail.description_text_hash,
                    "detail_html_hash": extracted_detail.detail_html_hash,
                    "detail_refresh_reason": extracted_detail.detail_refresh_reason,
                    "footer_image_id": footer_image_id,
                    "job_title_normalized": extracted_detail.job_title_normalized,
                },
            )
            snapshots_written += 1

        for failure in failures:
            self.event_repository.record_event(
                scrape_run_id=failure.scrape_run_id,
                stage="detail_extract",
                event="detail_extract_failed",
                status="warning",
                canonical_job_url=failure.canonical_job_url,
                source_host=failure.source_host,
                details={
                    "detail_html_hash": failure.detail_html_hash,
                    "detail_refresh_reason": failure.detail_refresh_reason,
                    "error_message": failure.error_message,
                    "job_id": failure.job_id,
                },
            )
            extraction_failed += 1

        self.connection.commit()
        return DetailExtractionPersistenceResult(
            extraction_failed=extraction_failed,
            snapshots_written=snapshots_written,
        )

    def record_event(
        self,
        scrape_run_id: UUID,
        stage: str,
        event: str,
        status: str,
        canonical_job_url: str | None = None,
        source_host: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.event_repository.record_event(
            scrape_run_id=scrape_run_id,
            stage=stage,
            event=event,
            status=status,
            canonical_job_url=canonical_job_url,
            source_host=source_host,
            details=details,
        )
        self.connection.commit()

    def rollback(self) -> None:
        rollback = getattr(self.connection, "rollback", None)
        if callable(rollback):
            rollback()

    def close(self) -> None:
        self.connection.close()

    def _persist_listing_images(self, extracted_detail: ExtractedDetail) -> tuple[int | None, int | None]:
        return (
            self._persist_listing_image(
                job_id=extracted_detail.job_id,
                image_role="banner",
                raw_url=extracted_detail.banner_image_url_raw,
            ),
            self._persist_listing_image(
                job_id=extracted_detail.job_id,
                image_role="footer",
                raw_url=extracted_detail.footer_image_url_raw,
            ),
        )

    def _persist_listing_image(
        self,
        job_id: int,
        image_role: str,
        raw_url: str | None,
    ) -> int | None:
        source_url = _normalize_image_source_url(raw_url)
        if not source_url or self.image_session is None:
            return None

        try:
            response = self.image_session.get(source_url, timeout=self.image_timeout_seconds)
            response.raise_for_status()
        except requests.RequestException:
            return None

        image_bytes = response.content
        if not image_bytes:
            return None

        content_type = response.headers.get("Content-Type") if getattr(response, "headers", None) else None
        if content_type is not None:
            content_type = content_type.split(";", 1)[0].strip() or None
        if content_type is not None and not content_type.lower().startswith("image/"):
            return None

        return self.job_image_repository.upsert_image(
            job_id=job_id,
            image_role=image_role,
            source_url=source_url,
            content_type=content_type,
            image_bytes=image_bytes,
        )


def _build_detail_fetch_task(
    scrape_run_id: UUID,
    job_id: int,
    observation: ListingObservation,
    detail_refresh_reason: str,
) -> DetailFetchTask:
    return DetailFetchTask(
        scrape_run_id=scrape_run_id,
        job_id=job_id,
        canonical_job_url=observation.canonical_job_url,
        source_host=observation.source_host,
        category_key=observation.category_key,
        category_name=observation.category_name,
        listing_page_url=observation.listing_page_url,
        job_title_raw=observation.job_title_raw,
        company_name_raw=observation.company_name_raw,
        company_url_raw=observation.company_url_raw,
        location_raw=observation.location_raw,
        published_raw=observation.published_raw,
        banner_image_url_raw=observation.banner_image_url_raw,
        footer_image_url_raw=observation.footer_image_url_raw,
        listing_hash=observation.listing_hash,
        detail_refresh_reason=detail_refresh_reason,
    )


def _is_success_status(http_status: int | None) -> bool:
    if http_status is None:
        return False
    return 200 <= http_status < 400


def _normalize_image_source_url(raw_url: str | None) -> str | None:
    if raw_url is None:
        return None
    normalized = raw_url.strip()
    if not normalized:
        return None
    return urljoin(JOBINDEX_BASE_URL, normalized)