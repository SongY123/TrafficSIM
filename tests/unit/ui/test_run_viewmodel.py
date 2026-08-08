from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from ui.models import ExperimentStatus, LiveMetrics
from ui.viewmodels import RunViewModel

EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000010")
RESTARTED_EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000011")
SCENARIO_ID = UUID("00000000-0000-0000-0000-000000000042")
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")


class FakeRest(QObject):
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, object]] = []

    def check_readiness(self) -> None:
        self.calls.append(("ready", None))

    def check_health(self) -> None:
        self.calls.append(("health", None))

    def list_maps(self) -> None:
        self.calls.append(("maps", None))

    def list_workspaces(self, query: str | None = None) -> None:
        self.calls.append(("workspaces", query))

    def get_workspace_overview(self, workspace_id: UUID) -> None:
        self.calls.append(("workspace-overview", workspace_id))

    def list_agent_assets(self, workspace_id: UUID) -> None:
        self.calls.append(("agent-assets", workspace_id))

    def configure_agent_asset(
        self,
        workspace_id: UUID,
        name: str,
        api_base_url: str,
        model_id: str,
        credential_env_var: str,
        description: str,
    ) -> None:
        self.calls.append(
            (
                "agent-configure",
                (
                    workspace_id,
                    name,
                    api_base_url,
                    model_id,
                    credential_env_var,
                    description,
                ),
            )
        )

    def delete_agent_asset(self, workspace_id: UUID, agent_api_id: UUID) -> None:
        self.calls.append(("agent-delete", (workspace_id, agent_api_id)))

    def create_workspace(self, name: str, description: str) -> None:
        self.calls.append(("workspace-create", (name, description)))

    def update_workspace(self, workspace_id: UUID, name: str, description: str) -> None:
        self.calls.append(("workspace-update", (workspace_id, name, description)))

    def delete_workspace(self, workspace_id: UUID) -> None:
        self.calls.append(("workspace-delete", workspace_id))

    def get_map_network(self, map_id: str) -> None:
        self.calls.append(("network", map_id))

    def get_asset_map_network(self, map_id: str) -> None:
        self.calls.append(("asset-network", map_id))

    def get_map_manifest(self, map_id: str) -> None:
        self.calls.append(("manifest", map_id))

    def get_import_job(self, job_id: UUID) -> None:
        self.calls.append(("import-job", job_id))

    def import_map(self, path: Path) -> None:
        self.calls.append(("import", path))

    def create_experiment(self, workspace_id: UUID, scenario_id: UUID, map_id: str) -> None:
        self.calls.append(("create", (workspace_id, scenario_id, map_id)))


class FakeRealtime(QObject):
    connection_changed = Signal(str)
    envelope_received = Signal(object)
    protocol_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.connected: UUID | None = None
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.snapshot_requests = 0
        self.closed = False
        self.raise_on_send = False

    def connect_to_experiment(self, experiment_id: UUID) -> None:
        self.connected = experiment_id

    def send_command(self, command: str, payload: dict[str, object]) -> str:
        if self.raise_on_send:
            raise RuntimeError("realtime connection is unavailable")
        self.sent.append((command, payload))
        return "message-1"

    def request_snapshot(self) -> str:
        self.snapshot_requests += 1
        return "snapshot-1"

    def close(self) -> None:
        self.closed = True


def _app() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _viewmodel() -> tuple[RunViewModel, FakeRest, FakeRealtime]:
    _app()
    rest = FakeRest()
    realtime = FakeRealtime()
    viewmodel = RunViewModel(rest, realtime, SCENARIO_ID)  # type: ignore[arg-type]
    return viewmodel, rest, realtime


def _enter_workspace(viewmodel: RunViewModel) -> None:
    viewmodel.handle_rest_success(
        "workspaces.list",
        [
            {
                "workspace_id": str(WORKSPACE_ID),
                "name": "测试工作区",
                "description": "",
                "created_at": "2026-07-31T00:00:00Z",
                "updated_at": "2026-07-31T00:00:00Z",
            }
        ],
    )
    viewmodel.enter_selected_workspace()


