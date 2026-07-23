"""Shared bounded transport used only through fixed source-specific adapters."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from breachgazette.contracts import SourceSnapshot
from breachgazette.contracts.models import RecordProvenance


class SourceClientError(RuntimeError):
    """Raised when an official source cannot be retrieved or safely interpreted."""


@dataclass(slots=True)
class AdapterResult:
    source_id: str
    records: list[RecordProvenance]
    snapshot: SourceSnapshot
    rejected: list[dict[str, str]] = field(default_factory=list)


class BoundedSourceClient:
    """HTTPS-only client with exact origins, path prefixes, retries, and byte caps."""

    def __init__(
        self,
        *,
        allowed_origins: set[str],
        allowed_path_prefixes: tuple[str, ...],
        max_response_bytes: int,
        timeout_seconds: float = 30.0,
        total_deadline_seconds: float = 90.0,
        max_retries: int = 2,
        rate_delay_seconds: float = 0.05,
        transport: httpx.BaseTransport | None = None,
        user_agent: str = "Mozilla/5.0 (compatible; public-data-research/1.0)",
    ) -> None:
        self.allowed_origins = allowed_origins
        self.allowed_path_prefixes = allowed_path_prefixes
        self.max_response_bytes = max_response_bytes
        self.total_deadline_seconds = total_deadline_seconds
        self.max_retries = max_retries
        self.rate_delay_seconds = rate_delay_seconds
        self._started = time.monotonic()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": user_agent,
            },
        )

    def __enter__(self) -> BoundedSourceClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise SourceClientError("source URL must be credential-free HTTPS")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.allowed_origins:
            raise SourceClientError("source URL origin is not allowlisted")
        if not any(parsed.path.startswith(prefix) for prefix in self.allowed_path_prefixes):
            raise SourceClientError("source URL path is not allowlisted")

    def _deadline(self) -> None:
        if time.monotonic() - self._started > self.total_deadline_seconds:
            raise SourceClientError("source request exceeded the total deadline")

    def get_bytes(self, url: str, *, accept: str) -> tuple[bytes, httpx.Headers, str]:
        self._validate_url(url)
        current = url
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._deadline()
            try:
                for _redirect in range(4):
                    self._validate_url(current)
                    with self._client.stream(
                        "GET", current, headers={"Accept": accept}
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise SourceClientError("source redirect omitted Location")
                            candidate = urljoin(current, location)
                            self._validate_url(candidate)
                            current = candidate
                            continue
                        if response.status_code == 429 or response.status_code >= 500:
                            response.raise_for_status()
                        response.raise_for_status()
                        content_length = response.headers.get("Content-Length")
                        if content_length and int(content_length) > self.max_response_bytes:
                            raise SourceClientError(
                                "source response exceeded the compressed byte cap"
                            )
                        chunks: list[bytes] = []
                        total = 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > self.max_response_bytes:
                                raise SourceClientError(
                                    "source response exceeded the decompressed byte cap"
                                )
                            chunks.append(chunk)
                        time.sleep(self.rate_delay_seconds)
                        return b"".join(chunks), response.headers, str(response.url)
                raise SourceClientError("source exceeded the redirect limit")
            except (httpx.HTTPError, SourceClientError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(min(2**attempt, 4))
        raise SourceClientError("official source request failed safely") from last_error

    def get_json(self, url: str) -> tuple[Any, httpx.Headers, str]:
        content, headers, final_url = self.get_bytes(
            url,
            accept="application/json",
        )
        content_type = headers.get("Content-Type", "").lower()
        if "json" not in content_type and not final_url.endswith(".json"):
            raise SourceClientError("source returned an unexpected JSON content type")
        try:
            return json.loads(content), headers, final_url
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceClientError("source returned malformed JSON") from exc

    def get_text(self, url: str, *, accept: str = "text/html") -> tuple[str, httpx.Headers, str]:
        content, headers, _final_url = self.get_bytes(url, accept=accept)
        content_type = headers.get("Content-Type", "").lower()
        if accept == "text/html" and "html" not in content_type:
            raise SourceClientError("source returned an unexpected HTML content type")
        try:
            return content.decode("utf-8"), headers, _final_url
        except UnicodeDecodeError as exc:
            raise SourceClientError("source text was not UTF-8") from exc


def source_snapshot(
    *,
    source_id: str,
    retrieved_at: datetime,
    revision: str,
    checksum: str,
    completeness: str,
    discovered: int,
    accepted: int,
    rejected: int,
    bounded_limit: int,
    source_updated_at: datetime | None = None,
    notes: list[str] | None = None,
) -> SourceSnapshot:
    completed_at = datetime.now(UTC)
    return SourceSnapshot(
        source_id=source_id,
        retrieved_at=retrieved_at,
        completed_at=completed_at,
        revision=revision,
        checksum_sha256=checksum,
        completeness=completeness,
        records_discovered=discovered,
        records_accepted=accepted,
        records_rejected=rejected,
        bounded_limit=bounded_limit,
        source_updated_at=source_updated_at,
        last_successful_complete_update=(completed_at if completeness == "complete" else None),
        latest_attempted_update=retrieved_at,
        notes=notes or [],
    )
