"""UI mirrors of the versioned simulation history and replay contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ui.models.protocol import ExperimentStatus, ProtocolModel, TrafficLight, Vehicle


class ReplaySummary(ProtocolModel):
    run_id: str = Field(pattern=r"^\d{4}(?:-\d{2}){5}$")
    workspace_id: UUID | None = None
    experiment_id: UUID | None = None
    status: ExperimentStatus
    status_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    scene_name: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    map_name: str = Field(min_length=1)
    configured_duration_ms: int = Field(ge=0)
    simulation_time_ms: int = Field(ge=0)
    replay_available: bool
    export_available: bool


class ReplayMetric(ProtocolModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | None = None
    unit: str = Field(min_length=1)
    source: str = Field(min_length=1)


class ReplayTrendSample(ProtocolModel):
    simulation_time_ms: int = Field(ge=0)
    value: float


class ReplayTrend(ProtocolModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    samples: tuple[ReplayTrendSample, ...]


class ReplayRoadResult(ProtocolModel):
    edge_id: str = Field(min_length=1)
    average_speed_mps: float | None = Field(default=None, ge=0.0)
    congestion_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    traffic_flow_veh_per_hour: float | None = Field(default=None, ge=0.0)
    queue_length_m: float | None = Field(default=None, ge=0.0)


class ReplayRecord(ReplaySummary):
    metrics: tuple[ReplayMetric, ...]
    trends: tuple[ReplayTrend, ...]
    road_results: tuple[ReplayRoadResult, ...]


class ReplayFrame(ProtocolModel):
    simulation_time_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)
    vehicles: tuple[Vehicle, ...] = ()
    traffic_lights: tuple[TrafficLight, ...] = ()
    collision_vehicle_ids: tuple[str, ...] = ()


class ReplayWindow(ProtocolModel):
    run_id: str = Field(pattern=r"^\d{4}(?:-\d{2}){5}$")
    frames: tuple[ReplayFrame, ...]
    next_time_ms: int | None = Field(default=None, ge=0)


ReplayStatus = Literal[
    "CREATED",
    "PREPARING",
    "READY",
    "RUNNING",
    "PAUSED",
    "STOPPING",
    "COMPLETED",
    "FAILED",
]
