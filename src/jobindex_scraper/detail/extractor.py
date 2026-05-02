from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import hashlib
import html
import json
import re

from bs4 import BeautifulSoup

from ..models import DetailFetchResult, DetailFetchTask, ExtractedDetail


OG_TITLE_PROPERTY = "og:title"


class GenericJobDetailExtractor:
    def extract_tasks(
        self,
        detail_tasks: Sequence[DetailFetchTask],
        detail_results: Sequence[DetailFetchResult],
    ) -> list[ExtractedDetail]:
        tasks_by_job_id = {task.job_id: task for task in detail_tasks}
        extracted_details: list[ExtractedDetail] = []

        for result in detail_results:
            task = tasks_by_job_id.get(result.job_id)
            if task is None:
                continue
            extracted_detail = self.extract_result(task=task, result=result)
            if extracted_detail is not None:
                extracted_details.append(extracted_detail)

        return extracted_details

    def extract_result(
        self,
        task: DetailFetchTask,
        result: DetailFetchResult,
    ) -> ExtractedDetail | None:
        if result.error_message or not result.detail_html_hash or not result.html_content:
            return None

        soup = BeautifulSoup(result.html_content, "html.parser")

        platform_domain = _platform_domain_for_host(task.source_host)
        if platform_domain == "thehub.io":
            return _extract_thehub_detail(task=task, result=result, soup=soup)
        if platform_domain == "hr-manager.net":
            return _extract_hr_manager_detail(task=task, result=result, soup=soup)
        if platform_domain == "teamtailor.com":
            return _extract_teamtailor_detail(task=task, result=result, soup=soup)
        if platform_domain == "myworkdayjobs.com":
            return _extract_workday_detail(task=task, result=result, soup=soup)
        if platform_domain == "emply.com":
            return _extract_emply_detail(task=task, result=result, soup=soup)
        if platform_domain == "midtjob.dk":
            return _extract_midtjob_detail(task=task, result=result, soup=soup)
        if platform_domain == "nytlaegejob.dk":
            return _extract_nytlaegejob_detail(task=task, result=result, soup=soup)
        if platform_domain == "hr-on.com":
            return _extract_hr_on_detail(task=task, result=result, soup=soup)
        if platform_domain == "signatur.dk":
            return _extract_signatur_detail(task=task, result=result, soup=soup)

        return _extract_generic_detail(task=task, result=result, soup=soup)


def _extract_generic_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    title_from_page = _extract_title(soup)
    if not title_from_page and not task.job_title_raw:
        return None

    job_title_raw = title_from_page or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    description_raw = _extract_description(soup)
    description_clean = _normalize_text(description_raw)
    warnings: list[str] = []
    if not description_clean:
        warnings.append("description_empty_after_cleaning")
        description_clean = job_title_normalized

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=_parse_published_datetime(task.published_raw),
        field_provenance={
            "job_description_clean": "detail_page",
            "job_title_normalized": "detail_page" if title_from_page else "listing",
            "company_name_normalized": "listing" if task.company_name_raw else "missing",
            "company_url_normalized": "listing" if task.company_url_raw else "missing",
            "location_normalized": "listing" if task.location_raw else "missing",
        },
    )


def _extract_hr_manager_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    description_container = soup.find(id="AdvertisementInnerContent")
    title_from_page = _extract_hr_manager_title(soup)

    if description_container is None and not title_from_page:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    job_title_raw = title_from_page or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    description_raw = _normalize_text(
        description_container.get_text(" ", strip=True) if description_container is not None else None
    )
    warnings: list[str] = []
    if not description_raw:
        description_raw = _extract_description(soup)
        warnings.append("hr_manager_container_missing")

    description_clean = _clean_hr_manager_description(
        description_text=description_raw,
        job_title_normalized=job_title_normalized,
    )
    if not description_clean:
        description_clean = job_title_normalized
        warnings.append("description_empty_after_cleaning")

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=_parse_published_datetime(task.published_raw),
        field_provenance={
            "job_description_clean": "hr_manager_container",
            "job_title_normalized": "detail_page",
            "company_name_normalized": "listing" if task.company_name_raw else "missing",
            "company_url_normalized": "listing" if task.company_url_raw else "missing",
            "location_normalized": "listing" if task.location_raw else "missing",
        },
    )


