"""Use cases for saving UI configurations and preparing isolated runs."""

from __future__ import annotations

import asyncio
from uuid import UUID

from trafficverse.domain.enums import SimulationRunKind
from trafficverse.domain.models import (
    SimulationConfigurationDraft,
    SimulationConfigurationSnapshot,
    SimulationRunInput,
)
from trafficverse.ports import SimulationConfigurationStoragePort


class SimulationConfigurationService:
    """Keep blocking configuration file work outside the API event loop."""

    def __init__(self, storage: SimulationConfigurationStoragePort) -> None:
        self._storage = storage

    async def save(
        self,
        draft: SimulationConfigurationDraft,
    ) -> SimulationConfigurationSnapshot:
        return await asyncio.to_thread(self._storage.save, draft)

    async def prepare_run(
        self,
        configuration_id: str,
        run_kind: SimulationRunKind,
        workspace_id: UUID,
        scenario_id: UUID,
        map_id: str | None,
    ) -> SimulationRunInput:
        return await asyncio.to_thread(
            self._storage.prepare_run,
            configuration_id,
            run_kind,
            workspace_id,
            scenario_id,
            map_id,
        )
