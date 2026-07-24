from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from breachgazette.privacy.audit import (
    PrivacyAuditError,
    audit_public_value,
    csv_safe,
    require_public_safe,
)


@pytest.mark.parametrize(
    ("value", "detector"),
    [
        ("person@example.org", "personal_email"),
        ("02 9876 5432", "australian_phone"),
        ("12 Example Street", "street_address"),
        ("password=hunter2", "credential_pattern"),
        ("<script>alert(1)</script>", "html_or_script"),
        ("safe\u202eevil", "bidi_control"),
        ("\x01control", "control_character"),
        ("=SUM(A1:A2)", "csv_formula"),
    ],
)
def test_sensitive_and_hostile_text_is_rejected(value: str, detector: str) -> None:
    findings = audit_public_value({"field": value}, record_identity="test")
    assert detector in {finding.detector_id for finding in findings}
    assert all(value not in finding.redacted_fingerprint for finding in findings)


def test_unsafe_urls_and_complete_html_are_rejected() -> None:
    findings = audit_public_value(
        {"source_url": "https://user:secret@example.gov/path"},
        record_identity="url",
    )
    assert [finding.detector_id for finding in findings] == ["unsafe_url"]
    with pytest.raises(PrivacyAuditError, match="html_or_script"):
        require_public_safe({"narrative": "<p>complete notification</p>"}, record_identity="record")


def test_safe_source_record_passes() -> None:
    require_public_safe(
        {"source_url": "https://example.gov/source", "organization": "Example Health"},
        record_identity="record",
    )


def test_opaque_identifiers_do_not_trigger_phone_detectors() -> None:
    require_public_safe(
        {
            "source_record_id": "ca:743bf4be2c0339299357d76d:1",
            "record_ids": ["ca:077065575516518341c47b1d:1"],
            "source_revision": "293f77604737bf7a",
            "canonical_organization_id": "org_0479028280477635",
            "query_bloom": "020478026102047802610204780261",
            "sha256": "aaaaaaaaaa0298765432bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "snapshot_checksum": (
                "cccccccccc0298765432dddddddddddddddddddddddddddddddddddddddddddd"
            ),
            "organization": "Outcomes One, Inc.",
        },
        record_identity="record",
    )
    findings = audit_public_value(
        {"summary": "Checksum-like text 0298765432 remains source content."},
        record_identity="record",
    )
    assert "australian_phone" in {finding.detector_id for finding in findings}


@given(st.text(max_size=200))
def test_csv_safety_never_leaves_a_formula_prefix(value: str) -> None:
    safe = csv_safe(value)
    if isinstance(safe, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        assert safe.startswith("'")
