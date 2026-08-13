from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from trafficverse.bootstrap import build_core_api

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_PATH = REPOSITORY_ROOT / "configs/scenarios/core-run-town04.yaml"
SOURCE_OUTPUTS = REPOSITORY_ROOT / "configs/maps/image2road/outputs"

pytestmark = [pytest.mark.integration, pytest.mark.traffic]


def _message(
    experiment_id: UUID, message_type: str, payload: dict[str, object]
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


def _source_output_hashes() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(SOURCE_OUTPUTS.glob("*.xml"))
    }


@pytest.mark.skipif(
    os.getenv("TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION") != "1" or shutil.which("sumo") is None,
    reason="set TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION=1 with host SUMO available",
)
def test_image2road_runs_through_api_websocket_and_preserves_source_outputs(
    tmp_path: Path,
) -> None:
    source_hashes = _source_output_hashes()
    sumo_artifacts = tmp_path / "sumo"
    app = build_core_api(
        SCENARIO_PATH,
        repository_root=REPOSITORY_ROOT,
        artifact_root=tmp_path / "maps",
        sumo_artifact_root=sumo_artifacts,
    )

    with TestClient(app) as client:
        workspace_id = client.get("/api/v1/workspaces").json()[0]["workspace_id"]
        created = client.post(
            "/api/v1/experiments",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "map_id": "image2road",
            },
        )
        assert created.status_code == 202
        experiment_id = UUID(created.json()["experiment_id"])
        prepared = client.post(f"/api/v1/experiments/{experiment_id}/prepare")
        assert prepared.json()["status"] == "READY"
        readiness = client.get("/api/v1/ready").json()
        assert (
            next(item for item in readiness["components"] if item["component"] == "carla")["status"]
            == "DISABLED"
        )

        with client.websocket_connect(f"/api/v1/ws?experiment_id={experiment_id}") as websocket:
            assert websocket.receive_json()["type"] == "session.ready"
            websocket.send_json(
                _message(
                    experiment_id,
                    "subscribe",
                    {"topics": ["vehicles", "traffic_lights"], "max_hz": 10},
                )
            )
            assert websocket.receive_json()["type"] == "command.accepted"
            websocket.send_json(_message(experiment_id, "experiment.start", {}))
            messages = [websocket.receive_json() for _ in range(4)]
            vehicle_delta = next(item for item in messages if item["type"] == "vehicle.delta")
            traffic_light_delta = next(
                item for item in messages if item["type"] == "traffic_light.delta"
            )
            assert vehicle_delta["payload"]["vehicles"]
            assert traffic_light_delta["payload"]["traffic_lights"]
            websocket.send_json(
                _message(experiment_id, "experiment.stop", {"reason": "TEST_COMPLETE"})
            )

    staged_outputs = sumo_artifacts / str(experiment_id) / "package/image2road/outputs"
    assert staged_outputs.is_dir()
    assert tuple(staged_outputs.glob("*.xml"))
    assert _source_output_hashes() == source_hashes


@pytest.mark.skipif(
    os.getenv("TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION") != "1" or shutil.which("sumo") is None,
    reason="set TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION=1 with host SUMO available",
)
def test_occasional_accident_click_path_streams_lane_change_and_frozen_collisions(
    tmp_path: Path,
) -> None:
    app = build_core_api(
        SCENARIO_PATH,
        repository_root=REPOSITORY_ROOT,
        artifact_root=tmp_path / "maps",
        sumo_artifact_root=tmp_path / "sumo",
        configuration_root=tmp_path / "configs/configs",
        simulation_artifact_root=tmp_path / "artifacts/simulations",
        test_artifact_root=tmp_path / "artifacts/tests",
    )

    with TestClient(app) as client:
        workspace_id = client.get("/api/v1/workspaces").json()[0]["workspace_id"]
        saved = client.post(
            "/api/v1/simulation-configurations",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "scene_name": "偶发事故",
                "description": "固定事故台本",
                "map_id": "mixed-automation-occasional-accident",
                "duration_ms": 60_000,
                "automation_demands": [
                    {"level": "L0", "vehicle_count": 4},
                    {"level": "L1", "vehicle_count": 1},
                    {"level": "L3", "vehicle_count": 1},
                    {"level": "L5", "vehicle_count": 1},
                ],
            },
        )
        assert saved.status_code == 201
        created = client.post(
            "/api/v1/experiments",
            json={
                "workspace_id": workspace_id,
                "scenario_id": str(UUID(int=42)),
                "map_id": "mixed-automation-occasional-accident",
                "configuration_id": saved.json()["configuration_id"],
                "run_kind": "simulation",
            },
        )
        experiment_id = UUID(created.json()["experiment_id"])
        prepared = client.post(f"/api/v1/experiments/{experiment_id}/prepare")
        assert prepared.json()["status"] == "READY"

        actor_lane_ids: set[str] = set()
        collision_ids: set[str] = set()
        latest_vehicles: dict[str, dict[str, object]] = {}
        with client.websocket_connect(f"/api/v1/ws?experiment_id={experiment_id}") as websocket:
            assert websocket.receive_json()["type"] == "session.ready"
            websocket.send_json(
                _message(
                    experiment_id,
                    "subscribe",
                    {"topics": ["vehicles"], "max_hz": 20},
                )
            )
            assert websocket.receive_json()["type"] == "command.accepted"
            websocket.send_json(_message(experiment_id, "experiment.start", {}))
            websocket.send_json(
                _message(experiment_id, "experiment.speed.set", {"multiplier": 2.0})
            )
            for _ in range(500):
                message = websocket.receive_json()
                if message["type"] != "vehicle.delta":
                    continue
                payload = message["payload"]
                latest_vehicles = {
                    vehicle["vehicle_id"]: vehicle for vehicle in payload["vehicles"]
                }
                actor = latest_vehicles.get("accident_actor_L0_0")
                if actor is not None:
                    actor_lane_ids.add(str(actor["lane_id"]))
                collision_ids.update(payload["collision_vehicle_ids"])
                l5 = latest_vehicles.get("accident_follow_L5_0")
                if (
                    "accident_follow_L0_0" in collision_ids
                    and all(
                        float(latest_vehicles[vehicle_id]["speed_mps"]) < 0.5
                        for vehicle_id in collision_ids
                    )
                    and l5 is not None
                    and l5["lane_id"] == "right_exit_0"
                ):
                    break
            websocket.send_json(
                _message(experiment_id, "experiment.stop", {"reason": "TEST_COMPLETE"})
            )

    assert {"road_curve_0", "road_curve_1"} <= actor_lane_ids
    assert {
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
    } <= collision_ids
    assert all(
        float(latest_vehicles[vehicle_id]["speed_mps"]) < 0.5 for vehicle_id in collision_ids
    )
    assert latest_vehicles["accident_follow_L5_0"]["lane_id"] == "right_exit_0"
    assert "accident_follow_L1_0" not in collision_ids
    assert "accident_follow_L3_0" not in collision_ids
    assert "accident_follow_L5_0" not in collision_ids
