"""Offline reconstruction of legacy metric context from exact workbook evidence."""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from breachgazette.clients.oaic import EXPECTED_SHEETS, ROOT_CAUSES, OaicNdbAdapter
from breachgazette.clients.xlsx import bounded_workbook
from breachgazette.contracts import SourceAggregateRecord
from breachgazette.contracts.models import RecordProvenance
from breachgazette.utils import normalize_text, sha256_hex


def review_legacy_workbook(
    records: list[SourceAggregateRecord], workbook_path: Path
) -> tuple[dict[str, str], dict[str, str], dict[str, str], str]:
    """Return a verified ID bridge, parent repairs, representatives and evidence checksum."""
    if not records:
        raise ValueError("review requires nonempty legacy metrics")
    if not workbook_path.is_file() or workbook_path.stat().st_size > 10_000_000:
        raise ValueError("review evidence must be a bounded workbook")
    content = workbook_path.read_bytes()
    checksum = sha256_hex(content)
    first = records[0]
    if not all(
        record.source_id == "oaic_ndb"
        and record.normalization_version == "1.0"
        and record.source_checksum == checksum
        and record.source_revision == first.source_revision
        and record.reporting_period_start == first.reporting_period_start
        and record.reporting_period_end == first.reporting_period_end
        for record in records
    ):
        raise ValueError("workbook evidence does not match the legacy generation")
    resource_id, modified = first.source_revision.split(":", 1)
    resource = {
        "id": resource_id,
        "name": (
            f"NDB Data {first.reporting_period_start:%d %B %Y} "
            f"to {first.reporting_period_end:%d %b %Y}"
        ),
    }
    rows: dict[tuple[str, int], str] = {}
    with bounded_workbook(
        content,
        max_rows=5_000,
        max_columns=64,
        max_entry_bytes=20_000_000,
        max_expanded_bytes=60_000_000,
    ) as workbook:
        header = next(
            workbook["Source of breach"].iter_rows(
                min_row=1,
                max_row=1,
                max_col=1,
                values_only=True,
            ),
            (None,),
        )[0]
        if not isinstance(header, str):
            raise ValueError("workbook period heading must be text")
        heading = normalize_text(header, maximum=500)
        period = re.search(r"([A-Za-z]+)\s*[-\u2013\u2014]\s*([A-Za-z]+)\s+(\d{4})", heading)
        if period is None:
            raise ValueError("workbook heading does not establish the reviewed reporting period")
        start = datetime.strptime(f"1 {period[1]} {period[3]}", "%d %B %Y").date()
        end = datetime.strptime(f"1 {period[2]} {period[3]}", "%d %B %Y").date()
        end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
        if (start, end) != (first.reporting_period_start, first.reporting_period_end):
            raise ValueError("workbook heading conflicts with the legacy reporting period")
        parsed = OaicNdbAdapter()._parse(
            workbook,
            resource,
            {"metadata_modified": modified},
            content,
            first.source_retrieval_time,
            identity_rows=rows,
        )
    current = {
        record.source_record_id: record
        for record in parsed.records
        if isinstance(record, SourceAggregateRecord)
    }
    mapping: dict[str, str] = {}
    parents: dict[str, str] = {}
    grouped: dict[str, list[SourceAggregateRecord]] = defaultdict(list)
    reviewed_rows: set[tuple[str, int]] = set()
    for record in records:
        sheet, offset, signature = record.source_record_id.rsplit(":", 2)
        row = (sheet, int(offset))
        if (
            sheet not in EXPECTED_SHEETS[1:]
            or row in reviewed_rows
            or signature
            != sha256_hex([record.category, record.parent_category, record.value.value])[:12]
            or row not in rows
        ):
            raise ValueError("legacy row identity does not match the reviewed evidence")
        reviewed_rows.add(row)
        candidate = current[rows[row]]
        exclusions = set(RecordProvenance.model_fields) | {"parent_category"}
        if record.model_dump(exclude=exclusions) != candidate.model_dump(exclude=exclusions):
            raise ValueError("review evidence would change an unsupported metric field")
        if record.parent_category != candidate.parent_category:
            if not (
                sheet == "Top 5 sectors by source"
                and record.category in ROOT_CAUSES
                and record.parent_category is None
                and candidate.parent_category is not None
            ):
                raise ValueError("review evidence contains an unsupported context transition")
            parents[record.source_record_id] = candidate.parent_category
        mapping[record.source_record_id] = candidate.source_record_id
        grouped[candidate.source_record_id].append(record)
    if reviewed_rows != set(rows) or set(grouped) != set(current):
        raise ValueError("review evidence does not cover the complete legacy generation")
    representatives: dict[str, str] = {}
    for identity, group in grouped.items():
        selected = min(group, key=lambda record: int(record.source_record_id.rsplit(":", 2)[1]))
        if any(
            record.model_dump(exclude={"source_record_id"})
            != selected.model_dump(exclude={"source_record_id"})
            for record in group
        ):
            raise ValueError("repeated metrics do not have identical values and provenance")
        representatives[identity] = selected.source_record_id
    return mapping, parents, representatives, checksum
