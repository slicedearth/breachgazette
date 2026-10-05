"""Offline state compatibility checks and explicitly reviewed identity transitions."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from breachgazette.clients.oaic import plan_identity_migration
from breachgazette.contracts import SourceAggregateRecord
from breachgazette.contracts.models import RecordProvenance
from breachgazette.monitoring import build_source_health_report, load_monitoring_catalogue
from breachgazette.policies import load_source_policies
from breachgazette.privacy.audit import require_public_safe
from breachgazette.publish.builder import audit_public_tree, build_site_data
from breachgazette.retention import restore_state_backup, state_inventory
from breachgazette.state import PrivateStateStore
from breachgazette.state.transaction import copy_candidate, promote_candidate, state_lock
from breachgazette.utils import atomic_write_json, canonical_json_bytes, sha256_hex


class IdentityMigrationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str = "1.0"
    source_id: str = "oaic_ndb"
    from_version: str = "1.0"
    to_version: str = "2.0"
    state_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(ge=1, le=2_000)
    approved: bool = False
    mapping: dict[str, str]


def _source_checkout() -> Path:
    return Path(__file__).resolve().parents[2]


def _checkout_for(path: Path) -> Path | None:
    checkout = _source_checkout()
    if (checkout / "pyproject.toml").is_file():
        return checkout
    # Installed wheels must also recognise a public checkout containing the target.
    for parent in (path, *path.parents):
        if (
            (parent / "pyproject.toml").is_file()
            and (parent / "src" / "breachgazette").is_dir()
            and (parent / "site" / "package.json").is_file()
        ):
            return parent
    return None


def _private_root(value: Path, *, allow_workflow_checkout: bool = False) -> Path:
    if value.is_symlink():
        raise ValueError("state root must not be a symbolic link")
    root = value.resolve()
    checkout = _checkout_for(root)
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("state root is too broad")
    if (
        checkout is not None
        and (root == checkout or checkout in root.parents)
        and not (
            allow_workflow_checkout
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and root == checkout / ".private-production-data"
        )
    ):
        raise ValueError("private state must remain outside the source checkout")
    if not root.is_dir():
        raise ValueError("state root must be an existing directory")
    return root


def _outside_state(value: Path, root: Path) -> Path:
    if value.is_symlink():
        raise ValueError("operational files must not be symbolic links")
    target = value.resolve()
    checkout = _checkout_for(target)
    if target == root or root in target.parents:
        raise ValueError("operational files must remain outside authoritative state")
    if checkout is not None and (target == checkout or checkout in target.parents):
        raise ValueError("operational files must remain outside the source checkout")
    return target


def _fingerprint(root: Path) -> str:
    inventory = state_inventory(root)
    if not inventory["within_size_limit"]:
        raise ValueError("private state exceeds its reviewed size bound")
    return sha256_hex(inventory["checksums"])


def _legacy_metrics(store: PrivateStateStore) -> list[SourceAggregateRecord]:
    if store.dataset_class() not in {"real_source_data", "test_fixture"}:
        raise ValueError("state has no supported dataset-class marker")
    records = store.load_records("oaic_ndb")
    if not records or not all(isinstance(record, SourceAggregateRecord) for record in records):
        raise ValueError("migration requires nonempty aggregate metric state")
    return [record for record in records if isinstance(record, SourceAggregateRecord)]


def plan_oaic_migration(*, data_root: Path, output: Path) -> dict[str, Any]:
    """Write a private draft mapping without locking or changing source state."""
    root = _private_root(data_root)
    target = _outside_state(output, root)
    before = _fingerprint(root)
    records = _legacy_metrics(PrivateStateStore(root))
    mapping = plan_identity_migration(records)
    if before != _fingerprint(root):
        raise ValueError("state changed while preparing its identity mapping")
    plan = IdentityMigrationPlan(
        state_fingerprint=before, record_count=len(records), mapping=mapping
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".identity-plan-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(canonical_json_bytes(plan))
        # Linking a private temporary file prevents overwriting an existing reviewed plan.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"planned": True, "approved": False, "record_count": len(records)}


def _read_plan(path: Path) -> IdentityMigrationPlan:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("identity plan must be a bounded regular file")

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("identity plan contains duplicate keys")
            result[key] = value
        return result

    plan = IdentityMigrationPlan.model_validate(
        json.loads(path.read_bytes(), object_pairs_hook=unique_keys)
    )
    if (
        plan.schema_version != "1.0"
        or plan.source_id != "oaic_ndb"
        or plan.from_version != "1.0"
        or plan.to_version != "2.0"
        or len(plan.mapping) != plan.record_count
    ):
        raise ValueError("identity plan has an unsupported contract")
    return plan


def migrate_oaic_identities(
    *,
    data_root: Path,
    plan_path: Path,
    backup: Path | None = None,
    expected_backup_sha256: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate a mapping by default; mutate only with approval and a verified backup."""
    root = _private_root(data_root)
    plan = _read_plan(_outside_state(plan_path, root))
    if apply:
        if not plan.approved or backup is None or expected_backup_sha256 is None:
            raise ValueError("applying identities requires an approved plan and verified backup")
        with state_lock(root):
            return _migrate_locked(root, plan, backup, expected_backup_sha256)
    records = _legacy_metrics(PrivateStateStore(root))
    _validate_mapping(root, records, plan)
    return {
        "validated": True,
        "applied": False,
        "approved": plan.approved,
        "record_count": len(records),
        "backup_restore_verified": False,
    }


