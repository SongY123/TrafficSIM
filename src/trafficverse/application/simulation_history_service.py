"""Application boundary for immutable simulation results and replay data."""

from __future__ import annotations

import asyncio
from uuid import UUID

from trafficverse.domain.models import (
    SimulationHistoryDetail,
    SimulationHistorySummary,
    SimulationReplayWindow,
    SimulationResultExport,
)
from trafficverse.ports import SimulationHistoryStorePort


class SimulationHistoryService:
    """Move blocking artifact reads away from the API event loop."""

    def __init__(self, store: SimulationHistoryStorePort) -> None:
        self._store = store

    async def list_runs(
        self, workspace_id: UUID | None = None
    ) -> tuple[SimulationHistorySummary, ...]:
        return await asyncio.to_thread(self._store.list_runs, workspace_id)

    async def get_run(self, run_id: str) -> SimulationHistoryDetail:
        return await asyncio.to_thread(self._store.get_run, run_id)

    async def get_network(self, run_id: str) -> dict[str, object]:
        return await asyncio.to_thread(self._store.get_network, run_id)

    async def get_replay(
        self,
        run_id: str,
        *,
        from_time_ms: int,
        limit: int,
    ) -> SimulationReplayWindow:
        return await asyncio.to_thread(
            self._store.get_replay,
            run_id,
            from_time_ms=from_time_ms,
            limit=limit,
        )

    async def export_run(self, run_id: str) -> SimulationResultExport:
        return await asyncio.to_thread(self._store.export_run, run_id)
