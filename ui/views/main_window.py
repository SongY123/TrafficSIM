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

from ui.models import (
    ControlAvailability,
    MapSummary,
    ReplayResult,
    WorkspaceOverview,
    WorkspaceSummary,
)
from ui.viewmodels import RunViewModel
from ui.views.agent_asset_page import AgentAssetPage
from ui.views.data_replay_page import DataReplayPage
from ui.views.live_monitor_page import LiveMonitorPage
from ui.views.map_asset_page import MapAssetPage
from ui.views.navigation import NavigationRail, WorkspaceNavigationRail
from ui.views.scene_configuration_page import SceneConfigurationPage
from ui.views.system_settings_page import SystemSettingsPage
from ui.views.theme import ThemeMode, configure_application_font, load_stylesheet
from ui.views.traffic_scene_page import TrafficScenePage
from ui.views.workspace_page import (
    WorkspaceDeleteDialog,
    WorkspaceEditDialog,
    WorkspaceOverviewPage,
    run_workspace_dialog,
)

_WINDOW_ICON_PATH = Path(__file__).resolve().parents[1] / "assets/icons/logo.svg"


class MainWindow(QMainWindow):
    """Compose the navigation shell and route view-model state into pages."""

    def __init__(self, viewmodel: RunViewModel, *, load_web_map: bool = True) -> None:
        configure_application_font()
        super().__init__()
        self._viewmodel = viewmodel
        self.setWindowIcon(QIcon(str(_WINDOW_ICON_PATH)))
        self.setWindowTitle("TrafficVerse · 交互式交通仿真系统")
        self.resize(1600, 960)
        self.setMinimumSize(1180, 720)

        self.navigation = NavigationRail()
        self.workspace_navigation = WorkspaceNavigationRail()
        self.navigation_stack = QStackedWidget()
        self.navigation_stack.setObjectName("navigationStack")
        self.navigation_stack.addWidget(self.workspace_navigation)
        self.navigation_stack.addWidget(self.navigation)
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("pageStack")
        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        self.notice.hide()

        self.live_page = LiveMonitorPage(load_web_map=load_web_map)
        self.scene_page = SceneConfigurationPage()
        self.replay_page = DataReplayPage(load_web_map=load_web_map)
        self.traffic_scenes_page = TrafficScenePage()
        self.maps_page = MapAssetPage(load_web_map=load_web_map)
        self.agents_page = AgentAssetPage()
        self.settings_page = SystemSettingsPage()
        self.workspace_page = WorkspaceOverviewPage()
        self._pages = {
            "workspace": self.workspace_page,
            "live": self.live_page,
            "scene": self.scene_page,
            "experiments": self.replay_page,
            "replay": self.replay_page,
            "traffic_scenes": self.traffic_scenes_page,
            "maps": self.maps_page,
            "agents": self.agents_page,
            "settings": self.settings_page,
        }
        for page in dict.fromkeys(self._pages.values()):
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
        shell_layout.addWidget(self.navigation_stack)
        shell_layout.addWidget(content, 1)
        self.setCentralWidget(shell)

        self._connect_pages()
        self.navigation.set_history_results(self.replay_page.history_results)
        self._connect_viewmodel()
        self._apply_theme(ThemeMode.DARK.value)
        self.navigation_stack.setCurrentWidget(self.workspace_navigation)
        self.page_stack.setCurrentWidget(self.workspace_page)

    def _connect_pages(self) -> None:
        vm = self._viewmodel
        self.navigation.page_selected.connect(
            lambda key: self._show_page("replay" if key == "experiments" else key)
        )
        self.navigation.history_record_selected.connect(self._show_history_record)
        self.navigation.workspace_exit_requested.connect(vm.leave_workspace)
        self.workspace_navigation.workspace_selected.connect(vm.select_workspace)
        self.workspace_navigation.workspace_enter_requested.connect(vm.enter_selected_workspace)
        self.workspace_navigation.search_changed.connect(vm.search_workspaces)
        self.workspace_navigation.create_requested.connect(self._create_workspace)
        self.workspace_navigation.delete_requested.connect(self._delete_workspace_entry)
        self.workspace_navigation.settings_requested.connect(lambda: self._show_page("settings"))
        self.workspace_page.enter_requested.connect(vm.enter_selected_workspace)
        self.workspace_page.rename_requested.connect(self._rename_workspace)
        self.workspace_page.delete_requested.connect(self._delete_workspace)
        self.live_page.start_requested.connect(vm.start)
        self.live_page.pause_requested.connect(vm.pause)
        self.live_page.resume_requested.connect(vm.resume)
        self.live_page.stop_requested.connect(vm.stop)
        self.live_page.speed_changed.connect(vm.set_speed)
        self.live_page.vehicle_speed_requested.connect(self._control_speed)
        self.live_page.lane_change_requested.connect(self._control_lane)
        self.live_page.vehicle_stop_requested.connect(self._control_stop)
        self.replay_page.rerun_requested.connect(self._rerun_from_result)
        self.replay_page.return_requested.connect(lambda: self._show_page("scene"))
        self.replay_page.export_requested.connect(self._export_replay_result)
        self.scene_page.map_selected.connect(vm.select_map)
        self.scene_page.launch_requested.connect(vm.launch_experiment)
        self.traffic_scenes_page.scene_selected.connect(vm.select_map)
        self.maps_page.import_requested.connect(self._choose_map)
        self.maps_page.preview_requested.connect(vm.preview_map_asset)
        self.agents_page.configure_requested.connect(vm.configure_agent_api)
        self.agents_page.delete_requested.connect(vm.delete_agent_api)
        self.settings_page.theme_changed.connect(self._apply_theme)

    def _connect_viewmodel(self) -> None:
        vm = self._viewmodel
        vm.workspace_catalog_changed.connect(self._set_workspaces)
        vm.workspace_selected_changed.connect(self._set_selected_workspace)
        vm.workspace_overview_changed.connect(self._set_workspace_overview)
        vm.workspace_context_changed.connect(self._set_workspace_context)
        vm.agent_catalog_changed.connect(self.agents_page.set_agents)
        vm.map_catalog_changed.connect(self._set_maps)
        vm.map_manifest_changed.connect(self.maps_page.set_manifest)
        vm.asset_network_changed.connect(self.maps_page.set_preview_network)
        vm.network_changed.connect(self.live_page.map_widget.set_network)
        vm.network_changed.connect(self.replay_page.set_network)
        vm.vehicles_changed.connect(self._set_vehicles)
        vm.traffic_lights_changed.connect(self.live_page.map_widget.set_traffic_lights)
        vm.component_health_changed.connect(self._set_health)
        vm.experiment_status_changed.connect(self._set_status)
        vm.simulation_time_changed.connect(self._set_time)
        vm.control_availability_changed.connect(self._set_controls)
        vm.connection_changed.connect(self.live_page.set_connection)
        vm.monitor_requested.connect(lambda: self._show_page("live"))
        vm.notification.connect(self._show_notice)

    @Slot(str)
    def _show_page(self, key: str) -> None:
        if key not in {"workspace", "settings"} and self._viewmodel.active_workspace is None:
            self._show_notice("warning", "请先进入工作区，再使用仿真功能。")
            return
        page = self._pages.get(key)
        if page is None:
            return
        self.page_stack.setCurrentWidget(page)
        self.navigation.set_active(key)

    def _rerun_from_result(self, result: object) -> None:
        if isinstance(result, ReplayResult):
            self.scene_page.set_replay_configuration(result)
        self._show_page("scene")

    @Slot(str)
    def _export_replay_result(self, file_type: str) -> None:
        export_options = {
            "json": ("导出 JSON 结果", "trafficverse-replay.json", "JSON 文件 (*.json)", ".json"),
            "image": ("导出回放图片", "trafficverse-replay.png", "PNG 图片 (*.png)", ".png"),
        }
        option = export_options.get(file_type)
        if option is None:
            self._show_notice("error", "不支持的导出格式。")
            return
        title, default_name, file_filter, suffix = option
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(Path.home() / default_name),
            file_filter,
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != suffix:
            target = target.with_suffix(suffix)
        try:
            exported = (
                self.replay_page.export_json(target)
                if file_type == "json"
                else self.replay_page.export_image(target)
            )
        except OSError as error:
            self._show_notice("error", f"导出失败：{error}")
            return
        self._show_notice("success", f"已导出：{exported.name}")

    @Slot(int)
    def _show_history_record(self, index: int) -> None:
        self.replay_page.select_history(index)
        self._show_page("replay")

    @Slot(object)
    def _set_workspaces(self, workspaces: object) -> None:
        values = (
            tuple(item for item in workspaces if isinstance(item, WorkspaceSummary))
            if isinstance(workspaces, tuple)
            else ()
        )
        selected = self.workspace_page.workspace
        selected_id = str(selected.workspace_id) if selected is not None else None
        self.workspace_navigation.set_workspaces(values, selected_id)

    @Slot(object)
    def _set_selected_workspace(self, workspace: object) -> None:
        selected = workspace if isinstance(workspace, WorkspaceSummary) else None
        self.workspace_page.set_workspace(selected)
        self.workspace_navigation.set_selected(
            str(selected.workspace_id) if selected is not None else None
        )
        if self._viewmodel.active_workspace is None:
            self.page_stack.setCurrentWidget(self.workspace_page)

    @Slot(object)
    def _set_workspace_overview(self, overview: object) -> None:
        value = overview if isinstance(overview, WorkspaceOverview) else None
        self.workspace_page.set_overview(value)

    @Slot(object)
    def _set_workspace_context(self, workspace: object) -> None:
        selected = workspace if isinstance(workspace, WorkspaceSummary) else None
        if selected is None:
            self.navigation_stack.setCurrentWidget(self.workspace_navigation)
            self.page_stack.setCurrentWidget(self.workspace_page)
            return
        self.navigation.set_workspace(selected.name)
        self.navigation_stack.setCurrentWidget(self.navigation)
        self._show_page("scene")

    @Slot(object)
    def _set_maps(self, maps: object) -> None:
        values = (
            tuple(item for item in maps if isinstance(item, MapSummary))
            if isinstance(maps, tuple)
            else ()
        )
        self.scene_page.set_maps(tuple(item for item in values if item.kind == "sumo"))
        self.traffic_scenes_page.set_maps(values)
        self.maps_page.set_maps(values)

    @Slot(object)
    def _set_vehicles(self, vehicles: object) -> None:
        self.live_page.map_widget.set_vehicles(vehicles)
        count = len(vehicles) if isinstance(vehicles, tuple) else 0
        self.live_page.set_vehicle_count(count)

    @Slot(object)
    def _set_health(self, components: object) -> None:
        values = components if isinstance(components, tuple) else ()
        carla = next((item for item in values if getattr(item, "component", "") == "carla"), None)
        status = str(getattr(carla, "status", "UNKNOWN"))
        normalized_status = status.removeprefix("ComponentStatus.")
        health_labels = {
            "HEALTHY": "正常",
            "DEGRADED": "降级",
            "UNAVAILABLE": "不可用",
            "UNKNOWN": "未知",
        }
        self.live_page.set_carla_status(health_labels.get(normalized_status, normalized_status))
        if carla is not None and normalized_status != "HEALTHY":
            message = getattr(carla, "message", None) or "本机 CARLA 当前不可用"
            self.live_page.carla_window.show_unavailable(str(message))

    @Slot(str)
    def _set_status(self, status: str) -> None:
        labels = {
            "NOT_CREATED": "未创建",
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
        self.replay_page.set_status(display_status)

    @Slot(int)
    def _set_time(self, simulation_time_ms: int) -> None:
        self.live_page.set_time(simulation_time_ms)
        self.replay_page.set_simulation_time(simulation_time_ms)

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

    def _create_workspace(self) -> None:
        run_workspace_dialog(
            WorkspaceEditDialog(title="新增工作区", parent=self),
            self._viewmodel.create_workspace,
        )

    def _rename_workspace(self) -> None:
        workspace = self.workspace_page.workspace
        if workspace is None:
            return
        run_workspace_dialog(
            WorkspaceEditDialog(title="修改工作区", workspace=workspace, parent=self),
            lambda name, description: self._viewmodel.update_workspace(
                workspace.workspace_id,
                name,
                description,
            ),
        )

    def _delete_workspace(self) -> None:
        workspace = self.workspace_page.workspace
        if workspace is None:
            return
        self._confirm_delete_workspace(workspace)

    @Slot(object)
    def _delete_workspace_entry(self, workspace: object) -> None:
        if isinstance(workspace, WorkspaceSummary):
            self._confirm_delete_workspace(workspace)

    def _confirm_delete_workspace(self, workspace: WorkspaceSummary) -> None:
        dialog = WorkspaceDeleteDialog(workspace, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self._viewmodel.delete_workspace(workspace.workspace_id)

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
        self.maps_page.map_widget.set_theme(theme.value)
