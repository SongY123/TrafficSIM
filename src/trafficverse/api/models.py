"""Versioned HTTP and WebSocket gateway models."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from trafficverse.domain.enums import (
    ComponentStatus,
    ExperimentStatus,
    LaneChangeDirection,
)
from trafficverse.domain.models import StrictModel, WebSocketEnvelope


class ErrorDetail(StrictModel):
    path: str = ""
    reason: str = Field(min_length=1)


class ErrorBody(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: tuple[ErrorDetail, ...] = ()
    trace_id: str = Field(min_length=1)


class ErrorResponse(StrictModel):
    error: ErrorBody


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["trafficverse-api"] = "trafficverse-api"


class ReadinessComponent(StrictModel):
    component: str = Field(min_length=1)
    status: ComponentStatus
    required: bool
    message: str | None = None


class ReadinessResponse(StrictModel):
    ready: bool
    components: tuple[ReadinessComponent, ...]


class MapSummary(StrictModel):
    map_id: str = Field(min_length=1)
    sumo_version: str = Field(min_length=1)
    validated: bool
    network_schema_version: str = Field(min_length=1)


class MapImportJob(StrictModel):
    job_id: UUID
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    map_id: str | None = None
    error_code: str | None = None
    errors: tuple[str, ...] = ()


class ExperimentCreateRequest(StrictModel):
    scenario_id: UUID
    map_id: str | None = Field(default=None, min_length=1)


class ExperimentView(StrictModel):
    experiment_id: UUID
    status: ExperimentStatus
    simulation_time_ms: int = Field(ge=0)
    speed_multiplier: float = Field(gt=0.0)


class StopExperimentRequest(StrictModel):
    reason: str = Field(default="USER_REQUEST", min_length=1, max_length=100)


class SetSpeedRequest(StrictModel):
    multiplier: float = Field(gt=0.0, le=16.0)


class VehicleControlRequest(StrictModel):
    vehicle_id: str = Field(min_length=1)
    desired_acceleration_mps2: float | None = None
    desired_speed_mps: float | None = Field(default=None, ge=0.0)
    lane_change: LaneChangeDirection = LaneChangeDirection.NONE
    takeover_requested: bool = False
    stop_requested: bool = False

    @model_validator(mode="after")
    def requires_control_intent(self) -> VehicleControlRequest:
        if (
            self.desired_acceleration_mps2 is None
            and self.desired_speed_mps is None
            and self.lane_change is LaneChangeDirection.NONE
            and not self.takeover_requested
            and not self.stop_requested
        ):
            raise ValueError("vehicle control requires at least one intent")
        return self


class SubscribeRequest(StrictModel):
    topics: tuple[Literal["vehicles", "traffic_lights", "health", "events"], ...] = Field(
        min_length=1
    )
    max_hz: float = Field(default=10.0, gt=0.0, le=20.0)


class ClientCommand(WebSocketEnvelope):
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class CommandOutcome(StrictModel):
    accepted: bool
    status: ExperimentStatus
    error_code: str | None = None
    message: str | None = None
