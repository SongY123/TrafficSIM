"""Reusable in-memory Port implementations for unit and contract tests."""

from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from trafficverse.config.models import SumoConfig
from trafficverse.domain.enums import ComponentStatus, ExperimentStatus
from trafficverse.domain.models import (
    ComponentHealth,
    ControlCommand,
    DomainEvent,
    MetricSample,
    SimulationFrame,
    TrafficSnapshot,
    WebSocketEnvelope,
)
class FakeTrafficEnginePort:
    def __init__(self, experiment_id: UUID) -> None:
        self.experiment_id = experiment_id
        self.started = False
        self.closed = False
        self.sequence = 0
        self.last_time_ms = -1
        self.controls: dict[str, ControlCommand] = {}

    def load(self, config: SumoConfig) -> None:
        del config
        self.started = True
        self.closed = False

    def apply_controls(self, commands: Mapping[str, ControlCommand]) -> None:
        self.controls = dict(commands)

    def step(self, target_time_ms: int) -> TrafficSnapshot:
        if not self.started or self.closed:
            raise RuntimeError("Fake traffic engine is not running")
        if target_time_ms <= self.last_time_ms:
            raise ValueError("target simulation time must increase")
        self.last_time_ms = target_time_ms
        self.sequence += 1
        return TrafficSnapshot(
            experiment_id=self.experiment_id,
            simulation_time_ms=target_time_ms,
            sequence=self.sequence,
        )

    def health(self) -> ComponentHealth:
        status = (
            ComponentStatus.HEALTHY
            if self.started and not self.closed
            else ComponentStatus.UNAVAILABLE
        )
        return ComponentHealth(component="traffic-engine", status=status, version="fake")

    def close(self) -> None:
        self.closed = True


class FakeExperimentRepository:
    def __init__(self) -> None:
        self.statuses: dict[UUID, ExperimentStatus] = {}
        self.events: list[DomainEvent] = []
        self.metrics: list[MetricSample] = []

    async def get_status(self, experiment_id: UUID) -> ExperimentStatus:
        return self.statuses[experiment_id]

    async def set_status(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        *,
        reason: str | None = None,
    ) -> None:
        del reason
        self.statuses[experiment_id] = status

    async def append_event(self, event: DomainEvent) -> None:
        self.events.append(event)

    async def append_metric(self, metric: MetricSample) -> None:
        self.metrics.append(metric)


class FakeEventPublisher:
    def __init__(self) -> None:
        self.messages: list[WebSocketEnvelope] = []

    async def publish(self, message: WebSocketEnvelope) -> None:
        self.messages.append(message)


class FakeDataLogger:
    def __init__(self) -> None:
        self.frames: list[SimulationFrame] = []
        self.events: list[DomainEvent] = []
        self.flushed = False

    async def record_frame(self, frame: SimulationFrame) -> None:
        self.frames.append(frame)

    async def record_event(self, event: DomainEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        self.flushed = True


class FakeArtifactWriter:
    def __init__(self) -> None:
        self.payloads: dict[tuple[UUID, Path], bytes] = {}

    async def write_bytes(
        self,
        experiment_id: UUID,
        relative_path: Path,
        payload: bytes,
    ) -> str:
        self.payloads[(experiment_id, relative_path)] = payload
        return f"memory://{experiment_id}/{relative_path.as_posix()}"
