from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from trafficverse.adapters.persistence import InMemoryWorkspaceRepository
from trafficverse.api import create_app
from trafficverse.application.workspace_service import WorkspaceService
from trafficverse.domain.models import WorkspaceRecord
from tests.unit.api.test_app import FakeManager, _dependencies

BASE_TIME = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _record(value: int, name: str, description: str) -> WorkspaceRecord:
    return WorkspaceRecord(
        workspace_id=UUID(int=value),
        name=name,
        description=description,
        created_at=BASE_TIME,
        updated_at=BASE_TIME + timedelta(minutes=value),
    )


def test_workspace_routes_list_search_page_detail_and_not_found(tmp_path: Path) -> None:
    repository = InMemoryWorkspaceRepository(
        (
            _record(1, "Traffic baseline", "morning commute"),
            _record(2, "Percent % study", "literal_underbar"),
        )
    )
    dependencies = replace(
        _dependencies(tmp_path, FakeManager(uuid4())),
        workspaces=WorkspaceService(repository),
    )

    with TestClient(create_app(dependencies)) as client:
        page = client.get("/api/v1/workspaces", params={"offset": 0, "limit": 1})
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert len(page.json()["items"]) == 1

        by_name = client.get("/api/v1/workspaces", params={"q": " traffic "})
        by_description = client.get("/api/v1/workspaces", params={"q": "COMMUTE"})
        percent = client.get("/api/v1/workspaces", params={"q": "%"})
        underscore = client.get("/api/v1/workspaces", params={"q": "_"})
        assert by_name.json()["items"][0]["workspace_id"] == str(UUID(int=1))
        assert by_description.json()["items"][0]["workspace_id"] == str(UUID(int=1))
        assert percent.json()["total"] == 1
        assert underscore.json()["total"] == 1

        detail = client.get(f"/api/v1/workspaces/{UUID(int=2)}")
        assert detail.status_code == 200
        assert detail.json()["name"] == "Percent % study"

        missing = client.get(f"/api/v1/workspaces/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_workspace_routes_return_503_without_dependency(tmp_path: Path) -> None:
    dependencies = _dependencies(tmp_path, FakeManager(uuid4()))

    with TestClient(create_app(dependencies)) as client:
        response = client.get("/api/v1/workspaces")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "COMPONENT_UNAVAILABLE"
