"""Verify a non-editable package and its resources with synthetic input only."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

import breachgazette
from breachgazette.clients.oaic_regulatory import OaicRegulatoryAdapter
from breachgazette.contracts import NormalizedNotification
from breachgazette.monitoring import load_monitoring_catalogue
from breachgazette.policies import load_source_policies, repository_root
from breachgazette.publish.builder import _build_search_assets
from breachgazette.publish.search import normalize_search
from breachgazette.retention import load_retention_policy
from breachgazette.utils import sha256_hex


def main() -> None:
    installed = Path(breachgazette.__file__).resolve()
    if "site-packages" not in installed.parts:
        raise RuntimeError("smoke check requires a non-editable installed wheel")
    if (Path.cwd() / "pyproject.toml").exists() or (Path.cwd() / "src").exists():
        raise RuntimeError("smoke check must run outside a source checkout")
    resource_root = repository_root()
    if not resource_root.is_relative_to(installed.parent):
        raise RuntimeError("source resources must come from the installed wheel")
    policies = load_source_policies()
    monitoring = load_monitoring_catalogue()
    retention = load_retention_policy()
    regulatory = yaml.safe_load(OaicRegulatoryAdapter().manifest_path.read_text(encoding="utf-8"))
    if regulatory["schema_version"] != "1.0" or not regulatory["entries"]:
        raise RuntimeError("packaged regulatory catalogue is incomplete")
    marker = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    if marker["manifest"]["dataset_class"] != "test_fixture":
        raise RuntimeError("installed smoke input must be explicitly synthetic")
    fixture = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))[0]
    notification = NormalizedNotification.model_validate(
        {
            **fixture,
            "source_checksum": sha256_hex(fixture),
            "parser_version": "synthetic",
            "normalization_version": "synthetic",
            "named_entity": {**fixture["named_entity"], "origin": "source_observed"},
        }
    )
    if not notification.source_record_id.startswith("fixture-"):
        raise RuntimeError("installed smoke input must be explicitly synthetic")
    manifest, partitions = _build_search_assets(
        [notification], detail_ids=set(), generated_at=datetime(2026, 1, 15, tzinfo=UTC)
    )
    assert manifest["record_count"] == 1 and len(partitions) == 1
    assert normalize_search("Straße 𐐀ex") == "strasse 𐐨ex"
    assert retention.maximum_state_bytes > 0
    print(
        json.dumps(
            {
                "installed_wheel": True,
                "source_policies": len(policies),
                "monitored_sources": len(monitoring.sources),
                "retention_loaded": True,
                "regulatory_catalogue_loaded": True,
                "synthetic_search_records": manifest["record_count"],
                "search_resources_loaded": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
