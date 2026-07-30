"""Vehicle, signal, and control contracts."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from trafficverse.domain.enums import (
    AutomationLevel,
    LaneChangeDirection,
    VehicleAction,
)
from trafficverse.domain.models.common import StrictModel, Vector3


class VehicleState(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: UUID
    vehicle_id: str = Field(min_length=1)
    simulation_time_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)
    automation_level: AutomationLevel
    position: Vector3
    speed_mps: float = Field(ge=0.0)
    acceleration_mps2: float
    heading_rad: float
    lane_id: str = Field(min_length=1)
    target_lane_id: str | None = None
    controller_id: str = Field(min_length=1)
    action: VehicleAction
    risk_score: float = Field(ge=0.0, le=1.0)
    route_id: str | None = None


class TrafficLightState(StrictModel):
    signal_id: str = Field(min_length=1)
    simulation_time_ms: int = Field(ge=0)
    phase: str = Field(min_length=1)
    remaining_ms: int | None = Field(default=None, ge=0)


class ControlCommand(StrictModel):
    desired_acceleration_mps2: float | None = None
    desired_speed_mps: float | None = Field(default=None, ge=0.0)
    lane_change: LaneChangeDirection = LaneChangeDirection.NONE
    takeover_requested: bool = False
    stop_requested: bool = False

    @model_validator(mode="after")
    def command_must_contain_an_intent(self) -> "ControlCommand":
        if (
            self.desired_acceleration_mps2 is None
            and self.desired_speed_mps is None
            and self.lane_change is LaneChangeDirection.NONE
            and not self.takeover_requested
            and not self.stop_requested
        ):
            raise ValueError("control command must contain at least one intent")
        return self
