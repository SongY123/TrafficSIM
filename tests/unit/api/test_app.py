from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from trafficverse.adapters.messaging import FrameBroker
from trafficverse.adapters.persistence import InMemoryWorkspaceRepository
from trafficverse.api import ApiDependencies, RuntimeDirectory, create_app
from trafficverse.api.command_bus import ExperimentCommandBus
from trafficverse.api.map_catalog import MapCatalog
from trafficverse.api.models import ReadinessComponent
from trafficverse.application.workspace_service import WorkspaceService
from trafficverse.bootstrap import build_core_api
from trafficverse.domain.enums import (
    ComponentStatus,
    ErrorCode,
    ExperimentStatus,
)
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import ControlCommand, SimulationFrame

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAP_DIRECTORY = REPOSITORY_ROOT / "configs/maps/town04"
SCENARIO_PATH = REPOSITORY_ROOT / "configs/scenarios/core-run-town04.yaml"


class FakeManager:
    def __init__(
        self, experiment_id: UUID, status: ExperimentStatus = ExperimentStatus.CREATED
    ) -> None:
        self._experiment_id = experiment_id
        self.status = status
        self.simulation_time_ms = 0
        self.speed_multiplier = 1.0
        self.last_frame: SimulationFrame | None = None
        self.controls: list[tuple[str, ControlCommand]] = []

    @property
    def experiment_id(self) -> UUID:
        return self._experiment_id

    async def prepare(self, experiment_id: UUID) -> None:
        assert experiment_id == self._experiment_id
        if self.status is not ExperimentStatus.CREATED:
            self._reject("prepare requires CREATED")
        self.status = ExperimentStatus.READY

    async def start(self) -> None:
        if self.status is not ExperimentStatus.READY:
            self._reject("start requires READY")
        self.status = ExperimentStatus.RUNNING

    async def pause(self) -> None:
        if self.status is not ExperimentStatus.RUNNING:
            self._reject("pause requires RUNNING")
        self.status = ExperimentStatus.PAUSED

    async def resume(self) -> None:
        if self.status is not ExperimentStatus.PAUSED:
            self._reject("resume requires PAUSED")
        self.status = ExperimentStatus.RUNNING

    async def stop(self, reason: str = "USER_REQUEST") -> None:
        del reason
        if self.status not in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED}:
            self._reject("stop requires RUNNING or PAUSED")
        self.status = ExperimentStatus.COMPLETED

    async def set_speed(self, multiplier: float) -> None:
        self.speed_multiplier = multiplier

    async def get_status(self) -> ExperimentStatus:
        return self.status

    async def control_vehicle(self, vehicle_id: str, command: ControlCommand) -> None:
        if self.status not in {ExperimentStatus.RUNNING, ExperimentStatus.PAUSED}:
            self._reject("vehicle control requires RUNNING or PAUSED")
        self.controls.append((vehicle_id, command))

    @staticmethod
    def _reject(message: str) -> None:
        raise TrafficVerseError(ErrorCode.INVALID_STATE_TRANSITION, message)


def _dependencies(
    tmp_path: Path,
    manager: FakeManager,
    *,
    ready: bool = True,
) -> ApiDependencies:
    runtimes = RuntimeDirectory()
    runtimes.register(manager.experiment_id, manager)
    broker = FrameBroker()
    maps = MapCatalog((MAP_DIRECTORY,), artifact_root=tmp_path / "maps")
    commands = ExperimentCommandBus(runtimes)

    async def readiness() -> tuple[ReadinessComponent, ...]:
        return (
            ReadinessComponent(
                component="traffic-engine",
                status=ComponentStatus.HEALTHY if ready else ComponentStatus.UNAVAILABLE,
                required=True,
            ),
            ReadinessComponent(
                component="carla",
                status=ComponentStatus.DISABLED,
                required=False,
            ),
        )

    return ApiDependencies(
        runtimes,
        maps,
        commands,
        broker,
        readiness,
        WorkspaceService(InMemoryWorkspaceRepository(initial=())),
    )