def _extract_thehub_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    job_posting = _extract_job_posting_jsonld(soup)
    if job_posting is None:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    job_title_raw = _normalize_text(job_posting.get("title")) or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    description_raw = _clean_html_fragment(job_posting.get("description"))
    description_clean = _normalize_text(description_raw)
    warnings: list[str] = []
    if not description_clean:
        description_clean = _extract_description(soup)
        description_clean = _normalize_text(description_clean) or job_title_normalized
        warnings.append("thehub_jsonld_description_missing")

    company_name_raw = task.company_name_raw or _extract_job_posting_company_name(job_posting)
    location_raw = task.location_raw or _extract_job_posting_location(job_posting)
    published_utc = _parse_published_datetime(job_posting.get("datePosted"))

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=published_utc,
        company_name_raw=company_name_raw,
        location_raw=location_raw,
        field_provenance={
            "job_description_clean": "thehub_jsonld",
            "job_title_normalized": "thehub_jsonld",
            "company_name_normalized": "thehub_jsonld" if company_name_raw and not task.company_name_raw else "listing",
            "company_url_normalized": "listing" if task.company_url_raw else "missing",
            "location_normalized": "thehub_jsonld" if location_raw and not task.location_raw else "listing",
        },
    )


def _extract_teamtailor_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    job_posting = _extract_job_posting_jsonld(soup)
    if job_posting is None:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    return _extract_job_posting_detail(
        task=task,
        result=result,
        soup=soup,
        job_posting=job_posting,
        provenance_label="teamtailor_jsonld",
    )


def _extract_workday_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    job_posting = _extract_job_posting_jsonld(soup)
    if job_posting is None:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    return _extract_job_posting_detail(
        task=task,
        result=result,
        soup=soup,
        job_posting=job_posting,
        provenance_label="workday_jsonld",
    )


def _extract_emply_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    return _extract_csa_jobad_detail(
        task=task,
        result=result,
        soup=soup,
        provenance_label="emply_jobad",
        title_extractor=_extract_emply_title,
    )


def _extract_midtjob_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    return _extract_csa_jobad_detail(
        task=task,
        result=result,
        soup=soup,
        provenance_label="midtjob_jobad",
        title_extractor=_extract_csa_jobad_title,
    )


def _extract_nytlaegejob_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    job_posting = _extract_job_posting_jsonld(soup)
    if job_posting is None:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    job_title_raw = _normalize_text(job_posting.get("title")) or _extract_title(soup) or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    description_raw, description_clean, description_provenance, warnings = _extract_nytlaegejob_description_fields(
        soup=soup,
        job_posting=job_posting,
        job_title_normalized=job_title_normalized,
    )

    company_from_job_posting = _extract_job_posting_company_name(job_posting)
    company_from_meta = _extract_nytlaegejob_company_name(soup)
    company_name_raw = task.company_name_raw or company_from_job_posting or company_from_meta

    location_from_job_posting = _extract_job_posting_location(job_posting)
    location_from_meta = _extract_nytlaegejob_location(
        soup=soup,
        company_name_raw=task.company_name_raw or company_name_raw,
    )
    location_raw = task.location_raw or location_from_job_posting or location_from_meta

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=_parse_published_datetime(job_posting.get("datePosted")),
        company_name_raw=company_name_raw,
        location_raw=location_raw,
        field_provenance=_build_nytlaegejob_field_provenance(
            task=task,
            description_provenance=description_provenance,
            company_from_job_posting=company_from_job_posting,
            company_from_meta=company_from_meta,
            location_from_job_posting=location_from_job_posting,
            location_from_meta=location_from_meta,
        ),
    )


