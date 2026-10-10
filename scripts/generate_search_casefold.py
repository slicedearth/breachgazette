"""Regenerate the shared search table only with the reviewed Unicode runtime."""

import json
import unicodedata
from pathlib import Path

if unicodedata.unidata_version != "15.0.0":
    raise SystemExit("Search table generation requires Unicode 15.0.0 (Python 3.12)")

table = {
    chr(point): chr(point).casefold()
    for point in range(0x110000)
    if chr(point).casefold() != chr(point)
}
destination = Path(__file__).resolve().parents[1] / "src/breachgazette/publish/search-casefold.json"
destination.write_text(
    json.dumps(table, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8"
)
