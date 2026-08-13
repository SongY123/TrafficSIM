from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from PySide6.QtWidgets import QApplication, QPushButton
from ui.models import AgentApiSummary
from ui.views.agent_asset_page import AgentAssetPage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def test_empty_catalog_displays_mock_agents_for_all_automation_levels() -> None:
    _application()
    page = AgentAssetPage()

    assert page.table.rowCount() == 6
    assert [page.table.item(row, 0).text() for row in range(6)] == [
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
    ]
    assert page.table.item(0, 1).text() == "L0人工驾驶智能体"
    assert page.table.item(5, 1).text() == "L5完全自动驾驶智能体"


def test_each_mock_agent_row_has_edit_and_delete_buttons() -> None:
    _application()
    page = AgentAssetPage()

    for row in range(page.table.rowCount()):
        actions = page.table.cellWidget(row, 4)
        assert actions is not None
        assert actions.findChild(QPushButton, "agentRowEditButton") is not None
        assert actions.findChild(QPushButton, "agentRowDeleteButton") is not None


def test_edit_button_populates_form_and_saves_mock_agent_locally() -> None:
    _application()
    page = AgentAssetPage()
    actions = page.table.cellWidget(2, 4)
    assert actions is not None
    edit_button = actions.findChild(QPushButton, "agentRowEditButton")
    assert edit_button is not None

    edit_button.click()
    assert page.name_input.text() == "L2部分自动驾驶智能体"
    assert page.save_button.text() == "保存修改"

    page.name_input.setText("L2园区巡航智能体")
    page.save_button.click()

    assert page.table.item(2, 1).text() == "L2园区巡航智能体"
    assert page.save_button.text() == "添加 API 智能体"


def test_delete_button_removes_mock_agent_locally() -> None:
    _application()
    page = AgentAssetPage()
    actions = page.table.cellWidget(0, 4)
    assert actions is not None
    delete_button = actions.findChild(QPushButton, "agentRowDeleteButton")
    assert delete_button is not None

    delete_button.click()

    assert page.table.rowCount() == 5
    assert page.table.item(0, 0).text() == "L1"


def test_delete_button_emits_identifier_for_persisted_agent() -> None:
    _application()
    page = AgentAssetPage()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    agent_id = UUID("00000000-0000-0000-0000-000000000099")
    page.set_agents(
        (
            AgentApiSummary(
                agent_api_id=agent_id,
                workspace_id=UUID("00000000-0000-0000-0000-000000000098"),
                name="L3真实智能体",
                api_base_url="https://agents.example.com/v1/l3",
                model_id="trafficverse-l3",
                credential_env_var="TRAFFICVERSE_L3_API_KEY",
                description="真实后端配置",
                created_at=now,
                updated_at=now,
            ),
        )
    )
    deleted_ids: list[UUID] = []
    page.delete_requested.connect(deleted_ids.append)
    actions = page.table.cellWidget(0, 4)
    assert actions is not None
    delete_button = actions.findChild(QPushButton, "agentRowDeleteButton")
    assert delete_button is not None

    delete_button.click()

    assert deleted_ids == [agent_id]
