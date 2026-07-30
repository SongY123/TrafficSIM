from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from trafficverse.application.clock import SimulationClock
from trafficverse.application.experiment_registry import ExperimentRegistry
from trafficverse.application.simulation_manager import SimulationManager
from trafficverse.config.loader import load_scenario
from trafficverse.config.models import SumoConfig
from trafficverse.domain.enums import (
    AutomationLevel,
    ComponentStatus,
    ErrorCode,
    ExperimentStatus,
    VehicleAction,
)
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    ComponentHealth,
    ControlCommand,
    DomainEvent,
    MetricSample,
    SimulationFrame,
    TrafficLightState,
    TrafficSnapshot,
    Vector3,
    VehicleState,
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_PATH = REPOSITORY_ROOT / "configs/scenarios/core-run-town04.yaml"


class FailureInjector:
    def __init__(self) -> None:
        self.stage: str | None = None

    def check(self, stage: str) -> None:
        if self.stage == stage:
            raise RuntimeError(f"injected failure at {stage}")


class TraceTraffic:
    def __init__(self, experiment_id: UUID, trace: list[str], failures: FailureInjector) -> None:
        self.experiment_id = experiment_id
        self.trace = trace
        self.failures = failures
        self.opened = False
        self.closed = False
        self.sequence = 0
        self.applied_commands: list[dict[str, ControlCommand]] = []

    def load(self, config: SumoConfig) -> None:
        del config
        self.trace.append("traffic.load")
        self.failures.check("traffic.load")
        self.opened = True

    def apply_controls(self, commands: Mapping[str, ControlCommand]) -> None:
        self.trace.append(f"traffic.apply:{len(commands)}")
        self.failures.check("traffic.apply")
        self.applied_commands.append(dict(commands))

    def step(self, target_time_ms: int) -> TrafficSnapshot:
        self.trace.append(f"traffic.step:{target_time_ms}")
        self.failures.check("traffic.step")
        self.sequence += 1
        return TrafficSnapshot(
            experiment_id=self.experiment_id,
            simulation_time_ms=target_time_ms,
            sequence=self.sequence,
            vehicles=(
                VehicleState(
                    experiment_id=self.experiment_id,
                    vehicle_id="vehicle-1",
                    simulation_time_ms=target_time_ms,
                    sequence=self.sequence,
                    automation_level=AutomationLevel.HUMAN,
                    position=Vector3(x=float(self.sequence), y=0.0),
                    speed_mps=5.0,
                    acceleration_mps2=0.0,
                    heading_rad=0.0,
                    lane_id="lane-1",
                    controller_id="fixture",
                    action=VehicleAction.KEEP_LANE,
                    risk_score=0.0,
                ),
            ),
            traffic_lights=(
                TrafficLightState(
                    signal_id="signal-1",
                    simulation_time_ms=target_time_ms,
                    phase="RED",
                ),
            ),
        )

    def health(self) -> ComponentHealth:
        self.trace.append("traffic.health")
        self.failures.check("traffic.health")
        return ComponentHealth(
            component="traffic-engine",
            status=ComponentStatus.HEALTHY,
            version="fake",
        )

    def close(self) -> None:
        self.trace.append("traffic.close")
        self.closed = True
        self.failures.check("traffic.close")


class TraceRepository:
    def __init__(self, experiment_id: UUID, trace: list[str]) -> None:
        self.statuses = {experiment_id: ExperimentStatus.CREATED}
        self.transitions: list[ExperimentStatus] = []
        self.events: list[DomainEvent] = []
        self.metrics: list[MetricSample] = []
        self.trace = trace

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
        self.trace.append(f"status:{status.value}")
        self.statuses[experiment_id] = status
        self.transitions.append(status)

    async def append_event(self, event: DomainEvent) -> None:
        self.trace.append("repository.event")
        self.events.append(event)

    async def append_metric(self, metric: MetricSample) -> None:
        self.metrics.append(metric)


