"""Runtime profile selection and dependency compatibility reporting."""

import importlib.metadata
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field

from trafficverse.config.models import RuntimeBaseline, RuntimeProfile
from trafficverse.domain.enums import RequirementMode
from trafficverse.domain.models.common import StrictModel


class CompatibilityIssue(StrictModel):
    severity: Literal["warning", "error"]
    component: str = Field(min_length=1)
    message: str = Field(min_length=1)


class CompatibilityReport(StrictModel):
    profile_name: str
    ready: bool
    operating_system: str
    architecture: str
    python_version: str
    detected_versions: dict[str, str | None]
    issues: tuple[CompatibilityIssue, ...] = ()


def select_runtime_profile(
    baseline: RuntimeBaseline,
    *,
    requested_profile: str,
    operating_system: str | None = None,
    architecture: str | None = None,
) -> tuple[str, RuntimeProfile]:
    system_name = operating_system or platform.system()
    machine = architecture or platform.machine()
    if requested_profile != "auto":
        try:
            return requested_profile, baseline.profiles[requested_profile]
        except KeyError as error:
            known = ", ".join(sorted(baseline.profiles))
            raise ValueError(
                f"unknown runtime profile {requested_profile!r}; expected one of {known}"
            ) from error

    matches = [
        (name, profile)
        for name, profile in baseline.profiles.items()
        if profile.operating_system == system_name and machine in profile.architectures
    ]
    if len(matches) != 1:
        raise ValueError(
            f"cannot select one runtime profile for {system_name}/{machine}; found {len(matches)}"
        )
    return matches[0]


def _detect_package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _detect_sumo_version() -> str | None:
    executable = shutil.which("sumo")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            (executable, "--version"),
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"\bsumo\s+(\d+\.\d+\.\d+)\b", result.stdout)
    return match.group(1) if match is not None else None


def _requirement_issues(
    component: str,
    expected: str,
    mode: RequirementMode,
    actual: str | None,
) -> list[CompatibilityIssue]:
    if mode is RequirementMode.DISABLED:
        return []
    if actual is None:
        severity: Literal["warning", "error"] = (
            "error" if mode is RequirementMode.REQUIRED else "warning"
        )
        return [
            CompatibilityIssue(
                severity=severity,
                component=component,
                message=f"{component} {expected} is {mode.value} but was not detected",
            )
        ]
    if actual != expected:
        return [
            CompatibilityIssue(
                severity="error",
                component=component,
                message=f"expected {component} {expected}, detected {actual}",
            )
        ]
    return []


def inspect_runtime(
    baseline: RuntimeBaseline,
    *,
    requested_profile: str,
) -> CompatibilityReport:
    profile_name, selected = select_runtime_profile(
        baseline,
        requested_profile=requested_profile,
    )
    operating_system = platform.system()
    architecture = platform.machine()
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    detected = {
        "sumo": _detect_sumo_version(),
        "postgres": None,
    }
    issues: list[CompatibilityIssue] = []
    if operating_system != selected.operating_system:
        issues.append(
            CompatibilityIssue(
                severity="error",
                component="operating-system",
                message=(
                    f"profile {profile_name} requires {selected.operating_system}, "
                    f"detected {operating_system}"
                ),
            )
        )
    if architecture not in selected.architectures:
        expected_architectures = ", ".join(selected.architectures)
        issues.append(
            CompatibilityIssue(
                severity="error",
                component="architecture",
                message=(
                    f"profile {profile_name} requires one of [{expected_architectures}], "
                    f"detected {architecture}"
                ),
            )
        )
    if python_version != selected.python_version:
        issues.append(
            CompatibilityIssue(
                severity="error",
                component="python",
                message=f"expected Python {selected.python_version}, detected {python_version}",
            )
        )
    issues.extend(
        _requirement_issues(
            "sumo",
            selected.sumo.version,
            selected.sumo.mode,
            detected["sumo"],
        )
    )
    return CompatibilityReport(
        profile_name=profile_name,
        ready=not any(issue.severity == "error" for issue in issues),
        operating_system=operating_system,
        architecture=architecture,
        python_version=python_version,
        detected_versions=detected,
        issues=tuple(issues),
    )


def default_baseline_path(repository_root: Path) -> Path:
    return repository_root / "configs" / "runtime-baseline.yaml"
