from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib
import time

import requests
from requests import Session

from ..config import Settings
from ..http.client import build_session
from ..models import DetailFetchResult, DetailFetchTask


class JobDetailFetcher:
    def __init__(self, settings: Settings, session: Session | None = None) -> None:
        self.settings = settings
        self.session = session or build_session(settings)

    def fetch_tasks(
        self,
        tasks: Sequence[DetailFetchTask],
        max_tasks: int | None = None,
    ) -> list[DetailFetchResult]:
        if max_tasks is not None and max_tasks < 1:
            raise ValueError("max_tasks must be at least 1 when provided")

        selected_tasks = list(tasks)
        if max_tasks is not None:
            selected_tasks = selected_tasks[:max_tasks]

        return [self.fetch_task(task) for task in selected_tasks]

    def fetch_task(self, task: DetailFetchTask) -> DetailFetchResult:
        started = time.perf_counter()
        fetched_at = datetime.now(timezone.utc)

        try:
            response = self.session.get(
                task.canonical_job_url,
                timeout=self.settings.http_timeout_seconds,
            )
        except requests.RequestException as error:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            response_url = None
            http_status = None
            if getattr(error, "response", None) is not None:
                response_url = getattr(error.response, "url", None)
                http_status = getattr(error.response, "status_code", None)
            return DetailFetchResult(
                scrape_run_id=task.scrape_run_id,
                job_id=task.job_id,
                canonical_job_url=task.canonical_job_url,
                source_host=task.source_host,
                response_url=response_url,
                http_status=http_status,
                fetched_at=fetched_at,
                elapsed_ms=elapsed_ms,
                detail_html_hash=None,
                detail_refresh_reason=task.detail_refresh_reason,
                error_message=str(error).strip() or error.__class__.__name__,
                html_content=None,
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        detail_html_hash = None
        error_message = None
        if _is_success_status(response.status_code):
            detail_html_hash = hashlib.sha256(response.content).hexdigest()
        else:
            error_message = f"HTTP {response.status_code}"

        return DetailFetchResult(
            scrape_run_id=task.scrape_run_id,
            job_id=task.job_id,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=response.url,
            http_status=response.status_code,
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
            detail_html_hash=detail_html_hash,
            detail_refresh_reason=task.detail_refresh_reason,
            error_message=error_message,
            html_content=response.text if _is_success_status(response.status_code) else None,
        )


def _is_success_status(http_status: int | None) -> bool:
    if http_status is None:
        return False
    return 200 <= http_status < 400