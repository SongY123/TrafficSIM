"""Single-clock experiment lifecycle and tick orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from trafficverse.application.clock import SimulationClock
from trafficverse.application.experiment_registry import ExperimentRegistry
from trafficverse.config.models import ScenarioConfig
from trafficverse.domain.enums import (
    ComponentStatus,
    ErrorCode,
    ExperimentStatus,
)
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    ControlCommand,
    SimulationFrame,
    TrafficSnapshot,
)
from trafficverse.domain.state_machine import require_transition
from trafficverse.ports import (
    DataLoggerPort,
    ExperimentRepositoryPort,
    TrafficEnginePort,
)


class ControllerStepPort(Protocol):
    def step(
        self, previous: TrafficSnapshot | None, dt_s: float
    ) -> Mapping[str, ControlCommand]: ...


class SimulationFramePublisherPort(Protocol):
    async def publish_frame(self, frame: SimulationFrame) -> None: ...


class NoOpController:
    def step(self, previous: TrafficSnapshot | None, dt_s: float) -> Mapping[str, ControlCommand]:
        del previous, dt_s
        return {}


class NoOpFramePublisher:
    async def publish_frame(self, frame: SimulationFrame) -> None:
        del frame


class SimulationManager:
    """Owns all SUMO steps for one experiment."""

    def __init__(
        self,
        *,
        scenario: ScenarioConfig,
        traffic: TrafficEnginePort,
        experiments: ExperimentRepositoryPort,
        data_logger: DataLoggerPort,
        controller: ControllerStepPort | None = None,
        frame_publisher: SimulationFramePublisherPort | None = None,
        registry: ExperimentRegistry | None = None,
        clock: SimulationClock | None = None,
    ) -> None:
        self._scenario = scenario
        self._traffic = traffic
        self._experiments = experiments
        self._data_logger = data_logger
        self._controller = controller or NoOpController()
        self._frame_publisher = frame_publisher or NoOpFramePublisher()
        self._registry = registry
        self._clock = clock or SimulationClock(
            scenario.simulation.step_ms,
            speed_multiplier=scenario.simulation.speed_multiplier,
        )
        if self._clock.step_ms != scenario.simulation.step_ms:
            raise ValueError("clock step must match scenario step_ms")
        self._experiment_id: UUID | None = None
        self._previous_snapshot: TrafficSnapshot | None = None
        self._last_frame: SimulationFrame | None = None
        self._traffic_opened = False
        self._cleanup_done = False
        self._logger_flushed = False
        self._pending_api_controls: dict[str, ControlCommand] = {}
        self._command_lock = asyncio.Lock()

    @property
    def experiment_id(self) -> UUID | None:
        return self._experiment_id

    @property
    def simulation_time_ms(self) -> int:
        return self._clock.current_time_ms

    @property
    def step_ms(self) -> int:
        return self._clock.step_ms

    @property
    def speed_multiplier(self) -> float:
        return self._clock.speed_multiplier

    @property
    def last_frame(self) -> SimulationFrame | None:
        return self._last_frame

    async def prepare(self, experiment_id: UUID) -> None:
        async with self._command_lock:
            if self._experiment_id is not None:
                if self._experiment_id == experiment_id:
                    status = await self._status()
                    if status in {
                        ExperimentStatus.PREPARING,
                        ExperimentStatus.READY,
                        ExperimentStatus.RUNNING,
                        ExperimentStatus.PAUSED,
                    }:
                        return
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_CONFLICT,
                    "simulation manager is already assigned to an experiment",
                )
            self._experiment_id = experiment_id
            if self._registry is not None:
                await self._registry.register(experiment_id, self)
            try:
                await self._transition(ExperimentStatus.PREPARING)
                self._traffic_opened = True
                self._traffic.load(self._scenario.sumo)
                if self._traffic.health().status is not ComponentStatus.HEALTHY:
                    raise TrafficVerseError(
                        ErrorCode.COMPONENT_UNAVAILABLE,
                        "SUMO is not healthy after initialization",
                    )
                await self._transition(ExperimentStatus.READY)
            except Exception as error:
                await self._fail(error)
                raise

    async def start(self) -> None:
        async with self._command_lock:
            status = await self._status()
            if status is ExperimentStatus.RUNNING:
                return
            if status is not ExperimentStatus.READY:
                raise TrafficVerseError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"start requires READY status, found {status.value}",
                )
            experiment_id = self._require_experiment_id()
            if self._registry is not None:
                await self._registry.acquire_running(experiment_id)
            try:
                await self._transition(ExperimentStatus.RUNNING)
            except Exception:
                if self._registry is not None:
                    await self._registry.release_running(experiment_id)
                raise

    async def pause(self) -> None:
        async with self._command_lock:
            status = await self._status()
            if status is ExperimentStatus.PAUSED:
                return
            await self._transition(ExperimentStatus.PAUSED)
            if self._registry is not None:
                await self._registry.release_running(self._require_experiment_id())

    async def resume(self) -> None:
        async with self._command_lock:
            status = await self._status()
            if status is ExperimentStatus.RUNNING:
                return
            if status is not ExperimentStatus.PAUSED:
                raise TrafficVerseError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"resume requires PAUSED status, found {status.value}",
                )
            experiment_id = self._require_experiment_id()
            if self._registry is not None:
                await self._registry.acquire_running(experiment_id)
            try:
                await self._transition(ExperimentStatus.RUNNING)
            except Exception:
                if self._registry is not None:
                    await self._registry.release_running(experiment_id)
                raise

    async def stop(self, reason: str = "USER_REQUEST") -> None:
        async with self._command_lock:
            status = await self._status()
            if status is ExperimentStatus.COMPLETED:
                return
            if status is ExperimentStatus.FAILED:
                errors = await self._cleanup()
                if errors:
                    raise TrafficVerseError(
                        ErrorCode.COMPONENT_UNAVAILABLE,
                        "component cleanup is still failing",
                        details={"errors": "; ".join(str(item) for item in errors)},
                    )
                return
            if status is not ExperimentStatus.STOPPING:
                await self._transition(ExperimentStatus.STOPPING, reason=reason)
            errors = await self._cleanup()
            if errors:
                error = TrafficVerseError(
                    ErrorCode.COMPONENT_UNAVAILABLE,
                    "one or more components failed during cleanup",
                    details={"errors": "; ".join(str(item) for item in errors)},
                )
                await self._transition(ExperimentStatus.FAILED, reason=str(error))
                raise error
            await self._transition(ExperimentStatus.COMPLETED, reason=reason)

    async def set_speed(self, multiplier: float) -> None:
        async with self._command_lock:
            self._clock.set_speed(multiplier)

    async def get_status(self) -> ExperimentStatus:
        async with self._command_lock:
            if self._experiment_id is None:
                return ExperimentStatus.CREATED
            return await self._status()

    async def control_vehicle(self, vehicle_id: str, command: ControlCommand) -> None:
        async with self._command_lock:
            status = await self._status()
            if status not in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED}:
                raise TrafficVerseError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"vehicle control requires RUNNING or PAUSED status, found {status.value}",
                )
            if self._previous_snapshot is None or vehicle_id not in {
                vehicle.vehicle_id for vehicle in self._previous_snapshot.vehicles
            }:
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    f"vehicle is not active: {vehicle_id}",
                )
            self._pending_api_controls[vehicle_id] = command

    async def run_tick(self) -> SimulationFrame:
        async with self._command_lock:
            status = await self._status()
            if status is ExperimentStatus.PAUSED and self._last_frame is not None:
                return self._last_frame
            if status is not ExperimentStatus.RUNNING:
                raise TrafficVerseError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"cannot tick experiment while {status.value}",
                )
            target_time_ms = self._clock.next_time_ms
            try:
                controls = dict(
                    self._controller.step(self._previous_snapshot, self._clock.step_ms / 1000.0)
                )
                controls.update(self._pending_api_controls)
                self._traffic.apply_controls(controls)
                self._pending_api_controls.clear()
                traffic_snapshot = self._traffic.step(target_time_ms)
                self._previous_snapshot = traffic_snapshot
                self._clock.commit(target_time_ms)

                frame = SimulationFrame(traffic=traffic_snapshot)
                await self._data_logger.record_frame(frame)
                await self._frame_publisher.publish_frame(frame)
                self._last_frame = frame
                if target_time_ms >= self._scenario.simulation.duration_ms:
                    await self._stop_from_tick("DURATION_REACHED")
                return frame
            except Exception as error:
                await self._fail(error)
                raise

    async def _stop_from_tick(self, reason: str) -> None:
        await self._transition(ExperimentStatus.STOPPING, reason=reason)
        errors = await self._cleanup()
        if errors:
            await self._transition(
                ExperimentStatus.FAILED,
                reason="; ".join(str(item) for item in errors),
            )
            return
        await self._transition(ExperimentStatus.COMPLETED, reason=reason)

    async def _fail(self, error: Exception) -> None:
        experiment_id = self._require_experiment_id()
        try:
            status = await self._status()
            if status is not ExperimentStatus.FAILED:
                await self._transition(ExperimentStatus.FAILED, reason=str(error))
        finally:
            await self._cleanup()
            if self._registry is not None:
                await self._registry.release_running(experiment_id)

    async def _cleanup(self) -> tuple[Exception, ...]:
        if self._cleanup_done:
            return ()
        errors: list[Exception] = []
        if not self._logger_flushed:
            try:
                await self._data_logger.flush()
                self._logger_flushed = True
            except Exception as error:
                errors.append(error)
        if self._traffic_opened:
            try:
                self._traffic.close()
                self._traffic_opened = False
            except Exception as error:
                errors.append(error)
        if self._registry is not None and self._experiment_id is not None:
            await self._registry.release_running(self._experiment_id)
        self._cleanup_done = not errors
        if self._cleanup_done and self._registry is not None and self._experiment_id is not None:
            await self._registry.unregister(self._experiment_id)
        return tuple(errors)

    async def _transition(self, status: ExperimentStatus, *, reason: str | None = None) -> None:
        experiment_id = self._require_experiment_id()
        current = await self._experiments.get_status(experiment_id)
        if current is status:
            return
        require_transition(current, status)
        await self._experiments.set_status(experiment_id, status, reason=reason)

    async def _status(self) -> ExperimentStatus:
        return await self._experiments.get_status(self._require_experiment_id())

    def _require_experiment_id(self) -> UUID:
        if self._experiment_id is None:
            raise TrafficVerseError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "simulation manager has not been prepared",
            )
        return self._experiment_id
