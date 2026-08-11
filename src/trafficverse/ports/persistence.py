"""Persistence ports kept independent from SQLAlchemy and file implementations."""

from pathlib import Path
from typing import Protocol
from uuid import UUID

from trafficverse.domain.enums import ExperimentStatus
from trafficverse.domain.models import (
    AgentApiRecord,
    AgentApiWrite,
    ArtifactCreate,
    ArtifactRecord,
    DomainEvent,
    ExperimentCreate,
    ExperimentRecord,
    ExperimentStateChangeRecord,
    MapAssetRegistration,
    MetricSample,
    ScenarioListQuery,
    ScenarioPage,
    ScenarioRecord,
    ScenarioWrite,
    SimulationHistoryDetail,
    SimulationHistorySummary,
    SimulationReplayWindow,
    SimulationResultExport,
    WorkspaceRecord,
    WorkspaceWrite,
)


class ScenarioRepositoryPort(Protocol):
    async def register_map_asset(self, asset: MapAssetRegistration) -> None: ...

    async def create_scenario(self, write: ScenarioWrite) -> ScenarioRecord: ...

    async def get_scenario(
        self, scenario_id: UUID, *, include_deleted: bool = False
    ) -> ScenarioRecord: ...

    async def list_scenarios(self, query: ScenarioListQuery) -> ScenarioPage: ...

    async def update_scenario(
        self,
        scenario_id: UUID,
        write: ScenarioWrite,
        *,
        expected_version: int,
    ) -> ScenarioRecord: ...

    async def soft_delete_scenario(self, scenario_id: UUID) -> None: ...


class ExperimentRepositoryPort(Protocol):
    async def get_status(self, experiment_id: UUID) -> ExperimentStatus: ...

    async def set_status(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        *,
        reason: str | None = None,
    ) -> None: ...

    async def append_event(self, event: DomainEvent) -> None: ...

    async def append_metric(self, metric: MetricSample) -> None: ...


class ExperimentMetadataRepositoryPort(ExperimentRepositoryPort, Protocol):
    async def create_experiment(self, create: ExperimentCreate) -> ExperimentRecord: ...

    async def get_experiment(self, experiment_id: UUID) -> ExperimentRecord: ...

    async def transition_status(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        *,
        simulation_time_ms: int,
        reason: str | None = None,
    ) -> ExperimentRecord: ...

    async def list_state_changes(
        self, experiment_id: UUID
    ) -> tuple[ExperimentStateChangeRecord, ...]: ...

    async def append_artifact(self, artifact: ArtifactCreate) -> ArtifactRecord: ...

    async def list_events(
        self, experiment_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[DomainEvent, ...]: ...

    async def list_metrics(
        self,
        experiment_id: UUID,
        *,
        metric_name: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[MetricSample, ...]: ...

    async def list_artifacts(self, experiment_id: UUID) -> tuple[ArtifactRecord, ...]: ...


class ArtifactWriterPort(Protocol):
    async def write_bytes(
        self,
        experiment_id: UUID,
        relative_path: Path,
        payload: bytes,
    ) -> str: ...


class SimulationHistoryStorePort(Protocol):
    """Read formal simulation artifacts without exposing filesystem paths to callers."""

    def list_runs(
        self, workspace_id: UUID | None = None
    ) -> tuple[SimulationHistorySummary, ...]: ...

    def get_run(self, run_id: str) -> SimulationHistoryDetail: ...

    def get_network(self, run_id: str) -> dict[str, object]: ...

    def get_replay(
        self,
        run_id: str,
        *,
        from_time_ms: int,
        limit: int,
    ) -> SimulationReplayWindow: ...

    def export_run(self, run_id: str) -> SimulationResultExport: ...


class WorkspaceRepositoryPort(Protocol):
    async def create_workspace(self, write: WorkspaceWrite) -> WorkspaceRecord: ...

    async def get_workspace(self, workspace_id: UUID) -> WorkspaceRecord: ...

    async def list_workspaces(self, query: str | None = None) -> tuple[WorkspaceRecord, ...]: ...

    async def update_workspace(
        self,
        workspace_id: UUID,
        write: WorkspaceWrite,
    ) -> WorkspaceRecord: ...

    async def delete_workspace(self, workspace_id: UUID) -> None: ...

    async def create_agent_api(
        self,
        workspace_id: UUID,
        write: AgentApiWrite,
    ) -> AgentApiRecord: ...

    async def list_agent_apis(self, workspace_id: UUID) -> tuple[AgentApiRecord, ...]: ...

    async def delete_agent_api(self, workspace_id: UUID, agent_api_id: UUID) -> None: ...
