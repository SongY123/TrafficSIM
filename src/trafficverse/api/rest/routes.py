"""Core Run REST resources."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse

from trafficverse.api.command_bus import ExperimentCommandBus
from trafficverse.api.dependencies import ApiDependencies
from trafficverse.api.models import (
    CommandOutcome,
    ExperimentCreateRequest,
    ExperimentView,
    HealthResponse,
    MapImportJob,
    MapSummary,
    ReadinessResponse,
    SetSpeedRequest,
    StopExperimentRequest,
    WorkspacePageResponse,
    WorkspaceSummary,
)
from trafficverse.domain.enums import ErrorCode
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import WorkspaceListQuery, WorkspaceRecord


def _require_accepted(outcome: CommandOutcome) -> None:
    if not outcome.accepted:
        code = ErrorCode(outcome.error_code or ErrorCode.RESOURCE_CONFLICT.value)
        raise TrafficVerseError(code, outcome.message or "command was rejected")


async def _execute(
    commands: ExperimentCommandBus,
    experiment_id: UUID,
    command_type: str,
    payload: object,
) -> CommandOutcome:
    outcome = await commands.execute(experiment_id, command_type, payload)
    _require_accepted(outcome)
    return outcome


def _workspace_summary(record: WorkspaceRecord) -> WorkspaceSummary:
    return WorkspaceSummary(
        workspace_id=record.workspace_id,
        name=record.name,
        description=record.description,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


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

    @router.get("/maps/{map_id}/manifest")
    async def map_manifest(map_id: str) -> object:
        return dependencies.maps.manifest(map_id).model_dump(mode="json")

    @router.get("/maps/{map_id}/network")
    async def map_network(map_id: str) -> JSONResponse:
        return JSONResponse(
            dependencies.maps.network_geojson(map_id),
            media_type="application/geo+json",
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

    @router.get("/workspaces", response_model=WorkspacePageResponse)
    async def list_workspaces(
        q: Annotated[str | None, Query()] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> WorkspacePageResponse:
        if dependencies.workspaces is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "workspace repository is not configured",
            )
        page = await dependencies.workspaces.list(
            WorkspaceListQuery(q=q, offset=offset, limit=limit)
        )
        return WorkspacePageResponse(
            items=tuple(_workspace_summary(record) for record in page.items),
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )

    @router.get("/workspaces/{workspace_id}", response_model=WorkspaceSummary)
    async def get_workspace(workspace_id: UUID) -> WorkspaceSummary:
        if dependencies.workspaces is None:
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "workspace repository is not configured",
            )
        return _workspace_summary(await dependencies.workspaces.get(workspace_id))

    @router.post(
        "/experiments",
        response_model=ExperimentView,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_experiment(request: ExperimentCreateRequest) -> ExperimentView:
        return await dependencies.runtimes.create(
            uuid4(),
            request.scenario_id,
            request.map_id,
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
