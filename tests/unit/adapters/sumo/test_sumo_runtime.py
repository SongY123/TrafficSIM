from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from trafficverse.adapters.sumo.runtime import PythonSumoRuntime
from trafficverse.config.models import SumoConfig


class _FakeConnection:
    def __init__(self) -> None:
        self.simulation = SimpleNamespace(getTime=lambda: 0.0)
        self.closed_with: bool | None = None

    def getVersion(self) -> tuple[int, str]:
        return (22, "SUMO 1.26.0")

    def close(self, wait: bool) -> None:
        self.closed_with = wait


class _FakeTraci:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.start_calls: list[tuple[list[str], dict[str, object]]] = []

    def start(self, command: list[str], **options: object) -> None:
        self.start_calls.append((command, options))

    def getConnection(self, label: str) -> _FakeConnection:
        assert label.startswith("trafficverse-")
        return self.connection


def test_managed_runtime_uses_ephemeral_port_and_nonblocking_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection()
    traci = _FakeTraci(connection)
    runtime = PythonSumoRuntime()
    monkeypatch.setattr(runtime, "_load_traci", lambda config: traci)
    monkeypatch.setattr(
        "trafficverse.adapters.sumo.runtime.shutil.which",
        lambda binary: "/bin/sumo",
    )
    output_directory = tmp_path / "run"
    config = SumoConfig(
        launch_mode="managed",
        config_file=str(tmp_path / "scene.sumocfg"),
        output_directory=str(output_directory),
    )

    version = runtime.connect(config)
    runtime.close()

    command, options = traci.start_calls[0]
    assert version == "1.26.0"
    assert command == ["/bin/sumo", "-c", str(tmp_path / "scene.sumocfg")]
    assert options["port"] is None
    assert options["stdout"] is None
    assert options["doSwitch"] is False
    assert connection.closed_with is False


def test_generic_sumo_tls_ids_are_used_without_opendrive_parameters() -> None:
    class TrafficLights:
        @staticmethod
        def getIDList() -> tuple[str, ...]:
            return ("junction",)

        @staticmethod
        def getRedYellowGreenState(traffic_light_id: str) -> str:
            assert traffic_light_id == "junction"
            return "rG"

        @staticmethod
        def getParameter(traffic_light_id: str, key: str) -> str:
            del traffic_light_id, key
            raise RuntimeError("parameter is not defined")

    runtime = PythonSumoRuntime()
    runtime._connection = SimpleNamespace(trafficlight=TrafficLights())

    samples = runtime.traffic_light_samples()

    assert [(item.signal_id, item.phase) for item in samples] == [
        ("sumo-tls:junction:0", "RED"),
        ("sumo-tls:junction:1", "GREEN"),
    ]
