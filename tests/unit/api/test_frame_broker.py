from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from trafficverse.adapters.messaging import FrameBroker, make_envelope
from trafficverse.domain.enums import AutomationLevel, VehicleAction
from trafficverse.domain.models import (
    CarlaFrame,
    SimulationFrame,
    TrafficLightState,
    TrafficSnapshot,
    Vector3,
    VehicleState,
)

EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000009")


def _frame(
    sequence: int,
    x: float,
    *,
    collision_vehicle_ids: tuple[str, ...] = (),
) -> SimulationFrame:
    vehicle = VehicleState(
        experiment_id=EXPERIMENT_ID,
        vehicle_id="vehicle-1",
        simulation_time_ms=sequence * 50,
        sequence=sequence,
        automation_level=AutomationLevel.HUMAN,
        position=Vector3(x=x, y=0.0),
        speed_mps=1.0,
        acceleration_mps2=0.0,
        heading_rad=0.0,
        lane_id="lane:1",
        controller_id="fixture",
        action=VehicleAction.KEEP_LANE,
        risk_score=0.0,
    )
    return SimulationFrame(
        traffic=TrafficSnapshot(
            experiment_id=EXPERIMENT_ID,
            simulation_time_ms=sequence * 50,
            sequence=sequence,
            vehicles=(vehicle,),
            traffic_lights=(
                TrafficLightState(
                    signal_id="signal:1",
                    simulation_time_ms=sequence * 50,
                    phase="RED",
                ),
            ),
            collision_vehicle_ids=collision_vehicle_ids,
        ),
        carla=CarlaFrame(
            simulation_time_ms=sequence * 50,
            carla_frame=sequence,
            actor_count=1,
        ),
    )


def test_slow_client_coalesces_vehicle_by_id() -> None:
    async def exercise() -> None:
        broker = FrameBroker()
        subscription = broker.subscribe(EXPERIMENT_ID)
        subscription.set_topics(frozenset({"vehicles"}), max_hz=10.0)

        await broker.publish_frame(_frame(1, 1.0))
        await broker.publish_frame(_frame(2, 2.0, collision_vehicle_ids=("target_L0_001",)))

        vehicle = await subscription.buffer.next()
        assert vehicle.type == "vehicle.delta"
        assert vehicle.sequence == 2
        vehicle_payload = cast("dict[str, JsonValue]", vehicle.payload)
        vehicles = cast("list[JsonValue]", vehicle_payload["vehicles"])
        first_vehicle = cast("dict[str, JsonValue]", vehicles[0])
        position = cast("dict[str, JsonValue]", first_vehicle["position"])
        assert position["x"] == 2.0
        assert vehicle_payload["collision_vehicle_ids"] == ["target_L0_001"]
        assert subscription.buffer.coalesced_vehicle_deltas == 1
        assert subscription.buffer.depth == 0

    asyncio.run(exercise())


def test_critical_overflow_disconnects_instead_of_growing_without_bound() -> None:
    broker = FrameBroker(critical_capacity=2)
    subscription = broker.subscribe(EXPERIMENT_ID)
    for index in range(3):
        subscription.offer(
            make_envelope(
                "event.created",
                EXPERIMENT_ID,
                simulation_time_ms=index,
                sequence=index,
                payload={"index": index},
            )
        )

    assert subscription.buffer.overflowed
    assert subscription.buffer.depth == 2


def test_snapshot_request_returns_latest_complete_frame() -> None:
    async def exercise() -> None:
        broker = FrameBroker()
        await broker.publish_frame(_frame(7, 7.0, collision_vehicle_ids=("target_L3_002",)))

        snapshot = broker.world_snapshot(EXPERIMENT_ID)

        assert snapshot is not None
        assert snapshot.type == "world.snapshot"
        assert snapshot.sequence == 7
        snapshot_payload = cast("dict[str, JsonValue]", snapshot.payload)
        traffic = cast("dict[str, JsonValue]", snapshot_payload["traffic"])
        assert traffic["sequence"] == 7
        assert traffic["collision_vehicle_ids"] == ["target_L3_002"]
        lights = cast("list[JsonValue]", traffic["traffic_lights"])
        first_light = cast("dict[str, JsonValue]", lights[0])
        assert first_light["simulation_time_ms"] == 350

    asyncio.run(exercise())
