"""Workspace management use cases and temporary overview data."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from trafficverse.domain.models import (
    AgentApiRecord,
    AgentApiWrite,
    WorkspaceActivitySample,
    WorkspaceAutomationCount,
    WorkspaceOverview,
    WorkspaceRecentSimulation,
    WorkspaceRecord,
    WorkspaceWrite,
)
from trafficverse.ports.persistence import WorkspaceRepositoryPort


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepositoryPort) -> None:
        self._repository = repository

    async def create(self, write: WorkspaceWrite) -> WorkspaceRecord:
        return await self._repository.create_workspace(self._normalized(write))

    async def get(self, workspace_id: UUID) -> WorkspaceRecord:
        return await self._repository.get_workspace(workspace_id)

    async def list(self, query: str | None = None) -> tuple[WorkspaceRecord, ...]:
        return await self._repository.list_workspaces(query)

    async def update(self, workspace_id: UUID, write: WorkspaceWrite) -> WorkspaceRecord:
        return await self._repository.update_workspace(workspace_id, self._normalized(write))

    async def delete(self, workspace_id: UUID) -> None:
        await self._repository.delete_workspace(workspace_id)

    async def overview(self, workspace_id: UUID) -> WorkspaceOverview:
        """Return stable mock data behind the final overview interface."""
        workspace = await self.get(workspace_id)
        offset = workspace.workspace_id.int % 17
        simulations = 18 + offset
        failed = 1 + offset % 3
        return WorkspaceOverview(
            workspace_id=workspace.workspace_id,
            map_count=6,
            agent_count=200,
            scenario_count=4,
            simulation_count=simulations,
            automation_counts=(
                WorkspaceAutomationCount(level="L0", count=30),
                WorkspaceAutomationCount(level="L1", count=30),
                WorkspaceAutomationCount(level="L2", count=35),
                WorkspaceAutomationCount(level="L3", count=35),
                WorkspaceAutomationCount(level="L4", count=30),
                WorkspaceAutomationCount(level="L5", count=25),
                WorkspaceAutomationCount(level="其他交通参与方", count=15),
            ),
            succeeded_simulations=simulations - failed,
            failed_simulations=failed,
            runtime_hours=simulations * 0.35,
            activity=tuple(
                WorkspaceActivitySample(day=date(2026, 7, day), simulations=value + offset % 2)
                for day, value in zip(
                    range(13, 20),
                    (2, 3, 1, 4, 3, 2, 3),
                    strict=True,
                )
            ),
            recent_simulations=(
                WorkspaceRecentSimulation(
                    name="Peak_Hour_Mix_01",
                    status="SUCCEEDED",
                    occurred_at=datetime(2026, 7, 19, 8, 30, tzinfo=timezone.utc),
                    duration_ms=1_500_000,
                    automation_summary="L3 · 45%",
                ),
                WorkspaceRecentSimulation(
                    name="Intersection_Test_Night",
                    status="SUCCEEDED",
                    occurred_at=datetime(2026, 7, 18, 22, 15, tzinfo=timezone.utc),
                    duration_ms=1_200_000,
                    automation_summary="L4 · 10%",
                ),
                WorkspaceRecentSimulation(
                    name="Highway_Merge_Stress",
                    status="WARNING",
                    occurred_at=datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc),
                    duration_ms=1_800_000,
                    automation_summary="L2 · 60%",
                ),
            ),
            preview_region=f"{workspace.name}核心区",
        )

    async def create_agent_api(
        self,
        workspace_id: UUID,
        write: AgentApiWrite,
    ) -> AgentApiRecord:
        return await self._repository.create_agent_api(workspace_id, write)

    async def list_agent_apis(self, workspace_id: UUID) -> tuple[AgentApiRecord, ...]:
        return await self._repository.list_agent_apis(workspace_id)

    async def delete_agent_api(self, workspace_id: UUID, agent_api_id: UUID) -> None:
        await self._repository.delete_agent_api(workspace_id, agent_api_id)

    @staticmethod
    def _normalized(write: WorkspaceWrite) -> WorkspaceWrite:
        return WorkspaceWrite(
            name=write.name.strip(),
            description=write.description.strip(),
        )
