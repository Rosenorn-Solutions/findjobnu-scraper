from __future__ import annotations

from .models import CategoryRecord


JOBINDEX_BASE_URL = "https://www.jobindex.dk"


def category_from_subid(subid: int) -> CategoryRecord:
    category_key = f"subid_{subid}"
    return CategoryRecord(
        category_key=category_key,
        category_name=category_key,
        listing_url=f"{JOBINDEX_BASE_URL}/jobsoegning?subid={subid}",
    )