def _envelope(message_type: str, sequence: int, payload: object) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "type": message_type,
        "message_id": f"message-{sequence}",
        "correlation_id": None,
        "experiment_id": str(EXPERIMENT_ID),
        "simulation_time_ms": sequence * 50,
        "sequence": sequence,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def _vehicle(
    sequence: int,
    *,
    vehicle_id: str = "vehicle-1",
    speed_mps: float = 5.0,
    automation_level: str = "HUMAN",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "experiment_id": str(EXPERIMENT_ID),
        "vehicle_id": vehicle_id,
        "simulation_time_ms": sequence * 50,
        "sequence": sequence,
        "automation_level": automation_level,
        "position": {"x": 1.0, "y": 2.0, "z": 0.0},
        "speed_mps": speed_mps,
        "acceleration_mps2": 0.0,
        "heading_rad": 0.0,
        "lane_id": "lane-1",
        "target_lane_id": None,
        "controller_id": "fixture",
        "action": "KEEP_LANE",
        "risk_score": 0.0,
        "route_id": "route-1",
    }


def test_initialize_loads_workspaces_without_exposing_simulation_resources() -> None:
    viewmodel, rest, _ = _viewmodel()
    connection_states: list[str] = []
    viewmodel.connection_changed.connect(connection_states.append)

    viewmodel.initialize()
    viewmodel.handle_rest_success(
        "health",
        {"status": "ok", "service": "trafficverse-api"},
    )

    assert rest.calls == [("health", None), ("workspaces", None)]
    assert connection_states == ["API_CONNECTED"]


def test_workspace_crud_search_selection_and_entry_drive_backend_calls() -> None:
    viewmodel, rest, _ = _viewmodel()
    workspace_id = UUID("10000000-0000-0000-0000-000000000001")
    contexts: list[object] = []
    viewmodel.workspace_context_changed.connect(contexts.append)
    viewmodel.handle_rest_success(
        "workspaces.list",
        [
            {
                "workspace_id": str(workspace_id),
                "name": "北京亦庄",
                "description": "核心路网",
                "created_at": "2026-07-31T00:00:00Z",
                "updated_at": "2026-07-31T00:00:00Z",
            }
        ],
    )

    viewmodel.search_workspaces("  北京  ")
    viewmodel.create_workspace(" 新工作区 ", " 描述 ")
    viewmodel.update_workspace(workspace_id, "新名称", "新描述")
    viewmodel.enter_selected_workspace()

    assert ("workspace-overview", workspace_id) in rest.calls
    assert ("workspaces", "北京") in rest.calls
    assert ("workspace-create", ("新工作区", "描述")) in rest.calls
    assert ("workspace-update", (workspace_id, "新名称", "新描述")) in rest.calls
    assert ("maps", None) in rest.calls
    assert ("agent-assets", workspace_id) in rest.calls
    assert contexts and getattr(contexts[-1], "workspace_id", None) == workspace_id


def test_created_workspace_is_entered_without_success_notification() -> None:
    viewmodel, rest, _ = _viewmodel()
    workspace_id = UUID("10000000-0000-0000-0000-000000000099")
    contexts: list[object] = []
    notifications: list[tuple[str, str]] = []
    viewmodel.workspace_context_changed.connect(contexts.append)
    viewmodel.notification.connect(lambda level, message: notifications.append((level, message)))
    payload = {
        "workspace_id": str(workspace_id),
        "name": "新建工作区",
        "description": "自动进入",
        "created_at": "2026-07-31T00:00:00Z",
        "updated_at": "2026-07-31T00:00:00Z",
    }

    viewmodel.handle_rest_success("workspace.create", payload)
    viewmodel.handle_rest_success("workspaces.list", [payload])

    assert viewmodel.active_workspace is not None
    assert viewmodel.active_workspace.workspace_id == workspace_id
    assert contexts and getattr(contexts[-1], "workspace_id", None) == workspace_id
    assert notifications == []
    assert ("maps", None) in rest.calls


def test_map_catalog_skips_core_run_asset_and_auto_selects_sumo_package() -> None:
    viewmodel, rest, _ = _viewmodel()
    notifications: list[tuple[str, str]] = []
    viewmodel.notification.connect(lambda level, message: notifications.append((level, message)))
    viewmodel.handle_rest_success(
        "workspaces.list",
        [
            {
                "workspace_id": "10000000-0000-0000-0000-000000000001",
                "name": "测试工作区",
                "description": "",
                "created_at": "2026-07-31T00:00:00Z",
                "updated_at": "2026-07-31T00:00:00Z",
            }
        ],
    )
    viewmodel.enter_selected_workspace()
    viewmodel.handle_rest_success(
        "maps.list",
        [
            {
                "map_id": "town04",
                "carla_map": "Town04",
                "carla_version": "0.9.16",
                "validated": True,
                "network_schema_version": "traffic-network/1.0",
            },
            {
                "map_id": "image2road",
                "kind": "sumo",
                "display_name": "图像识别路网",
                "carla_map": None,
                "carla_version": None,
                "validated": True,
                "network_schema_version": "sumo-net/display-1.0",
                "manifest_available": False,
                "sumo_config_file": "image2road.sumocfg",
                "sumo_step_ms": 1000,
            },
        ],
    )
    viewmodel.select_map("town04")
    viewmodel.create_experiment()

    assert ("manifest", "town04") in rest.calls
    assert ("network", "town04") not in rest.calls
    assert ("network", "image2road") in rest.calls
    assert (
        "create",
        (
            UUID("10000000-0000-0000-0000-000000000001"),
            SCENARIO_ID,
            "image2road",
        ),
    ) in rest.calls
    assert notifications[-1] == ("error", "所选资产不是可直接运行的 SUMO 场景包。")


