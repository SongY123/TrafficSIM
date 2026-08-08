"""Lazy TraCI SDK wrapper for external or TrafficVerse-managed SUMO."""

from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from trafficverse.adapters.sumo.models import SumoTrafficLightSample, SumoVehicleSample
from trafficverse.config.models import SumoConfig

_VERSION_PATTERN = re.compile(r"(?P<version>\d+\.\d+\.\d+)")


class PythonSumoRuntime:
    """Keep all untyped TraCI objects inside the adapter boundary."""

    def __init__(self) -> None:
        self._connection: Any | None = None
        self._connection_label: str | None = None

    def connect(self, config: SumoConfig) -> str:
        traci = self._load_traci(config)
        if config.launch_mode == "managed":
            executable = shutil.which(config.binary)
            if executable is None:
                raise RuntimeError(f"SUMO executable is unavailable: {config.binary}")
            command = [executable, "-c", config.config_file]
            if config.output_directory is not None:
                output_directory = Path(config.output_directory)
                output_directory.mkdir(parents=True, exist_ok=True)
            label = f"trafficverse-{uuid4()}"
            traci.start(
                command,
                port=config.port,
                numRetries=config.connect_retries,
                label=label,
                stdout=None,
                doSwitch=False,
            )
            self._connection_label = label
            self._connection = traci.getConnection(label)
        else:
            self._connection = traci.connect(
                port=config.port,
                host=config.host,
                numRetries=config.connect_retries,
                proc=None,
            )
        _api_version, description = self._connection.getVersion()
        match = _VERSION_PATTERN.search(str(description))
        return match.group("version") if match is not None else str(description)

    def simulation_step(self, target_time_s: float) -> None:
        self._require_connection().simulationStep(target_time_s)

    def simulation_time_s(self) -> float:
        return float(self._require_connection().simulation.getTime())

    def departed_vehicle_ids(self) -> tuple[str, ...]:
        values = self._require_connection().simulation.getDepartedIDList()
        return tuple(sorted(str(value) for value in values))

    def arrived_vehicle_ids(self) -> tuple[str, ...]:
        values = self._require_connection().simulation.getArrivedIDList()
        return tuple(sorted(str(value) for value in values))

    def vehicle_samples(self) -> tuple[SumoVehicleSample, ...]:
        vehicle_api = self._require_connection().vehicle
        samples = []
        for vehicle_id in sorted(str(value) for value in vehicle_api.getIDList()):
            x_m, y_m, z_m = vehicle_api.getPosition3D(vehicle_id)
            samples.append(
                SumoVehicleSample(
                    vehicle_id=vehicle_id,
                    x_m=float(x_m),
                    y_m=float(y_m),
                    z_m=float(z_m),
                    speed_mps=max(0.0, float(vehicle_api.getSpeed(vehicle_id))),
                    acceleration_mps2=float(vehicle_api.getAcceleration(vehicle_id)),
                    angle_deg=float(vehicle_api.getAngle(vehicle_id)),
                    lane_id=str(vehicle_api.getLaneID(vehicle_id)),
                    route_id=str(vehicle_api.getRouteID(vehicle_id)),
                )
            )
        return tuple(samples)

    def traffic_light_samples(self) -> tuple[SumoTrafficLightSample, ...]:
        traffic_lights = self._require_connection().trafficlight
        phases: dict[str, str] = {}
        for traffic_light_id in sorted(str(value) for value in traffic_lights.getIDList()):
            state = str(traffic_lights.getRedYellowGreenState(traffic_light_id))
            for link_index, state_character in enumerate(state):
                parameter = str(
                    self._traffic_light_parameter(
                        traffic_lights,
                        traffic_light_id,
                        f"linkSignalID:{link_index}",
                    )
                )
                signal_ids = tuple(parameter.split()) or (
                    f"sumo-tls:{traffic_light_id}:{link_index}",
                )
                for signal_id in signal_ids:
                    phase = _phase_name(state_character)
                    previous = phases.get(signal_id)
                    phases[signal_id] = _strictest_phase(previous, phase)
        return tuple(
            SumoTrafficLightSample(
                signal_id=(
                    signal_id if signal_id.startswith("sumo-tls:") else f"signal:{signal_id}"
                ),
                phase=phase,
            )
            for signal_id, phase in sorted(phases.items())
        )

    def set_vehicle_speed(self, vehicle_id: str, speed_mps: float) -> None:
        self._require_connection().vehicle.setSpeed(vehicle_id, speed_mps)

    def set_vehicle_speed_mode(self, vehicle_id: str, mode: int) -> None:
        self._require_connection().vehicle.setSpeedMode(vehicle_id, mode)

    def set_vehicle_acceleration(
        self, vehicle_id: str, acceleration_mps2: float, duration_s: float
    ) -> None:
        self._require_connection().vehicle.setAcceleration(
            vehicle_id,
            acceleration_mps2,
            duration_s,
        )

    def change_lane_relative(self, vehicle_id: str, direction: int, duration_s: float) -> None:
        self._require_connection().vehicle.changeLaneRelative(vehicle_id, direction, duration_s)

    def set_vehicle_lane_change_mode(self, vehicle_id: str, mode: int) -> None:
        self._require_connection().vehicle.setLaneChangeMode(vehicle_id, mode)

    def colliding_vehicle_ids(self) -> tuple[str, ...]:
        values = self._require_connection().simulation.getCollidingVehiclesIDList()
        return tuple(sorted(str(value) for value in values))

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.close(True)
        finally:
            self._connection = None
            self._connection_label = None

    @staticmethod
    def _load_traci(config: SumoConfig) -> Any:
        candidates = PythonSumoRuntime._traci_tools_candidates(config)
        if config.launch_mode == "managed":
            for tools_path in reversed(candidates):
                if tools_path.is_dir() and str(tools_path) not in sys.path:
                    sys.path.insert(0, str(tools_path))
        try:
            return importlib.import_module("traci")
        except ModuleNotFoundError:
            for tools_path in candidates:
                if tools_path.is_dir() and str(tools_path) not in sys.path:
                    sys.path.append(str(tools_path))
            return importlib.import_module("traci")

    @staticmethod
    def _traci_tools_candidates(config: SumoConfig) -> tuple[Path, ...]:
        candidates: list[Path] = []
        sumo_home = os.getenv("SUMO_HOME")
        if sumo_home:
            candidates.append(Path(sumo_home) / "tools")
        executable = shutil.which(config.binary)
        if executable is not None:
            binary_path = Path(executable).resolve()
            candidates.extend(
                (
                    binary_path.parent.parent / "share/sumo/tools",
                    binary_path.parent.parent / "tools",
                )
            )
        candidates.extend((Path("/usr/share/sumo/tools"), Path("/usr/local/share/sumo/tools")))
        return tuple(candidates)

    @staticmethod
    def _traffic_light_parameter(traffic_lights: Any, traffic_light_id: str, key: str) -> str:
        try:
            return str(traffic_lights.getParameter(traffic_light_id, key))
        except Exception:
            # Standard SUMO networks need no OpenDRIVE parameter; generic TLS IDs remain stable.
            return ""

    def _require_connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("TraCI connection is not open")
        return self._connection


def _phase_name(value: str) -> str:
    if value in {"r", "R"}:
        return "RED"
    if value in {"y", "Y"}:
        return "YELLOW"
    if value in {"g", "G"}:
        return "GREEN"
    return "OFF"


def _strictest_phase(previous: str | None, current: str) -> str:
    priority = {"OFF": 0, "GREEN": 1, "YELLOW": 2, "RED": 3}
    if previous is None or priority[current] > priority[previous]:
        return current
    return previous
