from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CategoryRecord:
    category_key: str
    category_name: str
    listing_url: str


@dataclass(frozen=True)
class ListingObservation:
    listing_page_url: str
    category_key: str
    category_name: str
    listing_position: int
    job_url_raw: str
    canonical_job_url: str
    source_host: str
    job_title_raw: str | None
    company_name_raw: str | None
    company_url_raw: str | None
    location_raw: str | None
    published_raw: str | None
    banner_image_url_raw: str | None
    footer_image_url_raw: str | None
    listing_hash: str


@dataclass(frozen=True)
class ListingPageResult:
    category: CategoryRecord
    page_url: str
    next_page_url: str | None
    observations: tuple[ListingObservation, ...]


@dataclass(frozen=True)
class ScrapeRunRecord:
    scrape_run_id: UUID
    started_at: datetime
    status: str
    extraction_version: str


@dataclass(frozen=True)
class DetailFetchTask:
    scrape_run_id: UUID
    job_id: int
    canonical_job_url: str
    source_host: str
    category_key: str
    category_name: str
    listing_page_url: str
    job_title_raw: str | None
    company_name_raw: str | None
    company_url_raw: str | None
    location_raw: str | None
    published_raw: str | None
    banner_image_url_raw: str | None
    footer_image_url_raw: str | None
    listing_hash: str
    detail_refresh_reason: str


@dataclass(frozen=True)
class DetailFetchResult:
    scrape_run_id: UUID
    job_id: int
    canonical_job_url: str
    source_host: str
    response_url: str | None
    http_status: int | None
    fetched_at: datetime
    elapsed_ms: int
    detail_html_hash: str | None
    detail_refresh_reason: str
    error_message: str | None
    html_content: str | None


@dataclass(frozen=True)
class ExtractedDetail:
    scrape_run_id: UUID
    job_id: int
    canonical_job_url: str
    source_host: str
    listing_hash: str
    detail_html_hash: str
    job_title_raw: str | None
    job_title_normalized: str
    company_name_raw: str | None
    company_name_normalized: str | None
    company_url_raw: str | None
    company_url_normalized: str | None
    location_raw: str | None
    location_normalized: str | None
    published_raw: str | None
    published_utc: datetime | None
    job_description_raw: str
    job_description_clean: str
    description_text_hash: str
    field_provenance: dict[str, Any]
    extraction_warnings: list[str]
    detail_refresh_reason: str


@dataclass(frozen=True)
class ListingPersistenceResult:
    jobs_touched: int
    changed_jobs: int
    new_jobs: int
    observations_written: int
    unchanged_jobs: int
    detail_tasks: tuple[DetailFetchTask, ...]


@dataclass(frozen=True)
class DetailFetchPersistenceResult:
    fetch_failed: int
    fetch_succeeded: int
    tasks_fetched: int


@dataclass(frozen=True)
class DetailExtractionFailure:
    scrape_run_id: UUID
    job_id: int
    canonical_job_url: str
    source_host: str
    detail_html_hash: str | None
    detail_refresh_reason: str
    error_message: str


@dataclass(frozen=True)
class DetailExtractionPersistenceResult:
    extraction_failed: int
    snapshots_written: int


@dataclass(frozen=True)
class JobUpsertResult:
    job_id: int
    state: str
