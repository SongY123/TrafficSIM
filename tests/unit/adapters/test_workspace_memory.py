import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from trafficverse.adapters.persistence import InMemoryWorkspaceRepository
from trafficverse.domain.enums import ErrorCode
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import WorkspaceListQuery, WorkspaceRecord

BASE_TIME = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _record(
    value: int,
    name: str,
    description: str,
    *,
    deleted: bool = False,
) -> WorkspaceRecord:
    return WorkspaceRecord(
        workspace_id=UUID(int=value),
        name=name,
        description=description,
        created_at=BASE_TIME,
        updated_at=BASE_TIME + timedelta(minutes=value),
        deleted_at=BASE_TIME if deleted else None,
    )


def test_empty_repository_returns_empty_page() -> None:
    page = asyncio.run(InMemoryWorkspaceRepository().list_workspaces(WorkspaceListQuery()))
    assert page.total == 0
    assert page.items == ()


def test_list_search_pagination_and_literal_wildcards() -> None:
    repository = InMemoryWorkspaceRepository(
        (
            _record(1, "Alpha", "city traffic"),
            _record(2, "Percent % plan", "literal underscore_value"),
            _record(3, "Deleted traffic", "hidden", deleted=True),
        )
    )

    async def exercise() -> None:
        all_active = await repository.list_workspaces(WorkspaceListQuery(limit=1))
        by_name = await repository.list_workspaces(WorkspaceListQuery(q=" alpha "))
        by_description = await repository.list_workspaces(WorkspaceListQuery(q="CITY"))
        percent = await repository.list_workspaces(WorkspaceListQuery(q="%"))
        underscore = await repository.list_workspaces(WorkspaceListQuery(q="_"))
        missing = await repository.list_workspaces(WorkspaceListQuery(q="missing"))

        assert all_active.total == 2
        assert len(all_active.items) == 1
        assert all_active.items[0].workspace_id == UUID(int=2)
        assert by_name.items[0].workspace_id == UUID(int=1)
        assert by_description.items[0].workspace_id == UUID(int=1)
        assert percent.items[0].workspace_id == UUID(int=2)
        assert underscore.items[0].workspace_id == UUID(int=2)
        assert missing.total == 0

        with pytest.raises(TrafficVerseError) as deleted:
            await repository.get_workspace(UUID(int=3))
        assert deleted.value.code is ErrorCode.RESOURCE_NOT_FOUND

    asyncio.run(exercise())
