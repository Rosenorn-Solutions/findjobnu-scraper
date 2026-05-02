from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..catalog import JOBINDEX_BASE_URL
from ..models import CategoryRecord, ListingObservation, ListingPageResult
from .pagination import extract_next_page_url


STASH_MARKER = "var Stash ="


class ListingParseError(ValueError):
    pass


def parse_jobindex_listing_page(
    html_content: str,
    category: CategoryRecord,
    page_url: str,
) -> ListingPageResult:
    stash_payload = extract_stash_payload(html_content)
    next_page_url = extract_next_page_url(stash_payload, page_url)
    observations: list[ListingObservation] = []
    seen_urls: set[str] = set()

    for default_position, fragment_html in enumerate(_iter_listing_fragments(stash_payload), start=1):
        observation = _parse_listing_fragment(
            fragment_html=fragment_html,
            category=category,
            page_url=page_url,
            default_position=default_position,
        )
        if observation is None:
            continue
        if observation.canonical_job_url in seen_urls:
            continue
        seen_urls.add(observation.canonical_job_url)
        observations.append(observation)

    return ListingPageResult(
        page_url=page_url,
        next_page_url=next_page_url,
        observations=tuple(observations),
    )


def extract_stash_payload(html_content: str) -> dict[str, Any]:
    soup = BeautifulSoup(html_content, "html.parser")
    for script in soup.find_all("script"):
        script_text = script.get_text(" ", strip=False)
        if STASH_MARKER not in script_text:
            continue
        return _parse_stash_script(script_text)
    raise ListingParseError("Could not find Jobindex Stash payload in listing HTML.")


def _parse_stash_script(script_text: str) -> dict[str, Any]:
    marker_index = script_text.index(STASH_MARKER) + len(STASH_MARKER)
    brace_start = script_text.index("{", marker_index)
    brace_end = _find_matching_brace(script_text, brace_start)
    payload_text = script_text[brace_start:brace_end]

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as error:
        raise ListingParseError("Failed to decode Jobindex Stash JSON payload.") from error

    if not isinstance(payload, dict):
        raise ListingParseError("Decoded Stash payload was not a JSON object.")
    return payload


def _find_matching_brace(script_text: str, brace_start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    quote_char = ""

    for index in range(brace_start, len(script_text)):
        character = script_text[index]

        consumed, in_string, escape, quote_char = _consume_string_character(
            character=character,
            in_string=in_string,
            escape=escape,
            quote_char=quote_char,
        )
        if consumed:
            continue

        if character == "{":
            depth += 1
            continue
        if character == "}":
            depth -= 1
            if depth == 0:
                return index + 1

    raise ListingParseError("Could not find the end of the Jobindex Stash payload.")


def _consume_string_character(
    character: str,
    in_string: bool,
    escape: bool,
    quote_char: str,
) -> tuple[bool, bool, bool, str]:
    if in_string:
        if escape:
            return True, True, False, quote_char
        if character == "\\":
            return True, True, True, quote_char
        if character == quote_char:
            return True, False, False, ""
        return True, True, False, quote_char

    if character in ('"', "'"):
        return True, True, False, character
    return False, False, False, ""


def _iter_listing_fragments(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        html_fragment = node.get("html")
        if isinstance(html_fragment, str) and "jobad-wrapper-" in html_fragment:
            yield html_fragment
        for value in node.values():
            yield from _iter_listing_fragments(value)
        return
    if isinstance(node, list):
        for item in node:
            yield from _iter_listing_fragments(item)


def _parse_listing_fragment(
    fragment_html: str,
    category: CategoryRecord,
    page_url: str,
    default_position: int,
) -> ListingObservation | None:
    soup = BeautifulSoup(fragment_html, "html.parser")
    root = soup.find("div", id=re.compile(r"^jobad-wrapper-"))
    if root is None:
        return None

    title_anchor = root.select_one("h4 a")
    if title_anchor is None:
        return None

    job_url_raw = title_anchor.get("href")
    if not job_url_raw:
        return None

    job_title_raw = _normalize_text(title_anchor.get_text(" ", strip=True))
    canonical_job_url = _canonicalize_url(job_url_raw)
    source_host = urlsplit(canonical_job_url).netloc

    company_anchor = root.select_one("div.jix-toolbar-top__company a")
    company_name_raw = _normalize_text(company_anchor.get_text(" ", strip=True)) if company_anchor else None
    company_url_raw = company_anchor.get("href") if company_anchor else None

    location_tag = root.select_one("div.jobad-element-area span")
    location_raw = _normalize_text(location_tag.get_text(" ", strip=True)) if location_tag else None

    time_tag = root.select_one("div.jix-toolbar__pubdate time")
    published_raw = time_tag.get("datetime") if time_tag else None

    banner_image_url_raw, footer_image_url_raw = _extract_image_urls(root)

    position_value = root.get("data-jobsearch_position")
    try:
        listing_position = int(position_value) if position_value else default_position
    except ValueError:
        listing_position = default_position

    listing_hash = _build_listing_hash(
        canonical_job_url=canonical_job_url,
        job_title_raw=job_title_raw,
        company_name_raw=company_name_raw,
        published_raw=published_raw,
        location_raw=location_raw,
    )

    return ListingObservation(
        listing_page_url=page_url,
        category_key=category.category_key,
        category_name=category.category_name,
        listing_position=listing_position,
        job_url_raw=job_url_raw,
        canonical_job_url=canonical_job_url,
        source_host=source_host,
        job_title_raw=job_title_raw,
        company_name_raw=company_name_raw,
        company_url_raw=company_url_raw,
        location_raw=location_raw,
        published_raw=published_raw,
        banner_image_url_raw=banner_image_url_raw,
        footer_image_url_raw=footer_image_url_raw,
        listing_hash=listing_hash,
    )


def _extract_image_urls(root: BeautifulSoup) -> tuple[str | None, str | None]:
    image_tags = root.select("div.PaidJob-inner center img")
    if not image_tags:
        return None, None
    banner_url = image_tags[0].get("src")
    footer_url = image_tags[-1].get("src")
    return banner_url, footer_url


def _build_listing_hash(
    canonical_job_url: str,
    job_title_raw: str | None,
    company_name_raw: str | None,
    published_raw: str | None,
    location_raw: str | None,
) -> str:
    digest_input = "\x1f".join(
        [
            canonical_job_url,
            job_title_raw or "",
            company_name_raw or "",
            published_raw or "",
            location_raw or "",
        ]
    )
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def _canonicalize_url(raw_url: str) -> str:
    absolute_url = urljoin(JOBINDEX_BASE_URL, raw_url)
    split_url = urlsplit(absolute_url)
    normalized_query = sorted(parse_qsl(split_url.query, keep_blank_values=True))
    query_text = "&".join(f"{key}={value}" for key, value in normalized_query)
    return urlunsplit(
        (
            split_url.scheme.lower(),
            split_url.netloc.lower(),
            split_url.path,
            query_text,
            "",
        )
    )


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None
