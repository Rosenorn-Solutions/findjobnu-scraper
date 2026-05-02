from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .models import DetailFetchTask, ListingObservation


@dataclass(frozen=True)
class ReferralHostStat:
    source_host: str
    platform_domain: str
    unique_jobs: int
    queued_detail_tasks: int
    is_jobindex_host: bool
    is_danish_domain: bool


@dataclass(frozen=True)
class ReferralPlatformStat:
    platform_domain: str
    unique_jobs: int
    unique_hosts: int
    queued_detail_tasks: int
    is_jobindex_host: bool
    is_danish_domain: bool


@dataclass(frozen=True)
class ReferralStatsReport:
    total_unique_jobs: int
    unique_source_hosts: int
    unique_platform_domains: int
    jobindex_unique_jobs: int
    third_party_unique_jobs: int
    danish_unique_jobs: int
    danish_third_party_unique_jobs: int
    non_danish_unique_jobs: int
    non_danish_third_party_unique_jobs: int
    top_source_hosts: tuple[ReferralHostStat, ...]
    top_jobindex_source_hosts: tuple[ReferralHostStat, ...]
    top_platform_domains: tuple[ReferralPlatformStat, ...]
    top_third_party_platform_domains: tuple[ReferralPlatformStat, ...]


def build_referral_stats_report(
    observations: Sequence[ListingObservation],
    detail_tasks: Sequence[DetailFetchTask],
    limit: int = 10,
) -> ReferralStatsReport:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    host_job_urls: dict[str, set[str]] = defaultdict(set)
    host_detail_job_urls: dict[str, set[str]] = defaultdict(set)
    platform_job_urls: dict[str, set[str]] = defaultdict(set)
    platform_detail_job_urls: dict[str, set[str]] = defaultdict(set)
    platform_hosts: dict[str, set[str]] = defaultdict(set)

    for observation in observations:
        source_host = _normalize_host(observation.source_host)
        platform_domain = _platform_domain_for_host(source_host)
        host_job_urls[source_host].add(observation.canonical_job_url)
        platform_job_urls[platform_domain].add(observation.canonical_job_url)
        platform_hosts[platform_domain].add(source_host)

    for detail_task in detail_tasks:
        source_host = _normalize_host(detail_task.source_host)
        platform_domain = _platform_domain_for_host(source_host)
        host_detail_job_urls[source_host].add(detail_task.canonical_job_url)
        platform_detail_job_urls[platform_domain].add(detail_task.canonical_job_url)

    top_source_hosts = tuple(
        sorted(
            (
                ReferralHostStat(
                    source_host=source_host,
                    platform_domain=_platform_domain_for_host(source_host),
                    unique_jobs=len(job_urls),
                    queued_detail_tasks=len(host_detail_job_urls.get(source_host, set())),
                    is_jobindex_host=_is_jobindex_domain(_platform_domain_for_host(source_host)),
                    is_danish_domain=_is_danish_domain(_platform_domain_for_host(source_host)),
                )
                for source_host, job_urls in host_job_urls.items()
            ),
            key=lambda item: (-item.unique_jobs, -item.queued_detail_tasks, item.source_host),
        )[:limit]
    )
    top_platform_domains = tuple(
        sorted(
            (
                ReferralPlatformStat(
                    platform_domain=platform_domain,
                    unique_jobs=len(job_urls),
                    unique_hosts=len(platform_hosts.get(platform_domain, set())),
                    queued_detail_tasks=len(platform_detail_job_urls.get(platform_domain, set())),
                    is_jobindex_host=_is_jobindex_domain(platform_domain),
                    is_danish_domain=_is_danish_domain(platform_domain),
                )
                for platform_domain, job_urls in platform_job_urls.items()
            ),
            key=lambda item: (-item.unique_jobs, -item.queued_detail_tasks, item.platform_domain),
        )[:limit]
    )
    top_jobindex_source_hosts = tuple(
        sorted(
            (
                host_stat
                for host_stat in top_source_hosts if host_stat.is_jobindex_host
            ),
            key=lambda item: (-item.unique_jobs, -item.queued_detail_tasks, item.source_host),
        )[:limit]
    )
    top_third_party_platform_domains = tuple(
        sorted(
            (
                platform_stat
                for platform_stat in top_platform_domains if not platform_stat.is_jobindex_host
            ),
            key=lambda item: (-item.unique_jobs, -item.queued_detail_tasks, item.platform_domain),
        )[:limit]
    )

    all_job_urls = {observation.canonical_job_url for observation in observations}
    jobindex_job_urls = _union_job_urls(
        platform_job_urls,
        predicate=_is_jobindex_domain,
    )
    danish_job_urls = _union_job_urls(
        platform_job_urls,
        predicate=_is_danish_domain,
    )
    danish_third_party_job_urls = _union_job_urls(
        platform_job_urls,
        predicate=lambda platform_domain: _is_danish_domain(platform_domain)
        and not _is_jobindex_domain(platform_domain),
    )
    non_danish_job_urls = all_job_urls - danish_job_urls
    non_danish_third_party_job_urls = _union_job_urls(
        platform_job_urls,
        predicate=lambda platform_domain: not _is_danish_domain(platform_domain)
        and not _is_jobindex_domain(platform_domain),
    )

    return ReferralStatsReport(
        total_unique_jobs=len(all_job_urls),
        unique_source_hosts=len(host_job_urls),
        unique_platform_domains=len(platform_job_urls),
        jobindex_unique_jobs=len(jobindex_job_urls),
        third_party_unique_jobs=len(all_job_urls - jobindex_job_urls),
        danish_unique_jobs=len(danish_job_urls),
        danish_third_party_unique_jobs=len(danish_third_party_job_urls),
        non_danish_unique_jobs=len(non_danish_job_urls),
        non_danish_third_party_unique_jobs=len(non_danish_third_party_job_urls),
        top_source_hosts=top_source_hosts,
        top_jobindex_source_hosts=top_jobindex_source_hosts,
        top_platform_domains=top_platform_domains,
        top_third_party_platform_domains=top_third_party_platform_domains,
    )


def _union_job_urls(
    platform_job_urls: dict[str, set[str]],
    predicate,
) -> set[str]:
    collected: set[str] = set()
    for platform_domain, job_urls in platform_job_urls.items():
        if predicate(platform_domain):
            collected.update(job_urls)
    return collected


def _normalize_host(source_host: str) -> str:
    return source_host.strip().lower().rstrip(".")


def _platform_domain_for_host(source_host: str) -> str:
    labels = source_host.split(".")
    if len(labels) <= 2:
        return source_host
    return ".".join(labels[-2:])


def _is_jobindex_domain(platform_domain: str) -> bool:
    return platform_domain == "jobindex.dk"


def _is_danish_domain(platform_domain: str) -> bool:
    return platform_domain.endswith(".dk")