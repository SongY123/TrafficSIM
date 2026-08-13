from __future__ import annotations

from uuid import UUID

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QPoint, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
)
from ui.viewmodels import RunViewModel
from ui.views import MainWindow
from ui.widgets import MapLibreDeckMapWidget


class _Rest(QObject):
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, str)

    def get_workspace_overview(self, workspace_id: UUID) -> None:
        del workspace_id

    def list_maps(self) -> None:
        return

    def list_agent_assets(self, workspace_id: UUID) -> None:
        del workspace_id

    def list_simulations(self, workspace_id: UUID | None = None) -> None:
        self.request_succeeded.emit(
            "simulations.list",
            [
                {
                    "run_id": "2026-08-11-09-08-07",
                    "workspace_id": str(workspace_id) if workspace_id is not None else None,
                    "status": "COMPLETED",
                    "created_at": "2026-08-11T09:08:07+08:00",
                    "started_at": "2026-08-11T09:08:08+08:00",
                    "ended_at": "2026-08-11T09:09:08+08:00",
                    "scene_name": "History smoke run",
                    "map_id": "image2road",
                    "map_name": "Image2Road",
                    "configured_duration_ms": 60_000,
                    "simulation_time_ms": 60_000,
                    "replay_available": True,
                    "export_available": True,
                }
            ],
        )

    def get_simulation(self, run_id: str) -> None:
        metrics = [
            {
                "key": key,
                "label": key,
                "value": float(index),
                "unit": unit,
                "source": source,
            }
            for index, (key, unit, source) in enumerate(
                (
                    ("vehicle_total", "veh", "summary.loaded"),
                    ("completed_total", "veh", "summary.arrived"),
                    ("average_speed_mps", "m/s", "summary.meanSpeed"),
                    ("average_travel_time_s", "s", "tripinfo.duration"),
                    ("average_waiting_time_s", "s", "tripinfo.waitingTime"),
                    ("average_queue_length_veh", "veh", "summary.halting"),
                    ("maximum_queue_length_veh", "veh", "summary.halting"),
                ),
                start=1,
            )
        ]
        trends = [
            {
                "key": key,
                "label": key,
                "unit": unit,
                "samples": [
                    {"simulation_time_ms": 0, "value": 0},
                    {"simulation_time_ms": 60_000, "value": 1},
                ],
            }
            for key, unit in (
                ("vehicle_count", "veh"),
                ("average_speed_mps", "m/s"),
                ("queue_length_veh", "veh"),
                ("average_waiting_time_s", "s"),
                ("completed_total", "veh"),
            )
        ]
        self.request_succeeded.emit(
            f"simulation.get:{run_id}",
            {
                "run_id": run_id,
                "workspace_id": "10000000-0000-0000-0000-000000000001",
                "status": "COMPLETED",
                "created_at": "2026-08-11T09:08:07+08:00",
                "started_at": "2026-08-11T09:08:08+08:00",
                "ended_at": "2026-08-11T09:09:08+08:00",
                "scene_name": "History smoke run",
                "map_id": "image2road",
                "map_name": "Image2Road",
                "configured_duration_ms": 60_000,
                "simulation_time_ms": 60_000,
                "replay_available": True,
                "export_available": True,
                "metrics": metrics,
                "trends": trends,
                "road_results": [
                    {
                        "edge_id": "edge-a",
                        "average_speed_mps": 10,
                        "congestion_ratio": 0.5,
                        "traffic_flow_veh_per_hour": 720,
                        "queue_length_m": 12,
                    }
                ],
            },
        )

    def get_simulation_network(self, run_id: str) -> None:
        self.request_succeeded.emit(
            f"simulation.network:{run_id}",
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"sumo_edge_id": "edge-a"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0, 0, 0], [100, 0, 0]],
                        },
                    }
                ],
            },
        )

    def get_simulation_replay(self, run_id: str, from_time_ms: int = 0) -> None:
        self.request_succeeded.emit(
            f"simulation.replay:{run_id}:{from_time_ms}",
            {
                "run_id": run_id,
                "frames": [
                    {
                        "simulation_time_ms": 0,
                        "sequence": 1,
                        "vehicles": [],
                        "traffic_lights": [],
                        "collision_vehicle_ids": [],
                    }
                ],
                "next_time_ms": None,
            },
        )


class _Realtime(QObject):
    connection_changed = Signal(str)
    envelope_received = Signal(object)
    protocol_error = Signal(str)

    def close(self) -> None:
        return


