"""Composition roots for the database-free Core Run and later product adapters."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI

from trafficverse.adapters.carla import CarlaAdapter
from trafficverse.adapters.messaging import FrameBroker, ParquetReplayDataLogger
from trafficverse.adapters.persistence import (
    FileSimulationHistoryStore,
    InMemoryExperimentRepository,
    InMemoryWorkspaceRepository,
    RunMetadataExperimentRepository,
)
from trafficverse.adapters.sumo import SumoTrafficEngineAdapter
from trafficverse.api import ApiDependencies, RuntimeDirectory, create_app
from trafficverse.api.command_bus import ExperimentCommandBus
from trafficverse.api.map_catalog import MapCatalog
from trafficverse.api.models import ReadinessComponent
from trafficverse.application.experiment_registry import ExperimentRegistry
from trafficverse.application.simulation_configuration_service import (
    SimulationConfigurationService,
)
from trafficverse.application.simulation_history_service import SimulationHistoryService
from trafficverse.application.simulation_manager import SimulationManager
from trafficverse.application.simulation_runner import SimulationRunner
from trafficverse.application.workspace_service import WorkspaceService
from trafficverse.config.loader import load_scenario, validate_map_manifest
from trafficverse.config.models import MapManifest, ScenarioConfig
from trafficverse.controllers import controller_for_sumo_package
from trafficverse.domain.enums import ComponentStatus, ExperimentStatus, RequirementMode
from trafficverse.domain.models import SimulationRunInput
from trafficverse.maps.simulation_configuration import SumoSimulationConfigurationStore
from trafficverse.maps.sumo_package import (
    SumoScenarioPackage,
    load_sumo_package,
    stage_sumo_package,
)
from trafficverse.ports import (
    CarlaPort,
    DataLoggerPort,
    EventPublisherPort,
    ExperimentRepositoryPort,
    TrafficEnginePort,
)
from trafficverse.roi import CoordinateTransformer, RoiDefinition, RoiSynchronizer
from trafficverse.roi.signal_synchronizer import SignalSynchronizer


@dataclass(frozen=True, slots=True)
class AppContainer:
    """Explicit dependencies available to the application layer."""

    traffic: TrafficEnginePort
    carla: CarlaPort
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
        sumo_artifact_root: Path,
    ) -> None:
        self._scenario = _resolve_scenario_paths(scenario, repository_root)
        self._repository = InMemoryExperimentRepository()
        self._broker = broker
        self._maps = maps
        self._sumo_artifact_root = sumo_artifact_root
        self._registry = ExperimentRegistry(maximum_running=1)
        self._managers: dict[UUID, SimulationManager] = {}
        self._runners: dict[UUID, SimulationRunner] = {}
        self._carla_modes: dict[UUID, RequirementMode] = {}

    async def create(
        self,
        experiment_id: UUID,
        scenario_id: UUID,
        map_id: str | None,
        run_input: SimulationRunInput | None,
    ) -> SimulationManager:
        del scenario_id
        await self._repository.create(experiment_id)
        run_directory = (
            run_input.directory
            if run_input is not None
            else self._sumo_artifact_root / str(experiment_id)
        )
        experiments: ExperimentRepositoryPort = (
            RunMetadataExperimentRepository(
                self._repository,
                experiment_id=experiment_id,
                run_directory=run_input.directory,
            )
            if run_input is not None
            else self._repository
        )
        selected_map_id = map_id or self._scenario.scenario.map_id
        package = (
            load_sumo_package(
                run_input.sumo_config_path,
                allowed_root=run_input.directory,
                package_id=run_input.map_id,
            )
            if run_input is not None
            else self._maps.sumo_package(selected_map_id)
        )
        if package is not None:
            scenario = self._scenario_for_sumo_package(
                package,
                experiment_id,
                run_input=run_input,
            )
            manager = SimulationManager(
                scenario=scenario,
                carla_map_name="SUMO_2D",
                traffic=SumoTrafficEngineAdapter(experiment_id),
                carla=CarlaAdapter(),
                experiments=experiments,
                data_logger=self._replay_logger(scenario, run_directory),
                controller=controller_for_sumo_package(package.package_id),
                frame_publisher=self._broker,
                registry=self._registry,
            )
        else:
            scenario, manifest, map_directory = self._scenario_for_map(selected_map_id)
            focus = scenario.roi.focus
            definition = RoiDefinition(
                radius_m=scenario.roi.radius_m,
                buffer_m=scenario.roi.buffer_m,
                max_actors=scenario.roi.max_actors,
                focus_x=focus.x if focus.mode == "fixed" else None,
                focus_y=focus.y if focus.mode == "fixed" else None,
                focus_vehicle_id=focus.vehicle_id if focus.mode == "follow_vehicle" else None,
            )
            manager = SimulationManager(
                scenario=scenario,
                carla_map_name=manifest.carla_map,
                traffic=SumoTrafficEngineAdapter(experiment_id),
                carla=CarlaAdapter(),
                experiments=experiments,
                data_logger=self._replay_logger(scenario, run_directory),
                roi_planner=RoiSynchronizer(
                    definition,
                    CoordinateTransformer.from_yaml(
                        map_directory / "registration.yaml",
                        max_error_m=manifest.max_registration_error_m,
                    ),
                    blueprint_id=scenario.carla.fallback_blueprints[0],
                ),
                signal_planner=SignalSynchronizer.from_assets(
                    Path(scenario.traffic.network),
                    Path(scenario.traffic.signals),
                    strict=manifest.strict_signal_mapping,
                ),
                frame_publisher=self._broker,
                registry=self._registry,
            )
        runner = SimulationRunner(manager)
        self._managers[experiment_id] = manager
        self._runners[experiment_id] = runner
        self._carla_modes[experiment_id] = scenario.carla.mode
        runner.start()
        return manager

    @staticmethod
    def _replay_logger(
        scenario: ScenarioConfig,
        run_directory: Path,
    ) -> ParquetReplayDataLogger:
        return ParquetReplayDataLogger(
            run_directory,
            trajectory_hz=scenario.logging.trajectory_hz,
            parquet_batch_rows=scenario.logging.parquet_batch_rows,
            snapshot_interval_ms=scenario.replay.snapshot_interval_ms,
        )

    def _scenario_for_sumo_package(
        self,
        package: SumoScenarioPackage,
        experiment_id: UUID,
        *,
        run_input: SimulationRunInput | None = None,
    ) -> ScenarioConfig:
        output_directory = (
            run_input.directory
            if run_input is not None
            else self._sumo_artifact_root / str(experiment_id)
        )
        if run_input is None:
            package_id = package.package_id
            staged_config = stage_sumo_package(package, output_directory / "package")
            package = load_sumo_package(
                staged_config,
                allowed_root=output_directory,
                package_id=package_id,
            )
        else:
            staged_config = run_input.sumo_config_path
        duration_ms = self._scenario.simulation.duration_ms
        if package.end_time_ms is not None:
            configured_duration_ms = package.end_time_ms - package.begin_time_ms
            steps = max(1, math.ceil(configured_duration_ms / package.step_ms))
            duration_ms = steps * package.step_ms
        routes_path = package.route_paths[0] if package.route_paths else package.config_path
        signals_path = (
            package.additional_paths[0] if package.additional_paths else package.network_path
        )
        return self._scenario.model_copy(
            update={
                "scenario": self._scenario.scenario.model_copy(
                    update={"name": package.display_name, "map_id": package.package_id}
                ),
                "simulation": self._scenario.simulation.model_copy(
                    update={
                        "start_time_ms": package.begin_time_ms,
                        "step_ms": package.step_ms,
                        "duration_ms": duration_ms,
                    }
                ),
                "traffic": self._scenario.traffic.model_copy(
                    update={
                        "network": str(package.network_path),
                        "routes": str(routes_path),
                        "signals": str(signals_path),
                    }
                ),
                "sumo": self._scenario.sumo.model_copy(
                    update={
                        "launch_mode": "managed",
                        "step_ms": package.step_ms,
                        "begin_time_ms": package.begin_time_ms,
                        "config_file": str(staged_config),
                        "expected_version": None,
                        "output_directory": str(output_directory),
                        "freeze_collisions": package.package_id
                        in {
                            "mixed-automation-obstacle",
                            "mixed-automation-occasional-accident",
                        },
                    }
                ),
                "carla": self._scenario.carla.model_copy(update={"mode": RequirementMode.DISABLED}),
            }
        )

    def _scenario_for_map(self, map_id: str | None) -> tuple[ScenarioConfig, MapManifest, Path]:
        selected_map_id = map_id or self._scenario.scenario.map_id
        map_directory = self._maps.directory(selected_map_id)
        manifest = validate_map_manifest(
            map_directory / "manifest.yaml",
            expected_carla_version=self._scenario.carla.expected_version,
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
                "map_registration": self._scenario.map_registration.model_copy(
                    update={"manifest": str(map_directory / "manifest.yaml")}
                ),
                "sumo": self._scenario.sumo.model_copy(update={"config_file": sumo_config_file}),
            }
        )
        return scenario, manifest, map_directory

    async def readiness(self) -> tuple[ReadinessComponent, ...]:
        selected_modes = tuple(self._carla_modes.values())
        carla_mode = (
            RequirementMode.DISABLED
            if selected_modes and all(mode is RequirementMode.DISABLED for mode in selected_modes)
            else self._scenario.carla.mode
        )
        carla_message: str | None
        if carla_mode is RequirementMode.DISABLED:
            carla_status = ComponentStatus.DISABLED
            carla_required = False
            carla_message = "CARLA disabled; global 2D mode is available"
        else:
            prepared = [
                manager
                for manager in self._managers.values()
                if manager.experiment_id is not None and not manager.carla_degraded
            ]
            carla_status = ComponentStatus.HEALTHY if prepared else ComponentStatus.DEGRADED
            carla_required = carla_mode is RequirementMode.REQUIRED
            carla_message = (
                None
                if prepared
                else "CARLA connection will be validated while preparing the experiment"
            )
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
            ReadinessComponent(
                component="carla",
                status=carla_status,
                required=carla_required,
                message=carla_message,
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
        self._carla_modes.clear()


def build_core_api(
    scenario_path: Path,
    *,
    repository_root: Path,
    carla_mode: RequirementMode | None = None,
    artifact_root: Path | None = None,
    sumo_artifact_root: Path | None = None,
    configuration_root: Path | None = None,
    simulation_artifact_root: Path | None = None,
    test_artifact_root: Path | None = None,
) -> FastAPI:
    scenario = load_scenario(scenario_path)
    if carla_mode is not None:
        scenario = scenario.model_copy(
            update={"carla": scenario.carla.model_copy(update={"mode": carla_mode})}
        )
    resolved = _resolve_scenario_paths(scenario, repository_root)
    map_directory = Path(resolved.map_registration.manifest).parent
    maps_root = repository_root / "configs/maps"
    built_in_directories = tuple(
        sorted(
            (
                directory
                for directory in maps_root.iterdir()
                if directory.is_dir() and not directory.name.startswith(".")
            ),
            key=lambda path: path.name,
        )
    )
    if map_directory not in built_in_directories:
        built_in_directories = (*built_in_directories, map_directory)
    broker = FrameBroker()
    maps = MapCatalog(
        built_in_directories,
        artifact_root=artifact_root or repository_root / "artifacts/maps",
        package_root=maps_root,
    )
    factory = CoreRuntimeFactory(
        resolved,
        repository_root,
        broker,
        maps,
        sumo_artifact_root=sumo_artifact_root or repository_root / "artifacts/sumo",
    )
    configuration_storage = SumoSimulationConfigurationStore(
        package_resolver=maps.sumo_package,
        configuration_root=configuration_root or repository_root / "configs/configs",
        simulation_artifact_root=(
            simulation_artifact_root or repository_root / "artifacts/simulations"
        ),
        test_artifact_root=test_artifact_root or repository_root / "artifacts/tests",
    )
    runtimes = RuntimeDirectory(factory.create)
    dependencies = ApiDependencies(
        runtimes=runtimes,
        maps=maps,
        commands=ExperimentCommandBus(runtimes),
        broker=broker,
        readiness=factory.readiness,
        workspaces=WorkspaceService(InMemoryWorkspaceRepository()),
        configurations=SimulationConfigurationService(configuration_storage),
        histories=SimulationHistoryService(
            FileSimulationHistoryStore(
                simulation_artifact_root or repository_root / "artifacts/simulations"
            )
        ),
        shutdown=factory.close,
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
            "map_registration": scenario.map_registration.model_copy(
                update={"manifest": resolved(scenario.map_registration.manifest)}
            ),
            "sumo": scenario.sumo.model_copy(update={"config_file": sumo_config_file}),
        }
    )
