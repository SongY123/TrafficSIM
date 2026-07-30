import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from trafficverse.application.workspace_service import WorkspaceService
from trafficverse.domain.models import WorkspaceListQuery, WorkspacePage, WorkspaceRecord


def _record(workspace_id: UUID) -> WorkspaceRecord:
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    return WorkspaceRecord(
        workspace_id=workspace_id,
        name="Research workspace",
        description="Traffic experiments",
        created_at=now,
        updated_at=now,
    )


class RecordingWorkspaceRepository:
    def __init__(self, record: WorkspaceRecord) -> None:
        self.record = record
        self.query: WorkspaceListQuery | None = None
        self.workspace_id: UUID | None = None

    async def list_workspaces(self, query: WorkspaceListQuery) -> WorkspacePage:
        self.query = query
        return WorkspacePage(items=(self.record,), total=1, offset=query.offset, limit=query.limit)

    async def get_workspace(self, workspace_id: UUID) -> WorkspaceRecord:
        self.workspace_id = workspace_id
        return self.record


def test_list_and_get_delegate_to_read_only_repository() -> None:
    async def exercise() -> None:
        workspace_id = uuid4()
        repository = RecordingWorkspaceRepository(_record(workspace_id))
        service = WorkspaceService(repository)
        query = WorkspaceListQuery(q="  traffic  ", offset=2, limit=5)

        page = await service.list(query)
        detail = await service.get(workspace_id)

        assert repository.query == WorkspaceListQuery(q="traffic", offset=2, limit=5)
        assert repository.workspace_id == workspace_id
        assert page.items == (detail,)

    asyncio.run(exercise())
