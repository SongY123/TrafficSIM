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
    sumo_version: str = Field(min_length=1)
    validated: bool
    network_schema_version: str = Field(min_length=1)


class MapManifest(ProtocolModel):
    schema_version: Literal["2.0"] = "2.0"
    map_id: str = Field(min_length=1)
    sumo_version: str = Field(min_length=1)
    network_schema_version: Literal["traffic-network/1.0"]
    compiler_version: str = Field(min_length=1)
    source_repository: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    sumo_generation_command: str = Field(min_length=1)
    validated: bool
    files: dict[str, str] = Field(min_length=1)


class MapImportJob(ProtocolModel):
    job_id: UUID
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    map_id: str | None = None
    error_code: str | None = None
    errors: tuple[str, ...] = ()


class ExperimentView(ProtocolModel):
    experiment_id: UUID
    status: ExperimentStatus
    simulation_time_ms: int = Field(ge=0)
    speed_multiplier: float = Field(gt=0.0)


class ReadinessComponent(ProtocolModel):
    component: str = Field(min_length=1)
    status: str = Field(min_length=1)
    required: bool
    message: str | None = None


class ReadinessResponse(ProtocolModel):
    ready: bool
    components: tuple[ReadinessComponent, ...]


@dataclass(frozen=True, slots=True)
class ControlAvailability:
    can_create: bool
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_stop: bool
    can_control_vehicle: bool

    @classmethod
    def for_status(cls, status: ExperimentStatus | None) -> ControlAvailability:
        return cls(
            can_create=status is None
            or status in {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED},
            can_start=status in {ExperimentStatus.CREATED, ExperimentStatus.READY},
            can_pause=status is ExperimentStatus.RUNNING,
            can_resume=status is ExperimentStatus.PAUSED,
            can_stop=status in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED},
            can_control_vehicle=status in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED},
        )


@dataclass(frozen=True, slots=True)
class WorldUpdate:
    message_type: str
    sequence_gap: tuple[int, int] | None = None
    vehicles_changed: bool = False
    traffic_lights_changed: bool = False
    health_changed: bool = False
    status_changed: bool = False


@dataclass(slots=True)
class WorldState:
    experiment_id: UUID
    simulation_time_ms: int = 0
    sequence: int = 0
    vehicle_sequence: int | None = None
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    traffic_lights: dict[str, TrafficLight] = field(default_factory=dict)
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
            return WorldUpdate(envelope.type, sequence_gap=gap, vehicles_changed=True)
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
        self.vehicle_sequence = envelope.sequence
        return WorldUpdate(
            envelope.type,
            vehicles_changed=True,
            traffic_lights_changed=True,
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


ModelT = TypeVar("ModelT", bound=BaseModel)


def _model_list(payload: dict[str, JsonValue], key: str, model: type[ModelT]) -> tuple[ModelT, ...]:
    values = payload.get(key)
    if not isinstance(values, list):
        raise ValueError(f"message payload field {key!r} must be an array")
    return tuple(model.model_validate(value) for value in values)