def _client_message(
    experiment_id: UUID,
    message_type: str,
    payload: dict[str, object],
    *,
    message_id: str,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "type": message_type,
        "message_id": message_id,
        "correlation_id": None,
        "experiment_id": str(experiment_id),
        "simulation_time_ms": 0,
        "sequence": 0,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def test_health_readiness_maps_and_unified_errors(tmp_path: Path) -> None:
    experiment_id = uuid4()
    dependencies = _dependencies(tmp_path, FakeManager(experiment_id))
    map_id = dependencies.maps.list_maps()[0].map_id

    with TestClient(create_app(dependencies)) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        assert client.get("/api/v1/ready").json()["ready"] is True
        assert client.get("/api/v1/maps").json()[0]["map_id"] == map_id
        network = client.get(f"/api/v1/maps/{map_id}/network")
        assert network.headers["content-type"].startswith("application/geo+json")
        assert network.json()["type"] == "FeatureCollection"
        assert client.get(f"/api/v1/maps/{map_id}/manifest").json()["validated"] is True

        missing = client.get("/api/v1/maps/missing/manifest")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
        invalid = client.get("/api/v1/experiments/not-a-uuid")
        assert invalid.status_code == 422
        assert invalid.json()["error"]["trace_id"]


def test_not_ready_returns_503(tmp_path: Path) -> None:
    dependencies = _dependencies(tmp_path, FakeManager(uuid4()), ready=False)
    with TestClient(create_app(dependencies)) as client:
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["ready"] is False


def test_workspace_search_create_rename_overview_and_delete(tmp_path: Path) -> None:
    dependencies = _dependencies(tmp_path, FakeManager(uuid4()))

    with TestClient(create_app(dependencies)) as client:
        created = client.post(
            "/api/v1/workspaces",
            json={"name": "北京测试区", "description": "用于 API 验证"},
        )
        assert created.status_code == 201
        workspace_id = created.json()["workspace_id"]

        searched = client.get("/api/v1/workspaces", params={"query": "北京"}).json()
        assert [item["workspace_id"] for item in searched] == [workspace_id]

        renamed = client.patch(
            f"/api/v1/workspaces/{workspace_id}",
            json={"name": "北京核心区", "description": "更新后"},
        )
        assert renamed.json()["name"] == "北京核心区"

        overview = client.get(f"/api/v1/workspaces/{workspace_id}/overview")
        assert overview.status_code == 200
        overview_payload = overview.json()
        assert overview_payload["workspace_id"] == workspace_id
        assert overview_payload["agent_count"] == 200
        assert overview_payload["scenario_count"] == 4
        assert overview_payload["simulation_count"] <= 34
        assert overview_payload["runtime_hours"] <= 12
        assert overview_payload["recent_simulations"]

        configured_agent = client.post(
            f"/api/v1/workspaces/{workspace_id}/agent-assets",
            json={
                "name": "城市驾驶智能体",
                "api_base_url": "https://agents.example.com/v1",
                "model_id": "urban-driver-v1",
                "credential_env_var": "TRAFFICVERSE_AGENT_API_KEY",
                "description": "通过远程 API 接入",
            },
        )
        assert configured_agent.status_code == 201
        agent_api_id = configured_agent.json()["agent_api_id"]
        agents = client.get(f"/api/v1/workspaces/{workspace_id}/agent-assets")
        assert [item["agent_api_id"] for item in agents.json()] == [agent_api_id]
        removed_agent = client.delete(
            f"/api/v1/workspaces/{workspace_id}/agent-assets/{agent_api_id}"
        )
        assert removed_agent.status_code == 204

        deleted = client.delete(f"/api/v1/workspaces/{workspace_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/workspaces/{workspace_id}/overview").status_code == 404
        invalid_experiment = client.post(
            "/api/v1/experiments",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "map_id": "image2road",
            },
        )
        assert invalid_experiment.status_code == 404


def test_core_api_discovers_image2road_as_directly_runnable_sumo_package(
    tmp_path: Path,
) -> None:
    app = build_core_api(
        SCENARIO_PATH,
        repository_root=REPOSITORY_ROOT,
        artifact_root=tmp_path / "maps",
        sumo_artifact_root=tmp_path / "sumo",
    )

    with TestClient(app) as client:
        summaries = {item["map_id"]: item for item in client.get("/api/v1/maps").json()}
        image2road = summaries["image2road"]
        assert image2road["kind"] == "sumo"
        assert image2road["sumo_step_ms"] == 1000
        assert image2road["manifest_available"] is False
        network = client.get("/api/v1/maps/image2road/network")
        assert network.status_code == 200
        assert network.json()["features"]

        created = client.post(
            "/api/v1/experiments",
            json={
                "workspace_id": client.get("/api/v1/workspaces").json()[0]["workspace_id"],
                "scenario_id": str(UUID(int=42)),
                "map_id": "image2road",
            },
        )
        assert created.status_code == 202
        assert created.json()["simulation_time_ms"] == 0


