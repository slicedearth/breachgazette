"""Privacy detectors applied before state, publication, and built-output release."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from breachgazette.contracts.models import QualityFinding
from breachgazette.utils import canonical_data, sha256_hex


class PrivacyAuditError(RuntimeError):
    """Raised when source-derived values violate the publication contract."""


@dataclass(frozen=True, slots=True)
class Detector:
    detector_id: str
    pattern: re.Pattern[str]
    reason: str


DETECTORS = (
    Detector(
        "personal_email",
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        "email address",
    ),
    Detector(
        "telephone_number",
        re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-])\d{3}[\s.-]\d{4}(?!\d)"),
        "telephone number",
    ),
    Detector(
        "australian_phone",
        re.compile(r"(?<!\d)(?:\+?61[\s.-]?|0)[2-478](?:[\s.-]?\d){8}(?!\d)"),
        "telephone number",
    ),
    Detector(
        "street_address",
        re.compile(
            r"(?i)\b\d{1,6}\s+[A-Z0-9.' -]{2,80}\s+"
            r"(?:street|st|road|rd|avenue|ave|boulevard|blvd|lane|ln|drive|dr|court|ct)\b"
        ),
        "street address",
    ),
    Detector(
        "government_identifier",
        re.compile(
            r"(?i)\b(?:SSN|TFN|Medicare|passport|driver(?:'s)? licence)\s*[:#]\s*[A-Z0-9-]{5,}"
        ),
        "government identifier",
    ),
    Detector(
        "credential_pattern",
        re.compile(r"(?i)\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+"),
        "credential-like value",
    ),
    Detector(
        "html_or_script",
        re.compile(r"(?is)<\s*(?:script|iframe|object|embed|style|[a-z][^>]*)>|on\w+\s*="),
        "HTML, script, or event handler",
    ),
    Detector(
        "bidi_control",
        re.compile("[\u202a-\u202e\u2066-\u2069]"),
        "bidirectional control character",
    ),
    Detector(
        "control_character",
        re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
        "control character",
    ),
)

SKIP_TEXT_DETECTORS_FOR_FIELDS = {
    "candidate_id",
    "canonical_organization_id",
    "event_id",
    "matter_id",
    "organization_id",
    "record_ids",
    "redacted_fingerprint",
    "sha256",
    "snapshot_checksum",
    "source_record_id",
    "source_revision",
    "source_url",
    "source_detail_url",
    "fixed_urls",
    "source_checksum",
    "checksum_sha256",
    "publication_checksum",
    "query_bloom",
}


def csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return f"'{value}"
    return value


def _walk(value: Any, path: str = "$") -> list[tuple[str, Any]]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        result: list[tuple[str, Any]] = []
        for key, item in value.items():
            result.extend(_walk(item, f"{path}.{key}"))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = []
        for index, item in enumerate(value):
            result.extend(_walk(item, f"{path}[{index}]"))
        return result
    return [(path, value)]


def _finding(
    detector_id: str,
    field: str,
    reason: str,
    value: str,
    record_identity: str,
) -> QualityFinding:
    return QualityFinding(
        detector_id=detector_id,
        field=field,
        reason=reason,
        redacted_fingerprint=sha256_hex(value)[:16],
        record_identity=record_identity,
        outcome="rejected",
    )


def audit_public_value(value: Any, *, record_identity: str) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for field, item in _walk(canonical_data(value)):
        leaf = re.sub(r"\[\d+\]", "", field.rsplit(".", 1)[-1])
        if not isinstance(item, str):
            continue
        if len(item) > 20_000:
            findings.append(
                _finding(
                    "unexpectedly_long_text",
                    field,
                    "source text exceeded the 20,000-character publication limit",
                    item,
                    record_identity,
                )
            )
        if leaf in SKIP_TEXT_DETECTORS_FOR_FIELDS:
            try:
                parsed = urlparse(item)
                if leaf.endswith("url") and (
                    parsed.scheme != "https"
                    or parsed.username
                    or parsed.password
                    or parsed.scheme in {"javascript", "data", "file", "vbscript"}
                ):
                    findings.append(
                        _finding(
                            "unsafe_url",
                            field,
                            "URL was not credential-free HTTPS",
                            item,
                            record_identity,
                        )
                    )
            except ValueError:
                findings.append(
                    _finding("unsafe_url", field, "URL could not be parsed", item, record_identity)
                )
            continue
        for detector in DETECTORS:
            if detector.pattern.search(item):
                findings.append(
                    _finding(
                        detector.detector_id,
                        field,
                        detector.reason,
                        item,
                        record_identity,
                    )
                )
        if item.startswith(("=", "+", "@", "\t", "\r", "\n")):
            findings.append(
                _finding(
                    "csv_formula",
                    field,
                    "text could be interpreted as a spreadsheet formula",
                    item,
                    record_identity,
                )
            )
    return findings


def require_public_safe(value: Any, *, record_identity: str) -> None:
    findings = audit_public_value(value, record_identity=record_identity)
    if findings:
        detectors = ", ".join(sorted({finding.detector_id for finding in findings}))
        fields = ", ".join(sorted({finding.field for finding in findings})[:5])
        raise PrivacyAuditError(
            f"privacy audit rejected {record_identity}: {detectors} in {fields}"
        )
