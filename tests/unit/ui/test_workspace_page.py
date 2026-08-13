from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from ui.models import MapSummary, WorkspaceOverview, WorkspaceSummary
from ui.views.navigation import WorkspaceNavigationRail
from ui.views.theme import ThemeMode, load_stylesheet
from ui.views.workspace_page import WorkspaceDeleteDialog, WorkspaceOverviewPage
from ui.widgets import MapLibreDeckMapWidget


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _workspace() -> WorkspaceSummary:
    return WorkspaceSummary.model_validate(
        {
            "workspace_id": "10000000-0000-0000-0000-000000000001",
            "name": "北京亦庄",
            "description": "核心路网",
            "created_at": "2026-07-31T00:00:00Z",
            "updated_at": "2026-07-31T00:00:00Z",
        }
    )


def test_workspace_navigation_searches_selects_and_requests_creation() -> None:
    _application()
    navigation = WorkspaceNavigationRail()
    navigation.setStyleSheet(load_stylesheet(ThemeMode.DARK))
    workspace = _workspace()
    selections: list[str] = []
    searches: list[str] = []
    creates: list[bool] = []
    deletes: list[WorkspaceSummary] = []
    entries: list[bool] = []
    navigation.workspace_selected.connect(selections.append)
    navigation.workspace_enter_requested.connect(lambda: entries.append(True))
    navigation.search_changed.connect(searches.append)
    navigation.create_requested.connect(lambda: creates.append(True))
    navigation.delete_requested.connect(deletes.append)

    navigation.set_workspaces((workspace,))
    navigation.show()
    QApplication.processEvents()
    item = navigation.workspace_list.item(0)
    row = navigation.workspace_list.itemWidget(item)
    assert row is not None
    delete_button = row.findChild(QPushButton, "workspaceListDeleteButton")
    name_label = row.findChild(QLabel, "workspaceListName")
    assert delete_button is not None
    assert name_label is not None
    assert delete_button.isHidden() is True
    QApplication.sendEvent(name_label, QEvent(QEvent.Type.Enter))
    QApplication.processEvents()
    assert delete_button.isHidden() is False
    assert name_label.alignment() & Qt.AlignmentFlag.AlignVCenter
    row_layout = row.layout()
    assert isinstance(row_layout, QHBoxLayout)
    delete_layout_item = row_layout.itemAt(row_layout.indexOf(delete_button))
    assert delete_layout_item is not None
    assert delete_layout_item.alignment() & Qt.AlignmentFlag.AlignVCenter
    item_rect = navigation.workspace_list.visualItemRect(item)
    delete_top = delete_button.mapTo(navigation.workspace_list.viewport(), QPoint()).y()
    delete_bottom = delete_top + delete_button.height()
    name_center_y = (
        name_label.mapTo(navigation.workspace_list.viewport(), QPoint()).y()
        + name_label.height() // 2
    )
    delete_center_y = delete_top + delete_button.height() // 2
    settings_button = navigation.findChild(QPushButton, "workspaceSettingsButton")
    assert settings_button is not None
    assert item_rect.top() <= delete_top < delete_bottom <= item_rect.bottom() + 1
    assert abs(name_center_y - delete_center_y) <= 1
    assert name_label.font().pixelSize() == settings_button.font().pixelSize()
    QApplication.sendEvent(delete_button, QEvent(QEvent.Type.Enter))
    assert delete_button.isHidden() is False
    delete_button.click()
    QApplication.sendEvent(name_label, QEvent(QEvent.Type.Leave))
    QApplication.sendEvent(delete_button, QEvent(QEvent.Type.Leave))
    QApplication.processEvents()
    assert delete_button.isHidden() is True
    navigation.search_input.setText("北京")
    create_button = navigation.findChild(QPushButton, "workspaceCreateButton")
    assert create_button is not None
    create_button.click()
    navigation.workspace_list.setCurrentRow(-1)
    navigation.workspace_list.setCurrentRow(0)
    navigation.workspace_list.itemDoubleClicked.emit(item)

    assert selections[-1] == str(workspace.workspace_id)
    assert entries == [True]
    assert searches[-1] == "北京"
    assert creates == [True]
    assert deletes == [workspace]
    navigation.close()


def test_workspace_overview_renders_mock_contract_and_enters() -> None:
    _application()
    page = WorkspaceOverviewPage()
    workspace = _workspace()
    entered: list[bool] = []
    page.enter_requested.connect(lambda: entered.append(True))
    page.set_workspace(workspace)
    page.set_overview(
        WorkspaceOverview.model_validate(
            {
                "workspace_id": str(workspace.workspace_id),
                "map_count": 12,
                "agent_count": 250000,
                "scenario_count": 158,
                "simulation_count": 1284,
                "automation_counts": [{"level": "L4", "count": 2800}],
                "succeeded_simulations": 1250,
                "failed_simulations": 34,
                "runtime_hours": 4582.0,
                "activity": [{"day": "2026-07-19", "simulations": 49}],
                "recent_simulations": [
                    {
                        "name": "Peak_Hour",
                        "status": "SUCCEEDED",
                        "occurred_at": "2026-07-19T08:30:00Z",
                        "duration_ms": 7200000,
                        "automation_summary": "L3 · 45%",
                    }
                ],
                "preview_region": "亦庄核心区",
            }
        )
    )

    enter_button = page.findChild(QPushButton, "workspaceEnterButton")
    rename_button = page.findChild(QPushButton, "workspaceRenameButton")
    delete_button = page.findChild(QPushButton, "dangerButton")
    assert enter_button is not None
    assert rename_button is not None
    assert delete_button is not None
    assert {button.size() for button in (rename_button, delete_button, enter_button)} == {
        enter_button.size()
    }
    enter_button.click()
    labels = {label.text() for label in page.findChildren(QLabel)}

    assert "1,284" in labels
    assert "250,000" in labels
    assert entered == [True]
    page.close()


def test_workspace_region_preview_renders_the_selected_standard_network() -> None:
    _application()
    page = WorkspaceOverviewPage(load_web_map=False)
    network = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"trafficverse_role": "sumo_lane"},
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
            }
        ],
    }

    page.set_preview_network(network)

    preview = page.findChild(MapLibreDeckMapWidget, "workspacePreviewMap")
    assert preview is not None
    assert preview._pending["setLegendVisible"] is False
    assert preview._pending["setNetwork"] == network
    assert page.preview_status.text() == "已加载标准路网预览"
    page.close()


def test_workspace_region_preview_reports_when_no_valid_sumo_map_exists() -> None:
    _application()
    page = WorkspaceOverviewPage(load_web_map=False)

    page.set_maps(
        (
            MapSummary(
                map_id="town04",
                kind="core_run",
                display_name="Town04",
                validated=True,
                network_schema_version="traffic-network/1.0",
            ),
        )
    )

    assert page.preview_status.text() == "暂无可预览的SUMO路网"
    page.close()


def test_workspace_delete_requires_exact_name_confirmation() -> None:
    _application()
    dialog = WorkspaceDeleteDialog(_workspace())
    delete = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert delete.isEnabled() is True
    dialog.confirm_input.setText("北京")
    delete.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error_label.isHidden() is False
    assert "名称不匹配" in dialog.error_label.text()
    dialog.confirm_input.setText("北京亦庄")
    assert dialog.error_label.isHidden() is True
    delete.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()