def test_native_sumo_package_loads_network_without_town04_manifest() -> None:
    viewmodel, rest, _ = _viewmodel()
    workspace_id = UUID("10000000-0000-0000-0000-000000000001")
    viewmodel.handle_rest_success(
        "workspaces.list",
        [
            {
                "workspace_id": str(workspace_id),
                "name": "测试工作区",
                "description": "",
                "created_at": "2026-07-31T00:00:00Z",
                "updated_at": "2026-07-31T00:00:00Z",
            }
        ],
    )
    viewmodel.enter_selected_workspace()
    viewmodel.handle_rest_success(
        "maps.list",
        [
            {
                "map_id": "image2road",
                "kind": "sumo",
                "display_name": "图像识别路网",
                "carla_map": None,
                "carla_version": None,
                "validated": True,
                "network_schema_version": "sumo-net/display-1.0",
                "manifest_available": False,
                "sumo_config_file": "image2road.sumocfg",
                "sumo_step_ms": 1000,
            }
        ],
    )
    viewmodel.create_experiment()

    assert ("network", "image2road") in rest.calls
    assert ("manifest", "image2road") not in rest.calls
    assert ("create", (workspace_id, SCENARIO_ID, "image2road")) in rest.calls


def test_asset_manifest_and_preview_network_are_forwarded_separately() -> None:
    viewmodel, rest, _ = _viewmodel()
    manifests: list[tuple[str, object]] = []
    previews: list[tuple[str, object]] = []
    viewmodel.map_manifest_changed.connect(
        lambda map_id, manifest: manifests.append((map_id, manifest))
    )
    viewmodel.asset_network_changed.connect(
        lambda map_id, network: previews.append((map_id, network))
    )
    viewmodel.handle_rest_success(
        "maps.list",
        [
            {
                "map_id": "town04",
                "carla_map": "Town04",
                "carla_version": "0.9.16",
                "validated": True,
                "network_schema_version": "traffic-network/1.0",
            }
        ],
    )
    manifest = {
        "schema_version": "1.1",
        "map_id": "town04",
        "carla_map": "Town04",
        "carla_version": "0.9.16",
        "sumo_version": "1.27.1",
        "network_schema_version": "traffic-network/1.0",
        "compiler_version": "1.1.0",
        "source_repository": "https://example.invalid/maps",
        "source_ref": "fixture",
        "sumo_generation_command": "fixture",
        "validated": True,
        "max_registration_error_m": 0.001,
        "strict_signal_mapping": True,
        "files": {"network.geojson": "sha256:" + "a" * 64},
    }
    viewmodel.handle_rest_success("map.manifest:town04", manifest)
    viewmodel.preview_map_asset("town04")
    network = {"type": "FeatureCollection", "features": []}
    viewmodel.handle_rest_success("asset.map.network:town04", network)

    assert manifests and manifests[0][0] == "town04"
    assert ("asset-network", "town04") in rest.calls
    assert previews == [("town04", network)]


def test_agent_api_configuration_is_validated_and_scoped_to_active_workspace() -> None:
    viewmodel, rest, _ = _viewmodel()
    _enter_workspace(viewmodel)
    notifications: list[tuple[str, str]] = []
    viewmodel.notification.connect(lambda level, message: notifications.append((level, message)))

    viewmodel.configure_agent_api(
        "城市驾驶智能体",
        "https://agents.example.com/v1",
        "urban-driver-v1",
        "TRAFFICVERSE_AGENT_API_KEY",
        "远程接入",
    )
    viewmodel.configure_agent_api(
        "无效智能体",
        "not-a-url",
        "invalid",
        "invalid-key",
        "",
    )

    assert (
        "agent-configure",
        (
            WORKSPACE_ID,
            "城市驾驶智能体",
            "https://agents.example.com/v1",
            "urban-driver-v1",
            "TRAFFICVERSE_AGENT_API_KEY",
            "远程接入",
        ),
    ) in rest.calls
    assert notifications[-1] == ("error", "请填写名称、有效的 API 地址和模型 ID。")