@pytest.mark.e2e
def test_success_notice_auto_hides() -> None:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QCoreApplication)
    viewmodel = RunViewModel(
        _Rest(),  # type: ignore[arg-type]
        _Realtime(),  # type: ignore[arg-type]
        UUID("00000000-0000-0000-0000-000000000042"),
    )
    window = MainWindow(viewmodel, load_web_map=False)

    window._show_notice("success", "配置已保存。")

    assert window._notice_timer.isActive()
    assert not window.notice.isHidden()
    window._notice_timer.timeout.emit()
    assert window.notice.isHidden()
    window.close()


@pytest.mark.e2e
def test_navigation_rail_scales_with_window_and_fills_its_stack() -> None:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QCoreApplication)
    viewmodel = RunViewModel(
        _Rest(),  # type: ignore[arg-type]
        _Realtime(),  # type: ignore[arg-type]
        UUID("00000000-0000-0000-0000-000000000042"),
    )
    window = MainWindow(viewmodel, load_web_map=False)
    window.navigation_stack.setCurrentWidget(window.navigation)
    window.resize(1600, 960)
    window.show()
    app.processEvents()

    initial_stack_width = window.navigation_stack.width()
    assert window.navigation.width() == initial_stack_width

    window.resize(2400, 960)
    app.processEvents()

    enlarged_stack_width = window.navigation_stack.width()
    assert window.navigation.width() == enlarged_stack_width
    assert enlarged_stack_width > initial_stack_width
    assert enlarged_stack_width / window.width() == pytest.approx(
        initial_stack_width / 1600,
        abs=0.01,
    )
    window.close()


@pytest.mark.e2e
def test_workspace_region_preview_receives_the_selected_map_network() -> None:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QCoreApplication)
    viewmodel = RunViewModel(
        _Rest(),  # type: ignore[arg-type]
        _Realtime(),  # type: ignore[arg-type]
        UUID("00000000-0000-0000-0000-000000000042"),
    )
    window = MainWindow(viewmodel, load_web_map=False)
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

    viewmodel.handle_rest_success("map.network:image2road", network)

    assert window.workspace_page.preview_map._pending["setNetwork"] == network
    assert window.workspace_page.preview_status.text() == "已加载标准路网预览"
    window._apply_theme("dark")
    map_widgets = (
        window.live_page.map_widget,
        window.scene_page.map_widget,
        window.workspace_page.preview_map,
        window.maps_page.map_widget,
        window.traffic_scenes_page.map_widget,
    )
    assert all(widget._pending["setTheme"] == "dark" for widget in map_widgets)
    window.close()


