#!/usr/bin/env python3
"""Validate or regenerate the fully pinned Python dependency lock."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "requirements.lock"
LOCK_PYTHON = (3, 12)
LOCK_PIP = "26.1.2"
PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s]+)$")


class LockError(RuntimeError):
    """Raised when the lock contract is incomplete or inconsistent."""


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def parse_requirements(lines: list[str], *, source: str) -> dict[str, tuple[str, str]]:
    parsed: dict[str, tuple[str, str]] = {}
    previous_key = ""
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise LockError(f"{source}:{line_number} is not an exact name==version pin")
        name = match.group("name")
        version = match.group("version")
        key = normalized_name(name)
        if key in parsed:
            raise LockError(f"{source}:{line_number} duplicates {name}")
        sort_key = name.casefold()
        if sort_key < previous_key:
            raise LockError(f"{source}:{line_number} is not sorted by package name")
        previous_key = sort_key
        parsed[key] = (name, version)
    if not parsed:
        raise LockError(f"{source} contains no dependency pins")
    return parsed


def declared_requirements() -> dict[str, tuple[str, str]]:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirement_lines = [
        *configuration["build-system"]["requires"],
        *configuration["project"]["dependencies"],
        *configuration["project"]["optional-dependencies"]["dev"],
    ]
    parsed: dict[str, tuple[str, str]] = {}
    for requirement in requirement_lines:
        match = PIN.fullmatch(requirement)
        if not match:
            raise LockError(f"pyproject.toml dependency is not exactly pinned: {requirement}")
        name = match.group("name")
        key = normalized_name(name)
        if key in parsed and parsed[key][1] != match.group("version"):
            raise LockError(f"pyproject.toml declares conflicting pins for {name}")
        parsed[key] = (name, match.group("version"))
    return parsed


def validate_lock(path: Path) -> dict[str, tuple[str, str]]:
    if not path.is_file():
        raise LockError(f"lock file does not exist: {path}")
    locked = parse_requirements(path.read_text(encoding="utf-8").splitlines(), source=str(path))
    missing_or_changed = [
        f"{name}=={version}"
        for key, (name, version) in declared_requirements().items()
        if key not in locked or locked[key][1] != version
    ]
    if missing_or_changed:
        raise LockError(
            "lock does not match declared direct dependencies: "
            + ", ".join(sorted(missing_or_changed, key=str.casefold))
        )
    return locked


def run(command: list[str], *, environment: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def frozen_requirements(python: Path, *, environment: dict[str, str] | None = None) -> str:
    command_environment = (environment or os.environ).copy()
    command_environment.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    command_environment.setdefault("PIP_NO_CACHE_DIR", "1")
    output = run(
        [str(python), "-m", "pip", "freeze", "--exclude-editable"],
        environment=command_environment,
    )
    pins = parse_requirements(output.splitlines(), source="installed environment")
    ordered = sorted(pins.values(), key=lambda item: item[0].casefold())
    return "".join(f"{name}=={version}\n" for name, version in ordered)


def check_installed(path: Path) -> None:
    locked = validate_lock(path)
    installed_text = frozen_requirements(Path(sys.executable))
    installed = parse_requirements(
        installed_text.splitlines(),
        source=f"installed environment ({sys.executable})",
    )
    if installed != locked:
        missing = sorted(set(locked) - set(installed))
        unexpected = sorted(set(installed) - set(locked))
        changed = sorted(
            key
            for key in set(locked) & set(installed)
            if locked[key][1] != installed[key][1]
        )
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        if changed:
            details.append(f"version mismatch: {', '.join(changed)}")
        raise LockError("installed environment differs from lock; " + "; ".join(details))


def regenerate(path: Path) -> None:
    if sys.version_info[:2] != LOCK_PYTHON:
        required = ".".join(str(part) for part in LOCK_PYTHON)
        actual = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise LockError(f"lock regeneration requires Python {required}; running {actual}")
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build_requirements = list(configuration["build-system"]["requires"])
    with tempfile.TemporaryDirectory(prefix="breachgazette-lock-") as temporary:
        temporary_root = Path(temporary)
        environment = os.environ.copy()
        environment.update(
            {
                "PIP_CACHE_DIR": str(temporary_root / "pip-cache"),
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        environment_root = temporary_root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment_root)
        python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(
            [str(python), "-m", "pip", "install", f"pip=={LOCK_PIP}"],
            environment=environment,
        )
        run(
            [str(python), "-m", "pip", "install", *build_requirements],
            environment=environment,
        )
        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-build-isolation",
                "--editable",
                f"{ROOT}[dev]",
            ],
            environment=environment,
        )
        run([str(python), "-m", "pip", "check"], environment=environment)
        generated = frozen_requirements(python, environment=environment)
    parse_requirements(generated.splitlines(), source="generated lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        handle.write(generated)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    validate_lock(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate lock structure and pins")
    mode.add_argument(
        "--check-installed",
        action="store_true",
        help="validate the lock and compare it with the active Python environment",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_LOCK,
        help="lock path to validate or write (default: requirements.lock)",
    )
    arguments = parser.parse_args()
    try:
        if arguments.check_installed:
            check_installed(arguments.output)
        elif arguments.check:
            validate_lock(arguments.output)
        else:
            regenerate(arguments.output)
    except (LockError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
