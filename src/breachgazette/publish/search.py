"""Versioned cross-language search semantics, independent of host locale."""

from __future__ import annotations

import json
import re
from importlib.resources import files

NORMALIZATION_VERSION = "unicode15_casefold_whitespace_codepoint_v1"
_SPACE = re.compile(
    r"[\x09-\x0d\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+"
)
_CASEFOLD: dict[str, str] = json.loads(
    files("breachgazette.publish").joinpath("search-casefold.json").read_text(encoding="utf-8")
)


def normalize_search(value: str) -> str:
    """Use the same pinned Unicode table as the browser, not the host's locale."""
    return _SPACE.sub(" ", "".join(_CASEFOLD.get(char, char) for char in value)).strip(" ")


def search_trigrams(value: str) -> set[str]:
    normalized = normalize_search(value)
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def population_band(count: int | None) -> str:
    if count is None:
        return "not_published"
    if count == 0:
        return "zero"
    if count < 500:
        return "1_499"
    if count < 1_000:
        return "500_999"
    if count < 10_000:
        return "1000_9999"
    if count < 100_000:
        return "10000_99999"
    return "100000_plus"