def _extract_csa_jobad_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
    provenance_label: str,
    title_extractor,
) -> ExtractedDetail | None:
    title_from_page = title_extractor(soup)
    description_raw = _extract_emply_description(soup)

    if not title_from_page and not description_raw:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    job_title_raw = title_from_page or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    warnings: list[str] = []
    description_clean = _normalize_text(description_raw)
    if not description_clean:
        description_clean = _normalize_text(_extract_description(soup)) or job_title_normalized
        warnings.append(f"{provenance_label}_text_missing")

    company_name_raw = task.company_name_raw or _extract_emply_company_name(soup)
    location_raw = task.location_raw or _extract_emply_location(soup)

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=_parse_published_datetime(task.published_raw),
        company_name_raw=company_name_raw,
        location_raw=location_raw,
        field_provenance={
            "job_description_clean": provenance_label,
            "job_title_normalized": provenance_label,
            "company_name_normalized": provenance_label if company_name_raw and not task.company_name_raw else "listing",
            "company_url_normalized": "listing" if task.company_url_raw else "missing",
            "location_normalized": provenance_label if location_raw and not task.location_raw else "listing",
        },
    )


def _extract_hr_on_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    title_from_page = _extract_hr_on_title(soup)
    description_raw = _extract_hr_on_description(soup)

    if not title_from_page and not description_raw:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    job_title_raw = title_from_page or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    warnings: list[str] = []
    description_clean = _normalize_text(description_raw)
    if not description_clean:
        description_clean = _normalize_text(_extract_description(soup)) or job_title_normalized
        warnings.append("hr_on_description_missing")

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=_parse_published_datetime(task.published_raw),
        field_provenance={
            "job_description_clean": "hr_on_job",
            "job_title_normalized": "hr_on_job",
            "company_name_normalized": "listing" if task.company_name_raw else "missing",
            "company_url_normalized": "listing" if task.company_url_raw else "missing",
            "location_normalized": "listing" if task.location_raw else "missing",
        },
    )


def _extract_signatur_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
) -> ExtractedDetail | None:
    company_name_raw = task.company_name_raw or _extract_signatur_company_name(soup)
    title_from_page = _extract_signatur_title(soup=soup, company_name_raw=company_name_raw)
    description_raw = _extract_signatur_description(soup)

    if not title_from_page and not description_raw:
        return _extract_generic_detail(task=task, result=result, soup=soup)

    job_title_raw = title_from_page or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    warnings: list[str] = []
    description_clean = _normalize_text(description_raw)
    if not description_clean:
        description_clean = _normalize_text(_extract_description(soup)) or job_title_normalized
        warnings.append("signatur_description_missing")

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=_parse_published_datetime(task.published_raw),
        company_name_raw=company_name_raw,
        field_provenance={
            "job_description_clean": "signatur_page",
            "job_title_normalized": "signatur_page",
            "company_name_normalized": "signatur_page" if company_name_raw and not task.company_name_raw else "listing",
            "company_url_normalized": "listing" if task.company_url_raw else "missing",
            "location_normalized": "listing" if task.location_raw else "missing",
        },
    )


def _extract_job_posting_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    soup: BeautifulSoup,
    job_posting: dict[str, object],
    provenance_label: str,
) -> ExtractedDetail | None:
    job_title_raw = _normalize_text(job_posting.get("title")) or _extract_title(soup) or task.job_title_raw
    job_title_normalized = _normalize_text(job_title_raw)
    if not job_title_normalized:
        return None

    description_raw = _clean_html_fragment(job_posting.get("description"))
    description_clean = _normalize_text(description_raw)
    warnings: list[str] = []
    if not description_clean:
        description_clean = _extract_description(soup)
        description_clean = _normalize_text(description_clean) or job_title_normalized
        warnings.append(f"{provenance_label}_description_missing")

    company_name_raw = task.company_name_raw or _extract_job_posting_company_name(job_posting)
    location_raw = task.location_raw or _extract_job_posting_location(job_posting)

    return _build_extracted_detail(
        task=task,
        result=result,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        description_raw=description_raw,
        description_clean=description_clean,
        warnings=warnings,
        published_utc=_parse_published_datetime(job_posting.get("datePosted")),
        company_name_raw=company_name_raw,
        location_raw=location_raw,
        field_provenance={
            "job_description_clean": provenance_label,
            "job_title_normalized": provenance_label,
            "company_name_normalized": provenance_label if company_name_raw and not task.company_name_raw else "listing",
            "company_url_normalized": "listing" if task.company_url_raw else "missing",
            "location_normalized": provenance_label if location_raw and not task.location_raw else "listing",
        },
    )


