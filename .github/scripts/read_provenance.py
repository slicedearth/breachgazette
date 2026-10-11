"""Read a bounded provenance record without extracting an artifact to disk."""

from __future__ import annotations

import io
import json
import stat
import sys
import zipfile

ARTIFACT_LIMIT = 128 * 1024 * 1024
RECORD_LIMIT = 16 * 1024


def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate provenance field")
        result[key] = value
    return result


def read_provenance(data: bytes) -> dict[str, object]:
    if not data or len(data) > ARTIFACT_LIMIT:
        raise ValueError("Invalid artifact size")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if sorted(entry.filename for entry in entries) != [
            "breachgazette-site.zip", "deployment-provenance.json"
        ] or any(stat.S_ISLNK(entry.external_attr >> 16) for entry in entries):
            raise ValueError("Unexpected artifact entries")
        record = archive.getinfo("deployment-provenance.json")
        if record.file_size > RECORD_LIMIT or record.flag_bits & 1:
            raise ValueError("Invalid provenance record size or encoding")
        with archive.open(record) as stream:
            raw = stream.read(RECORD_LIMIT + 1)
        if len(raw) > RECORD_LIMIT:
            raise ValueError("Provenance record is too large")
        result = json.loads(raw, object_pairs_hook=unique_fields)
        if not isinstance(result, dict):
            raise ValueError("Provenance must be an object")
        return result


if __name__ == "__main__":
    try:
        print(json.dumps(read_provenance(sys.stdin.buffer.read(ARTIFACT_LIMIT + 1))))
    except (ValueError, OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
        sys.exit("Deployment provenance archive is invalid or unavailable.")
