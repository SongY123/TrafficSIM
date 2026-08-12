from __future__ import annotations

import pytest
import ui.views.live_monitor_page as live_monitor_module
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)
from ui.models import ControlAvailability, ExperimentStatus, LiveMetrics
from ui.views.live_monitor_page import LiveMonitorPage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


class _MapWidgetStub(QWidget):
    vehicle_selected = Signal(str)

    def __init__(self, *, load_page: bool) -> None:
        super().__init__()
        self.load_page = load_page


@pytest.fixture(autouse=True)
def _stub_web_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid starting Chromium while testing only the native Qt page layout."""
    monkeypatch.setattr(live_monitor_module, "MapLibreDeckMapWidget", _MapWidgetStub)


def test_live_monitor_is_two_dimensional_and_exposes_requested_controls_and_metrics() -> None:
    _application()
    page = LiveMonitorPage(load_web_map=False)

    labels = {label.text() for label in page.findChildren(QLabel)}
    buttons = {button.text() for button in page.findChildren(QPushButton)}

    assert not hasattr(page, "carla_window")
    assert "二维仿真场景" in labels
    assert "ROI 局部三维" not in labels
    assert "CARLA" not in labels
    assert all("SUMO" not in label for label in labels)
    assert {"启动", "暂停", "继续", "停止", "重新开始"} <= buttons
    assert {"0.5×", "1×", "2×"} <= buttons
    assert {"当前车辆数", "车辆总数", "平均速度", "平均通过时间"} <= labels
    assert {"分级实时指标", "各智驾等级车辆平均速度", "各智驾等级碰撞车辆数"} <= labels
    assert page.map_panel.maximumHeight() > 400
    assert page.map_widget.minimumHeight() == 520
    assert page.details_sidebar.minimumWidth() == 320
    assert page.details_sidebar.maximumWidth() == 360
    workspace = page.map_panel.parentWidget()
    assert isinstance(workspace, QWidget)
    workspace_layout = workspace.layout()
    assert isinstance(workspace_layout, QHBoxLayout)
    assert workspace_layout.indexOf(page.map_panel) == 0
    assert workspace_layout.indexOf(page.details_sidebar) == 1
    assert workspace_layout.stretch(0) == 1
    assert workspace_layout.stretch(1) == 0
    assert page.findChild(QScrollArea, "liveMonitorScroll") is not None
    assert "车辆控制" not in labels
    assert {"应用车速", "左换道", "右换道", "单车停车"}.isdisjoint(buttons)
    assert not hasattr(page, "vehicle_id")

    page.close()


def test_live_monitor_formats_metrics_and_enables_controls_from_experiment_state() -> None:
    _application()
    page = LiveMonitorPage(load_web_map=False)

    page.set_metrics(
        LiveMetrics(
            current_vehicle_count=12,
            total_vehicle_count=37,
            average_speed_mps=8.5,
            average_travel_time_ms=125_000.0,
            level_average_speed_mps=(
                ("L0", 4.0),
                ("L1", 5.0),
                ("L2", 6.0),
                ("L3", 7.0),
                ("L4", 8.0),
                ("L5", 9.0),
            ),
            level_collision_counts=(
                ("L0", 3),
                ("L1", 2),
                ("L2", 1),
                ("L3", 0),
                ("L4", 0),
                ("L5", 0),
            ),
        )
    )
    page.set_controls(ControlAvailability.for_status(ExperimentStatus.RUNNING))

    values = {label.text() for label in page.findChildren(QLabel, "metricValue")}
    assert {"12 辆", "37 辆", "30.6 km/h", "125.0 s"} <= values
    assert not page.start_button.isEnabled()
    assert page.pause_button.isEnabled()
    assert not page.resume_button.isEnabled()
    assert page.stop_button.isEnabled()
    assert page.restart_button.isEnabled()
    assert all(button.isEnabled() for button in page.speed_group.buttons())
    assert page.level_speed_chart.values["L5"] == 32.4
    assert page.level_collision_chart.values["L0"] == 3.0

    page.close()
