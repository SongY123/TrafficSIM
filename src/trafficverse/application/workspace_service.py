"""Read-only workspace list, search, and detail use cases."""

from uuid import UUID

from trafficverse.domain.models import WorkspaceListQuery, WorkspacePage, WorkspaceRecord
from trafficverse.ports.persistence import WorkspaceRepositoryPort


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepositoryPort) -> None:
        self._repository = repository

    async def list(self, query: WorkspaceListQuery) -> WorkspacePage:
        return await self._repository.list_workspaces(query)

    async def get(self, workspace_id: UUID) -> WorkspaceRecord:
        return await self._repository.get_workspace(workspace_id)
