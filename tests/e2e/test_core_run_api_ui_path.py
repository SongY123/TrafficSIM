from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from trafficverse.bootstrap import build_core_api

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = REPOSITORY_ROOT / "configs/scenarios/core-run-town04.yaml"


def _message(
    experiment_id: UUID,
    message_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "type": message_type,
        "message_id": str(uuid4()),
        "correlation_id": None,
        "experiment_id": str(experiment_id),
        "simulation_time_ms": 0,
        "sequence": 0,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


@pytest.mark.e2e
def test_native_core_runtime_reaches_ui_over_rest_and_websocket(tmp_path: Path) -> None:
    app = build_core_api(
        SCENARIO_PATH,
        repository_root=REPOSITORY_ROOT,
        artifact_root=tmp_path / "maps",
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": str(UUID(int=42)),
                "map_id": "town04-sumo-1.27.1-v2",
            },
        )
        assert created.status_code == 202
        experiment_id = UUID(created.json()["experiment_id"])
        prepared = client.post(f"/api/v1/experiments/{experiment_id}/prepare")
        assert prepared.json()["status"] == "READY"

        with client.websocket_connect(f"/api/v1/ws?experiment_id={experiment_id}") as websocket:
            assert websocket.receive_json()["type"] == "session.ready"
            websocket.send_json(
                _message(
                    experiment_id,
                    "subscribe",
                    {
                        "topics": ["vehicles", "traffic_lights", "health"],
                        "max_hz": 10,
                    },
                )
            )
            assert websocket.receive_json()["type"] == "command.accepted"
            websocket.send_json(_message(experiment_id, "experiment.start", {}))

            received_types = []
            vehicle_message = None
            for _ in range(8):
                message = websocket.receive_json()
                received_types.append(message["type"])
                if message["type"] == "vehicle.delta":
                    vehicle_message = message
                    break

            assert "command.accepted" in received_types
            assert "experiment.state.changed" in received_types
            assert vehicle_message is not None
            assert vehicle_message["sequence"] >= 1
            assert vehicle_message["payload"]["vehicles"][0]["vehicle_id"] == "vehicle-000"

            websocket.send_json(
                _message(
                    experiment_id,
                    "experiment.stop",
                    {"reason": "E2E_COMPLETE"},
                )
            )
            stop_messages = []
            for _ in range(6):
                message = websocket.receive_json()
                if message["type"] in {
                    "command.accepted",
                    "experiment.state.changed",
                }:
                    stop_messages.append(message)
                if len(stop_messages) == 2:
                    break
            assert [item["type"] for item in stop_messages] == [
                "command.accepted",
                "experiment.state.changed",
            ]
            assert stop_messages[1]["payload"]["status"] == "COMPLETED"
