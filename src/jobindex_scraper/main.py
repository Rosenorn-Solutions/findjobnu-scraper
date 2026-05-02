from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from typing import Sequence
from uuid import UUID

from .catalog import category_from_subid
from .config import load_settings
from .detail.extractor import GenericJobDetailExtractor
from .detail.fetcher import JobDetailFetcher
from .listing.collector import JobindexListingCollector
from .logging import configure_logging
from .models import (
    CategoryRecord,
    DetailExtractionFailure,
    DetailFetchResult,
    DetailFetchTask,
    ExtractedDetail,
    ListingObservation,
)
from .persistence.pool import PersistenceConfigurationError
from .persistence.writer import PersistenceWriter
from .referral_stats import ReferralStatsReport, build_referral_stats_report


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Jobindex listing observations over HTTP.")
    parser.add_argument("--subid", type=int, help="Jobindex subid to scrape.")
    parser.add_argument("--category-url", help="Explicit category URL to scrape.")
    parser.add_argument("--category-key", help="Category key for explicit category URLs.")
    parser.add_argument("--category-name", help="Category name for explicit category URLs.")
    parser.add_argument("--max-pages", type=int, default=1, help="Maximum number of listing pages to collect.")
    parser.add_argument(
        "--record-run",
        action="store_true",
        help="Persist scrape-run lifecycle metadata in MSSQL. Not required for referral statistics-only runs.",
    )
    parser.add_argument(
        "--fetch-details",
        action="store_true",
        help="Fetch queued detail pages for new and changed jobs.",
    )
    parser.add_argument(
        "--max-detail-tasks",
        type=int,
        help="Maximum number of queued detail tasks to fetch.",
    )
    parser.add_argument(
        "--dump-observations",
        action="store_true",
        help="Print every parsed listing observation as JSON.",
    )
    parser.add_argument(
        "--dump-detail-tasks",
        action="store_true",
        help="Print queued detail fetch tasks as JSON.",
    )
    parser.add_argument(
        "--dump-referral-stats",
        action="store_true",
        help="Print aggregated referral host statistics for the observed jobs. Works without --record-run.",
    )
    parser.add_argument(
        "--referral-stats-limit",
        type=int,
        default=10,
        help="Maximum number of referral hosts and platform domains to include in the statistics output.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    _validate_runtime_options(args=args, parser=parser)

    settings = load_settings()
    configure_logging(settings.log_level)

    category = _build_category(args, parser)
    writer = _build_persistence_writer(args, settings, parser)
    scrape_run_id: UUID | None = None
    category_id: int | None = None

    try:
        if writer is not None:
            scrape_run_id, category_id = _start_persisted_run(
                writer=writer,
                settings=settings,
                category=category,
            )

        summary, observations, detail_tasks = _run_collection(
            category=category,
            max_pages=args.max_pages,
            settings=settings,
            writer=writer,
            scrape_run_id=scrape_run_id,
            category_id=category_id,
        )
        referral_stats = build_referral_stats_report(
            observations=observations,
            detail_tasks=detail_tasks,
            limit=args.referral_stats_limit,
        )
        summary.update(_build_referral_summary(referral_stats))
        detail_results: list[DetailFetchResult] = []
        if args.fetch_details:
            detail_summary, detail_results = _run_detail_fetch_stage(
                settings=settings,
                detail_tasks=detail_tasks,
                writer=writer,
                max_detail_tasks=args.max_detail_tasks,
            )
            summary.update(detail_summary)

        if writer is not None and scrape_run_id is not None:
            writer.finish_run(
                scrape_run_id=scrape_run_id,
                status="completed",
                notes=json.dumps(summary, ensure_ascii=False),
            )

        _print_results(
            summary=summary,
            observations=observations,
            detail_tasks=detail_tasks,
            detail_results=detail_results,
            referral_stats=referral_stats,
            dump_observations=args.dump_observations,
            dump_detail_tasks=args.dump_detail_tasks,
            dump_detail_results=False,
            dump_referral_stats=args.dump_referral_stats,
        )
        return 0
    except Exception as error:
        if writer is not None and scrape_run_id is not None:
            _finish_failed_run(writer=writer, scrape_run_id=scrape_run_id, error=error)
        raise
    finally:
        if writer is not None:
            writer.close()


def _build_persistence_writer(
    args: argparse.Namespace,
    settings,
    parser: argparse.ArgumentParser,
) -> PersistenceWriter | None:
    if not args.record_run:
        return None
    try:
        return PersistenceWriter.from_settings(settings)
    except PersistenceConfigurationError as error:
        parser.error(str(error))


def _validate_runtime_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.fetch_details and not args.record_run:
        parser.error("--fetch-details requires --record-run so jobs can be classified against persisted state.")
    if args.max_detail_tasks is not None and args.max_detail_tasks < 1:
        parser.error("--max-detail-tasks must be at least 1 when provided.")
    if args.referral_stats_limit < 1:
        parser.error("--referral-stats-limit must be at least 1.")


def _start_persisted_run(
    writer: PersistenceWriter,
    settings,
    category: CategoryRecord,
) -> tuple[UUID, int]:
    scrape_run = writer.start_run(settings=settings)
    category_id = writer.ensure_category(category)
    return scrape_run.scrape_run_id, category_id


def _run_collection(
    category: CategoryRecord,
    max_pages: int,
    settings,
    writer: PersistenceWriter | None,
    scrape_run_id: UUID | None,
    category_id: int | None,
) -> tuple[dict[str, object], list[ListingObservation], list[DetailFetchTask]]:
    collector = JobindexListingCollector(settings=settings)
    page_results = collector.collect_pages(category=category, max_pages=max_pages)
    observations = [
        observation
        for page_result in page_results
        for observation in page_result.observations
    ]

    persistence_result = None
    detail_tasks: list[DetailFetchTask] = []
    if writer is not None and scrape_run_id is not None and category_id is not None:
        persistence_result = writer.persist_listing_observations(
            scrape_run_id=scrape_run_id,
            category_id=category_id,
            observations=observations,
        )
        detail_tasks = list(persistence_result.detail_tasks)

    summary = {
        "category_key": category.category_key,
        "category_name": category.category_name,
        "changed_jobs": persistence_result.changed_jobs if persistence_result else None,
        "detail_tasks_queued": len(detail_tasks),
        "pages_collected": len(page_results),
        "observations_collected": len(observations),
        "first_job_url": observations[0].canonical_job_url if observations else None,
        "jobs_touched": persistence_result.jobs_touched if persistence_result else None,
        "last_page_url": page_results[-1].page_url if page_results else None,
        "new_jobs": persistence_result.new_jobs if persistence_result else None,
        "next_page_url": page_results[-1].next_page_url if page_results else None,
        "observations_written": (
            persistence_result.observations_written if persistence_result else None
        ),
        "scrape_run_id": str(scrape_run_id) if scrape_run_id is not None else None,
        "unchanged_jobs": persistence_result.unchanged_jobs if persistence_result else None,
    }

    return summary, observations, detail_tasks


def _run_detail_fetch_stage(
    settings,
    detail_tasks: list[DetailFetchTask],
    writer: PersistenceWriter | None,
    max_detail_tasks: int | None,
) -> tuple[dict[str, object], list[DetailFetchResult]]:
    fetcher = JobDetailFetcher(settings=settings)
    extractor = GenericJobDetailExtractor()
    detail_results = fetcher.fetch_tasks(detail_tasks, max_tasks=max_detail_tasks)

    fetch_persistence_result = None
    extraction_persistence_result = None
    extracted_details = extractor.extract_tasks(detail_tasks=detail_tasks, detail_results=detail_results)
    extraction_failures = _build_detail_extraction_failures(
        detail_results=detail_results,
        extracted_details=extracted_details,
    )
    if writer is not None:
        fetch_persistence_result = writer.persist_detail_fetch_results(detail_results)
        extraction_persistence_result = writer.persist_extracted_details(
            extracted_details=extracted_details,
            extraction_version=settings.extraction_version,
            failures=extraction_failures,
        )

    summary = {
        "detail_extract_failed": (
            extraction_persistence_result.extraction_failed
            if extraction_persistence_result
            else len(extraction_failures)
        ),
        "detail_fetch_failed": fetch_persistence_result.fetch_failed if fetch_persistence_result else None,
        "detail_fetch_succeeded": fetch_persistence_result.fetch_succeeded if fetch_persistence_result else None,
        "detail_snapshots_written": (
            extraction_persistence_result.snapshots_written if extraction_persistence_result else None
        ),
        "detail_tasks_fetched": len(detail_results),
    }
    return summary, detail_results


def _build_detail_extraction_failures(
    detail_results: list[DetailFetchResult],
    extracted_details: list[ExtractedDetail],
) -> list[DetailExtractionFailure]:
    extracted_job_ids = {detail.job_id for detail in extracted_details}
    failures: list[DetailExtractionFailure] = []

    for result in detail_results:
        if result.job_id in extracted_job_ids:
            continue
        if result.error_message or not result.detail_html_hash or not result.html_content:
            continue
        failures.append(
            DetailExtractionFailure(
                scrape_run_id=result.scrape_run_id,
                job_id=result.job_id,
                canonical_job_url=result.canonical_job_url,
                source_host=result.source_host,
                detail_html_hash=result.detail_html_hash,
                detail_refresh_reason=result.detail_refresh_reason,
                error_message="Detail extraction produced no snapshot.",
            )
        )

    return failures


def _print_results(
    summary: dict[str, object],
    observations: list[ListingObservation],
    detail_tasks: list[DetailFetchTask],
    detail_results: list[DetailFetchResult],
    referral_stats: ReferralStatsReport | None,
    dump_observations: bool,
    dump_detail_tasks: bool,
    dump_detail_results: bool,
    dump_referral_stats: bool,
) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if dump_observations:
        print(
            json.dumps(
                [asdict(observation) for observation in observations],
                ensure_ascii=False,
                indent=2,
            )
        )

    if dump_detail_tasks:
        print(
            json.dumps(
                [asdict(detail_task) for detail_task in detail_tasks],
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    if dump_detail_results:
        print(
            json.dumps(
                [asdict(detail_result) for detail_result in detail_results],
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    if dump_referral_stats and referral_stats is not None:
        print(
            json.dumps(
                asdict(referral_stats),
                ensure_ascii=False,
                indent=2,
            )
        )


def _build_referral_summary(referral_stats: ReferralStatsReport) -> dict[str, int]:
    return {
        "referral_danish_jobs": referral_stats.danish_unique_jobs,
        "referral_danish_third_party_jobs": referral_stats.danish_third_party_unique_jobs,
        "referral_jobindex_jobs": referral_stats.jobindex_unique_jobs,
        "referral_non_danish_jobs": referral_stats.non_danish_unique_jobs,
        "referral_non_danish_third_party_jobs": referral_stats.non_danish_third_party_unique_jobs,
        "referral_platforms_seen": referral_stats.unique_platform_domains,
        "referral_source_hosts_seen": referral_stats.unique_source_hosts,
        "referral_third_party_jobs": referral_stats.third_party_unique_jobs,
    }


def _finish_failed_run(writer: PersistenceWriter, scrape_run_id: UUID, error: Exception) -> None:
    error_text = str(error).strip() or error.__class__.__name__
    try:
        writer.rollback()
        writer.finish_run(
            scrape_run_id=scrape_run_id,
            status="failed",
            notes=error_text,
        )
    except Exception:
        return


def _build_category(args: argparse.Namespace, parser: argparse.ArgumentParser) -> CategoryRecord:
    if args.subid is not None:
        return category_from_subid(args.subid)

    if not args.category_url:
        parser.error("Either --subid or --category-url must be provided.")

    category_key = args.category_key or "ad_hoc"
    category_name = args.category_name or category_key
    return CategoryRecord(
        category_key=category_key,
        category_name=category_name,
        listing_url=args.category_url,
    )


if __name__ == "__main__":
    raise SystemExit(main())
