"""Core Run REST resources."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse

from trafficverse.api.command_bus import ExperimentCommandBus
from trafficverse.api.dependencies import ApiDependencies
from trafficverse.api.models import (
    AgentApiCreateRequest,
    AgentApiView,
    CommandOutcome,
    ExperimentCreateRequest,
    ExperimentView,
    HealthResponse,
    MapImportJob,
    MapSummary,
    ReadinessResponse,
    SetSpeedRequest,
    SimulationConfigurationSaveRequest,
    SimulationConfigurationView,
    StopExperimentRequest,
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceView,
)
from trafficverse.domain.enums import ErrorCode
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    AgentApiRecord,
    AgentApiWrite,
    SimulationConfigurationDraft,
    SimulationHistoryDetail,
    SimulationHistorySummary,
    SimulationReplayWindow,
    WorkspaceOverview,
    WorkspaceRecord,
    WorkspaceWrite,
)


def _require_accepted(outcome: CommandOutcome) -> None:
    if not outcome.accepted:
        code = ErrorCode(outcome.error_code or ErrorCode.RESOURCE_CONFLICT.value)
        raise TrafficVerseError(code, outcome.message or "command was rejected")


def _workspace_view(record: WorkspaceRecord) -> WorkspaceView:
    return WorkspaceView.model_validate(record.model_dump())


def _agent_api_view(record: AgentApiRecord) -> AgentApiView:
    return AgentApiView.model_validate(record.model_dump())


async def _execute(
    commands: ExperimentCommandBus,
    experiment_id: UUID,
    command_type: str,
    payload: object,
) -> CommandOutcome:
    outcome = await commands.execute(experiment_id, command_type, payload)
    _require_accepted(outcome)
    return outcome


def build_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @router.get("/ready", response_model=ReadinessResponse)
    async def ready(response: Response) -> ReadinessResponse:
        components = await dependencies.readiness()
        is_ready = all(
            not component.required or component.status.value in {"HEALTHY", "DISABLED"}
            for component in components
        )
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(ready=is_ready, components=components)

    @router.get("/maps", response_model=tuple[MapSummary, ...])
    async def maps() -> tuple[MapSummary, ...]:
        return dependencies.maps.list_maps()

    @router.get("/workspaces", response_model=tuple[WorkspaceView, ...])
    async def list_workspaces(
        query: Annotated[str | None, Query(max_length=200)] = None,
    ) -> tuple[WorkspaceView, ...]:
        records = await dependencies.workspaces.list(query)
        return tuple(_workspace_view(record) for record in records)

    @router.post(
        "/workspaces",
        response_model=WorkspaceView,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_workspace(request: WorkspaceCreateRequest) -> WorkspaceView:
        record = await dependencies.workspaces.create(
            WorkspaceWrite(name=request.name, description=request.description)
        )
        return _workspace_view(record)

    @router.patch("/workspaces/{workspace_id}", response_model=WorkspaceView)
    async def update_workspace(
        workspace_id: UUID,
        request: WorkspaceUpdateRequest,
    ) -> WorkspaceView:
        record = await dependencies.workspaces.update(
            workspace_id,
            WorkspaceWrite(name=request.name, description=request.description),
        )
        return _workspace_view(record)

    @router.delete(
        "/workspaces/{workspace_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    async def delete_workspace(workspace_id: UUID) -> Response:
        await dependencies.workspaces.delete(workspace_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/workspaces/{workspace_id}/overview",
        response_model=WorkspaceOverview,
    )
    async def workspace_overview(workspace_id: UUID) -> WorkspaceOverview:
        return await dependencies.workspaces.overview(workspace_id)

    @router.get(
        "/workspaces/{workspace_id}/agent-assets",
        response_model=tuple[AgentApiView, ...],
    )
    async def list_agent_assets(workspace_id: UUID) -> tuple[AgentApiView, ...]:
        records = await dependencies.workspaces.list_agent_apis(workspace_id)
        return tuple(_agent_api_view(record) for record in records)

    @router.post(
        "/workspaces/{workspace_id}/agent-assets",
        response_model=AgentApiView,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_agent_asset(
        workspace_id: UUID,
        request: AgentApiCreateRequest,
    ) -> AgentApiView:
        record = await dependencies.workspaces.create_agent_api(
            workspace_id,
            AgentApiWrite(
                name=request.name,
                api_base_url=request.api_base_url,
                model_id=request.model_id,
                credential_env_var=request.credential_env_var,
                description=request.description,
            ),
        )
        return _agent_api_view(record)

    @router.delete(
        "/workspaces/{workspace_id}/agent-assets/{agent_api_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    async def delete_agent_asset(workspace_id: UUID, agent_api_id: UUID) -> Response:
        await dependencies.workspaces.delete_agent_api(workspace_id, agent_api_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/maps/{map_id}/manifest")
    async def map_manifest(map_id: str) -> object:
        return dependencies.maps.manifest(map_id).model_dump(mode="json")

    @router.get("/maps/{map_id}/network")
    async def map_network(map_id: str) -> JSONResponse:
        return JSONResponse(
            dependencies.maps.network_geojson(map_id),
            media_type="application/geo+json",
        )

    @router.get("/simulations", response_model=tuple[SimulationHistorySummary, ...])
    async def list_simulations(
        workspace_id: Annotated[UUID | None, Query()] = None,
    ) -> tuple[SimulationHistorySummary, ...]:
        if dependencies.histories is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "simulation history storage is not configured",
            )
        return await dependencies.histories.list_runs(workspace_id)

    @router.get("/simulations/{run_id}", response_model=SimulationHistoryDetail)
    async def get_simulation(run_id: str) -> SimulationHistoryDetail:
        if dependencies.histories is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "simulation history storage is not configured",
            )
        return await dependencies.histories.get_run(run_id)

    @router.get("/simulations/{run_id}/network")
    async def get_simulation_network(run_id: str) -> JSONResponse:
        if dependencies.histories is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "simulation history storage is not configured",
            )
        return JSONResponse(
            await dependencies.histories.get_network(run_id),
            media_type="application/geo+json",
        )

    @router.get("/simulations/{run_id}/replay", response_model=SimulationReplayWindow)
    async def get_simulation_replay(
        run_id: str,
        from_time_ms: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=10_000)] = 2_000,
    ) -> SimulationReplayWindow:
        if dependencies.histories is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "simulation history storage is not configured",
            )
        return await dependencies.histories.get_replay(
            run_id,
            from_time_ms=from_time_ms,
            limit=limit,
        )

    @router.get("/simulations/{run_id}/export", response_class=Response)
    async def export_simulation(run_id: str) -> Response:
        if dependencies.histories is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "simulation history storage is not configured",
            )
        exported = await dependencies.histories.export_run(run_id)
        return Response(
            content=exported.payload,
            media_type=exported.media_type,
            headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
        )

    @router.post(
        "/maps/import",
        response_model=MapImportJob,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def import_map(file: Annotated[UploadFile, File()]) -> MapImportJob:
        if not file.filename or not file.filename.lower().endswith(".xodr"):
            raise TrafficVerseError(
                ErrorCode.MAP_ASSET_INVALID,
                "map import requires an .xodr file",
            )
        payload = await file.read(dependencies.maps.maximum_upload_bytes + 1)
        return await dependencies.maps.import_opendrive(payload)

    @router.get("/maps/import/{job_id}", response_model=MapImportJob)
    async def import_status(job_id: UUID) -> MapImportJob:
        return dependencies.maps.import_job(job_id)

    @router.post(
        "/simulation-configurations",
        response_model=SimulationConfigurationView,
        status_code=status.HTTP_201_CREATED,
    )
    async def save_simulation_configuration(
        request: SimulationConfigurationSaveRequest,
    ) -> SimulationConfigurationView:
        if dependencies.configurations is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "simulation configuration storage is not configured",
            )
        await dependencies.workspaces.get(request.workspace_id)
        snapshot = await dependencies.configurations.save(
            SimulationConfigurationDraft.model_validate(request.model_dump())
        )
        return SimulationConfigurationView.model_validate(snapshot.model_dump())

    @router.post(
        "/experiments",
        response_model=ExperimentView,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_experiment(request: ExperimentCreateRequest) -> ExperimentView:
        await dependencies.workspaces.get(request.workspace_id)
        run_input = None
        if request.configuration_id is not None:
            if dependencies.configurations is None:
                raise TrafficVerseError(
                    ErrorCode.COMPONENT_UNAVAILABLE,
                    "simulation configuration storage is not configured",
                )
            run_input = await dependencies.configurations.prepare_run(
                request.configuration_id,
                request.run_kind,
                request.workspace_id,
                request.scenario_id,
                request.map_id,
            )
            if (
                run_input.workspace_id != request.workspace_id
                or run_input.scenario_id != request.scenario_id
            ):
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_CONFLICT,
                    "saved simulation configuration does not belong to the requested context",
                )
            if request.map_id is not None and request.map_id != run_input.map_id:
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_CONFLICT,
                    "saved simulation configuration map does not match the request",
                )
        return await dependencies.runtimes.create(
            uuid4(),
            request.workspace_id,
            request.scenario_id,
            run_input.map_id if run_input is not None else request.map_id,
            run_input,
        )

    @router.get("/experiments/{experiment_id}", response_model=ExperimentView)
    async def get_experiment(experiment_id: UUID) -> ExperimentView:
        return await dependencies.runtimes.view(experiment_id)

    @router.post("/experiments/{experiment_id}/prepare", response_model=ExperimentView)
    async def prepare_experiment(experiment_id: UUID) -> ExperimentView:
        await _execute(dependencies.commands, experiment_id, "experiment.prepare", {})
        return await dependencies.runtimes.view(experiment_id)

    @router.post("/experiments/{experiment_id}/start", response_model=ExperimentView)
    async def start_experiment(experiment_id: UUID) -> ExperimentView:
        await _execute(dependencies.commands, experiment_id, "experiment.start", {})
        return await dependencies.runtimes.view(experiment_id)

    @router.post("/experiments/{experiment_id}/pause", response_model=ExperimentView)
    async def pause_experiment(experiment_id: UUID) -> ExperimentView:
        await _execute(dependencies.commands, experiment_id, "experiment.pause", {})
        return await dependencies.runtimes.view(experiment_id)

    @router.post("/experiments/{experiment_id}/resume", response_model=ExperimentView)
    async def resume_experiment(experiment_id: UUID) -> ExperimentView:
        await _execute(dependencies.commands, experiment_id, "experiment.resume", {})
        return await dependencies.runtimes.view(experiment_id)

    @router.post("/experiments/{experiment_id}/stop", response_model=ExperimentView)
    async def stop_experiment(
        experiment_id: UUID, request: StopExperimentRequest
    ) -> ExperimentView:
        await _execute(dependencies.commands, experiment_id, "experiment.stop", request)
        return await dependencies.runtimes.view(experiment_id)

    @router.post("/experiments/{experiment_id}/speed", response_model=ExperimentView)
    async def set_speed(experiment_id: UUID, request: SetSpeedRequest) -> ExperimentView:
        await _execute(dependencies.commands, experiment_id, "experiment.speed.set", request)
        return await dependencies.runtimes.view(experiment_id)

    return router
