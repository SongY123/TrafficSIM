"""Async PostgreSQL repositories with explicit transaction boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from trafficverse.adapters.persistence.postgres.models import (
    ArtifactRow,
    EventRow,
    ExperimentRow,
    ExperimentStateChangeRow,
    MapAssetRow,
    MetricSampleRow,
    ScenarioRow,
    ScenarioVersionRow,
    WorkspaceRow,
)
from trafficverse.domain.enums import ErrorCode, EventSeverity, ExperimentStatus
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
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
    ScenarioVersionRecord,
    ScenarioWrite,
    WorkspaceListQuery,
    WorkspacePage,
    WorkspaceRecord,
)
from trafficverse.domain.state_machine import require_transition

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def create_postgres_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


class PostgresRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def register_map_asset(self, asset: MapAssetRegistration) -> None:
        try:
            async with self._sessions() as session, session.begin():
                session.add(
                    MapAssetRow(
                        id=asset.map_asset_id,
                        map_id=asset.map_id,
                        name=asset.name,
                        source_format=asset.source_format,
                        source_checksum=asset.source_checksum,
                        network_schema_version=asset.network_schema_version,
                        manifest_uri=asset.manifest_uri,
                        status=asset.status,
                    )
                )
        except IntegrityError as error:
            raise self._conflict("map asset already exists", error) from error

    async def get_workspace(self, workspace_id: UUID) -> WorkspaceRecord:
        async with self._sessions() as session:
            row = await session.scalar(
                select(WorkspaceRow).where(
                    WorkspaceRow.id == workspace_id,
                    WorkspaceRow.deleted_at.is_(None),
                )
            )
            if row is None:
                raise self._not_found("workspace", workspace_id)
            return self._workspace_record(row)

    async def list_workspaces(self, query: WorkspaceListQuery) -> WorkspacePage:
        filters = [WorkspaceRow.deleted_at.is_(None)]
        if query.q is not None:
            escaped = (
                query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    WorkspaceRow.name.ilike(pattern, escape="\\"),
                    WorkspaceRow.description.ilike(pattern, escape="\\"),
                )
            )
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.count()).select_from(WorkspaceRow).where(*filters)
            )
            rows = (
                await session.scalars(
                    select(WorkspaceRow)
                    .where(*filters)
                    .order_by(WorkspaceRow.updated_at.desc(), WorkspaceRow.id)
                    .offset(query.offset)
                    .limit(query.limit)
                )
            ).all()
            return WorkspacePage(
                items=tuple(self._workspace_record(row) for row in rows),
                total=int(total or 0),
                offset=query.offset,
                limit=query.limit,
            )

    async def create_scenario(self, write: ScenarioWrite) -> ScenarioRecord:
        now = datetime.now(timezone.utc)
        scenario = ScenarioRow(
            name=write.name,
            description=write.description,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(scenario)
                await session.flush()
                version = ScenarioVersionRow(
                    scenario_id=scenario.id,
                    map_asset_id=write.map_asset_id,
                    version=1,
                    config=write.config,
                    config_hash=write.config_hash,
                    created_at=now,
                )
                session.add(version)
                await session.flush()
                return self._scenario_record(scenario, version)
        except IntegrityError as error:
            raise self._conflict("scenario references an invalid map asset", error) from error

    async def get_scenario(
        self, scenario_id: UUID, *, include_deleted: bool = False
    ) -> ScenarioRecord:
        async with self._sessions() as session:
            scenario = await session.get(ScenarioRow, scenario_id)
            scenario = self._require_scenario(scenario, include_deleted=include_deleted)
            version = await self._latest_version(session, scenario_id)
            return self._scenario_record(scenario, version)

    async def list_scenarios(self, query: ScenarioListQuery) -> ScenarioPage:
        filters = [] if query.include_deleted else [ScenarioRow.deleted_at.is_(None)]
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.count()).select_from(ScenarioRow).where(*filters)
            )
            rows = (
                await session.scalars(
                    select(ScenarioRow)
                    .where(*filters)
                    .order_by(ScenarioRow.created_at, ScenarioRow.id)
                    .offset(query.offset)
                    .limit(query.limit)
                )
            ).all()
            items_list: list[ScenarioRecord] = []
            for row in rows:
                version = await self._latest_version(session, row.id)
                items_list.append(self._scenario_record(row, version))
            return ScenarioPage(
                items=tuple(items_list),
                total=int(total or 0),
                offset=query.offset,
                limit=query.limit,
            )

    async def update_scenario(
        self,
        scenario_id: UUID,
        write: ScenarioWrite,
        *,
        expected_version: int,
    ) -> ScenarioRecord:
        try:
            async with self._sessions() as session, session.begin():
                scenario = await session.scalar(
                    select(ScenarioRow).where(ScenarioRow.id == scenario_id).with_for_update()
                )
                scenario = self._require_scenario(scenario, include_deleted=False)
                current = await self._latest_version(session, scenario_id)
                if current.version != expected_version:
                    raise TrafficVerseError(
                        ErrorCode.CONCURRENT_MODIFICATION,
                        "scenario was updated by another client",
                        details={
                            "expected_version": str(expected_version),
                            "current_version": str(current.version),
                        },
                    )
                now = datetime.now(timezone.utc)
                scenario.name = write.name
                scenario.description = write.description
                scenario.updated_at = now
                version = ScenarioVersionRow(
                    scenario_id=scenario.id,
                    map_asset_id=write.map_asset_id,
                    version=current.version + 1,
                    config=write.config,
                    config_hash=write.config_hash,
                    created_at=now,
                )
                session.add(version)
                await session.flush()
                return self._scenario_record(scenario, version)
        except IntegrityError as error:
            raise self._conflict("scenario update violates a database constraint", error) from error

    async def soft_delete_scenario(self, scenario_id: UUID) -> None:
        async with self._sessions() as session, session.begin():
            scenario = await session.scalar(
                select(ScenarioRow).where(ScenarioRow.id == scenario_id).with_for_update()
            )
            scenario = self._require_scenario(scenario, include_deleted=True)
            if scenario.deleted_at is None:
                now = datetime.now(timezone.utc)
                scenario.deleted_at = now
                scenario.updated_at = now

    async def create_experiment(self, create: ExperimentCreate) -> ExperimentRecord:
        row = ExperimentRow(
            id=create.experiment_id,
            scenario_version_id=create.scenario_version_id,
            status=ExperimentStatus.CREATED.value,
            seed=create.seed,
            step_ms=create.step_ms,
            duration_ms=create.duration_ms,
            current_time_ms=0,
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
                await session.flush()
                return self._experiment_record(row)
        except IntegrityError as error:
            raise self._conflict("experiment cannot be created", error) from error

    async def get_experiment(self, experiment_id: UUID) -> ExperimentRecord:
        async with self._sessions() as session:
            row = await session.get(ExperimentRow, experiment_id)
            if row is None:
                raise self._not_found("experiment", experiment_id)
            return self._experiment_record(row)

    async def get_status(self, experiment_id: UUID) -> ExperimentStatus:
        return (await self.get_experiment(experiment_id)).status

    async def set_status(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        *,
        reason: str | None = None,
    ) -> None:
        current = await self.get_experiment(experiment_id)
        await self.transition_status(
            experiment_id,
            status,
            simulation_time_ms=current.current_time_ms,
            reason=reason,
        )

    async def transition_status(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        *,
        simulation_time_ms: int,
        reason: str | None = None,
    ) -> ExperimentRecord:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(ExperimentRow).where(ExperimentRow.id == experiment_id).with_for_update()
            )
            if row is None:
                raise self._not_found("experiment", experiment_id)
            current = ExperimentStatus(row.status)
            require_transition(current, status)
            if current is status:
                return self._experiment_record(row)
            now = datetime.now(timezone.utc)
            row.status = status.value
            row.current_time_ms = simulation_time_ms
            if status is ExperimentStatus.RUNNING and row.started_at is None:
                row.started_at = now
            if status in {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED}:
                row.ended_at = now
            session.add(
                ExperimentStateChangeRow(
                    experiment_id=experiment_id,
                    from_status=current.value,
                    to_status=status.value,
                    reason=reason,
                    simulation_time_ms=simulation_time_ms,
                    occurred_at=now,
                )
            )
            await session.flush()
            return self._experiment_record(row)

    async def list_state_changes(
        self, experiment_id: UUID
    ) -> tuple[ExperimentStateChangeRecord, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ExperimentStateChangeRow)
                    .where(ExperimentStateChangeRow.experiment_id == experiment_id)
                    .order_by(ExperimentStateChangeRow.id)
                )
            ).all()
            return tuple(
                ExperimentStateChangeRecord(
                    state_change_id=row.id,
                    experiment_id=row.experiment_id,
                    from_status=ExperimentStatus(row.from_status),
                    to_status=ExperimentStatus(row.to_status),
                    reason=row.reason,
                    simulation_time_ms=row.simulation_time_ms,
                    occurred_at=row.occurred_at,
                )
                for row in rows
            )

    async def append_event(self, event: DomainEvent) -> None:
        row = EventRow(
            id=event.event_id,
            experiment_id=event.experiment_id,
            type=event.event_type,
            severity=event.severity.value,
            simulation_time_ms=event.simulation_time_ms,
            payload=event.payload,
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
        except IntegrityError as error:
            raise self._conflict("event cannot be appended", error) from error

    async def append_metric(self, metric: MetricSample) -> None:
        row = MetricSampleRow(
            experiment_id=metric.experiment_id,
            metric_name=metric.metric_name,
            value=metric.value,
            unit=metric.unit,
            simulation_time_ms=metric.simulation_time_ms,
            dimensions=metric.dimensions,
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
        except IntegrityError as error:
            raise self._conflict("metric cannot be appended", error) from error

    async def append_artifact(self, artifact: ArtifactCreate) -> ArtifactRecord:
        row = ArtifactRow(
            id=artifact.artifact_id,
            experiment_id=artifact.experiment_id,
            kind=artifact.kind,
            uri=artifact.uri,
            format=artifact.format,
            checksum=artifact.checksum,
            size_bytes=artifact.size_bytes,
            metadata_json=artifact.metadata,
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
                await session.flush()
                return ArtifactRecord(
                    **artifact.model_dump(mode="python"), created_at=row.created_at
                )
        except IntegrityError as error:
            raise self._conflict("artifact cannot be appended", error) from error

    async def list_events(
        self, experiment_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[DomainEvent, ...]:
        self._validate_page(offset, limit)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(EventRow)
                    .where(EventRow.experiment_id == experiment_id)
                    .order_by(EventRow.simulation_time_ms, EventRow.occurred_at, EventRow.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return tuple(
                DomainEvent(
                    event_id=row.id,
                    experiment_id=row.experiment_id,
                    event_type=row.type,
                    severity=EventSeverity(row.severity),
                    simulation_time_ms=row.simulation_time_ms,
                    payload=_JSON_VALUE.validate_python(row.payload),
                )
                for row in rows
            )

    async def list_metrics(
        self,
        experiment_id: UUID,
        *,
        metric_name: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[MetricSample, ...]:
        self._validate_page(offset, limit)
        filters = [MetricSampleRow.experiment_id == experiment_id]
        if metric_name is not None:
            filters.append(MetricSampleRow.metric_name == metric_name)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(MetricSampleRow)
                    .where(*filters)
                    .order_by(MetricSampleRow.simulation_time_ms, MetricSampleRow.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return tuple(
                MetricSample(
                    experiment_id=row.experiment_id,
                    metric_name=row.metric_name,
                    value=row.value,
                    unit=row.unit,
                    simulation_time_ms=row.simulation_time_ms,
                    dimensions=row.dimensions,
                )
                for row in rows
            )

    async def list_artifacts(self, experiment_id: UUID) -> tuple[ArtifactRecord, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ArtifactRow)
                    .where(ArtifactRow.experiment_id == experiment_id)
                    .order_by(ArtifactRow.created_at, ArtifactRow.id)
                )
            ).all()
            return tuple(
                ArtifactRecord(
                    artifact_id=row.id,
                    experiment_id=row.experiment_id,
                    kind=row.kind,
                    uri=row.uri,
                    format=row.format,
                    checksum=row.checksum,
                    size_bytes=row.size_bytes,
                    metadata=_JSON_OBJECT.validate_python(row.metadata_json),
                    created_at=row.created_at,
                )
                for row in rows
            )

    @staticmethod
    async def _latest_version(session: AsyncSession, scenario_id: UUID) -> ScenarioVersionRow:
        version = await session.scalar(
            select(ScenarioVersionRow)
            .where(ScenarioVersionRow.scenario_id == scenario_id)
            .order_by(ScenarioVersionRow.version.desc())
            .limit(1)
        )
        if version is None:
            raise TrafficVerseError(
                ErrorCode.RESOURCE_NOT_FOUND,
                f"scenario has no versions: {scenario_id}",
            )
        return version

    @staticmethod
    def _require_scenario(scenario: ScenarioRow | None, *, include_deleted: bool) -> ScenarioRow:
        if scenario is None or (scenario.deleted_at is not None and not include_deleted):
            identifier = "unknown" if scenario is None else str(scenario.id)
            raise PostgresRepository._not_found("scenario", identifier)
        return scenario

    @staticmethod
    def _scenario_record(scenario: ScenarioRow, version: ScenarioVersionRow) -> ScenarioRecord:
        return ScenarioRecord(
            scenario_id=scenario.id,
            name=scenario.name,
            description=scenario.description,
            current_version=ScenarioVersionRecord(
                scenario_version_id=version.id,
                scenario_id=version.scenario_id,
                map_asset_id=version.map_asset_id,
                version=version.version,
                config=_JSON_OBJECT.validate_python(version.config),
                config_hash=version.config_hash,
                created_at=version.created_at,
            ),
            created_at=scenario.created_at,
            updated_at=scenario.updated_at,
            deleted_at=scenario.deleted_at,
        )

    @staticmethod
    def _workspace_record(row: WorkspaceRow) -> WorkspaceRecord:
        return WorkspaceRecord(
            workspace_id=row.id,
            name=row.name,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )

    @staticmethod
    def _experiment_record(row: ExperimentRow) -> ExperimentRecord:
        return ExperimentRecord(
            experiment_id=row.id,
            scenario_version_id=row.scenario_version_id,
            status=ExperimentStatus(row.status),
            seed=row.seed,
            step_ms=row.step_ms,
            duration_ms=row.duration_ms,
            current_time_ms=row.current_time_ms,
            failure_code=row.failure_code,
            created_at=row.created_at,
            started_at=row.started_at,
            ended_at=row.ended_at,
        )

    @staticmethod
    def _not_found(resource: str, identifier: object) -> TrafficVerseError:
        return TrafficVerseError(
            ErrorCode.RESOURCE_NOT_FOUND,
            f"{resource} does not exist: {identifier}",
        )

    @staticmethod
    def _conflict(message: str, error: IntegrityError) -> TrafficVerseError:
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        return TrafficVerseError(
            ErrorCode.RESOURCE_CONFLICT,
            message,
            details={"constraint": str(constraint or "unknown")},
        )

    @staticmethod
    def _validate_page(offset: int, limit: int) -> None:
        if offset < 0 or limit < 1 or limit > 1000:
            raise ValueError("offset must be non-negative and limit must be between 1 and 1000")
