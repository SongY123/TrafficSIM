"""Versioned contracts for filesystem-backed simulation results and replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from trafficverse.domain.enums import ExperimentStatus
from trafficverse.domain.models.common import StrictModel
from trafficverse.domain.models.vehicle import TrafficLightState, VehicleState


class SimulationHistorySummary(StrictModel):
    """One formal run discovered below the configured simulation artifact root."""

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
    export_available: bool = True


class SimulationResultMetric(StrictModel):
    """One aggregate value calculated from an explicit SUMO result field."""

    key: Literal[
        "vehicle_total",
        "completed_total",
        "average_speed_mps",
        "average_travel_time_s",
        "average_waiting_time_s",
        "average_queue_length_veh",
        "maximum_queue_length_veh",
    ]
    label: str = Field(min_length=1)
    value: float | None = None
    unit: str = Field(min_length=1)
    source: str = Field(min_length=1)


class SimulationTrendSample(StrictModel):
    simulation_time_ms: int = Field(ge=0)
    value: float


class SimulationResultTrend(StrictModel):
    """A time-aligned SUMO summary series."""

    key: Literal[
        "vehicle_count",
        "average_speed_mps",
        "queue_length_veh",
        "average_waiting_time_s",
        "completed_total",
    ]
    label: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    samples: tuple[SimulationTrendSample, ...]


class SimulationRoadResult(StrictModel):
    """Aggregate values for one SUMO edge in the run's actual network."""

    edge_id: str = Field(min_length=1)
    average_speed_mps: float | None = Field(default=None, ge=0.0)
    congestion_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    traffic_flow_veh_per_hour: float | None = Field(default=None, ge=0.0)
    queue_length_m: float | None = Field(default=None, ge=0.0)


class SimulationHistoryDetail(SimulationHistorySummary):
    """Detailed immutable result view for a selected formal run."""

    metrics: tuple[SimulationResultMetric, ...]
    trends: tuple[SimulationResultTrend, ...]
    road_results: tuple[SimulationRoadResult, ...]


class SimulationReplayFrame(StrictModel):
    """One reconstructed authoritative state used by read-only playback."""

    simulation_time_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)
    vehicles: tuple[VehicleState, ...] = ()
    traffic_lights: tuple[TrafficLightState, ...] = ()
    collision_vehicle_ids: tuple[str, ...] = ()


class SimulationReplayWindow(StrictModel):
    """Bounded replay page; callers continue from ``next_time_ms`` when present."""

    run_id: str = Field(pattern=r"^\d{4}(?:-\d{2}){5}$")
    frames: tuple[SimulationReplayFrame, ...]
    next_time_ms: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, slots=True)
class SimulationResultExport:
    """In-memory export payload returned across the persistence Port boundary."""

    filename: str
    media_type: str
    payload: bytes