def test_start_prepares_created_experiment_then_starts_when_ready() -> None:
    viewmodel, _, realtime = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "CREATED",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    realtime.connection_changed.emit("CONNECTED")
    viewmodel.start()
    viewmodel.handle_envelope(_envelope("experiment.state.changed", 0, {"status": "READY"}))

    assert realtime.connected == EXPERIMENT_ID
    assert realtime.sent == [
        ("experiment.prepare", {}),
        ("experiment.start", {}),
    ]
    assert viewmodel.status is ExperimentStatus.READY


def test_launch_creates_experiment_then_opens_monitor_and_starts() -> None:
    viewmodel, rest, realtime = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "maps.list",
        [
            {
                "map_id": "image2road",
                "kind": "sumo",
                "display_name": "图像识别路网",
                "validated": True,
                "network_schema_version": "sumo-net/display-1.0",
                "manifest_available": False,
                "sumo_config_file": "image2road.sumocfg",
                "sumo_step_ms": 1000,
            }
        ],
    )
    monitor_requests = 0

    def record_monitor_request() -> None:
        nonlocal monitor_requests
        monitor_requests += 1

    viewmodel.monitor_requested.connect(record_monitor_request)

    viewmodel.launch_experiment()
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "CREATED",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    assert realtime.sent == []
    realtime.connection_changed.emit("CONNECTED")

    assert ("create", (WORKSPACE_ID, SCENARIO_ID, "image2road")) in rest.calls
    assert monitor_requests == 1
    assert realtime.sent == [("experiment.prepare", {})]


def test_launching_another_map_stops_active_experiment_then_launches_selected_map() -> None:
    viewmodel, rest, realtime = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "maps.list",
        [
            {
                "map_id": map_id,
                "kind": "sumo",
                "display_name": map_id,
                "validated": True,
                "network_schema_version": "sumo-net/display-1.0",
                "manifest_available": False,
                "sumo_config_file": f"{map_id}.sumocfg",
                "sumo_step_ms": 50,
            }
            for map_id in ("scene-a", "scene-b")
        ],
    )
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "RUNNING",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    viewmodel.select_map("scene-b")

    viewmodel.launch_experiment()

    assert realtime.sent[-1] == ("experiment.stop", {"reason": "SCENARIO_SWITCH"})

    viewmodel.handle_envelope(_envelope("experiment.state.changed", 1, {"status": "COMPLETED"}))

    assert realtime.closed is True
    assert rest.calls[-1] == ("create", (WORKSPACE_ID, SCENARIO_ID, "scene-b"))


def test_vehicle_sequence_gap_requests_world_snapshot() -> None:
    viewmodel, _, realtime = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "RUNNING",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    viewmodel.handle_envelope(
        _envelope(
            "world.snapshot",
            2,
            {
                "traffic": {"vehicles": [_vehicle(2)], "traffic_lights": []},
                "carla": None,
                "events": [],
                "metrics": [],
            },
        )
    )
    viewmodel.handle_envelope(_envelope("vehicle.delta", 4, {"vehicles": [_vehicle(4)]}))

    assert realtime.snapshot_requests == 1


def test_repeated_vehicle_sequence_gaps_rate_limit_snapshot_recovery() -> None:
    viewmodel, _, realtime = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "RUNNING",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    viewmodel.handle_envelope(
        _envelope(
            "world.snapshot",
            2,
            {
                "traffic": {"vehicles": [_vehicle(2)], "traffic_lights": []},
                "carla": None,
                "events": [],
                "metrics": [],
            },
        )
    )

    viewmodel.handle_envelope(_envelope("vehicle.delta", 4, {"vehicles": [_vehicle(4)]}))
    viewmodel.handle_envelope(_envelope("vehicle.delta", 6, {"vehicles": [_vehicle(6)]}))
    viewmodel.handle_envelope(_envelope("vehicle.delta", 25, {"vehicles": [_vehicle(25)]}))

    assert realtime.snapshot_requests == 2


def test_running_world_deltas_forward_new_vehicle_positions_to_the_map() -> None:
    viewmodel, _, _ = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "RUNNING",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    positions: list[tuple[float, float]] = []
    viewmodel.vehicles_changed.connect(
        lambda vehicles: positions.append((vehicles[0].position.x, vehicles[0].position.y))
    )
    first = _vehicle(1)
    second = _vehicle(2)
    second["position"] = {"x": 8.0, "y": 5.0, "z": 0.0}

    viewmodel.handle_envelope(_envelope("vehicle.delta", 1, {"vehicles": [first]}))
    viewmodel.handle_envelope(_envelope("vehicle.delta", 2, {"vehicles": [second]}))

    assert positions == [(1.0, 2.0), (8.0, 5.0)]


