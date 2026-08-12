"""Exercise the mixed-automation scenario details through the real Qt UI and API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication, QScrollArea
from ui.api_client import RealtimeClient, RestApiClient
from ui.models import TRAFFIC_SCENARIO_PRESETS, ExperimentStatus, WorkspaceSummary
from ui.viewmodels import RunViewModel
from ui.views import MainWindow

DEFAULT_SCENARIO_ID = UUID("00000000-0000-0000-0000-000000000042")
CAPTURE_TIME_MS = (32_000, 15_000, 28_000)


class MixedAutomationUiVerifier(QObject):
    """Drive every scenario detail and capture the corresponding live scene."""

    def __init__(
        self,
        app: QApplication,
        viewmodel: RunViewModel,
        window: MainWindow,
        output_dir: Path,
    ) -> None:
        super().__init__()
        self._app = app
        self._viewmodel = viewmodel
        self._window = window
        self._output_dir = output_dir
        self._row = 0
        self._captured = False
        self._started = False
        self._scenario_running = False
        self._switch_in_progress = False

        viewmodel.workspace_catalog_changed.connect(self._enter_first_workspace)
        viewmodel.map_catalog_changed.connect(self._catalog_ready)
        viewmodel.experiment_status_changed.connect(self._status_changed)
        viewmodel.simulation_time_changed.connect(self._simulation_time_changed)
        viewmodel.notification.connect(self._notification)

    @Slot(object)
    def _enter_first_workspace(self, payload: object) -> None:
        if self._viewmodel.active_workspace is not None or not isinstance(payload, tuple):
            return
        workspace = next((item for item in payload if isinstance(item, WorkspaceSummary)), None)
        if workspace is None:
            self._fail("没有可用于验收的工作区")
            return
        self._viewmodel.select_workspace(str(workspace.workspace_id))
        self._viewmodel.enter_selected_workspace()

    @Slot(object)
    def _catalog_ready(self, _payload: object) -> None:
        if self._started:
            return
        missing = [
            preset.map_id
            for preset in TRAFFIC_SCENARIO_PRESETS
            if not self._window.traffic_scenes_page.is_available(preset.scenario_id)
        ]
        if missing:
            self._fail(f"场景资源不可运行: {', '.join(missing)}")
            return
        self._started = True
        self._window._show_traffic_scene(TRAFFIC_SCENARIO_PRESETS[0].scenario_id)
        self._capture("00-traffic-scene-detail.png")
        QTimer.singleShot(300, self._launch_current_scenario)

    def _launch_current_scenario(self) -> None:
        preset = TRAFFIC_SCENARIO_PRESETS[self._row]
        page = self._window.traffic_scenes_page
        self._window._show_traffic_scene(preset.scenario_id)
        if page.selected_scenario != preset:
            self._fail(f"场景详情未切换: {preset.scenario_id}")
            return
        page.launch_button.click()
        QTimer.singleShot(100, lambda: self._verify_applied_preset(preset.map_id))

    def _verify_applied_preset(self, map_id: str) -> None:
        selected_map_id = self._window.scene_page.map_combo.currentData()
        levels = tuple(row.level for row in self._window.scene_page.automation_rows)
        if selected_map_id != map_id:
            self._fail(f"预设地图未应用: expected={map_id}, actual={selected_map_id}")
        elif levels != ("L0", "L1", "L2", "L3", "L4", "L5"):
            self._fail(f"智驾等级配置未完整应用: {levels}")

    @Slot(str)
    def _status_changed(self, status: str) -> None:
        if status == ExperimentStatus.RUNNING.value:
            self._scenario_running = True
        elif status == ExperimentStatus.FAILED.value:
            self._fail(f"{TRAFFIC_SCENARIO_PRESETS[self._row].name} 运行失败")
        elif status == ExperimentStatus.COMPLETED.value:
            if self._switch_in_progress:
                self._switch_in_progress = False
                return
            if not self._scenario_running:
                return
            self._scenario_running = False
            if not self._captured:
                self._fail(f"{TRAFFIC_SCENARIO_PRESETS[self._row].name} 未取得关键时刻截图")
                return
            self._row += 1
            if self._row == len(TRAFFIC_SCENARIO_PRESETS):
                self._finish()

    @Slot(int)
    def _simulation_time_changed(self, simulation_time_ms: int) -> None:
        if self._row >= len(CAPTURE_TIME_MS) or self._captured or not self._scenario_running:
            return
        if simulation_time_ms < CAPTURE_TIME_MS[self._row]:
            return
        if not self._validate_live_result():
            return
        self._captured = True
        preset = TRAFFIC_SCENARIO_PRESETS[self._row]
        self._capture(f"{self._row + 1:02d}-{preset.scenario_id}.png")
        if not self._capture_metrics_view(f"{self._row + 1:02d}-{preset.scenario_id}-metrics.png"):
            return
        if self._row + 1 == len(TRAFFIC_SCENARIO_PRESETS):
            QTimer.singleShot(250, self._viewmodel.stop)
            return
        self._scenario_running = False
        self._switch_in_progress = True
        self._row += 1
        self._captured = False
        self._window._show_traffic_scene(TRAFFIC_SCENARIO_PRESETS[self._row].scenario_id)
        QTimer.singleShot(250, self._launch_current_scenario)

    def _capture_metrics_view(self, filename: str) -> bool:
        scroll = self._window.live_page.findChild(QScrollArea, "liveMonitorScroll")
        if scroll is None:
            self._fail("找不到仿真运行页滚动区域")
            return False
        vertical_bar = scroll.verticalScrollBar()
        if vertical_bar.maximum() > 0:
            vertical_bar.setValue(vertical_bar.maximum())
        self._app.processEvents()
        self._capture(filename)
        vertical_bar.setValue(0)
        self._app.processEvents()
        return True

    def _validate_live_result(self) -> bool:
        levels = ("L0", "L1", "L2", "L3", "L4", "L5")
        speed_values = self._window.live_page.level_speed_chart.values
        collision_values = self._window.live_page.level_collision_chart.values
        speeds = [speed_values[level] for level in levels]
        collisions = [round(collision_values[level]) for level in levels]
        preset = TRAFFIC_SCENARIO_PRESETS[self._row]
        if any(
            current >= following for current, following in zip(speeds, speeds[1:], strict=False)
        ):
            self._fail(f"{preset.name} 速度未按 L0-L5 递增: {speeds}")
            return False
        if any(
            current < following
            for current, following in zip(collisions, collisions[1:], strict=False)
        ):
            self._fail(f"{preset.name} 碰撞数量随等级升高反而增加: {collisions}")
            return False
        if any(collisions[index] for index in (4, 5)):
            self._fail(f"{preset.name} L4-L5 仍发生碰撞: {collisions}")
            return False
        if preset.scenario_id != "mixed-automation-emergency-yield" and any(
            collisions[index] == 0 for index in (0, 1, 2, 3)
        ):
            self._fail(f"{preset.name} L0-L3 缺少脚本化碰撞: {collisions}")
            return False
        if self._window.live_page.map_panel.height() != 400:
            self._fail(
                f"二维仿真卡片高度不是 400 px: {self._window.live_page.map_panel.height()} px"
            )
            return False
        print(
            f"[metrics] {preset.scenario_id}: speeds={speeds}, collisions={collisions}, "
            f"map_panel_height={self._window.live_page.map_panel.height()}",
            flush=True,
        )
        return True

    @Slot(str, str)
    def _notification(self, level: str, message: str) -> None:
        print(f"[{level}] {message}", flush=True)

    def _capture(self, filename: str) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._app.processEvents()
        output = self._output_dir / filename
        if not self._window.grab().save(str(output)):
            self._fail(f"无法保存截图: {output}")
            return
        print(f"[capture] {output}", flush=True)

    def _finish(self) -> None:
        print("[success] 三个混合智驾场景均已通过 UI 启动并完成关键时刻截图", flush=True)
        self._app.exit(0)

    def _fail(self, message: str) -> None:
        print(f"[failure] {message}", file=sys.stderr, flush=True)
        self._app.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/ui-verification"),
    )
    args = parser.parse_args()

    existing_app = QApplication.instance()
    app = existing_app if isinstance(existing_app, QApplication) else QApplication(sys.argv)
    app.setApplicationName("TrafficVerse UI Verification")
    rest = RestApiClient(args.api_url)
    realtime = RealtimeClient(args.api_url)
    viewmodel = RunViewModel(rest, realtime, DEFAULT_SCENARIO_ID)
    window = MainWindow(viewmodel)
    window.resize(1600, 900)
    window.show()
    verifier = MixedAutomationUiVerifier(app, viewmodel, window, args.output_dir)
    QTimer.singleShot(0, viewmodel.initialize)
    QTimer.singleShot(120_000, lambda: verifier._fail("UI 验收超时"))
    result = app.exec()
    realtime.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
