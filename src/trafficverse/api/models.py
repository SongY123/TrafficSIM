"""Versioned HTTP and WebSocket gateway models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, JsonValue, StringConstraints, model_validator

from trafficverse.domain.enums import (
    ComponentStatus,
    ExperimentStatus,
    LaneChangeDirection,
    SimulationRunKind,
)
from trafficverse.domain.models import (
    SimulationConfigurationDraft,
    SimulationConfigurationSnapshot,
    StrictModel,
    WebSocketEnvelope,
)

WorkspaceName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


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
    kind: Literal["core_run", "sumo"] = "core_run"
    display_name: str | None = Field(default=None, min_length=1)
    carla_map: str | None = Field(default=None, min_length=1)
    carla_version: str | None = Field(default=None, min_length=1)
    validated: bool
    network_schema_version: str = Field(min_length=1)
    manifest_available: bool = True
    sumo_config_file: str | None = Field(default=None, min_length=1)
    sumo_step_ms: int | None = Field(default=None, gt=0)
    sumo_begin_time_ms: int = Field(default=0, ge=0)
    sumo_end_time_ms: int | None = Field(default=None, ge=0)
    files: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()


class MapImportJob(StrictModel):
    job_id: UUID
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    map_id: str | None = None
    error_code: str | None = None
    errors: tuple[str, ...] = ()


class ExperimentCreateRequest(StrictModel):
    workspace_id: UUID
    scenario_id: UUID
    map_id: str | None = Field(default=None, min_length=1)
    configuration_id: str | None = Field(default=None, pattern=r"^\d{4}(?:-\d{2}){5}$")
    run_kind: SimulationRunKind = SimulationRunKind.SIMULATION

    @model_validator(mode="after")
    def test_run_requires_configuration(self) -> ExperimentCreateRequest:
        if self.run_kind is SimulationRunKind.TEST and self.configuration_id is None:
            raise ValueError("test runs require a saved simulation configuration")
        return self


class SimulationConfigurationSaveRequest(SimulationConfigurationDraft):
    """Named REST request for persisting a configuration-page snapshot."""


class SimulationConfigurationView(SimulationConfigurationSnapshot):
    """REST view of a saved configuration snapshot."""


class ExperimentView(StrictModel):
    experiment_id: UUID
    workspace_id: UUID
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


class WorkspaceCreateRequest(StrictModel):
    name: WorkspaceName
    description: str = Field(default="", max_length=1000)


class WorkspaceUpdateRequest(StrictModel):
    name: WorkspaceName
    description: str = Field(default="", max_length=1000)


class WorkspaceView(StrictModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    created_at: datetime
    updated_at: datetime


class AgentApiCreateRequest(StrictModel):
    name: WorkspaceName
    api_base_url: AnyHttpUrl
    model_id: str = Field(min_length=1, max_length=200)
    credential_env_var: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    description: str = Field(default="", max_length=1000)


class AgentApiView(StrictModel):
    agent_api_id: UUID
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    api_base_url: AnyHttpUrl
    model_id: str = Field(min_length=1, max_length=200)
    credential_env_var: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    created_at: datetime
    updated_at: datetime
