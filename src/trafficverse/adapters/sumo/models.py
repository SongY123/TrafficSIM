"""Typed boundary between the SUMO adapter and the TraCI SDK."""

from dataclasses import dataclass
from typing import Protocol

from trafficverse.config.models import SumoConfig


@dataclass(frozen=True, slots=True)
class SumoVehicleSample:
    vehicle_id: str
    x_m: float
    y_m: float
    z_m: float
    speed_mps: float
    acceleration_mps2: float
    angle_deg: float
    lane_id: str
    route_id: str


@dataclass(frozen=True, slots=True)
class SumoTrafficLightSample:
    signal_id: str
    phase: str


class SumoRuntime(Protocol):
    """Small TraCI facade so unit tests never import or start SUMO."""

    def connect(self, config: SumoConfig) -> str: ...

    def simulation_step(self, target_time_s: float) -> None: ...

    def simulation_time_s(self) -> float: ...

    def departed_vehicle_ids(self) -> tuple[str, ...]: ...

    def arrived_vehicle_ids(self) -> tuple[str, ...]: ...

    def vehicle_samples(self) -> tuple[SumoVehicleSample, ...]: ...

    def traffic_light_samples(self) -> tuple[SumoTrafficLightSample, ...]: ...

    def set_vehicle_speed(self, vehicle_id: str, speed_mps: float) -> None: ...

    def set_vehicle_speed_mode(self, vehicle_id: str, mode: int) -> None: ...

    def set_vehicle_acceleration(
        self, vehicle_id: str, acceleration_mps2: float, duration_s: float
    ) -> None: ...

    def change_lane_relative(self, vehicle_id: str, direction: int, duration_s: float) -> None: ...

    def set_vehicle_lane_change_mode(self, vehicle_id: str, mode: int) -> None: ...

    def colliding_vehicle_ids(self) -> tuple[str, ...]: ...

    def close(self) -> None: ...