def _build_extracted_detail(
    task: DetailFetchTask,
    result: DetailFetchResult,
    job_title_raw: str | None,
    job_title_normalized: str,
    description_raw: str,
    description_clean: str,
    warnings: list[str],
    published_utc: datetime | None,
    field_provenance: dict[str, str],
    company_name_raw: str | None = None,
    location_raw: str | None = None,
) -> ExtractedDetail:
    effective_company_name_raw = task.company_name_raw if company_name_raw is None else company_name_raw
    effective_location_raw = task.location_raw if location_raw is None else location_raw

    return ExtractedDetail(
        scrape_run_id=task.scrape_run_id,
        job_id=task.job_id,
        canonical_job_url=task.canonical_job_url,
        source_host=task.source_host,
        listing_hash=task.listing_hash,
        detail_html_hash=result.detail_html_hash,
        job_title_raw=job_title_raw,
        job_title_normalized=job_title_normalized,
        company_name_raw=effective_company_name_raw,
        company_name_normalized=_normalize_text(effective_company_name_raw),
        company_url_raw=task.company_url_raw,
        company_url_normalized=_normalize_url(task.company_url_raw),
        location_raw=effective_location_raw,
        location_normalized=_normalize_text(effective_location_raw),
        published_raw=task.published_raw,
        published_utc=published_utc,
        banner_image_url_raw=task.banner_image_url_raw,
        footer_image_url_raw=task.footer_image_url_raw,
        job_description_raw=description_raw,
        job_description_clean=description_clean,
        description_text_hash=hashlib.sha256(description_clean.encode("utf-8")).hexdigest(),
        field_provenance=field_provenance,
        extraction_warnings=warnings,
        detail_refresh_reason=task.detail_refresh_reason,
    )


def _extract_title(soup: BeautifulSoup) -> str | None:
    meta_title = soup.find("meta", attrs={"property": OG_TITLE_PROPERTY})
    if meta_title is not None:
        content = meta_title.get("content")
        normalized = _normalize_text(content)
        if normalized:
            return normalized

    if soup.title is not None and soup.title.string:
        normalized = _normalize_text(soup.title.string)
        if normalized:
            return normalized

    heading = soup.find("h1")
    if heading is None:
        return None
    return _normalize_text(heading.get_text(" ", strip=True))


