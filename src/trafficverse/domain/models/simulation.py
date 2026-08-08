"""Simulation snapshots, events, metrics, and wire envelopes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator

from trafficverse.domain.enums import ComponentStatus, EventSeverity
from trafficverse.domain.models.common import StrictModel
from trafficverse.domain.models.vehicle import TrafficLightState, VehicleState


class TrafficSnapshot(StrictModel):
    experiment_id: UUID
    simulation_time_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)
    vehicles: tuple[VehicleState, ...] = ()
    traffic_lights: tuple[TrafficLightState, ...] = ()
    collision_vehicle_ids: tuple[str, ...] = ()


class CarlaFrame(StrictModel):
    simulation_time_ms: int = Field(ge=0)
    carla_frame: int = Field(ge=0)
    actor_count: int = Field(ge=0)


class DomainEvent(StrictModel):
    event_id: UUID
    experiment_id: UUID
    event_type: str = Field(min_length=1)
    severity: EventSeverity
    simulation_time_ms: int = Field(ge=0)
    payload: JsonValue


class MetricSample(StrictModel):
    experiment_id: UUID
    metric_name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    simulation_time_ms: int = Field(ge=0)
    dimensions: dict[str, str] = Field(default_factory=dict)


class ComponentHealth(StrictModel):
    component: str = Field(min_length=1)
    status: ComponentStatus
    version: str | None = None
    message: str | None = None


class SimulationFrame(StrictModel):
    traffic: TrafficSnapshot
    carla: CarlaFrame | None = None
    events: tuple[DomainEvent, ...] = ()
    metrics: tuple[MetricSample, ...] = ()


class WebSocketEnvelope(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    type: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    correlation_id: str | None = None
    experiment_id: UUID
    simulation_time_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)
    sent_at: datetime
    payload: JsonValue

    @field_validator("sent_at")
    @classmethod
    def sent_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sent_at must include a timezone")
        return value