class TraceController:
    def __init__(self, trace: list[str], failures: FailureInjector) -> None:
        self.trace = trace
        self.failures = failures
        self.previous_sequences: list[int | None] = []

    def step(self, previous: TrafficSnapshot | None, dt_s: float) -> Mapping[str, ControlCommand]:
        assert dt_s == 0.05
        sequence = previous.sequence if previous is not None else None
        self.previous_sequences.append(sequence)
        self.trace.append(f"controller:{sequence}")
        self.failures.check("controller")
        return {"vehicle-1": ControlCommand(desired_speed_mps=5.0)}


class TraceLogger:
    def __init__(self, trace: list[str], failures: FailureInjector) -> None:
        self.trace = trace
        self.failures = failures
        self.frames: list[SimulationFrame] = []
        self.events: list[DomainEvent] = []

    async def record_frame(self, frame: SimulationFrame) -> None:
        self.trace.append("logger.frame")
        self.failures.check("logger.frame")
        self.frames.append(frame)

    async def record_event(self, event: DomainEvent) -> None:
        self.trace.append("logger.event")
        self.failures.check("logger.event")
        self.events.append(event)

    async def flush(self) -> None:
        self.trace.append("logger.flush")
        self.failures.check("logger.flush")


class TracePublisher:
    def __init__(self, trace: list[str], failures: FailureInjector) -> None:
        self.trace = trace
        self.failures = failures
        self.frames: list[SimulationFrame] = []

    async def publish_frame(self, frame: SimulationFrame) -> None:
        self.trace.append("publisher.frame")
        self.failures.check("publisher.frame")
        self.frames.append(frame)


class Harness:
    def __init__(
        self,
        *,
        registry: ExperimentRegistry | None = None,
    ) -> None:
        self.experiment_id = uuid4()
        self.trace: list[str] = []
        self.failures = FailureInjector()
        self.traffic = TraceTraffic(self.experiment_id, self.trace, self.failures)
        self.repository = TraceRepository(self.experiment_id, self.trace)
        self.controller = TraceController(self.trace, self.failures)
        self.logger = TraceLogger(self.trace, self.failures)
        self.publisher = TracePublisher(self.trace, self.failures)
        scenario = load_scenario(SCENARIO_PATH, apply_environment=False)
        scenario = scenario.model_copy(
            update={"simulation": scenario.simulation.model_copy(update={"duration_ms": 1000})}
        )
        self.manager = SimulationManager(
            scenario=scenario,
            traffic=self.traffic,
            experiments=self.repository,
            data_logger=self.logger,
            controller=self.controller,
            frame_publisher=self.publisher,
            registry=registry,
            clock=SimulationClock(50),
        )

    async def ready_and_started(self) -> None:
        await self.manager.prepare(self.experiment_id)
        await self.manager.start()


def test_complete_lifecycle_tick_order_pause_and_speed() -> None:
    async def exercise() -> None:
        harness = Harness()
        await harness.ready_and_started()
        harness.trace.clear()

        first = await harness.manager.run_tick()
        assert harness.trace == [
            "controller:None",
            "traffic.apply:1",
            "traffic.step:50",
            "logger.frame",
            "publisher.frame",
        ]
        assert first.traffic.sequence == 1

        await harness.manager.pause()
        paused = await harness.manager.run_tick()
        assert paused is first
        assert harness.manager.simulation_time_ms == 50
        await harness.manager.set_speed(2.0)
        assert harness.manager.speed_multiplier == 2.0
        await harness.manager.resume()
        second = await harness.manager.run_tick()
        assert second.traffic.simulation_time_ms == 100
        assert harness.controller.previous_sequences == [None, 1]
        await harness.manager.stop("TEST_COMPLETE")

        assert harness.repository.transitions == [
            ExperimentStatus.PREPARING,
            ExperimentStatus.READY,
            ExperimentStatus.RUNNING,
            ExperimentStatus.PAUSED,
            ExperimentStatus.RUNNING,
            ExperimentStatus.STOPPING,
            ExperimentStatus.COMPLETED,
        ]
        assert harness.traffic.closed

    asyncio.run(exercise())