def test_live_metrics_track_active_total_speed_and_completed_travel_time() -> None:
    viewmodel, _, _ = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "RUNNING",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    samples: list[LiveMetrics] = []
    viewmodel.live_metrics_changed.connect(samples.append)

    viewmodel.handle_envelope(
        _envelope(
            "vehicle.delta",
            1,
            {
                "vehicles": [
                    _vehicle(
                        1,
                        vehicle_id="target_L0_001",
                        speed_mps=5.0,
                        automation_level="L0",
                    )
                ],
                "collision_vehicle_ids": [],
            },
        )
    )
    viewmodel.handle_envelope(
        _envelope(
            "vehicle.delta",
            2,
            {
                "vehicles": [
                    _vehicle(
                        2,
                        vehicle_id="target_L0_001",
                        speed_mps=5.0,
                        automation_level="L0",
                    ),
                    _vehicle(
                        2,
                        vehicle_id="target_L1_002",
                        speed_mps=15.0,
                        automation_level="L1",
                    ),
                ],
                "collision_vehicle_ids": ["target_L0_001"],
            },
        )
    )
    viewmodel.handle_envelope(
        _envelope(
            "vehicle.delta",
            3,
            {
                "vehicles": [
                    _vehicle(
                        3,
                        vehicle_id="target_L1_002",
                        speed_mps=15.0,
                        automation_level="L1",
                    )
                ],
                "collision_vehicle_ids": ["target_L0_001"],
            },
        )
    )

    assert samples[-1] == LiveMetrics(
        current_vehicle_count=1,
        total_vehicle_count=2,
        average_speed_mps=15.0,
        average_travel_time_ms=100.0,
        level_average_speed_mps=(
            ("L0", 0.0),
            ("L1", 15.0),
            ("L2", 0.0),
            ("L3", 0.0),
            ("L4", 0.0),
            ("L5", 0.0),
        ),
        level_collision_counts=(
            ("L0", 1),
            ("L1", 0),
            ("L2", 0),
            ("L3", 0),
            ("L4", 0),
            ("L5", 0),
        ),
    )


def test_restart_stops_active_experiment_then_creates_and_launches_a_new_one() -> None:
    viewmodel, rest, realtime = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "maps.list",
        [
            {
                "map_id": "image2road",
                "kind": "sumo",
                "display_name": "图像识别路网",
                "validated": True,
                "network_schema_version": "sumo-net/display-1.0",
                "manifest_available": False,
                "sumo_config_file": "image2road.sumocfg",
                "sumo_step_ms": 1000,
            }
        ],
    )
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "RUNNING",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )

    viewmodel.restart()
    viewmodel.handle_envelope(_envelope("experiment.state.changed", 1, {"status": "COMPLETED"}))

    assert realtime.sent[-1] == ("experiment.stop", {"reason": "USER_RESTART"})
    assert realtime.closed is True
    assert rest.calls[-1] == ("create", (WORKSPACE_ID, SCENARIO_ID, "image2road"))

    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(RESTARTED_EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "CREATED",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )

    assert realtime.connected == RESTARTED_EXPERIMENT_ID
    assert realtime.sent[-1] == ("experiment.stop", {"reason": "USER_RESTART"})
    realtime.connection_changed.emit("CONNECTED")
    assert realtime.sent[-1] == ("experiment.prepare", {})


def test_restart_does_not_create_new_experiment_when_stop_command_cannot_be_sent() -> None:
    viewmodel, rest, realtime = _viewmodel()
    _enter_workspace(viewmodel)
    viewmodel.handle_rest_success(
        "experiment.create",
        {
            "experiment_id": str(EXPERIMENT_ID),
            "workspace_id": str(WORKSPACE_ID),
            "status": "RUNNING",
            "simulation_time_ms": 0,
            "speed_multiplier": 1.0,
        },
    )
    notifications: list[tuple[str, str]] = []
    viewmodel.notification.connect(lambda level, message: notifications.append((level, message)))
    realtime.raise_on_send = True

    viewmodel.restart()
    realtime.raise_on_send = False
    viewmodel.handle_envelope(_envelope("experiment.state.changed", 1, {"status": "COMPLETED"}))

    assert not [call for call in rest.calls if call[0] == "create"]
    assert notifications[-1] == (
        "error",
        "命令发送失败：realtime connection is unavailable",
    )
