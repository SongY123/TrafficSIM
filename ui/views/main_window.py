"""TrafficVerse desktop application shell."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.models import ControlAvailability, MapSummary
from ui.viewmodels import RunViewModel, WorkspaceViewModel
from ui.views.asset_center_page import AssetCenterPage
from ui.views.data_analysis_page import DataAnalysisPage
from ui.views.experiment_management_page import ExperimentManagementPage
from ui.views.live_monitor_page import LiveMonitorPage
from ui.views.navigation import NavigationRail
from ui.views.scene_configuration_page import SceneConfigurationPage
from ui.views.system_settings_page import SystemSettingsPage
from ui.views.theme import ThemeMode, configure_application_font, load_stylesheet
from ui.views.workspace_page import WorkspacePageWidget

_WINDOW_ICON_PATH = Path(__file__).resolve().parents[1] / "assets/icons/logo.svg"


class MainWindow(QMainWindow):
    """Compose the navigation shell and route view-model state into pages."""

    def __init__(
        self,
        viewmodel: RunViewModel,
        workspace_viewmodel: WorkspaceViewModel | None = None,
        *,
        load_web_map: bool = True,
    ) -> None:
        configure_application_font()
        super().__init__()
        self._viewmodel = viewmodel
        self._workspace_viewmodel = workspace_viewmodel
        self.setWindowIcon(QIcon(str(_WINDOW_ICON_PATH)))
        self.setWindowTitle("TrafficVerse · 交互式交通仿真系统")
        self.resize(1600, 960)
        self.setMinimumSize(1180, 720)

        self.navigation = NavigationRail()
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("pageStack")
        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        self.notice.hide()

        self.workspace_page = WorkspacePageWidget()
        self.live_page = LiveMonitorPage(load_web_map=load_web_map)
        self.scene_page = SceneConfigurationPage()
        self.experiments_page = ExperimentManagementPage()
        self.analysis_page = DataAnalysisPage()
        self.assets_page = AssetCenterPage(load_web_map=load_web_map)
        self.settings_page = SystemSettingsPage()
        self._pages = {
            "workspace": self.workspace_page,
            "live": self.live_page,
            "scene": self.scene_page,
            "experiments": self.experiments_page,
            "analysis": self.analysis_page,
            "assets": self.assets_page,
            "settings": self.settings_page,
        }
        for page in self._pages.values():
            self.page_stack.addWidget(page)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.notice)
        content_layout.addWidget(self.page_stack, 1)

        shell = QWidget()
        shell.setObjectName("appShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self.navigation)
        shell_layout.addWidget(content, 1)
        self.setCentralWidget(shell)

        self._connect_pages()
        self._connect_viewmodel()
        self._apply_theme(ThemeMode.DARK.value)

    def _connect_pages(self) -> None:
        vm = self._viewmodel
        self.navigation.page_selected.connect(self._show_page)
        self.live_page.create_requested.connect(vm.create_experiment)
        self.live_page.start_requested.connect(vm.start)
        self.live_page.pause_requested.connect(vm.pause)
        self.live_page.resume_requested.connect(vm.resume)
        self.live_page.stop_requested.connect(vm.stop)
        self.live_page.speed_changed.connect(vm.set_speed)
        self.live_page.vehicle_speed_requested.connect(self._control_speed)
        self.live_page.lane_change_requested.connect(self._control_lane)
        self.live_page.vehicle_stop_requested.connect(self._control_stop)
        self.scene_page.map_selected.connect(vm.select_map)
        self.scene_page.import_requested.connect(self._choose_map)
        self.scene_page.create_requested.connect(vm.create_experiment)
        self.assets_page.import_requested.connect(self._choose_map)
        self.assets_page.preview_requested.connect(vm.preview_map_asset)
        self.settings_page.theme_changed.connect(self._apply_theme)
        if self._workspace_viewmodel is not None:
            self.workspace_page.search_changed.connect(
                self._workspace_viewmodel.set_search_query
            )
            self.workspace_page.workspace_selected.connect(
                self._workspace_viewmodel.select
            )

    def _connect_viewmodel(self) -> None:
        vm = self._viewmodel
        vm.map_catalog_changed.connect(self._set_maps)
        vm.map_manifest_changed.connect(self.assets_page.set_manifest)
        vm.asset_network_changed.connect(self.assets_page.set_preview_network)
        vm.network_changed.connect(self.live_page.map_widget.set_network)
        vm.vehicles_changed.connect(self._set_vehicles)
        vm.traffic_lights_changed.connect(self.live_page.map_widget.set_traffic_lights)
        vm.component_health_changed.connect(self._set_health)
        vm.experiment_status_changed.connect(self._set_status)
        vm.simulation_time_changed.connect(self._set_time)
        vm.control_availability_changed.connect(self._set_controls)
        vm.connection_changed.connect(self.live_page.set_connection)
        vm.notification.connect(self._show_notice)
        workspace_vm = self._workspace_viewmodel
        if workspace_vm is not None:
            workspace_vm.workspaces_changed.connect(self.workspace_page.set_workspaces)
            workspace_vm.selection_changed.connect(self.workspace_page.set_selection)
            workspace_vm.loading_changed.connect(self.workspace_page.set_loading)
            workspace_vm.notification.connect(self._show_notice)

    @Slot(str)
    def _show_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self.page_stack.setCurrentWidget(page)
        self.navigation.set_active(key)

    @Slot(object)
    def _set_maps(self, maps: object) -> None:
        values = (
            tuple(item for item in maps if isinstance(item, MapSummary))
            if isinstance(maps, tuple)
            else ()
        )
        self.scene_page.set_maps(values)
        self.assets_page.set_maps(values)

    @Slot(object)
    def _set_vehicles(self, vehicles: object) -> None:
        self.live_page.map_widget.set_vehicles(vehicles)
        count = len(vehicles) if isinstance(vehicles, tuple) else 0
        self.live_page.set_vehicle_count(count)

    @Slot(object)
    def _set_health(self, components: object) -> None:
        values = components if isinstance(components, tuple) else ()
        sumo = next((item for item in values if getattr(item, "component", "") == "sumo"), None)
        status = str(getattr(sumo, "status", "UNKNOWN")).removeprefix("ComponentStatus.")
        labels = {
            "HEALTHY": "正常",
            "DEGRADED": "降级",
            "UNAVAILABLE": "不可用",
            "DISABLED": "已禁用",
            "UNKNOWN": "未知",
        }
        message = getattr(sumo, "message", None) if sumo is not None else None
        self.live_page.set_sumo_status(labels.get(status, status), message)

    @Slot(str)
    def _set_status(self, status: str) -> None:
        labels = {
            "CREATED": "已创建",
            "PREPARING": "准备中",
            "READY": "已就绪",
            "RUNNING": "运行中",
            "PAUSED": "已暂停",
            "STOPPING": "停止中",
            "COMPLETED": "已完成",
            "FAILED": "失败",
        }
        display_status = labels.get(status, status)
        self.live_page.set_status(display_status)
        self.experiments_page.set_status(display_status)

    @Slot(int)
    def _set_time(self, simulation_time_ms: int) -> None:
        self.live_page.set_time(simulation_time_ms)
        self.experiments_page.set_time(simulation_time_ms)

    @Slot(object)
    def _set_controls(self, availability: object) -> None:
        if not isinstance(availability, ControlAvailability):
            return
        self.live_page.set_controls(availability)
        self.scene_page.set_create_enabled(availability.can_create)

    @Slot(str, str)
    def _show_notice(self, level: str, message: str) -> None:
        self.notice.setProperty("level", level)
        self.notice.setText(message)
        self.notice.show()
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)

    def _choose_map(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 OpenDRIVE 地图",
            str(Path.home()),
            "OpenDRIVE (*.xodr)",
        )
        if path:
            self._viewmodel.import_map(Path(path))

    @Slot(str, float)
    def _control_speed(self, vehicle_id: str, desired_speed_mps: float) -> None:
        self._viewmodel.control_vehicle(vehicle_id, desired_speed_mps=desired_speed_mps)

    @Slot(str, str)
    def _control_lane(self, vehicle_id: str, direction: str) -> None:
        self._viewmodel.control_vehicle(vehicle_id, lane_change=direction)

    @Slot(str)
    def _control_stop(self, vehicle_id: str) -> None:
        self._viewmodel.control_vehicle(vehicle_id, stop_requested=True)

    @Slot(str)
    def _apply_theme(self, theme_name: str) -> None:
        try:
            theme = ThemeMode(theme_name)
        except ValueError:
            return
        self.setProperty("theme", theme.value)
        self.setStyleSheet(load_stylesheet(theme))
        self.navigation.refresh_icons(theme)
        self.live_page.map_widget.set_theme(theme.value)
        self.assets_page.map_widget.set_theme(theme.value)
