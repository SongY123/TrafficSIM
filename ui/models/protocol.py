"""Local mirrors of the versioned REST/WebSocket protocol used by the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentStatus(str, Enum):
    CREATED = "CREATED"
    PREPARING = "PREPARING"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Position(ProtocolModel):
    x: float
    y: float
    z: float = 0.0


class Vehicle(ProtocolModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: UUID
    vehicle_id: str = Field(min_length=1)
    simulation_time_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)
    position: Position
    speed_mps: float = Field(ge=0.0)
    acceleration_mps2: float
    heading_rad: float
    lane_id: str = Field(min_length=1)
    target_lane_id: str | None = None
    automation_level: str = Field(min_length=1)
    controller_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    risk_score: float = Field(ge=0.0, le=1.0)
    route_id: str | None = None


class TrafficLight(ProtocolModel):
    signal_id: str = Field(min_length=1)
    simulation_time_ms: int = Field(ge=0)
    phase: str = Field(min_length=1)
    remaining_ms: int | None = Field(default=None, ge=0)


class ComponentHealth(ProtocolModel):
    component: str = Field(min_length=1)
    status: str = Field(min_length=1)
    required: bool = False
    message: str | None = None


class Envelope(ProtocolModel):
    schema_version: Literal["1.0"] = "1.0"
    type: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    correlation_id: str | None = None
    experiment_id: UUID
    simulation_time_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)
    sent_at: datetime
    payload: JsonValue


class MapSummary(ProtocolModel):
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


class MapManifest(ProtocolModel):
    schema_version: Literal["1.1"] = "1.1"
    map_id: str = Field(min_length=1)
    carla_map: str = Field(min_length=1)
    carla_version: str = Field(min_length=1)
    sumo_version: str = Field(min_length=1)
    network_schema_version: Literal["traffic-network/1.0"]
    compiler_version: str = Field(min_length=1)
    source_repository: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    sumo_generation_command: str = Field(min_length=1)
    validated: bool
    max_registration_error_m: float = Field(gt=0.0)
    strict_signal_mapping: bool
    files: dict[str, str] = Field(min_length=1)


class MapImportJob(ProtocolModel):
    job_id: UUID
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    map_id: str | None = None
    error_code: str | None = None
    errors: tuple[str, ...] = ()


class ExperimentView(ProtocolModel):
    experiment_id: UUID
    workspace_id: UUID
    status: ExperimentStatus
    simulation_time_ms: int = Field(ge=0)
    speed_multiplier: float = Field(gt=0.0)


class AutomationDemand(ProtocolModel):
    level: Literal["L0", "L1", "L2", "L3", "L4", "L5"]
    vehicle_count: int = Field(ge=0, le=100_000)


class SimulationConfigurationDraft(ProtocolModel):
    scene_name: str
    description: str = Field(default="", max_length=1_000)
    map_id: str
    duration_ms: int
    automation_demands: tuple[AutomationDemand, ...]


class SimulationConfigurationView(ProtocolModel):
    configuration_id: str = Field(pattern=r"^\d{4}(?:-\d{2}){5}$")
    map_id: str = Field(min_length=1)
    map_name: str = Field(min_length=1)
    relative_directory: str = Field(min_length=1)


class ReadinessComponent(ProtocolModel):
    component: str = Field(min_length=1)
    status: str = Field(min_length=1)
    required: bool
    message: str | None = None


class ReadinessResponse(ProtocolModel):
    ready: bool
    components: tuple[ReadinessComponent, ...]


class WorkspaceSummary(ProtocolModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    created_at: datetime
    updated_at: datetime


class AgentApiSummary(ProtocolModel):
    agent_api_id: UUID
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    api_base_url: str = Field(min_length=1)
    model_id: str = Field(min_length=1, max_length=200)
    credential_env_var: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    created_at: datetime
    updated_at: datetime


class WorkspaceAutomationCount(ProtocolModel):
    level: str = Field(min_length=1)
    count: int = Field(ge=0)


class WorkspaceActivitySample(ProtocolModel):
    day: str = Field(min_length=1)
    simulations: int = Field(ge=0)


class WorkspaceRecentSimulation(ProtocolModel):
    name: str = Field(min_length=1)
    status: Literal["SUCCEEDED", "WARNING", "FAILED"]
    occurred_at: datetime
    duration_ms: int = Field(ge=0)
    automation_summary: str = Field(min_length=1)


class WorkspaceOverview(ProtocolModel):
    workspace_id: UUID
    map_count: int = Field(ge=0)
    agent_count: int = Field(ge=0)
    scenario_count: int = Field(ge=0)
    simulation_count: int = Field(ge=0)
    automation_counts: tuple[WorkspaceAutomationCount, ...]
    succeeded_simulations: int = Field(ge=0)
    failed_simulations: int = Field(ge=0)
    runtime_hours: float = Field(ge=0.0)
    activity: tuple[WorkspaceActivitySample, ...]
    recent_simulations: tuple[WorkspaceRecentSimulation, ...]
    preview_region: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class ControlAvailability:
    can_create: bool
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_stop: bool
    can_restart: bool
    can_set_speed: bool

    @classmethod
    def for_status(cls, status: ExperimentStatus | None) -> ControlAvailability:
        return cls(
            can_create=status is None
            or status
            in {
                ExperimentStatus.RUNNING,
                ExperimentStatus.PAUSED,
                ExperimentStatus.COMPLETED,
                ExperimentStatus.FAILED,
            },
            can_start=status in {ExperimentStatus.CREATED, ExperimentStatus.READY},
            can_pause=status is ExperimentStatus.RUNNING,
            can_resume=status is ExperimentStatus.PAUSED,
            can_stop=status in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED},
            can_restart=status
            in {
                ExperimentStatus.RUNNING,
                ExperimentStatus.PAUSED,
                ExperimentStatus.COMPLETED,
                ExperimentStatus.FAILED,
            },
            can_set_speed=status
            in {
                ExperimentStatus.READY,
                ExperimentStatus.RUNNING,
                ExperimentStatus.PAUSED,
            },
        )


@dataclass(frozen=True, slots=True)
class LiveMetrics:
    """UI session metrics derived from authoritative vehicle snapshots."""

    current_vehicle_count: int
    total_vehicle_count: int
    average_speed_mps: float
    average_travel_time_ms: float | None
    level_average_speed_mps: tuple[tuple[str, float], ...] = ()
    level_collision_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class WorldUpdate:
    message_type: str
    sequence_gap: tuple[int, int] | None = None
    vehicles_changed: bool = False
    traffic_lights_changed: bool = False
    health_changed: bool = False
    status_changed: bool = False
    collisions_changed: bool = False


@dataclass(slots=True)
class WorldState:
    experiment_id: UUID
    simulation_time_ms: int = 0
    sequence: int = 0
    vehicle_sequence: int | None = None
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    traffic_lights: dict[str, TrafficLight] = field(default_factory=dict)
    collision_vehicle_ids: set[str] = field(default_factory=set)
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    status: ExperimentStatus | None = None

    def apply(self, envelope: Envelope) -> WorldUpdate:
        if envelope.experiment_id != self.experiment_id:
            raise ValueError("message experiment_id does not match the active experiment")
        self.simulation_time_ms = max(self.simulation_time_ms, envelope.simulation_time_ms)
        self.sequence = max(self.sequence, envelope.sequence)
        if envelope.type == "world.snapshot":
            return self._apply_snapshot(envelope)
        if envelope.type == "vehicle.delta":
            gap = self._vehicle_gap(envelope.sequence)
            payload = _payload_dict(envelope.payload)
            vehicles = _model_list(payload, "vehicles", Vehicle)
            self.vehicles = {vehicle.vehicle_id: vehicle for vehicle in vehicles}
            self.collision_vehicle_ids = set(_string_list(payload, "collision_vehicle_ids"))
            return WorldUpdate(
                envelope.type,
                sequence_gap=gap,
                vehicles_changed=True,
                collisions_changed=True,
            )
        if envelope.type == "traffic_light.delta":
            payload = _payload_dict(envelope.payload)
            lights = _model_list(payload, "traffic_lights", TrafficLight)
            self.traffic_lights = {light.signal_id: light for light in lights}
            return WorldUpdate(envelope.type, traffic_lights_changed=True)
        if envelope.type == "component.health":
            payload = _payload_dict(envelope.payload)
            components = _model_list(payload, "components", ComponentHealth)
            self.components = {component.component: component for component in components}
            return WorldUpdate(envelope.type, health_changed=True)
        if envelope.type in {"session.ready", "experiment.state.changed"}:
            payload = _payload_dict(envelope.payload)
            self.status = ExperimentStatus(str(payload["status"]))
            return WorldUpdate(envelope.type, status_changed=True)
        return WorldUpdate(envelope.type)

    def _apply_snapshot(self, envelope: Envelope) -> WorldUpdate:
        payload = _payload_dict(envelope.payload)
        traffic = _payload_dict(payload.get("traffic"))
        vehicles = _model_list(traffic, "vehicles", Vehicle)
        lights = _model_list(traffic, "traffic_lights", TrafficLight)
        self.vehicles = {vehicle.vehicle_id: vehicle for vehicle in vehicles}
        self.traffic_lights = {light.signal_id: light for light in lights}
        self.collision_vehicle_ids = set(_string_list(traffic, "collision_vehicle_ids"))
        self.vehicle_sequence = envelope.sequence
        return WorldUpdate(
            envelope.type,
            vehicles_changed=True,
            traffic_lights_changed=True,
            collisions_changed=True,
        )

    def _vehicle_gap(self, sequence: int) -> tuple[int, int] | None:
        previous = self.vehicle_sequence
        self.vehicle_sequence = max(sequence, previous or 0)
        if previous is not None and sequence > previous + 1:
            return previous, sequence
        return None


def _payload_dict(payload: JsonValue | None) -> dict[str, JsonValue]:
    if not isinstance(payload, dict):
        raise ValueError("message payload must be an object")
    return payload


def _string_list(payload: dict[str, JsonValue], key: str) -> tuple[str, ...]:
    values = payload.get(key, [])
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError(f"message payload field {key} must be a string array")
    return tuple(value for value in values if isinstance(value, str))


ModelT = TypeVar("ModelT", bound=BaseModel)


def _model_list(payload: dict[str, JsonValue], key: str, model: type[ModelT]) -> tuple[ModelT, ...]:
    values = payload.get(key)
    if not isinstance(values, list):
        raise ValueError(f"message payload field {key!r} must be an array")
    return tuple(model.model_validate(value) for value in values)
