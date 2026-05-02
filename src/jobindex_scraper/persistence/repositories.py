from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from ..models import (
    CategoryRecord,
    ExtractedDetail,
    JobUpsertResult,
    ListingObservation,
    ScrapeRunRecord,
)


class RunRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create_run(
        self,
        extraction_version: str,
        config_fingerprint: str,
        notes: str | None = None,
    ) -> ScrapeRunRecord:
        scrape_run_id = uuid4()
        started_at = datetime.now(timezone.utc)

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO scrape_runs (
                    scrape_run_id,
                    started_at,
                    extraction_version,
                    config_fingerprint,
                    notes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(scrape_run_id),
                    _normalize_datetime(started_at),
                    extraction_version,
                    config_fingerprint,
                    notes,
                ),
            )
        finally:
            _close_cursor(cursor)

        return ScrapeRunRecord(
            scrape_run_id=scrape_run_id,
            started_at=started_at,
            status="running",
            extraction_version=extraction_version,
        )

    def finish_run(self, scrape_run_id: UUID, status: str, notes: str | None = None) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE scrape_runs
                SET ended_at = SYSUTCDATETIME(),
                    status = ?,
                    notes = COALESCE(?, notes)
                WHERE scrape_run_id = ?
                """,
                (status, notes, str(scrape_run_id)),
            )
        finally:
            _close_cursor(cursor)


class CategoryRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def upsert_category(self, category: CategoryRecord) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT category_id FROM categories WHERE category_key = ?",
                (category.category_key,),
            )
            row = cursor.fetchone()
            if row is not None:
                category_id = int(row[0])
                cursor.execute(
                    """
                    UPDATE categories
                    SET category_name = ?,
                        listing_url = ?,
                        is_active = 1
                    WHERE category_id = ?
                    """,
                    (category.category_name, category.listing_url, category_id),
                )
                return category_id

            cursor.execute(
                """
                INSERT INTO categories (category_key, category_name, listing_url)
                OUTPUT INSERTED.category_id
                VALUES (?, ?, ?)
                """,
                (category.category_key, category.category_name, category.listing_url),
            )
            row = cursor.fetchone()
        finally:
            _close_cursor(cursor)

        return _require_identity_value(row, "Failed to upsert category record.")


class JobRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def upsert_listing_job(
        self,
        canonical_job_url: str,
        source_host: str,
        listing_hash: str,
    ) -> JobUpsertResult:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT job_id, current_listing_hash
                FROM jobs
                WHERE canonical_job_url = ?
                """,
                (canonical_job_url,),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    INSERT INTO jobs (canonical_job_url, source_host, current_listing_hash)
                    OUTPUT INSERTED.job_id
                    VALUES (?, ?, ?)
                    """,
                    (canonical_job_url, source_host, listing_hash),
                )
                inserted_row = cursor.fetchone()
                return JobUpsertResult(
                    job_id=_require_identity_value(
                        inserted_row,
                        "Failed to insert listing-backed job state.",
                    ),
                    state="new",
                )

            job_id = int(row[0])
            current_listing_hash = row[1]
            if current_listing_hash != listing_hash:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET source_host = ?,
                        current_listing_hash = ?,
                        last_seen_at = SYSUTCDATETIME(),
                        updated_at = SYSUTCDATETIME()
                    WHERE job_id = ?
                    """,
                    (source_host, listing_hash, job_id),
                )
                return JobUpsertResult(job_id=job_id, state="changed")

            cursor.execute(
                """
                UPDATE jobs
                SET last_seen_at = SYSUTCDATETIME()
                WHERE job_id = ?
                """,
                (job_id,),
            )
            return JobUpsertResult(job_id=job_id, state="unchanged")
        finally:
            _close_cursor(cursor)

    def touch_job(self, canonical_job_url: str, source_host: str) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT job_id FROM jobs WHERE canonical_job_url = ?",
                (canonical_job_url,),
            )
            row = cursor.fetchone()
            if row is not None:
                job_id = int(row[0])
                cursor.execute(
                    """
                    UPDATE jobs
                    SET source_host = ?,
                        last_seen_at = SYSUTCDATETIME(),
                        updated_at = SYSUTCDATETIME()
                    WHERE job_id = ?
                    """,
                    (source_host, job_id),
                )
                return job_id

            cursor.execute(
                """
                INSERT INTO jobs (canonical_job_url, source_host)
                OUTPUT INSERTED.job_id
                VALUES (?, ?)
                """,
                (canonical_job_url, source_host),
            )
            row = cursor.fetchone()
        finally:
            _close_cursor(cursor)

        return _require_identity_value(row, "Failed to upsert job identity.")

    def record_detail_fetch_outcome(self, job_id: int, http_status: int | None) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE jobs
                SET last_detail_fetched_at = SYSUTCDATETIME(),
                    last_http_status = ?,
                    updated_at = SYSUTCDATETIME()
                WHERE job_id = ?
                """,
                (http_status, job_id),
            )
        finally:
            _close_cursor(cursor)

    def set_current_snapshot(self, job_id: int, job_snapshot_id: int) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE jobs
                SET current_snapshot_id = ?,
                    updated_at = SYSUTCDATETIME()
                WHERE job_id = ?
                """,
                (job_snapshot_id, job_id),
            )
        finally:
            _close_cursor(cursor)


class JobCategoryRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def link_job_category(self, job_id: int, category_id: int) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM job_categories WHERE job_id = ? AND category_id = ?",
                (job_id, category_id),
            )
            if cursor.fetchone() is not None:
                return

            cursor.execute(
                "INSERT INTO job_categories (job_id, category_id) VALUES (?, ?)",
                (job_id, category_id),
            )
        finally:
            _close_cursor(cursor)


class ObservationRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def record_observation(
        self,
        scrape_run_id: UUID,
        job_id: int,
        category_id: int,
        observation: ListingObservation,
    ) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT job_observation_id
                FROM job_observations
                WHERE scrape_run_id = ?
                  AND job_id = ?
                  AND category_id = ?
                  AND listing_page_url = ?
                  AND listing_position = ?
                """,
                (
                    str(scrape_run_id),
                    job_id,
                    category_id,
                    observation.listing_page_url,
                    observation.listing_position,
                ),
            )
            row = cursor.fetchone()
            if row is not None:
                cursor.execute(
                    """
                    UPDATE job_observations
                    SET job_url_raw = ?,
                        job_title_raw = ?,
                        company_name_raw = ?,
                        company_url_raw = ?,
                        location_raw = ?,
                        published_raw = ?,
                        banner_image_url_raw = ?,
                        footer_image_url_raw = ?,
                        listing_hash = ?,
                        observed_at = SYSUTCDATETIME()
                    WHERE job_observation_id = ?
                    """,
                    (
                        observation.job_url_raw,
                        observation.job_title_raw,
                        observation.company_name_raw,
                        observation.company_url_raw,
                        observation.location_raw,
                        observation.published_raw,
                        observation.banner_image_url_raw,
                        observation.footer_image_url_raw,
                        observation.listing_hash,
                        int(row[0]),
                    ),
                )
                return

            cursor.execute(
                """
                INSERT INTO job_observations (
                    scrape_run_id,
                    job_id,
                    category_id,
                    listing_page_url,
                    listing_position,
                    job_url_raw,
                    job_title_raw,
                    company_name_raw,
                    company_url_raw,
                    location_raw,
                    published_raw,
                    banner_image_url_raw,
                    footer_image_url_raw,
                    listing_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(scrape_run_id),
                    job_id,
                    category_id,
                    observation.listing_page_url,
                    observation.listing_position,
                    observation.job_url_raw,
                    observation.job_title_raw,
                    observation.company_name_raw,
                    observation.company_url_raw,
                    observation.location_raw,
                    observation.published_raw,
                    observation.banner_image_url_raw,
                    observation.footer_image_url_raw,
                    observation.listing_hash,
                ),
            )
        finally:
            _close_cursor(cursor)


class JobImageRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def upsert_image(
        self,
        job_id: int,
        image_role: str,
        source_url: str,
        content_type: str | None,
        image_bytes: bytes,
    ) -> int:
        content_sha256 = hashlib.sha256(image_bytes).hexdigest()

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT job_image_id
                FROM job_images
                WHERE job_id = ?
                  AND image_role = ?
                  AND content_sha256 = ?
                """,
                (job_id, image_role, content_sha256),
            )
            row = cursor.fetchone()
            if row is not None:
                job_image_id = int(row[0])
                cursor.execute(
                    """
                    UPDATE job_images
                    SET source_url = ?,
                        content_type = ?,
                        fetched_at = SYSUTCDATETIME()
                    WHERE job_image_id = ?
                    """,
                    (source_url, content_type, job_image_id),
                )
                return job_image_id

            cursor.execute(
                """
                INSERT INTO job_images (
                    job_id,
                    image_role,
                    source_url,
                    content_type,
                    content_sha256,
                    image_bytes
                )
                OUTPUT INSERTED.job_image_id
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, image_role, source_url, content_type, content_sha256, image_bytes),
            )
            row = cursor.fetchone()
        finally:
            _close_cursor(cursor)

        return _require_identity_value(row, "Failed to upsert job image.")


class SnapshotRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def upsert_snapshot(
        self,
        extracted_detail: ExtractedDetail,
        extraction_version: str,
        banner_image_id: int | None = None,
        footer_image_id: int | None = None,
    ) -> int:
        field_provenance = _json_text(extracted_detail.field_provenance)
        extraction_warnings = _json_text(extracted_detail.extraction_warnings)

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT job_snapshot_id
                FROM job_snapshots
                WHERE job_id = ?
                  AND extraction_version = ?
                  AND detail_html_hash = ?
                """,
                (
                    extracted_detail.job_id,
                    extraction_version,
                    extracted_detail.detail_html_hash,
                ),
            )
            row = cursor.fetchone()
            if row is not None:
                job_snapshot_id = int(row[0])
                cursor.execute(
                    """
                    UPDATE job_snapshots
                    SET listing_hash = ?,
                        description_text_hash = ?,
                        job_title_raw = ?,
                        job_title_normalized = ?,
                        company_name_raw = ?,
                        company_name_normalized = ?,
                        company_url_raw = ?,
                        company_url_normalized = ?,
                        location_raw = ?,
                        location_normalized = ?,
                        published_raw = ?,
                        published_utc = ?,
                        job_description_raw = ?,
                        job_description_clean = ?,
                        banner_image_id = ?,
                        footer_image_id = ?,
                        field_provenance = ?,
                        extraction_warnings = ?
                    WHERE job_snapshot_id = ?
                    """,
                    (
                        extracted_detail.listing_hash,
                        extracted_detail.description_text_hash,
                        extracted_detail.job_title_raw,
                        extracted_detail.job_title_normalized,
                        extracted_detail.company_name_raw,
                        extracted_detail.company_name_normalized,
                        extracted_detail.company_url_raw,
                        extracted_detail.company_url_normalized,
                        extracted_detail.location_raw,
                        extracted_detail.location_normalized,
                        extracted_detail.published_raw,
                        _normalize_datetime(extracted_detail.published_utc),
                        extracted_detail.job_description_raw,
                        extracted_detail.job_description_clean,
                        banner_image_id,
                        footer_image_id,
                        field_provenance,
                        extraction_warnings,
                        job_snapshot_id,
                    ),
                )
                return job_snapshot_id

            cursor.execute(
                """
                INSERT INTO job_snapshots (
                    job_id,
                    extraction_version,
                    listing_hash,
                    detail_html_hash,
                    description_text_hash,
                    job_title_raw,
                    job_title_normalized,
                    company_name_raw,
                    company_name_normalized,
                    company_url_raw,
                    company_url_normalized,
                    location_raw,
                    location_normalized,
                    published_raw,
                    published_utc,
                    job_description_raw,
                    job_description_clean,
                    banner_image_id,
                    footer_image_id,
                    field_provenance,
                    extraction_warnings
                )
                OUTPUT INSERTED.job_snapshot_id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extracted_detail.job_id,
                    extraction_version,
                    extracted_detail.listing_hash,
                    extracted_detail.detail_html_hash,
                    extracted_detail.description_text_hash,
                    extracted_detail.job_title_raw,
                    extracted_detail.job_title_normalized,
                    extracted_detail.company_name_raw,
                    extracted_detail.company_name_normalized,
                    extracted_detail.company_url_raw,
                    extracted_detail.company_url_normalized,
                    extracted_detail.location_raw,
                    extracted_detail.location_normalized,
                    extracted_detail.published_raw,
                    _normalize_datetime(extracted_detail.published_utc),
                    extracted_detail.job_description_raw,
                    extracted_detail.job_description_clean,
                    banner_image_id,
                    footer_image_id,
                    field_provenance,
                    extraction_warnings,
                ),
            )
            row = cursor.fetchone()
        finally:
            _close_cursor(cursor)

        return _require_identity_value(row, "Failed to upsert job snapshot.")


class EventRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

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
        details_json = _json_text(details or {})
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO scrape_events (
                    scrape_run_id,
                    stage,
                    event,
                    status,
                    canonical_job_url,
                    source_host,
                    details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(scrape_run_id),
                    stage,
                    event,
                    status,
                    canonical_job_url,
                    source_host,
                    details_json,
                ),
            )
        finally:
            _close_cursor(cursor)


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _close_cursor(cursor: Any) -> None:
    close = getattr(cursor, "close", None)
    if callable(close):
        close()


def _require_identity_value(row: Any, message: str) -> int:
    if row is None or row[0] is None:
        raise RuntimeError(message)
    return int(row[0])