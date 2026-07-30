from pathlib import Path

import pytest

from trafficverse.config.compatibility import inspect_runtime, select_runtime_profile
from trafficverse.config.loader import load_runtime_baseline

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = REPOSITORY_ROOT / "configs" / "runtime-baseline.yaml"


def test_auto_selects_macos_profile_for_apple_silicon() -> None:
    baseline = load_runtime_baseline(BASELINE_PATH)
    name, profile = select_runtime_profile(
        baseline,
        requested_profile="auto",
        operating_system="Darwin",
        architecture="arm64",
    )
    assert name == "macos-dev"
    assert profile.sumo.mode.value == "required"


def test_auto_selects_linux_core_run_profile() -> None:
    baseline = load_runtime_baseline(BASELINE_PATH)
    name, profile = select_runtime_profile(
        baseline,
        requested_profile="auto",
        operating_system="Linux",
        architecture="x86_64",
    )
    assert name == "core-run"
    assert profile.sumo.version == "1.27.1"


def test_unknown_explicit_profile_is_rejected() -> None:
    baseline = load_runtime_baseline(BASELINE_PATH)
    with pytest.raises(ValueError, match="unknown runtime profile"):
        select_runtime_profile(baseline, requested_profile="missing")


def test_forcing_linux_profile_on_macos_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = load_runtime_baseline(BASELINE_PATH)
    monkeypatch.setattr("trafficverse.config.compatibility.platform.system", lambda: "Darwin")
    monkeypatch.setattr("trafficverse.config.compatibility.platform.machine", lambda: "arm64")
    monkeypatch.setattr(
        "trafficverse.config.compatibility.sys.version_info",
        type("VersionInfo", (), {"major": 3, "minor": 10})(),
    )
    monkeypatch.setattr("trafficverse.config.compatibility._detect_sumo_version", lambda: "1.27.1")
    report = inspect_runtime(baseline, requested_profile="core-run")

    assert report.ready is False
    assert {issue.component for issue in report.issues} >= {
        "operating-system",
        "architecture",
    }