def test_configuration_api_saves_and_stages_test_run_from_generated_package(
    tmp_path: Path,
) -> None:
    configuration_root = tmp_path / "configs/configs"
    simulation_root = tmp_path / "artifacts/simulations"
    test_root = tmp_path / "artifacts/tests"
    app = build_core_api(
        SCENARIO_PATH,
        repository_root=REPOSITORY_ROOT,
        artifact_root=tmp_path / "maps",
        sumo_artifact_root=tmp_path / "sumo",
        configuration_root=configuration_root,
        simulation_artifact_root=simulation_root,
        test_artifact_root=test_root,
    )

    with TestClient(app) as client:
        workspace_id = client.get("/api/v1/workspaces").json()[0]["workspace_id"]
        saved = client.post(
            "/api/v1/simulation-configurations",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "scene_name": "API generated test",
                "description": "exact level counts",
                "map_id": "image2road",
                "duration_ms": 60_000,
                "automation_demands": [
                    {"level": "L0", "vehicle_count": 2},
                    {"level": "L4", "vehicle_count": 3},
                ],
            },
        )
        assert saved.status_code == 201
        configuration_id = saved.json()["configuration_id"]
        saved_directory = configuration_root / configuration_id
        assert (saved_directory / "configuration.json").is_file()

        created = client.post(
            "/api/v1/experiments",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "map_id": "image2road",
                "configuration_id": configuration_id,
                "run_kind": "test",
            },
        )

        assert created.status_code == 202
        run_directories = tuple(path for path in test_root.iterdir() if path.is_dir())
        assert len(run_directories) == 1
        run_directory = run_directories[0]
        assert (run_directory / "run.json").is_file()
        assert (run_directory / "image2road/image2road.sumocfg").is_file()
        assert not simulation_root.exists()


def test_formal_simulation_history_network_detail_and_export_api(tmp_path: Path) -> None:
    configuration_root = tmp_path / "configs/configs"
    simulation_root = tmp_path / "artifacts/simulations"
    app = build_core_api(
        SCENARIO_PATH,
        repository_root=REPOSITORY_ROOT,
        artifact_root=tmp_path / "maps",
        sumo_artifact_root=tmp_path / "sumo",
        configuration_root=configuration_root,
        simulation_artifact_root=simulation_root,
        test_artifact_root=tmp_path / "artifacts/tests",
    )

    with TestClient(app) as client:
        workspace_id = client.get("/api/v1/workspaces").json()[0]["workspace_id"]
        saved = client.post(
            "/api/v1/simulation-configurations",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "scene_name": "History API validation",
                "description": "formal run artifact",
                "map_id": "image2road",
                "duration_ms": 60_000,
                "automation_demands": [],
            },
        ).json()
        client.post(
            "/api/v1/experiments",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "map_id": "image2road",
                "configuration_id": saved["configuration_id"],
                "run_kind": "simulation",
            },
        )

        listed = client.get("/api/v1/simulations", params={"workspace_id": workspace_id})
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        run_id = listed.json()[0]["run_id"]
        assert listed.json()[0]["scene_name"] == "History API validation"
        assert listed.json()[0]["status"] == "CREATED"
        detail = client.get(f"/api/v1/simulations/{run_id}")
        network = client.get(f"/api/v1/simulations/{run_id}/network")
        exported = client.get(f"/api/v1/simulations/{run_id}/export")

        assert detail.status_code == 200
        assert len(detail.json()["metrics"]) == 7
        assert network.status_code == 200
        assert network.headers["content-type"].startswith("application/geo+json")
        assert network.json()["features"]
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        assert exported.content.startswith(b"PK")


def test_map_import_endpoint_publishes_compiled_geojson(tmp_path: Path) -> None:
    dependencies = _dependencies(tmp_path, FakeManager(uuid4()))
    source = MAP_DIRECTORY / "Town04.xodr"

    with TestClient(create_app(dependencies)) as client:
        wrong_extension = client.post(
            "/api/v1/maps/import",
            files={"file": ("Town04.xml", b"<OpenDRIVE/>", "application/xml")},
        )
        assert wrong_extension.status_code == 422
        assert wrong_extension.json()["error"]["code"] == "MAP_ASSET_INVALID"

        accepted = client.post(
            "/api/v1/maps/import",
            files={"file": ("Town04.xodr", source.read_bytes(), "application/xml")},
        )
        assert accepted.status_code == 202
        job_id = UUID(accepted.json()["job_id"])
        assert client.portal is not None
        completed = client.portal.call(dependencies.maps.wait_for_job, job_id)
        assert completed.status == "SUCCEEDED"
        assert completed.map_id is not None

        status_response = client.get(f"/api/v1/maps/import/{job_id}")
        assert status_response.json()["status"] == "SUCCEEDED"
        network = client.get(f"/api/v1/maps/{completed.map_id}/network")
        assert network.headers["content-type"].startswith("application/geo+json")
        assert network.json()["type"] == "FeatureCollection"


