"""SUMO/TraCI production implementation of the traffic engine port."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from trafficverse.adapters.sumo.models import SumoRuntime, SumoVehicleSample
from trafficverse.adapters.sumo.runtime import PythonSumoRuntime
from trafficverse.config.models import SumoConfig
from trafficverse.domain.enums import (
    AutomationLevel,
    ComponentStatus,
    ErrorCode,
    LaneChangeDirection,
    VehicleAction,
)
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    ComponentHealth,
    ControlCommand,
    TrafficLightState,
    TrafficSnapshot,
    Vector3,
    VehicleState,
)

_AUTOMATION_LEVEL_PATTERN = re.compile(r"(?:^|_)L([0-5])(?:[._]|$)")


@dataclass(frozen=True, slots=True)
class SumoDiagnostics:
    connected: bool
    version: str | None
    sequence: int
    simulation_time_ms: int
    departed_vehicle_ids: tuple[str, ...]
    arrived_vehicle_ids: tuple[str, ...]
    rejected_control_vehicle_ids: tuple[str, ...]


class SumoTrafficEngineAdapter:
    """Connect to one SUMO instance and produce authoritative snapshots."""

    def __init__(self, experiment_id: UUID, runtime: SumoRuntime | None = None) -> None:
        self._experiment_id = experiment_id
        self._runtime = runtime or PythonSumoRuntime()
        self._config: SumoConfig | None = None
        self._version: str | None = None
        self._connected = False
        self._sequence = 0
        self._simulation_time_ms = 0
        self._departed_vehicle_ids: tuple[str, ...] = ()
        self._arrived_vehicle_ids: tuple[str, ...] = ()
        self._rejected_control_vehicle_ids: tuple[str, ...] = ()
        self._frozen_collision_poses: dict[str, SumoVehicleSample] = {}
        self._collision_vehicle_ids: set[str] = set()

    def load(self, config: SumoConfig) -> None:
        if self._connected:
            return
        try:
            version = self._runtime.connect(config)
        except Exception as error:
            self._runtime.close()
            raise TrafficVerseError(
                ErrorCode.SUMO_CONNECTION_FAILED,
                f"unable to connect to SUMO at {config.host}:{config.port}: {error}",
            ) from error
        if config.expected_version is not None and version != config.expected_version:
            self._runtime.close()
            raise TrafficVerseError(
                ErrorCode.SUMO_VERSION_MISMATCH,
                "SUMO version does not match the configured version",
                details={"expected": config.expected_version, "actual": version},
            )
        initial_time_ms = round(self._runtime.simulation_time_s() * 1000.0)
        if initial_time_ms != config.begin_time_ms:
            self._runtime.close()
            raise TrafficVerseError(
                ErrorCode.SUMO_TIME_MISMATCH,
                "SUMO initial time does not match the configured begin time",
                details={
                    "expected": str(config.begin_time_ms),
                    "actual": str(initial_time_ms),
                },
            )
        self._config = config
        self._version = version
        self._simulation_time_ms = initial_time_ms
        self._frozen_collision_poses.clear()
        self._collision_vehicle_ids.clear()
        self._connected = True

    def apply_controls(self, commands: Mapping[str, ControlCommand]) -> None:
        config = self._require_config()
        rejected = []
        for vehicle_id, command in sorted(commands.items()):
            try:
                if command.safety_checks_override:
                    self._runtime.set_vehicle_speed_mode(vehicle_id, 0)
                if command.lane_change_mode is not None:
                    self._runtime.set_vehicle_lane_change_mode(
                        vehicle_id,
                        command.lane_change_mode,
                    )
                if command.stop_requested:
                    self._runtime.set_vehicle_speed(vehicle_id, 0.0)
                elif command.desired_speed_mps is not None:
                    self._runtime.set_vehicle_speed(vehicle_id, command.desired_speed_mps)
                if command.desired_acceleration_mps2 is not None:
                    self._runtime.set_vehicle_acceleration(
                        vehicle_id,
                        command.desired_acceleration_mps2,
                        config.step_ms / 1000.0,
                    )
                direction = _lane_change_direction(command.lane_change)
                if direction != 0:
                    self._runtime.change_lane_relative(
                        vehicle_id,
                        direction,
                        command.lane_change_duration_s,
                    )
            except Exception:
                rejected.append(vehicle_id)
        if config.freeze_collisions:
            for vehicle_id, pose in tuple(sorted(self._frozen_collision_poses.items())):
                try:
                    self._runtime.set_vehicle_speed_mode(vehicle_id, 0)
                    self._runtime.set_vehicle_speed(vehicle_id, 0.0)
                    self._runtime.set_vehicle_pose(
                        vehicle_id,
                        pose.x_m,
                        pose.y_m,
                        pose.angle_deg,
                    )
                except Exception:
                    self._frozen_collision_poses.pop(vehicle_id, None)
        self._rejected_control_vehicle_ids = tuple(rejected)

    def step(self, target_time_ms: int) -> TrafficSnapshot:
        config = self._require_config()
        if target_time_ms != self._simulation_time_ms + config.step_ms:
            raise TrafficVerseError(
                ErrorCode.SUMO_TIME_MISMATCH,
                "SUMO target time must advance by exactly one configured step",
                details={
                    "current_time_ms": str(self._simulation_time_ms),
                    "target_time_ms": str(target_time_ms),
                },
            )
        try:
            self._runtime.simulation_step(target_time_ms / 1000.0)
            actual_time_ms = round(self._runtime.simulation_time_s() * 1000.0)
            if actual_time_ms != target_time_ms:
                raise TrafficVerseError(
                    ErrorCode.SUMO_TIME_MISMATCH,
                    "SUMO returned a different simulation time",
                    details={"expected": str(target_time_ms), "actual": str(actual_time_ms)},
                )
            self._departed_vehicle_ids = self._runtime.departed_vehicle_ids()
            self._arrived_vehicle_ids = self._runtime.arrived_vehicle_ids()
            vehicle_samples = self._runtime.vehicle_samples()
            current_collision_ids = set(self._runtime.colliding_vehicle_ids())
            self._collision_vehicle_ids.update(current_collision_ids)
            if config.freeze_collisions:
                vehicle_samples = self._freeze_collision_poses(
                    vehicle_samples,
                    current_collision_ids,
                )
            traffic_light_samples = self._runtime.traffic_light_samples()
        except TrafficVerseError:
            raise
        except Exception as error:
            raise TrafficVerseError(
                ErrorCode.SUMO_STEP_FAILED,
                f"SUMO simulation step failed: {error}",
            ) from error
        self._sequence += 1
        self._simulation_time_ms = target_time_ms
        return TrafficSnapshot(
            experiment_id=self._experiment_id,
            simulation_time_ms=target_time_ms,
            sequence=self._sequence,
            vehicles=tuple(
                self._vehicle_state(sample, target_time_ms) for sample in vehicle_samples
            ),
            traffic_lights=tuple(
                TrafficLightState(
                    signal_id=sample.signal_id,
                    simulation_time_ms=target_time_ms,
                    phase=sample.phase,
                )
                for sample in traffic_light_samples
            ),
            collision_vehicle_ids=tuple(sorted(self._collision_vehicle_ids)),
        )

    def health(self) -> ComponentHealth:
        return ComponentHealth(
            component="sumo",
            status=ComponentStatus.HEALTHY if self._connected else ComponentStatus.UNAVAILABLE,
            version=self._version,
        )

    def diagnostics(self) -> SumoDiagnostics:
        return SumoDiagnostics(
            connected=self._connected,
            version=self._version,
            sequence=self._sequence,
            simulation_time_ms=self._simulation_time_ms,
            departed_vehicle_ids=self._departed_vehicle_ids,
            arrived_vehicle_ids=self._arrived_vehicle_ids,
            rejected_control_vehicle_ids=self._rejected_control_vehicle_ids,
        )

    def close(self) -> None:
        if not self._connected:
            return
        try:
            self._runtime.close()
        finally:
            self._connected = False

    def _vehicle_state(self, sample: SumoVehicleSample, target_time_ms: int) -> VehicleState:
        return VehicleState(
            experiment_id=self._experiment_id,
            vehicle_id=sample.vehicle_id,
            simulation_time_ms=target_time_ms,
            sequence=self._sequence + 1,
            automation_level=_automation_level(sample.vehicle_id),
            position=Vector3(x=sample.x_m, y=sample.y_m, z=sample.z_m),
            speed_mps=sample.speed_mps,
            acceleration_mps2=sample.acceleration_mps2,
            heading_rad=_sumo_heading_rad(sample.angle_deg),
            lane_id=sample.lane_id,
            controller_id="sumo",
            action=_vehicle_action(sample.acceleration_mps2),
            risk_score=0.0,
            route_id=sample.route_id or None,
        )

    def _freeze_collision_poses(
        self,
        vehicle_samples: tuple[SumoVehicleSample, ...],
        current_collision_ids: set[str],
    ) -> tuple[SumoVehicleSample, ...]:
        samples_by_id = {sample.vehicle_id: sample for sample in vehicle_samples}
        self._frozen_collision_poses = {
            vehicle_id: pose
            for vehicle_id, pose in self._frozen_collision_poses.items()
            if vehicle_id in samples_by_id
        }
        for vehicle_id in sorted(current_collision_ids & samples_by_id.keys()):
            self._frozen_collision_poses.setdefault(vehicle_id, samples_by_id[vehicle_id])
        for vehicle_id, pose in sorted(self._frozen_collision_poses.items()):
            self._runtime.set_vehicle_speed_mode(vehicle_id, 0)
            self._runtime.set_vehicle_speed(vehicle_id, 0.0)
            self._runtime.set_vehicle_pose(
                vehicle_id,
                pose.x_m,
                pose.y_m,
                pose.angle_deg,
            )
        return self._runtime.vehicle_samples() if self._frozen_collision_poses else vehicle_samples

    def _require_config(self) -> SumoConfig:
        if not self._connected or self._config is None:
            raise TrafficVerseError(
                ErrorCode.SUMO_CONNECTION_FAILED,
                "SUMO adapter is not connected",
            )
        return self._config


def _sumo_heading_rad(angle_deg: float) -> float:
    value = math.radians(90.0 - angle_deg)
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _lane_change_direction(direction: LaneChangeDirection) -> int:
    if direction is LaneChangeDirection.LEFT:
        return 1
    if direction is LaneChangeDirection.RIGHT:
        return -1
    return 0


def _vehicle_action(acceleration_mps2: float) -> VehicleAction:
    if acceleration_mps2 > 0.05:
        return VehicleAction.ACCELERATE
    if acceleration_mps2 < -0.05:
        return VehicleAction.BRAKE
    return VehicleAction.KEEP_LANE


def _automation_level(vehicle_id: str) -> AutomationLevel:
    match = _AUTOMATION_LEVEL_PATTERN.search(vehicle_id)
    if match is None:
        return AutomationLevel.HUMAN
    return AutomationLevel(f"L{match.group(1)}")