def test_api_vehicle_control_is_validated_and_applied_on_next_tick() -> None:
    async def exercise() -> None:
        harness = Harness()
        await harness.ready_and_started()
        await harness.manager.run_tick()

        with pytest.raises(TrafficVerseError) as missing:
            await harness.manager.control_vehicle(
                "missing-vehicle", ControlCommand(desired_speed_mps=2.0)
            )
        assert missing.value.code is ErrorCode.RESOURCE_NOT_FOUND

        await harness.manager.control_vehicle("vehicle-1", ControlCommand(desired_speed_mps=8.0))
        await harness.manager.run_tick()

        assert harness.traffic.applied_commands[-1]["vehicle-1"].desired_speed_mps == 8.0

    asyncio.run(exercise())


def test_repeated_lifecycle_commands_are_idempotent() -> None:
    async def exercise() -> None:
        harness = Harness()
        await harness.manager.prepare(harness.experiment_id)
        await harness.manager.prepare(harness.experiment_id)
        await harness.manager.start()
        await harness.manager.start()
        await harness.manager.pause()
        await harness.manager.pause()
        with pytest.raises(TrafficVerseError) as wrong_command:
            await harness.manager.start()
        assert wrong_command.value.code is ErrorCode.INVALID_STATE_TRANSITION
        await harness.manager.resume()
        await harness.manager.resume()
        await harness.manager.stop()
        await harness.manager.stop()

        assert harness.trace.count("traffic.load") == 1
        assert harness.trace.count("traffic.close") == 1
        assert harness.trace.count("logger.flush") == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "stage",
    [
        "traffic.load",
        "traffic.health",
    ],
)
def test_initialization_failure_enters_failed_and_cleans_reverse_order(
    stage: str,
) -> None:
    async def exercise() -> None:
        harness = Harness()
        harness.failures.stage = stage

        with pytest.raises(RuntimeError, match="injected failure"):
            await harness.manager.prepare(harness.experiment_id)

        assert harness.repository.statuses[harness.experiment_id] is ExperimentStatus.FAILED
        assert harness.traffic.closed

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "stage",
    [
        "controller",
        "traffic.apply",
        "traffic.step",
        "logger.frame",
        "publisher.frame",
    ],
)
def test_tick_failure_enters_failed_and_cleans_all_components(stage: str) -> None:
    async def exercise() -> None:
        harness = Harness()
        await harness.ready_and_started()
        harness.failures.stage = stage

        with pytest.raises(RuntimeError, match="injected failure"):
            await harness.manager.run_tick()

        assert harness.repository.statuses[harness.experiment_id] is ExperimentStatus.FAILED
        assert harness.traffic.closed

    asyncio.run(exercise())


def test_registry_enforces_explicit_single_running_limit() -> None:
    async def exercise() -> None:
        registry = ExperimentRegistry(maximum_running=1)
        first = Harness(registry=registry)
        second = Harness(registry=registry)
        await first.manager.prepare(first.experiment_id)
        await second.manager.prepare(second.experiment_id)
        await first.manager.start()

        with pytest.raises(TrafficVerseError) as conflict:
            await second.manager.start()
        assert conflict.value.code is ErrorCode.RESOURCE_CONFLICT

        await first.manager.pause()
        await second.manager.start()
        await first.manager.stop()
        await second.manager.stop()
        with pytest.raises(TrafficVerseError) as missing:
            await registry.get(first.experiment_id)
        assert missing.value.code is ErrorCode.RESOURCE_NOT_FOUND

    asyncio.run(exercise())


@pytest.mark.parametrize("stage", ["logger.flush", "traffic.close"])
def test_cleanup_failure_continues_reverse_cleanup_and_can_retry(stage: str) -> None:
    async def exercise() -> None:
        harness = Harness()
        await harness.ready_and_started()
        harness.failures.stage = stage

        with pytest.raises(TrafficVerseError) as failed:
            await harness.manager.stop()
        assert failed.value.code is ErrorCode.COMPONENT_UNAVAILABLE
        assert harness.repository.statuses[harness.experiment_id] is ExperimentStatus.FAILED
        assert "traffic.close" in harness.trace

        harness.failures.stage = None
        await harness.manager.stop()
        assert harness.traffic.closed

    asyncio.run(exercise())
