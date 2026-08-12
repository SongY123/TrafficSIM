from datetime import datetime, timezone
from uuid import UUID

import pytest
from ui.models import ControlAvailability, Envelope, ExperimentStatus, WorldState

EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000010")


def _envelope(message_type: str, sequence: int, payload: object) -> Envelope:
    return Envelope.model_validate(
        {
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
    )


def _vehicle(vehicle_id: str, x: float) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "experiment_id": str(EXPERIMENT_ID),
        "vehicle_id": vehicle_id,
        "simulation_time_ms": 50,
        "sequence": 1,
        "position": {"x": x, "y": 2.0, "z": 0.0},
        "speed_mps": 5.0,
        "acceleration_mps2": 0.0,
        "heading_rad": 0.5,
        "lane_id": "lane-1",
        "target_lane_id": None,
        "automation_level": "HUMAN",
        "controller_id": "fixture",
        "action": "KEEP_LANE",
        "risk_score": 0.0,
        "route_id": "route-1",
    }


def test_world_state_replaces_snapshot_and_detects_vehicle_sequence_gap() -> None:
    state = WorldState(EXPERIMENT_ID)
    snapshot = _envelope(
        "world.snapshot",
        4,
        {
            "traffic": {
                "vehicles": [_vehicle("vehicle-1", 1.0)],
                "traffic_lights": [
                    {
                        "signal_id": "signal-1",
                        "simulation_time_ms": 200,
                        "phase": "RED",
                        "remaining_ms": 500,
                    }
                ],
            },
            "carla": None,
            "events": [],
            "metrics": [],
        },
    )
    state.apply(snapshot)

    update = state.apply(_envelope("vehicle.delta", 6, {"vehicles": [_vehicle("vehicle-2", 6.0)]}))

    assert update.sequence_gap == (4, 6)
    assert list(state.vehicles) == ["vehicle-2"]
    assert state.traffic_lights["signal-1"].phase == "RED"


def test_world_state_keeps_cumulative_collision_vehicle_ids() -> None:
    state = WorldState(EXPERIMENT_ID)

    update = state.apply(
        _envelope(
            "vehicle.delta",
            1,
            {
                "vehicles": [_vehicle("target_L2_001", 1.0)],
                "collision_vehicle_ids": ["target_L2_001", "target_L0_003"],
            },
        )
    )

    assert update.collisions_changed
    assert state.collision_vehicle_ids == {"target_L2_001", "target_L0_003"}


def test_world_state_rejects_another_experiment() -> None:
    state = WorldState(UUID(int=1))
    with pytest.raises(ValueError, match="active experiment"):
        state.apply(_envelope("vehicle.delta", 1, {"vehicles": []}))


@pytest.mark.parametrize(
    ("status", "enabled"),
    [
        (ExperimentStatus.CREATED, "start"),
        (ExperimentStatus.READY, "start"),
        (ExperimentStatus.RUNNING, "pause"),
        (ExperimentStatus.PAUSED, "resume"),
    ],
)
def test_control_availability_follows_experiment_state(
    status: ExperimentStatus, enabled: str
) -> None:
    availability = ControlAvailability.for_status(status)
    assert getattr(availability, f"can_{enabled}") is True


@pytest.mark.parametrize(
    "status",
    [
        ExperimentStatus.RUNNING,
        ExperimentStatus.PAUSED,
        ExperimentStatus.COMPLETED,
        ExperimentStatus.FAILED,
    ],
)
def test_restart_is_available_for_active_or_finished_experiment(
    status: ExperimentStatus,
) -> None:
    assert ControlAvailability.for_status(status).can_restart is True


@pytest.mark.parametrize(
    "status",
    [
        ExperimentStatus.RUNNING,
        ExperimentStatus.PAUSED,
        ExperimentStatus.COMPLETED,
        ExperimentStatus.FAILED,
    ],
)
def test_configuration_can_replace_active_or_finished_experiment(
    status: ExperimentStatus,
) -> None:
    assert ControlAvailability.for_status(status).can_create is True
