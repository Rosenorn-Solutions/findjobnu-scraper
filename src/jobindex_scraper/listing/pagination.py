from __future__ import annotations

from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from ..catalog import JOBINDEX_BASE_URL


def extract_next_page_url(stash_payload: dict[str, Any], current_page_url: str) -> str | None:
    current_page_number = _page_number(current_page_url)

    derived_url = _derive_next_page_from_search_response(
        stash_payload=stash_payload,
        current_page_number=current_page_number,
    )
    if derived_url is not None:
        return derived_url

    candidates: list[tuple[int, str]] = []

    for value in _iter_string_values(stash_payload):
        if "/jobsoegning" not in value or "page=" not in value:
            continue
        if "/jobannonce/" in value:
            continue

        absolute_url = urljoin(JOBINDEX_BASE_URL, value)
        split_url = urlsplit(absolute_url)
        if split_url.netloc and "jobindex.dk" not in split_url.netloc:
            continue

        page_number = _page_number(absolute_url)
        if page_number > current_page_number:
            candidates.append((page_number, absolute_url))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def _derive_next_page_from_search_response(
    stash_payload: dict[str, Any],
    current_page_number: int,
) -> str | None:
    search_response = _extract_search_response(stash_payload)
    if not isinstance(search_response, dict):
        return None

    canonical_url = search_response.get("link_canonical")
    total_pages = search_response.get("total_pages")
    if not isinstance(canonical_url, str):
        return None
    if not isinstance(total_pages, int):
        return None
    if current_page_number >= total_pages:
        return None

    absolute_url = urljoin(JOBINDEX_BASE_URL, canonical_url)
    return _with_page_number(absolute_url, current_page_number + 1)


def _extract_search_response(stash_payload: dict[str, Any]) -> dict[str, Any] | None:
    result_app = stash_payload.get("jobsearch/result_app")
    if not isinstance(result_app, dict):
        return None
    store_data = result_app.get("storeData")
    if not isinstance(store_data, dict):
        return None
    search_response = store_data.get("searchResponse")
    if not isinstance(search_response, dict):
        return None
    return search_response


def _iter_string_values(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
        return
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_string_values(value)
        return
    if isinstance(node, list):
        for item in node:
            yield from _iter_string_values(item)


def _page_number(url: str) -> int:
    query = parse_qs(urlsplit(url).query)
    page_values = query.get("page")
    if not page_values:
        return 1
    try:
        return int(page_values[0])
    except (TypeError, ValueError):
        return 1


def _with_page_number(url: str, page_number: int) -> str:
    split_url = urlsplit(url)
    query = parse_qs(split_url.query, keep_blank_values=True)
    query["page"] = [str(page_number)]
    normalized_query = urlencode(query, doseq=True)
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            normalized_query,
            "",
        )
    )
