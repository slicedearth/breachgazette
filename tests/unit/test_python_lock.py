"""The application distribution is not part of its third-party dependency lock."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def lock_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "lock_python.py"
    spec = importlib.util.spec_from_file_location("dependency_lock_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_freeze_excludes_only_declared_application(lock_module, monkeypatch):
    def run(command, *, environment):
        assert command == [
            "/synthetic/python",
            "-m",
            "pip",
            "freeze",
            "--exclude-editable",
            "--exclude",
            "breachgazette",
        ]
        assert environment["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
        return "example==1.0\n"

    monkeypatch.setattr(lock_module, "run", run)
    assert lock_module.frozen_requirements(Path("/synthetic/python")) == "example==1.0\n"


@pytest.mark.parametrize(
    ("installed", "error"),
    [
        ("example==1.0\nunexpected==2.0\n", "unexpected: unexpected"),
        ("example==2.0\n", "version mismatch: example"),
        ("other==1.0\n", "missing: example"),
        ("example @ file:///synthetic/dependency.whl\n", "not an exact"),
    ],
)
def test_installed_dependency_drift_still_fails(lock_module, monkeypatch, installed, error):
    monkeypatch.setattr(lock_module, "validate_lock", lambda path: {"example": ("example", "1.0")})
    monkeypatch.setattr(lock_module, "run", lambda command, **kwargs: installed)
    with pytest.raises(lock_module.LockError, match=error):
        lock_module.check_installed(Path("synthetic.lock"))