def test_rest_commands_use_serial_bus_and_return_stable_conflicts(tmp_path: Path) -> None:
    experiment_id = uuid4()
    manager = FakeManager(experiment_id)
    dependencies = _dependencies(tmp_path, manager)

    with TestClient(create_app(dependencies)) as client:
        conflict = client.post(f"/api/v1/experiments/{experiment_id}/start")
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

        assert (
            client.post(f"/api/v1/experiments/{experiment_id}/prepare").json()["status"] == "READY"
        )
        assert (
            client.post(f"/api/v1/experiments/{experiment_id}/start").json()["status"] == "RUNNING"
        )
        assert (
            client.post(f"/api/v1/experiments/{experiment_id}/pause").json()["status"] == "PAUSED"
        )
        speed = client.post(f"/api/v1/experiments/{experiment_id}/speed", json={"multiplier": 2.0})
        assert speed.json()["speed_multiplier"] == 2.0
        assert (
            client.post(f"/api/v1/experiments/{experiment_id}/resume").json()["status"] == "RUNNING"
        )
        stopped = client.post(
            f"/api/v1/experiments/{experiment_id}/stop",
            json={"reason": "TEST_COMPLETE"},
        )
        assert stopped.json()["status"] == "COMPLETED"


def test_websocket_correlation_rejection_and_state_change(tmp_path: Path) -> None:
    experiment_id = uuid4()
    manager = FakeManager(experiment_id)
    dependencies = _dependencies(tmp_path, manager)

    with (
        TestClient(create_app(dependencies)) as client,
        client.websocket_connect(f"/api/v1/ws?experiment_id={experiment_id}") as websocket,
    ):
        assert websocket.receive_json()["type"] == "session.ready"

        websocket.send_json(
            _client_message(
                experiment_id,
                "experiment.start",
                {},
                message_id="invalid-start",
            )
        )
        rejected = websocket.receive_json()
        assert rejected["type"] == "command.rejected"
        assert rejected["correlation_id"] == "invalid-start"

        websocket.send_json(
            _client_message(
                experiment_id,
                "experiment.prepare",
                {},
                message_id="prepare-1",
            )
        )
        accepted = websocket.receive_json()
        changed = websocket.receive_json()
        assert accepted["type"] == "command.accepted"
        assert accepted["correlation_id"] == "prepare-1"
        assert changed["type"] == "experiment.state.changed"
        assert changed["payload"]["status"] == "READY"


def test_websocket_subscribe_and_snapshot_recovery(tmp_path: Path) -> None:
    from tests.unit.api.test_frame_broker import EXPERIMENT_ID, _frame

    experiment_id = EXPERIMENT_ID
    dependencies = _dependencies(tmp_path, FakeManager(experiment_id))

    asyncio.run(dependencies.broker.publish_frame(_frame(4, 4.0)))
    with (
        TestClient(create_app(dependencies)) as client,
        client.websocket_connect(f"/api/v1/ws?experiment_id={experiment_id}") as websocket,
    ):
        websocket.receive_json()
        websocket.send_json(
            _client_message(
                experiment_id,
                "subscribe",
                {"topics": ["vehicles", "traffic_lights"], "max_hz": 10},
                message_id="subscribe-1",
            )
        )
        assert websocket.receive_json()["type"] == "command.accepted"
        snapshot = websocket.receive_json()
        assert snapshot["type"] == "world.snapshot"
        assert snapshot["sequence"] == 4

        websocket.send_json(
            _client_message(
                experiment_id,
                "world.snapshot.request",
                {},
                message_id="snapshot-1",
            )
        )
        assert websocket.receive_json()["type"] == "world.snapshot"


def test_websocket_health_vehicle_control_and_malformed_message_recovery(
    tmp_path: Path,
) -> None:
    experiment_id = uuid4()
    manager = FakeManager(experiment_id, status=ExperimentStatus.RUNNING)
    dependencies = _dependencies(tmp_path, manager)

    with (
        TestClient(create_app(dependencies)) as client,
        client.websocket_connect(f"/api/v1/ws?experiment_id={experiment_id}") as websocket,
    ):
        assert websocket.receive_json()["type"] == "session.ready"

        websocket.send_json({"not": "an envelope"})
        assert websocket.receive_json()["type"] == "error"

        websocket.send_json(
            _client_message(
                experiment_id,
                "subscribe",
                {"topics": ["health"], "max_hz": 10},
                message_id="subscribe-health",
            )
        )
        assert websocket.receive_json()["type"] == "command.accepted"
        health = websocket.receive_json()
        assert health["type"] == "component.health"
        assert health["payload"]["components"][0]["component"] == "traffic-engine"

        websocket.send_json(
            _client_message(
                experiment_id,
                "vehicle.control",
                {"vehicle_id": "vehicle-1", "desired_speed_mps": 8.0},
                message_id="control-1",
            )
        )
        accepted = websocket.receive_json()
        assert accepted["type"] == "command.accepted"
        assert accepted["correlation_id"] == "control-1"
        assert manager.controls[0][0] == "vehicle-1"
        assert manager.controls[0][1].desired_speed_mps == 8.0
