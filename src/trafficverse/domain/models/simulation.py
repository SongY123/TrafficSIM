"""Simulation snapshots, events, metrics, and wire envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from trafficverse.domain.enums import (
    AutomationLevel,
    ComponentStatus,
    EventSeverity,
    SimulationRunKind,
)
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


class AutomationDemand(StrictModel):
    """Exact number of generated vehicles for one supported automation level."""

    level: Literal[
        AutomationLevel.L0,
        AutomationLevel.L1,
        AutomationLevel.L2,
        AutomationLevel.L3,
        AutomationLevel.L4,
        AutomationLevel.L5,
    ]
    vehicle_count: int = Field(ge=0, le=100_000)


class SimulationConfigurationDraft(StrictModel):
    """Validated user input used to materialize an immutable SUMO configuration."""

    workspace_id: UUID
    scenario_id: UUID
    scene_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1_000)
    map_id: str = Field(min_length=1, max_length=200)
    duration_ms: int = Field(gt=0)
    automation_demands: tuple[AutomationDemand, ...] = Field(max_length=6)

    @field_validator("scene_name", "map_id")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @model_validator(mode="after")
    def require_unique_levels(self) -> SimulationConfigurationDraft:
        levels = tuple(item.level for item in self.automation_demands)
        if len(set(levels)) != len(levels):
            raise ValueError("automation levels must be unique")
        return self


class SimulationConfigurationSnapshot(StrictModel):
    """Stable reference returned after a user configuration has been saved."""

    configuration_id: str = Field(pattern=r"^\d{4}(?:-\d{2}){5}$")
    map_id: str = Field(min_length=1)
    map_name: str = Field(min_length=1)
    relative_directory: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class SimulationRunInput:
    """Internal artifact copy that is safe to pass to the runtime factory."""

    configuration_id: str
    run_id: str
    run_kind: SimulationRunKind
    workspace_id: UUID
    scenario_id: UUID
    map_id: str
    directory: Path
    sumo_config_path: Path
