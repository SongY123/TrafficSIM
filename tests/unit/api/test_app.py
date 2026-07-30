from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from trafficverse.adapters.messaging import FrameBroker
from trafficverse.api import ApiDependencies, RuntimeDirectory, create_app
from trafficverse.api.command_bus import ExperimentCommandBus
from trafficverse.api.map_catalog import MapCatalog
from trafficverse.api.models import ReadinessComponent
from trafficverse.domain.enums import (
    ComponentStatus,
    ErrorCode,
    ExperimentStatus,
)
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import ControlCommand, SimulationFrame

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAP_DIRECTORY = REPOSITORY_ROOT / "configs/maps/town04"


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
        )

    return ApiDependencies(runtimes, maps, commands, broker, readiness)


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


def test_map_import_endpoint_rejects_non_runnable_compiler_output(tmp_path: Path) -> None:
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
        assert completed.status == "FAILED"
        assert completed.map_id is None
        assert "map.sumocfg is missing" in completed.errors[0]

        status_response = client.get(f"/api/v1/maps/import/{job_id}")
        assert status_response.json()["status"] == "FAILED"


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