def _extract_description(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    container = soup.find("main") or soup.find("article") or soup.body or soup
    return container.get_text(" ", strip=True)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _normalize_url(value: str | None) -> str | None:
    return _normalize_text(value)


def _extract_hr_manager_title(soup: BeautifulSoup) -> str | None:
    title = _extract_title(soup)
    if title is None:
        return None
    if title.startswith("Talentech - "):
        return _normalize_text(title.removeprefix("Talentech - "))
    return title


def _clean_hr_manager_description(description_text: str | None, job_title_normalized: str) -> str | None:
    normalized = _normalize_text(description_text)
    if not normalized:
        return None

    cleaned = normalized
    for prefix in (
        job_title_normalized,
        "Warning Your browser is outdated.",
        "Get the best experience with speed, security and privacy by using the latest version of Chrome, Firefox, Microsoft Edge, Safari or Opera ×",
    ):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    footer_markers = (
        "APPLY FOR POSITION",
        "Application due",
        "Start date",
        "Work hours",
        "Position category",
        "Position type",
        "Workplace",
        "Homepage",
        "Contact E-mail",
        "Follow us",
        "This website uses cookies",
    )
    for marker in footer_markers:
        marker_index = cleaned.find(marker)
        if marker_index != -1:
            cleaned = cleaned[:marker_index].strip()
            break

    return _normalize_text(cleaned)


def _extract_hr_on_title(soup: BeautifulSoup) -> str | None:
    meta_title = soup.find("meta", attrs={"property": OG_TITLE_PROPERTY})
    if meta_title is not None:
        normalized = _normalize_text(meta_title.get("content"))
        if normalized:
            return normalized

    content = soup.find(id="content")
    if content is not None:
        headings = [
            _normalize_text(heading.get_text(" ", strip=True))
            for heading in content.find_all("h1")
        ]
        headings = [heading for heading in headings if heading]
        if headings:
            return headings[-1]

    return _extract_title(soup)


def _extract_hr_on_description(soup: BeautifulSoup) -> str:
    description_container = soup.select_one("#content > .job .description")
    if description_container is None:
        return ""

    _strip_hr_on_leading_metadata(description_container)
    return description_container.get_text(" ", strip=True)


def _strip_hr_on_leading_metadata(description_container: BeautifulSoup) -> None:
    for child in description_container.find_all(recursive=False):
        child_text = _normalize_text(child.get_text(" ", strip=True))
        if child.name != "h4" or not child_text or not _is_hr_on_metadata_heading(child_text):
            break
        child.decompose()


def _is_hr_on_metadata_heading(text: str) -> bool:
    normalized = text.lower()
    return " · " in text or any(
        marker in normalized
        for marker in ("full-time", "part-time", "on-site", "onsite", "remote", "hybrid", "reports to")
    )


def _extract_csa_jobad_title(soup: BeautifulSoup) -> str | None:
    heading = soup.select_one(".csa_jobadLeft h1.css_headline") or soup.select_one(".csa_jobadLeft h1")
    if heading is not None:
        normalized = _normalize_text(heading.get_text(" ", strip=True))
        if normalized:
            return normalized

    meta_title = soup.find("meta", attrs={"property": OG_TITLE_PROPERTY})
    if meta_title is not None:
        normalized = _normalize_text(meta_title.get("content"))
        if normalized:
            return normalized

    if soup.title is not None and soup.title.string:
        normalized = _normalize_text(soup.title.string)
        if normalized:
            return normalized

    return None


def _extract_signatur_title(soup: BeautifulSoup, company_name_raw: str | None) -> str | None:
    heading = soup.find(id="ctl00_mainContent_contentHeadlineH1") or soup.select_one("h1.content-wrapper-header")
    if heading is not None:
        normalized = _clean_signatur_title_text(
            value=heading.get_text(" ", strip=True),
            company_name_raw=company_name_raw,
        )
        if normalized:
            return normalized

    meta_title = soup.find("meta", attrs={"property": OG_TITLE_PROPERTY})
    if meta_title is not None:
        normalized = _clean_signatur_title_text(
            value=meta_title.get("content"),
            company_name_raw=company_name_raw,
        )
        if normalized:
            return normalized

    return None


def _clean_signatur_title_text(value: str | None, company_name_raw: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None

    company_name_normalized = _normalize_text(company_name_raw)
    if company_name_normalized:
        normalized = re.sub(
            rf"\s+[–-]\s+{re.escape(company_name_normalized)}$",
            "",
            normalized,
            flags=re.IGNORECASE,
        )

    return _normalize_text(normalized)


def _extract_signatur_description(soup: BeautifulSoup) -> str:
    description_container = soup.find(id="ctl00_mainContent_contentBodyOuterDiv")
    if description_container is None:
        return ""
    return description_container.get_text(" ", strip=True)


def _extract_signatur_company_name(soup: BeautifulSoup) -> str | None:
    heading = soup.select_one("h1.page-top-header.special-h1-header") or soup.select_one("h1.page-top-header")
    if heading is None:
        return None
    return _normalize_text(heading.get_text(" ", strip=True))


def _extract_nytlaegejob_description(soup: BeautifulSoup) -> str:
    description_container = soup.select_one(".single_job_listing .job_listing-description") or soup.select_one(
        ".single_job_listing .job-overview-content"
    )
    if description_container is None:
        return ""
    return description_container.get_text(" ", strip=True)


def _extract_nytlaegejob_company_name(soup: BeautifulSoup) -> str | None:
    company_element = soup.select_one(".job-listing-meta .job-company")
    if company_element is None:
        return None
    return _normalize_text(company_element.get_text(" ", strip=True))


def _extract_nytlaegejob_location(soup: BeautifulSoup, company_name_raw: str | None) -> str | None:
    location_element = soup.select_one(".job-listing-meta .location")
    if location_element is None:
        return None

    location = _normalize_text(location_element.get_text(" ", strip=True))
    if not location:
        return None

    company_name_normalized = _normalize_text(company_name_raw)
    if company_name_normalized and location.casefold() == company_name_normalized.casefold():
        return None

    return location


def _extract_nytlaegejob_description_fields(
    soup: BeautifulSoup,
    job_posting: dict[str, object],
    job_title_normalized: str,
) -> tuple[str, str, str, list[str]]:
    description_raw = _clean_html_fragment(job_posting.get("description"))
    description_clean = _normalize_text(description_raw)
    if description_clean:
        return description_raw, description_clean, "nytlaegejob_jsonld", []

    fallback_description = _normalize_text(_extract_nytlaegejob_description(soup))
    if not fallback_description:
        fallback_description = _normalize_text(_extract_description(soup)) or job_title_normalized

    return description_raw, fallback_description, "nytlaegejob_page", ["nytlaegejob_jsonld_description_missing"]


def _build_nytlaegejob_field_provenance(
    task: DetailFetchTask,
    description_provenance: str,
    company_from_job_posting: str | None,
    company_from_meta: str | None,
    location_from_job_posting: str | None,
    location_from_meta: str | None,
) -> dict[str, str]:
    return {
        "job_description_clean": description_provenance,
        "job_title_normalized": "nytlaegejob_jsonld",
        "company_name_normalized": _field_provenance(
            listing_value=task.company_name_raw,
            primary_value=company_from_job_posting,
            primary_label="nytlaegejob_jsonld",
            fallback_value=company_from_meta,
            fallback_label="nytlaegejob_meta",
        ),
        "company_url_normalized": "listing" if task.company_url_raw else "missing",
        "location_normalized": _field_provenance(
            listing_value=task.location_raw,
            primary_value=location_from_job_posting,
            primary_label="nytlaegejob_jsonld",
            fallback_value=location_from_meta,
            fallback_label="nytlaegejob_meta",
        ),
    }


def _field_provenance(
    listing_value: str | None,
    primary_value: str | None,
    primary_label: str,
    fallback_value: str | None = None,
    fallback_label: str | None = None,
) -> str:
    if listing_value:
        return "listing"
    if primary_value:
        return primary_label
    if fallback_value and fallback_label:
        return fallback_label
    return "missing"


def _extract_emply_title(soup: BeautifulSoup) -> str | None:
    normalized = _extract_csa_jobad_title(soup)
    return _clean_emply_title_text(normalized)


def _clean_emply_title_text(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None

    normalized = re.sub(r"\s+[Ii]\s+Career Site$", "", normalized)
    return _normalize_text(normalized)


def _extract_emply_description(soup: BeautifulSoup) -> str:
    description_container = soup.select_one(".csa_jobadLeft .csa_jobadText")
    if description_container is None:
        return ""
    return description_container.get_text(" ", strip=True)


def _extract_emply_company_name(soup: BeautifulSoup) -> str | None:
    return _extract_emply_info_value(
        soup=soup,
        labels=("company", "virksomhed", "organisation", "organization"),
    )


def _extract_emply_location(soup: BeautifulSoup) -> str | None:
    return _extract_emply_info_value(
        soup=soup,
        labels=("lokation", "location", "arbejdssted", "sted"),
    )


def _extract_emply_info_value(soup: BeautifulSoup, labels: tuple[str, ...]) -> str | None:
    info_items = _extract_emply_info_items(soup)
    for label in labels:
        value = info_items.get(label)
        if value:
            return value
    return None


def _extract_emply_info_items(soup: BeautifulSoup) -> dict[str, str]:
    info_items: dict[str, str] = {}
    for item in soup.select(".csa_jobadInfoItem"):
        label_element = item.find("strong")
        if label_element is None:
            continue

        label = _normalize_text(label_element.get_text(" ", strip=True))
        if not label:
            continue

        normalized_label = label.removesuffix(":").lower()
        item_text = _normalize_text(item.get_text(" ", strip=True))
        if not item_text:
            continue

        value = item_text.removeprefix(label).strip()
        value = _normalize_text(value)
        if value:
            info_items[normalized_label] = value

    return info_items


def _extract_job_posting_jsonld(soup: BeautifulSoup) -> dict[str, object] | None:
    for script_tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = script_tag.string or script_tag.get_text(strip=True)
        if not script_text:
            continue
        try:
            payload = json.loads(script_text)
        except json.JSONDecodeError:
            continue
        job_posting = _find_job_posting_jsonld(payload)
        if job_posting is not None:
            return job_posting
    return None


def _find_job_posting_jsonld(payload: object) -> dict[str, object] | None:
    for candidate in _iter_jsonld_dicts(payload):
        if _is_job_posting_payload(candidate):
            return candidate

    return None


def _iter_jsonld_dicts(payload: object):
    if isinstance(payload, dict):
        yield payload

        graph = payload.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_jsonld_dicts(item)
        return

    if isinstance(payload, list):
        for item in payload:
            yield from _iter_jsonld_dicts(item)


def _is_job_posting_payload(payload: dict[str, object]) -> bool:
    payload_type = payload.get("@type")
    if isinstance(payload_type, str):
        return payload_type == "JobPosting"
    if isinstance(payload_type, list):
        return any(item == "JobPosting" for item in payload_type if isinstance(item, str))
    return False


def _extract_job_posting_company_name(job_posting: dict[str, object]) -> str | None:
    hiring_organization = job_posting.get("hiringOrganization")
    if not isinstance(hiring_organization, dict):
        return None
    return _normalize_text(hiring_organization.get("name"))


def _extract_job_posting_location(job_posting: dict[str, object]) -> str | None:
    job_location = job_posting.get("jobLocation")
    location_candidates: list[dict[str, object]] = []
    if isinstance(job_location, dict):
        location_candidates.append(job_location)
    elif isinstance(job_location, list):
        location_candidates.extend(
            candidate for candidate in job_location if isinstance(candidate, dict)
        )

    for candidate in location_candidates:
        address = candidate.get("address")
        if not isinstance(address, dict):
            continue
        parts = [
            _normalize_text(address.get("addressLocality")),
            _normalize_text(address.get("addressRegion")),
            _normalize_text(address.get("addressCountry")),
        ]
        filtered_parts = [part for part in parts if part]
        if filtered_parts:
            return ", ".join(filtered_parts)

    return None


def _clean_html_fragment(value: object) -> str:
    if not isinstance(value, str):
        return ""
    fragment = BeautifulSoup(html.unescape(value), "html.parser")
    return fragment.get_text(" ", strip=True)


def _platform_domain_for_host(source_host: str) -> str:
    normalized_host = _normalize_host(source_host)
    labels = normalized_host.split(".")
    if len(labels) <= 2:
        return normalized_host
    return ".".join(labels[-2:])


def _normalize_host(source_host: str) -> str:
    return source_host.strip().lower().rstrip(".")


def _parse_published_datetime(value: str | None) -> datetime | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None

    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None