def _validate_mapping(
    root: Path, records: list[SourceAggregateRecord], plan: IdentityMigrationPlan
) -> None:
    if _fingerprint(root) != plan.state_fingerprint:
        raise ValueError("identity plan no longer matches the private-state generation")
    if len(records) != plan.record_count or plan_identity_migration(records) != plan.mapping:
        raise ValueError("identity plan does not match the deterministic semantic mapping")


def _migrate_locked(
    root: Path, plan: IdentityMigrationPlan, backup: Path, expected_backup_sha256: str
) -> dict[str, Any]:
    original = PrivateStateStore(root)
    records = _legacy_metrics(original)
    _validate_mapping(root, records, plan)
    archive = _outside_state(backup, root)
    # A matching archive checksum alone is insufficient: restore and compare the full state.
    with tempfile.TemporaryDirectory(prefix="breachgazette-backup-check-") as directory:
        restored = Path(directory) / "restored"
        restore_state_backup(archive, restored, expected_sha256=expected_backup_sha256)
        if _fingerprint(restored) != plan.state_fingerprint:
            raise ValueError("verified backup does not contain the reviewed state generation")
    rewritten: list[RecordProvenance] = [
        record.model_copy(
            update={
                "source_record_id": plan.mapping[record.source_record_id],
                "normalization_version": "2.0",
            }
        )
        for record in records
    ]
    for record in rewritten:
        require_public_safe(record, record_identity="oaic_ndb:identity-transition")
    candidate = copy_candidate(root)
    try:
        staged = PrivateStateStore(candidate)
        staged.write_records("oaic_ndb", rewritten)
        bridge_path = candidate / "reviews" / "oaic-identity-bridge.json"
        if bridge_path.exists():
            raise ValueError("an identity bridge already exists; review it before proceeding")
        atomic_write_json(
            bridge_path,
            {**plan.model_dump(), "backup_checksum_sha256": expected_backup_sha256},
        )
        if staged.load_events() != original.load_events():
            raise ValueError("identity transition must not rewrite historical events")
        _fingerprint(candidate)
        if _fingerprint(root) != plan.state_fingerprint:
            raise ValueError("state changed before identity promotion")
        promote_candidate(root, candidate)
    finally:
        shutil.rmtree(candidate, ignore_errors=True)
    return {
        "validated": True,
        "applied": True,
        "approved": True,
        "record_count": len(rewritten),
        "backup_restore_verified": True,
    }


def deployment_preflight(*, data_root: Path) -> dict[str, Any]:
    """Read-only offline checks. This is not hosted CI or provider verification."""
    checks: dict[str, bool] = {}

    def check(name: str, operation: Callable[[], Any]) -> bool:
        try:
            result = operation()
            checks[name] = result is not False
        except (OSError, ValueError, RuntimeError):
            checks[name] = False
        return checks[name]

    root: Path | None = None
    with suppress(OSError, ValueError):
        root = _private_root(data_root, allow_workflow_checkout=True)
    checks["private_root_valid"] = root is not None
    check("source_policies_valid", load_source_policies)
    check("monitoring_catalogue_valid", load_monitoring_catalogue)
    if root is not None:
        store = PrivateStateStore(root)
        before: str | None = None

        def inventory() -> None:
            nonlocal before
            before = _fingerprint(root)

        check("state_inventory_valid", inventory)
        check("real_dataset_class", lambda: store.dataset_class() == "real_source_data")

        def identities() -> bool:
            records = store.load_records("oaic_ndb")
            return bool(records) and all(
                isinstance(record, SourceAggregateRecord)
                and record.normalization_version == "2.0"
                and re.fullmatch(r"oaic:v2:[0-9a-f]{32}", record.source_record_id)
                for record in records
            )

        check("oaic_identities_current", identities)
        check("source_health_valid", lambda: build_source_health_report(data_root=root).passed)
        if all(checks.values()):

            def publication() -> bool:
                with tempfile.TemporaryDirectory(prefix="breachgazette-preflight-") as directory:
                    output = Path(directory) / "publication"
                    result = build_site_data(data_root=root, output=output)
                    return bool(result["quality_passed"] and audit_public_tree(output)["passed"])

            check("publication_quality_and_privacy_valid", publication)
        else:
            checks["publication_quality_and_privacy_valid"] = False
        check(
            "state_generation_unchanged",
            lambda: before is not None and before == _fingerprint(root),
        )
    return {
        "schema_version": "1.0",
        "scope": "offline_private_state",
        "passed": all(checks.values()),
        "checks": checks,
        "limitations": [
            "No source retrieval, promotion or deployment is performed.",
            "Hosted CI, static-site builds and provider settings require separate verification.",
            "Passing checks apply only to the private-state generation inspected.",
        ],
    }
