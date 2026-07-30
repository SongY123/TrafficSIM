"""Composition roots for the database-free Core Run and later product adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from trafficverse.adapters.messaging import DiscardDataLogger, FrameBroker
from trafficverse.adapters.persistence import (
    InMemoryExperimentRepository,
    InMemoryWorkspaceRepository,
)
from trafficverse.adapters.persistence.postgres import PostgresRepository, create_postgres_engine
from trafficverse.adapters.sumo import SumoTrafficEngineAdapter
from trafficverse.api import ApiDependencies, RuntimeDirectory, create_app
from trafficverse.api.command_bus import ExperimentCommandBus
from trafficverse.api.map_catalog import MapCatalog
from trafficverse.api.models import ReadinessComponent
from trafficverse.application.experiment_registry import ExperimentRegistry
from trafficverse.application.simulation_manager import SimulationManager
from trafficverse.application.simulation_runner import SimulationRunner
from trafficverse.application.workspace_service import WorkspaceService
from trafficverse.config.loader import load_scenario, validate_map_manifest
from trafficverse.config.models import ScenarioConfig
from trafficverse.domain.enums import ComponentStatus, ExperimentStatus
from trafficverse.ports import (
    DataLoggerPort,
    EventPublisherPort,
    ExperimentRepositoryPort,
    TrafficEnginePort,
    WorkspaceRepositoryPort,
)


@dataclass(frozen=True, slots=True)
class AppContainer:
    """Explicit dependencies available to the application layer."""

    traffic: TrafficEnginePort
    experiments: ExperimentRepositoryPort
    events: EventPublisherPort
    data_logger: DataLoggerPort


class CoreRuntimeFactory:
    """Constructs one fixed-scenario runtime per API experiment."""

    def __init__(
        self,
        scenario: ScenarioConfig,
        repository_root: Path,
        broker: FrameBroker,
        maps: MapCatalog,
    ) -> None:
        self._scenario = _resolve_scenario_paths(scenario, repository_root)
        self._repository = InMemoryExperimentRepository()
        self._broker = broker
        self._maps = maps
        self._registry = ExperimentRegistry(maximum_running=1)
        self._managers: dict[UUID, SimulationManager] = {}
        self._runners: dict[UUID, SimulationRunner] = {}

    async def create(
        self,
        experiment_id: UUID,
        scenario_id: UUID,
        map_id: str | None,
    ) -> SimulationManager:
        del scenario_id
        await self._repository.create(experiment_id)
        scenario = self._scenario_for_map(map_id)
        manager = SimulationManager(
            scenario=scenario,
            traffic=SumoTrafficEngineAdapter(experiment_id),
            experiments=self._repository,
            data_logger=DiscardDataLogger(),
            frame_publisher=self._broker,
            registry=self._registry,
        )
        runner = SimulationRunner(manager)
        self._managers[experiment_id] = manager
        self._runners[experiment_id] = runner
        runner.start()
        return manager

    def _scenario_for_map(self, map_id: str | None) -> ScenarioConfig:
        selected_map_id = map_id or self._scenario.scenario.map_id
        map_directory = self._maps.directory(selected_map_id)
        validate_map_manifest(
            map_directory / "manifest.yaml",
            expected_map_id=selected_map_id,
            expected_sumo_version=self._scenario.sumo.expected_version,
        )
        network = str(map_directory / "network.json")
        routes = str(map_directory / "routes.yaml")
        signals = str(map_directory / "signals.yaml")
        sumo_config_file = str(map_directory / "map.sumocfg")
        scenario = self._scenario.model_copy(
            update={
                "scenario": self._scenario.scenario.model_copy(update={"map_id": selected_map_id}),
                "traffic": self._scenario.traffic.model_copy(
                    update={"network": network, "routes": routes, "signals": signals}
                ),
                "sumo": self._scenario.sumo.model_copy(update={"config_file": sumo_config_file}),
            }
        )
        return scenario

    async def readiness(self) -> tuple[ReadinessComponent, ...]:
        return (
            ReadinessComponent(
                component="sumo",
                status=(
                    ComponentStatus.HEALTHY
                    if any(manager.experiment_id is not None for manager in self._managers.values())
                    else ComponentStatus.DEGRADED
                ),
                required=True,
                message="SUMO connection is validated while preparing the experiment",
            ),
        )

    async def close(self) -> None:
        for runner in tuple(self._runners.values()):
            await runner.close()
        for manager in tuple(self._managers.values()):
            if manager.experiment_id is None:
                continue
            if await manager.get_status() is not ExperimentStatus.COMPLETED:
                await manager.stop("SERVER_SHUTDOWN")
        self._runners.clear()
        self._managers.clear()


def build_core_api(
    scenario_path: Path,
    *,
    repository_root: Path,
    artifact_root: Path | None = None,
    database_url: str | None = None,
) -> FastAPI:
    scenario = load_scenario(scenario_path)
    resolved = _resolve_scenario_paths(scenario, repository_root)
    map_directory = Path(resolved.traffic.network).parent
    broker = FrameBroker()
    maps = MapCatalog(
        (map_directory,),
        artifact_root=artifact_root or repository_root / "artifacts/maps",
    )
    factory = CoreRuntimeFactory(resolved, repository_root, broker, maps)
    runtimes = RuntimeDirectory(factory.create)
    configured_database_url = (
        database_url
        if database_url is not None
        else os.getenv("TRAFFICVERSE_DATABASE_URL")
    )
    engine: AsyncEngine | None = None
    workspace_repository: WorkspaceRepositoryPort
    if configured_database_url and configured_database_url.strip():
        engine = create_postgres_engine(configured_database_url.strip())
        workspace_repository = PostgresRepository(engine)
    else:
        workspace_repository = InMemoryWorkspaceRepository()

    async def shutdown() -> None:
        try:
            await factory.close()
        finally:
            if engine is not None:
                await engine.dispose()

    dependencies = ApiDependencies(
        runtimes=runtimes,
        maps=maps,
        commands=ExperimentCommandBus(runtimes),
        broker=broker,
        readiness=factory.readiness,
        shutdown=shutdown,
        workspaces=WorkspaceService(workspace_repository),
    )
    return create_app(dependencies)


def _resolve_scenario_paths(scenario: ScenarioConfig, repository_root: Path) -> ScenarioConfig:
    def resolved(value: str) -> str:
        path = Path(value)
        return str(path if path.is_absolute() else repository_root / path)

    network = resolved(scenario.traffic.network)
    routes = resolved(scenario.traffic.routes)
    signals = resolved(scenario.traffic.signals)
    sumo_config_file = resolved(scenario.sumo.config_file)
    return scenario.model_copy(
        update={
            "traffic": scenario.traffic.model_copy(
                update={"network": network, "routes": routes, "signals": signals}
            ),
            "sumo": scenario.sumo.model_copy(update={"config_file": sumo_config_file}),
        }
    )
