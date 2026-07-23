"""Deterministic serialization, hashing, text, URL, and atomic file helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import BaseModel


def normalize_text(value: str, *, maximum: int = 2_000) -> str:
    """Normalize source text without changing its substantive letter case."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    normalized = " ".join(normalized.split())
    if len(normalized) > maximum:
        raise ValueError(f"text exceeds the {maximum}-character limit")
    return normalized


def normalize_organization_name(value: str) -> str:
    normalized = normalize_text(value, maximum=500).casefold()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    normalized = re.sub(r"[\"'`]", "", normalized)
    normalized = re.sub(r"[^\w&]+", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(
        r"\b(incorporated|inc|limited|ltd|llc|l\.l\.c|corporation|corp)\b\.?",
        "",
        normalized,
    )
    return " ".join(normalized.split())


def canonical_data(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return canonical_data(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): canonical_data(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical_data(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            canonical_data(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_hex(value: bytes | str | Any) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    return f"{prefix}_{sha256_hex(list(parts))[:length]}"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def sanitize_public_url(value: str) -> str:
    """Retain HTTPS evidence links while removing a known IPC mail-wrapper URL."""

    parsed = urlparse(value)
    if (
        parsed.scheme == "https"
        and parsed.hostname == "aus01.safelinks.protection.outlook.com"
        and parsed.path == "/"
    ):
        target = parse_qs(parsed.query).get("url", [""])[0]
        value = unquote(target)
        parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("public source URLs must be credential-free HTTPS URLs")
    if parsed.scheme.lower() in {"javascript", "data", "file", "vbscript"}:
        raise ValueError("dangerous public source URL scheme")
    return value
