"""Process-local experiment state adapter for the database-free Core Run."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID

from trafficverse.domain.enums import ErrorCode, ExperimentStatus
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    DomainEvent,
    MetricSample,
    WorkspaceListQuery,
    WorkspacePage,
    WorkspaceRecord,
)


class InMemoryExperimentRepository:
    def __init__(self) -> None:
        self._statuses: dict[UUID, ExperimentStatus] = {}
        self._events: dict[UUID, list[DomainEvent]] = {}
        self._metrics: dict[UUID, list[MetricSample]] = {}
        self._lock = asyncio.Lock()

    async def create(self, experiment_id: UUID) -> None:
        async with self._lock:
            if experiment_id in self._statuses:
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_CONFLICT,
                    f"experiment already exists: {experiment_id}",
                )
            self._statuses[experiment_id] = ExperimentStatus.CREATED

    async def get_status(self, experiment_id: UUID) -> ExperimentStatus:
        async with self._lock:
            try:
                return self._statuses[experiment_id]
            except KeyError as error:
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    f"experiment does not exist: {experiment_id}",
                ) from error

    async def set_status(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        *,
        reason: str | None = None,
    ) -> None:
        del reason
        async with self._lock:
            if experiment_id not in self._statuses:
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    f"experiment does not exist: {experiment_id}",
                )
            self._statuses[experiment_id] = status

    async def append_event(self, event: DomainEvent) -> None:
        async with self._lock:
            self._events.setdefault(event.experiment_id, []).append(event)

    async def append_metric(self, metric: MetricSample) -> None:
        async with self._lock:
            self._metrics.setdefault(metric.experiment_id, []).append(metric)


class InMemoryWorkspaceRepository:
    def __init__(self, seed: Sequence[WorkspaceRecord] = ()) -> None:
        self._records = {record.workspace_id: record for record in seed}
        self._lock = asyncio.Lock()

    async def get_workspace(self, workspace_id: UUID) -> WorkspaceRecord:
        async with self._lock:
            record = self._records.get(workspace_id)
            if record is None or record.deleted_at is not None:
                raise TrafficVerseError(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    f"workspace does not exist: {workspace_id}",
                )
            return record

    async def list_workspaces(self, query: WorkspaceListQuery) -> WorkspacePage:
        async with self._lock:
            records = [record for record in self._records.values() if record.deleted_at is None]
            if query.q is not None:
                needle = query.q.casefold()
                records = [
                    record
                    for record in records
                    if needle in record.name.casefold() or needle in record.description.casefold()
                ]
            records.sort(key=lambda record: str(record.workspace_id))
            records.sort(key=lambda record: record.updated_at, reverse=True)
            total = len(records)
            return WorkspacePage(
                items=tuple(records[query.offset : query.offset + query.limit]),
                total=total,
                offset=query.offset,
                limit=query.limit,
            )
