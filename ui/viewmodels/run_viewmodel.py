"""Run-page state and commands, independent from concrete widgets."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from PySide6.QtCore import QObject, QTimer, Signal

from ui.api_client import RealtimeClient, RestApiClient
from ui.models import (
    AgentApiSummary,
    ControlAvailability,
    Envelope,
    ExperimentStatus,
    ExperimentView,
    LiveMetrics,
    MapImportJob,
    MapManifest,
    MapSummary,
    ReadinessResponse,
    Vehicle,
    WorkspaceOverview,
    WorkspaceSummary,
    WorldState,
)

_AUTOMATION_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
_AUTOMATION_LEVEL_PATTERN = re.compile(r"(?:^|_)L([0-5])(?:_|$)")
_SNAPSHOT_RECOVERY_INTERVAL_MS = 1_000


class RunViewModel(QObject):
    workspace_catalog_changed = Signal(object)
    workspace_selected_changed = Signal(object)
    workspace_overview_changed = Signal(object)
    workspace_context_changed = Signal(object)
    agent_catalog_changed = Signal(object)
    map_catalog_changed = Signal(object)
    map_manifest_changed = Signal(str, object)
    asset_network_changed = Signal(str, object)
    selected_map_changed = Signal(str)
    network_changed = Signal(object)
    vehicles_changed = Signal(object)
    traffic_lights_changed = Signal(object)
    component_health_changed = Signal(object)
    experiment_status_changed = Signal(str)
    simulation_time_changed = Signal(int)
    live_metrics_changed = Signal(object)
    control_availability_changed = Signal(object)
    connection_changed = Signal(str)
    monitor_requested = Signal()
    notification = Signal(str, str)

    def __init__(
        self,
        rest: RestApiClient,
        realtime: RealtimeClient,
        scenario_id: UUID,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._rest = rest
        self._realtime = realtime
        self._scenario_id = scenario_id
        self._workspaces: tuple[WorkspaceSummary, ...] = ()
        self._selected_workspace_id: UUID | None = None
        self._active_workspace_id: UUID | None = None
        self._enter_created_workspace_id: UUID | None = None
        self._agent_apis: tuple[AgentApiSummary, ...] = ()
        self._maps: tuple[MapSummary, ...] = ()
        self._selected_map_id: str | None = None
        self._import_job_id: UUID | None = None
        self._experiment_id: UUID | None = None
        self._experiment_workspace_id: UUID | None = None
        self._status: ExperimentStatus | None = None
        self._world: WorldState | None = None
        self._last_snapshot_recovery_time_ms: int | None = None
        self._launch_after_create = False
        self._start_after_prepare = False
        self._restart_after_stop = False
        self._stop_for_relaunch_when_running = False
        self._seen_vehicle_ids: set[str] = set()
        self._active_vehicle_ids: set[str] = set()
        self._vehicle_entered_at_ms: dict[str, int] = {}
        self._vehicle_automation_levels: dict[str, str] = {}
        self._completed_travel_time_total_ms = 0
        self._completed_vehicle_count = 0
        self._realtime_connected = False
        self._import_timer = QTimer(self)
        self._import_timer.setInterval(500)
        self._import_timer.timeout.connect(self._poll_import)
        rest.request_succeeded.connect(self.handle_rest_success)
        rest.request_failed.connect(self.handle_rest_failure)
        realtime.connection_changed.connect(self._handle_realtime_connection)
        realtime.envelope_received.connect(self.handle_envelope)
        realtime.protocol_error.connect(
            lambda message: self.notification.emit("error", f"实时协议错误：{message}")
        )

    @property
    def experiment_id(self) -> UUID | None:
        return self._experiment_id

    @property
    def status(self) -> ExperimentStatus | None:
        return self._status

    @property
    def active_workspace(self) -> WorkspaceSummary | None:
        return self._workspace(self._active_workspace_id)

    def initialize(self) -> None:
        # Readiness describes a prepared experiment and is expected to fail before one exists.
        # At UI startup only probe whether the API control plane is reachable.
        self._rest.check_health()
        self._rest.list_workspaces()
        self._emit_controls()

    def search_workspaces(self, query: str) -> None:
        self._rest.list_workspaces(query.strip() or None)

    def select_workspace(self, workspace_id: str) -> None:
        try:
            parsed_id = UUID(workspace_id)
        except ValueError:
            self.notification.emit("error", "工作区标识无效。")
            return
        workspace = self._workspace(parsed_id)
        if workspace is None:
            self.notification.emit("error", "所选工作区已不存在或不在当前搜索结果中。")
            return
        self._selected_workspace_id = parsed_id
        self.workspace_selected_changed.emit(workspace)
        self._rest.get_workspace_overview(parsed_id)

    def create_workspace(self, name: str, description: str) -> None:
        if not name.strip():
            self.notification.emit("error", "工作区名称不能为空。")
            return
        self._rest.create_workspace(name.strip(), description.strip())

    def update_workspace(self, workspace_id: UUID, name: str, description: str) -> None:
        if not name.strip():
            self.notification.emit("error", "工作区名称不能为空。")
            return
        self._rest.update_workspace(workspace_id, name.strip(), description.strip())

    def delete_workspace(self, workspace_id: UUID) -> None:
        self._rest.delete_workspace(workspace_id)

    def enter_selected_workspace(self) -> None:
        workspace = self._workspace(self._selected_workspace_id)
        if workspace is None:
            self.notification.emit("error", "请先选择一个工作区。")
            return
        if (
            self._experiment_workspace_id is not None
            and self._experiment_workspace_id != workspace.workspace_id
        ):
            self._reset_experiment_context()
        self._active_workspace_id = workspace.workspace_id
        self.workspace_context_changed.emit(workspace)
        self._rest.list_agent_assets(workspace.workspace_id)
        if not self._maps:
            self._rest.list_maps()

    def leave_workspace(self) -> None:
        self._active_workspace_id = None
        self._agent_apis = ()
        self.agent_catalog_changed.emit(())
        self.workspace_context_changed.emit(None)

    def select_map(self, map_id: str) -> None:
        selected = next((item for item in self._maps if item.map_id == map_id), None)
        if selected is None:
            self.notification.emit("error", "所选场景不在 SUMO 场景包列表中。")
            return
        if selected.kind != "sumo":
            self.notification.emit("error", "所选资产不是可直接运行的 SUMO 场景包。")
            return
        if not selected.validated:
            detail = "; ".join(selected.validation_errors) or "SUMO 场景配置无效"
            self.notification.emit("error", detail)
            return
        self._selected_map_id = map_id
        self.selected_map_changed.emit(map_id)
        self._rest.get_map_network(map_id)

    def preview_map_asset(self, map_id: str) -> None:
        if map_id not in {item.map_id for item in self._maps}:
            self.notification.emit("error", "所选地图资产不在目录中。")
            return
        self._rest.get_asset_map_network(map_id)

    def import_map(self, path: Path) -> None:
        if path.suffix.lower() != ".xodr":
            self.notification.emit("error", "请选择 .xodr 格式的 OpenDRIVE 地图。")
            return
        self.notification.emit("info", "正在上传并校验地图……")
        self._rest.import_map(path)

    def configure_agent_api(
        self,
        name: str,
        api_base_url: str,
        model_id: str,
        credential_env_var: str,
        description: str,
    ) -> None:
        if self._active_workspace_id is None:
            self.notification.emit("error", "请先进入工作区，再配置智能体。")
            return
        parsed = urlparse(api_base_url)
        if not name or not model_id or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.notification.emit("error", "请填写名称、有效的 API 地址和模型 ID。")
            return
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", credential_env_var) is None:
            self.notification.emit("error", "凭证环境变量必须使用大写字母、数字和下划线。")
            return
        self._rest.configure_agent_asset(
            self._active_workspace_id,
            name,
            api_base_url,
            model_id,
            credential_env_var,
            description,
        )

    def delete_agent_api(self, agent_api_id: UUID) -> None:
        if self._active_workspace_id is None:
            self.notification.emit("error", "请先进入工作区。")
            return
        self._rest.delete_agent_asset(self._active_workspace_id, agent_api_id)

    def create_experiment(self) -> bool:
        if self._active_workspace_id is None:
            self.notification.emit("error", "请先进入工作区，再创建仿真实验。")
            return False
        if self._selected_map_id is None:
            self.notification.emit("error", "请先选择一份已验证的 SUMO 场景包。")
            return False
        self._rest.create_experiment(
            self._active_workspace_id,
            self._scenario_id,
            self._selected_map_id,
        )
        return True

    def launch_experiment(self) -> None:
        """Create the configured experiment, then enter and start live monitoring."""
        if self._status in {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED}:
            self._begin_restart()
            return
        if self._status in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED}:
            self._restart_after_stop = self._send(
                "experiment.stop",
                {"reason": "SCENARIO_SWITCH"},
            )
            return
        if self._status is ExperimentStatus.STOPPING:
            self._restart_after_stop = True
            return
        if self._status in {
            ExperimentStatus.CREATED,
            ExperimentStatus.PREPARING,
            ExperimentStatus.READY,
        }:
            self._restart_after_stop = True
            self._stop_for_relaunch_when_running = True
            if self._status is ExperimentStatus.CREATED:
                self.start()
            elif self._status is ExperimentStatus.PREPARING:
                self._start_after_prepare = True
            else:
                self.start()
            return
        self._launch_after_create = True
        if not self.create_experiment():
            self._launch_after_create = False

    def start(self) -> None:
        if self._status is ExperimentStatus.CREATED:
            self._start_after_prepare = True
            if self._realtime_connected:
                self._send("experiment.prepare", {})
        elif self._status is ExperimentStatus.READY:
            self._send("experiment.start", {})

    def pause(self) -> None:
        self._send("experiment.pause", {})

    def resume(self) -> None:
        self._send("experiment.resume", {})

    def stop(self) -> None:
        self._restart_after_stop = False
        self._stop_for_relaunch_when_running = False
        self._send("experiment.stop", {"reason": "USER_REQUEST"})

    def restart(self) -> None:
        if self._status in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED}:
            self._restart_after_stop = self._send(
                "experiment.stop",
                {"reason": "USER_RESTART"},
            )
            return
        if self._status in {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED}:
            self._begin_restart()
            return
        self.notification.emit("warning", "当前实验状态不支持重新开始。")

    def set_speed(self, multiplier: float) -> None:
        self._send("experiment.speed.set", {"multiplier": multiplier})

    def handle_rest_success(self, operation: str, payload: object) -> None:
        if operation == "health":
            self.connection_changed.emit("API_CONNECTED")
        elif operation == "workspaces.list":
            self._workspaces = tuple(
                WorkspaceSummary.model_validate(item) for item in _items(payload)
            )
            self.workspace_catalog_changed.emit(self._workspaces)
            selected = self._workspace(self._selected_workspace_id)
            if selected is None:
                selected = self._workspaces[0] if self._workspaces else None
                self._selected_workspace_id = (
                    selected.workspace_id if selected is not None else None
                )
            self.workspace_selected_changed.emit(selected)
            if selected is not None:
                self._rest.get_workspace_overview(selected.workspace_id)
                if self._enter_created_workspace_id == selected.workspace_id:
                    self._enter_created_workspace_id = None
                    self.enter_selected_workspace()
            else:
                self.workspace_overview_changed.emit(None)
        elif operation == "workspace.create":
            workspace = WorkspaceSummary.model_validate(payload)
            self._selected_workspace_id = workspace.workspace_id
            self._enter_created_workspace_id = workspace.workspace_id
            self._rest.list_workspaces()
        elif operation.startswith("workspace.update:"):
            workspace = WorkspaceSummary.model_validate(payload)
            self._selected_workspace_id = workspace.workspace_id
            self.notification.emit("success", "工作区信息已更新。")
            self._rest.list_workspaces()
        elif operation.startswith("workspace.delete:"):
            deleted_id = UUID(operation.removeprefix("workspace.delete:"))
            if self._selected_workspace_id == deleted_id:
                self._selected_workspace_id = None
            if self._active_workspace_id == deleted_id:
                self._active_workspace_id = None
                self.workspace_context_changed.emit(None)
            self.notification.emit("success", "工作区已删除。")
            self._rest.list_workspaces()
        elif operation.startswith("workspace.overview:"):
            overview = WorkspaceOverview.model_validate(payload)
            if overview.workspace_id == self._selected_workspace_id:
                self.workspace_overview_changed.emit(overview)
        elif operation.startswith("agent-assets.list:"):
            workspace_id = UUID(operation.removeprefix("agent-assets.list:"))
            if workspace_id == self._active_workspace_id:
                self._agent_apis = tuple(
                    AgentApiSummary.model_validate(item) for item in _items(payload)
                )
                self.agent_catalog_changed.emit(self._agent_apis)
        elif operation.startswith("agent-assets.create:"):
            workspace_id = UUID(operation.removeprefix("agent-assets.create:"))
            self.notification.emit("success", "智能体 API 已添加。")
            if workspace_id == self._active_workspace_id:
                self._rest.list_agent_assets(workspace_id)
        elif operation.startswith("agent-assets.delete:"):
            _, workspace_id_text, _ = operation.split(":", maxsplit=2)
            workspace_id = UUID(workspace_id_text)
            self.notification.emit("success", "智能体 API 已删除。")
            if workspace_id == self._active_workspace_id:
                self._rest.list_agent_assets(workspace_id)
        elif operation == "ready":
            readiness = ReadinessResponse.model_validate(payload)
            if not readiness.ready:
                self.notification.emit("warning", "后端尚未就绪，请检查组件状态。")
            self.component_health_changed.emit(readiness.components)
        elif operation == "maps.list":
            self._maps = tuple(MapSummary.model_validate(item) for item in _items(payload))
            self.map_catalog_changed.emit(self._maps)
            for item in self._maps:
                if item.manifest_available:
                    self._rest.get_map_manifest(item.map_id)
            if self._selected_map_id is None:
                first_valid = next(
                    (item for item in self._maps if item.kind == "sumo" and item.validated),
                    None,
                )
                if first_valid is not None:
                    self.select_map(first_valid.map_id)
        elif operation.startswith("map.manifest:"):
            map_id = operation.removeprefix("map.manifest:")
            manifest = MapManifest.model_validate(payload)
            if manifest.map_id != map_id:
                raise ValueError("map manifest id does not match the requested asset")
            self.map_manifest_changed.emit(map_id, manifest)
        elif operation.startswith("asset.map.network:"):
            map_id = operation.removeprefix("asset.map.network:")
            self.asset_network_changed.emit(map_id, payload)
        elif operation.startswith("map.network:"):
            self.network_changed.emit(payload)
        elif operation == "map.import.submit" or operation.startswith("map.import:"):
            self._handle_import_job(MapImportJob.model_validate(payload))
        elif operation == "experiment.create":
            self._set_experiment(ExperimentView.model_validate(payload))
            if self._launch_after_create:
                self._launch_after_create = False
                self.monitor_requested.emit()
                self.start()
        elif operation.startswith("experiment.get:"):
            self._set_experiment(ExperimentView.model_validate(payload))

    def handle_rest_failure(self, operation: str, message: str) -> None:
        if operation.startswith("map.import"):
            self._import_timer.stop()
        if operation == "experiment.create":
            self._launch_after_create = False
        self.notification.emit("error", f"操作失败：{message}")

    def handle_envelope(self, payload: object) -> None:
        try:
            envelope = Envelope.model_validate(payload)
            if self._world is None:
                return
            update = self._world.apply(envelope)
            self.simulation_time_changed.emit(self._world.simulation_time_ms)
            if update.sequence_gap is not None:
                last_recovery_ms = self._last_snapshot_recovery_time_ms
                if (
                    last_recovery_ms is None
                    or self._world.simulation_time_ms - last_recovery_ms
                    >= _SNAPSHOT_RECOVERY_INTERVAL_MS
                ):
                    self._last_snapshot_recovery_time_ms = self._world.simulation_time_ms
                    self._realtime.request_snapshot()
            if update.vehicles_changed:
                vehicles = tuple(self._world.vehicles.values())
                self._update_live_metrics(
                    vehicles,
                    self._world.collision_vehicle_ids,
                    self._world.simulation_time_ms,
                )
                self.vehicles_changed.emit(vehicles)
            if update.traffic_lights_changed:
                self.traffic_lights_changed.emit(tuple(self._world.traffic_lights.values()))
            if update.health_changed:
                self.component_health_changed.emit(tuple(self._world.components.values()))
            if update.status_changed and self._world.status is not None:
                self._set_status(self._world.status)
            if envelope.type == "command.rejected":
                self._restart_after_stop = False
                self._stop_for_relaunch_when_running = False
                message = (
                    envelope.payload.get("message") if isinstance(envelope.payload, dict) else None
                )
                self.notification.emit("error", str(message or "命令被后端拒绝。"))
            elif envelope.type == "error":
                self.notification.emit("error", "后端报告实时协议错误。")
        except (ValueError, TypeError) as error:
            self.notification.emit("error", f"无法处理实时消息：{error}")

    def _set_experiment(self, view: ExperimentView) -> None:
        if self._active_workspace_id != view.workspace_id:
            self.notification.emit("error", "实验不属于当前工作区，已拒绝加载。")
            return
        self._experiment_id = view.experiment_id
        self._experiment_workspace_id = view.workspace_id
        self._world = WorldState(view.experiment_id, simulation_time_ms=view.simulation_time_ms)
        self._last_snapshot_recovery_time_ms = None
        self._reset_live_metrics()
        self._set_status(view.status)
        self._realtime.connect_to_experiment(view.experiment_id)

    def _set_status(self, status: ExperimentStatus) -> None:
        self._status = status
        self.experiment_status_changed.emit(status.value)
        self._emit_controls()
        if status is ExperimentStatus.READY and self._start_after_prepare:
            self._start_after_prepare = False
            self._send("experiment.start", {})
        if status is ExperimentStatus.RUNNING and self._stop_for_relaunch_when_running:
            self._stop_for_relaunch_when_running = not self._send(
                "experiment.stop",
                {"reason": "SCENARIO_SWITCH"},
            )
        if (
            status in {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED}
            and self._restart_after_stop
        ):
            self._begin_restart()

    def _begin_restart(self) -> None:
        self._restart_after_stop = False
        self._stop_for_relaunch_when_running = False
        self._reset_experiment_context()
        self._launch_after_create = True
        if not self.create_experiment():
            self._launch_after_create = False

    def _update_live_metrics(
        self,
        vehicles: tuple[Vehicle, ...],
        collision_vehicle_ids: set[str],
        simulation_time_ms: int,
    ) -> None:
        current_ids = {vehicle.vehicle_id for vehicle in vehicles}
        self._seen_vehicle_ids.update(current_ids)
        for vehicle in vehicles:
            self._vehicle_automation_levels[vehicle.vehicle_id] = vehicle.automation_level
            self._vehicle_entered_at_ms.setdefault(
                vehicle.vehicle_id,
                min(vehicle.simulation_time_ms, simulation_time_ms),
            )
        for vehicle_id in self._active_vehicle_ids - current_ids:
            entered_at_ms = self._vehicle_entered_at_ms.pop(vehicle_id, None)
            if entered_at_ms is None:
                continue
            self._completed_travel_time_total_ms += max(
                0,
                simulation_time_ms - entered_at_ms,
            )
            self._completed_vehicle_count += 1
        self._active_vehicle_ids = current_ids
        average_speed_mps = (
            sum(vehicle.speed_mps for vehicle in vehicles) / len(vehicles) if vehicles else 0.0
        )
        average_travel_time_ms = (
            self._completed_travel_time_total_ms / self._completed_vehicle_count
            if self._completed_vehicle_count
            else None
        )
        level_speed_samples: dict[str, list[float]] = {level: [] for level in _AUTOMATION_LEVELS}
        for vehicle in vehicles:
            if vehicle.automation_level in level_speed_samples:
                level_speed_samples[vehicle.automation_level].append(vehicle.speed_mps)
        level_average_speed_mps = tuple(
            (
                level,
                sum(level_speed_samples[level]) / len(level_speed_samples[level])
                if level_speed_samples[level]
                else 0.0,
            )
            for level in _AUTOMATION_LEVELS
        )
        collision_counts = dict.fromkeys(_AUTOMATION_LEVELS, 0)
        for vehicle_id in collision_vehicle_ids:
            level = self._vehicle_automation_levels.get(vehicle_id) or _vehicle_level(vehicle_id)
            if level in collision_counts:
                collision_counts[level] += 1
        self.live_metrics_changed.emit(
            LiveMetrics(
                current_vehicle_count=len(vehicles),
                total_vehicle_count=len(self._seen_vehicle_ids),
                average_speed_mps=average_speed_mps,
                average_travel_time_ms=average_travel_time_ms,
                level_average_speed_mps=level_average_speed_mps,
                level_collision_counts=tuple(
                    (level, collision_counts[level]) for level in _AUTOMATION_LEVELS
                ),
            )
        )

    def _reset_live_metrics(self) -> None:
        self._seen_vehicle_ids.clear()
        self._active_vehicle_ids.clear()
        self._vehicle_entered_at_ms.clear()
        self._vehicle_automation_levels.clear()
        self._completed_travel_time_total_ms = 0
        self._completed_vehicle_count = 0
        self.live_metrics_changed.emit(
            LiveMetrics(
                current_vehicle_count=0,
                total_vehicle_count=0,
                average_speed_mps=0.0,
                average_travel_time_ms=None,
                level_average_speed_mps=tuple((level, 0.0) for level in _AUTOMATION_LEVELS),
                level_collision_counts=tuple((level, 0) for level in _AUTOMATION_LEVELS),
            )
        )

    def _send(self, command: str, payload: dict[str, object]) -> bool:
        if self._experiment_id is None:
            self.notification.emit("error", "请先创建实验。")
            return False
        try:
            self._realtime.send_command(command, payload)
        except RuntimeError as error:
            self.notification.emit("error", f"命令发送失败：{error}")
            return False
        return True

    def _handle_realtime_connection(self, status: str) -> None:
        self._realtime_connected = status == "CONNECTED"
        self.connection_changed.emit(status)
        if (
            self._realtime_connected
            and self._start_after_prepare
            and self._status is ExperimentStatus.CREATED
        ):
            self._send("experiment.prepare", {})

    def _handle_import_job(self, job: MapImportJob) -> None:
        self._import_job_id = job.job_id
        if job.status in {"PENDING", "RUNNING"}:
            self._import_timer.start()
            return
        self._import_timer.stop()
        if job.status == "FAILED":
            detail = "; ".join(job.errors) or "地图校验失败"
            self.notification.emit("error", detail)
            return
        self.notification.emit("success", "地图编译和校验已完成。")
        self._rest.list_maps()

    def _poll_import(self) -> None:
        if self._import_job_id is not None:
            self._rest.get_import_job(self._import_job_id)

    def _emit_controls(self) -> None:
        self.control_availability_changed.emit(ControlAvailability.for_status(self._status))

    def _reset_experiment_context(self) -> None:
        self._realtime.close()
        self._realtime_connected = False
        self._experiment_id = None
        self._experiment_workspace_id = None
        self._status = None
        self._world = None
        self._last_snapshot_recovery_time_ms = None
        self._launch_after_create = False
        self._start_after_prepare = False
        self._restart_after_stop = False
        self._stop_for_relaunch_when_running = False
        self.experiment_status_changed.emit("NOT_CREATED")
        self.simulation_time_changed.emit(0)
        self.vehicles_changed.emit(())
        self.traffic_lights_changed.emit(())
        self._reset_live_metrics()
        self._emit_controls()

    def _workspace(self, workspace_id: UUID | None) -> WorkspaceSummary | None:
        if workspace_id is None:
            return None
        return next(
            (item for item in self._workspaces if item.workspace_id == workspace_id),
            None,
        )


def _vehicle_level(vehicle_id: str) -> str | None:
    match = _AUTOMATION_LEVEL_PATTERN.search(vehicle_id)
    return f"L{match.group(1)}" if match is not None else None


def _items(payload: object) -> list[object]:
    if not isinstance(payload, list):
        raise ValueError("REST response must be an array")
    return payload