@pytest.mark.e2e
def test_core_run_window_constructs_and_closes_without_backend_or_carla() -> None:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QCoreApplication)
    viewmodel = RunViewModel(
        _Rest(),  # type: ignore[arg-type]
        _Realtime(),  # type: ignore[arg-type]
        UUID("00000000-0000-0000-0000-000000000042"),
    )

    window = MainWindow(viewmodel, load_web_map=False)

    assert window.windowTitle().startswith("TrafficVerse")
    assert window.minimumWidth() >= 1180

    page_stack = window.findChild(QStackedWidget, "pageStack")
    assert page_stack is not None
    assert page_stack.count() == 10
    assert page_stack.currentWidget().objectName() == "workspaceOverviewPage"
    assert window.findChild(MapLibreDeckMapWidget) is not None
    assert not hasattr(window.live_page, "carla_window")
    viewmodel.handle_rest_success(
        "workspaces.list",
        [
            {
                "workspace_id": "10000000-0000-0000-0000-000000000001",
                "name": "北京亦庄",
                "description": "核心路网",
                "created_at": "2026-07-31T00:00:00Z",
                "updated_at": "2026-07-31T00:00:00Z",
            }
        ],
    )
    enter = window.findChild(QPushButton, "workspaceEnterButton")
    assert enter is not None
    enter.click()
    assert page_stack.currentWidget().objectName() == "projectDetailPage"
    create_simulation = window.findChild(QPushButton, "projectCreateSimulationButton")
    assert create_simulation is not None
    create_simulation.click()
    assert page_stack.currentWidget().objectName() == "sceneConfigurationPage"
    project_name = window.findChild(QPushButton, "activeWorkspaceName")
    assert project_name is not None
    project_name.click()
    assert page_stack.currentWidget().objectName() == "projectDetailPage"
    window.project_detail_page.simulation_action_requested.emit(
        "早高峰联仿",
        "copy",
        "L3 · 45%",
    )
    assert window.scene_page.scene_name.text() == "早高峰联仿 副本"
    assert "L3 · 45%" in window.scene_page.description.toPlainText()

    window.page_stack.setCurrentWidget(window.live_page)
    window.show()
    app.processEvents()
    page_title = window.live_page.findChild(QLabel, "pageTitle")
    assert page_title is not None
    live_labels = window.live_page.findChildren(QLabel)
    map_title = next(label for label in live_labels if label.text() == "二维仿真场景")
    aligned_left_edges = {label.mapTo(window, QPoint()).x() for label in (page_title, map_title)}
    assert len(aligned_left_edges) == 1

    brand_logo = window.findChild(QLabel, "brandLogo")
    assert brand_logo is not None
    assert brand_logo.pixmap() is not None
    assert not brand_logo.pixmap().isNull()
    assert not window.windowIcon().isNull()

    live_text = " ".join(label.text() for label in live_labels)
    assert "ROI 局部三维" not in live_text
    assert "CARLA" not in live_text
    assert all(
        metric in live_text for metric in ("当前车辆数", "车辆总数", "平均速度", "平均通过时间")
    )
    assert "车辆控制" not in live_text
    assert "MapLibre" not in live_text
    assert "deck.gl" not in live_text
    visible_text = " ".join(label.text() for label in window.findChildren(QLabel))
    for english_copy in (
        "CONTROL CENTER",
        "SIMULATION OS",
        "CORE RUN CONSOLE",
        "LIVE STATISTICS",
        "VEHICLE COMMAND",
        "Replay library",
        "Timeline",
        "Insights",
    ):
        assert english_copy not in visible_text
    assert window.property("theme") == "light"

    theme_combo = window.settings_page.findChild(QComboBox, "themeModeCombo")
    assert theme_combo is not None
    assert theme_combo.currentData() == "light"
    theme_combo.setCurrentIndex(theme_combo.findData("dark"))
    assert window.property("theme") == "dark"

    expected_pages = {
        "scene": "sceneConfigurationPage",
        "traffic_scenes": "trafficScenePage",
        "maps": "mapAssetPage",
        "agents": "agentAssetPage",
        "settings": "systemSettingsPage",
    }
    for navigation_key, page_name in expected_pages.items():
        button = window.findChild(QPushButton, f"nav_{navigation_key}")
        assert button is not None
        assert not button.icon().isNull()
        assert button.iconSize().width() == 18
        assert button.iconSize().height() == 18
        button.click()
        assert page_stack.currentWidget().objectName() == page_name

    history_button = window.findChild(QPushButton, "nav_experiments")
    history_children = window.findChild(QPushButton, "nav_history_0")
    assert history_button is not None
    assert history_children is not None
    previous_page = page_stack.currentWidget()
    history_button.click()
    assert page_stack.currentWidget() is previous_page
    history_children.click()
    assert page_stack.currentWidget().objectName() == "dataReplayPage"
    assert window.replay_page.record_id == history_children.property("recordId")

    playback = window.findChild(QPushButton, "replayPlaybackButton")
    back = window.findChild(QPushButton, "replayBackButton")
    assert playback is not None
    assert back is not None
    playback.click()
    assert page_stack.currentWidget().objectName() == "liveMonitorPage"
    assert window.live_page.stop_button.text() == "退出回放"
    window.live_page.stop_button.click()
    assert page_stack.currentWidget().objectName() == "dataReplayPage"
    back.click()
    assert page_stack.currentWidget().objectName() == "projectDetailPage"

    assets_button = window.findChild(QPushButton, "nav_maps")
    assert assets_button is not None
    assets_button.click()
    assert window.findChild(QLineEdit, "assetSearchInput") is not None
    assert window.findChild(QTreeWidget, "assetDirectoryTree") is not None
    assert window.findChild(QPushButton, "assetImportButton") is not None
    assert window.findChild(QPushButton, "assetPreview2d") is None
    assert window.findChild(QPushButton, "assetPreview3d") is None
    asset_button_texts = {button.text() for button in window.maps_page.findChildren(QPushButton)}
    assert "2D 预览" not in asset_button_texts
    assert "3D 预览" not in asset_button_texts
    assert len(window.maps_page.findChildren(MapLibreDeckMapWidget)) == 1
    window.close()
