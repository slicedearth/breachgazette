from __future__ import annotations

import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github/scripts/read_provenance.py"
spec = importlib.util.spec_from_file_location("read_provenance", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def artifact(record: bytes, extra: str | None = None, symlink: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("breachgazette-site.zip", b"synthetic public archive")
        info = zipfile.ZipInfo("deployment-provenance.json")
        if symlink:
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, record)
        if extra:
            archive.writestr(extra, b"unexpected")
    return output.getvalue()


def test_reads_bounded_record_without_extracting_archive(tmp_path: Path) -> None:
    record = {"schema_version": "1.1", "publication_checksum": "c" * 64}
    assert module.read_provenance(artifact(json.dumps(record).encode())) == record
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("extra", ["../outside.json", "subdir/record.json", "extra.json"])
def test_rejects_unexpected_or_traversal_entries(extra: str) -> None:
    with pytest.raises(ValueError, match="entries"):
        module.read_provenance(artifact(b"{}", extra=extra))


@pytest.mark.parametrize(
    "record", [b"{", b"[]", b"x" * 16385, b'{"checksum":"one","checksum":"two"}']
)
def test_rejects_invalid_or_oversized_records(record: bytes) -> None:
    with pytest.raises(ValueError):
        module.read_provenance(artifact(record))


def test_rejects_symlink_and_duplicate_records() -> None:
    with pytest.raises(ValueError, match="entries"):
        module.read_provenance(artifact(b"{}", symlink=True))
    with pytest.warns(UserWarning, match="Duplicate"):
        data = artifact(b"{}", extra="deployment-provenance.json")
    with pytest.raises(ValueError, match="entries"):
        module.read_provenance(data)


def test_rejects_missing_record_and_invalid_archive() -> None:
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        module.read_provenance(b"invalid")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("breachgazette-site.zip", b"synthetic")
    with pytest.raises(ValueError, match="entries"):
        module.read_provenance(output.getvalue())
