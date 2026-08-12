"""Experiment repository decorator that mirrors lifecycle state into ``run.json``."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from trafficverse.domain.enums import ExperimentStatus
from trafficverse.domain.models import DomainEvent, MetricSample
from trafficverse.ports import ExperimentRepositoryPort

_TERMINAL = frozenset({ExperimentStatus.COMPLETED, ExperimentStatus.FAILED})


class RunMetadataExperimentRepository:
    """Delegate experiment persistence and atomically update one artifact's metadata."""

    def __init__(
        self,
        delegate: ExperimentRepositoryPort,
        *,
        experiment_id: UUID,
        run_directory: Path,
    ) -> None:
        self._delegate = delegate
        self._experiment_id = experiment_id
        self._metadata_path = run_directory.resolve() / "run.json"
        self._write_status(ExperimentStatus.CREATED, reason=None)

    async def get_status(self, experiment_id: UUID) -> ExperimentStatus:
        return await self._delegate.get_status(experiment_id)

    async def set_status(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        *,
        reason: str | None = None,
    ) -> None:
        await self._delegate.set_status(experiment_id, status, reason=reason)
        if experiment_id == self._experiment_id:
            self._write_status(status, reason=reason)

    async def append_event(self, event: DomainEvent) -> None:
        await self._delegate.append_event(event)

    async def append_metric(self, metric: MetricSample) -> None:
        await self._delegate.append_metric(metric)

    def _write_status(self, status: ExperimentStatus, *, reason: str | None) -> None:
        try:
            value = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        payload = value if isinstance(value, dict) else {}
        now = datetime.now().astimezone().isoformat()
        payload.update(
            {
                "schema_version": "1.1",
                "experiment_id": str(self._experiment_id),
                "status": status.value,
                "status_reason": reason,
                "updated_at": now,
            }
        )
        if status is ExperimentStatus.RUNNING and "started_at" not in payload:
            payload["started_at"] = now
        if status in _TERMINAL:
            payload["ended_at"] = now
        temporary = self._metadata_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._metadata_path)
