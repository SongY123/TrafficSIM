from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest

from trafficverse.adapters.messaging import ParquetReplayDataLogger
from trafficverse.adapters.persistence import FileSimulationHistoryStore
from trafficverse.domain.enums import AutomationLevel, VehicleAction
from trafficverse.domain.models import (
    SimulationFrame,
    TrafficLightState,
    TrafficSnapshot,
    Vector3,
    VehicleState,
)

RUN_ID = "2026-08-11-09-08-07"
EXPERIMENT_ID = UUID("30000000-0000-0000-0000-000000000003")


def _vehicle(sequence: int, time_ms: int, speed_mps: float) -> VehicleState:
    return VehicleState(
        experiment_id=EXPERIMENT_ID,
        vehicle_id="veh-1",
        simulation_time_ms=time_ms,
        sequence=sequence,
        automation_level=AutomationLevel.L3,
        position=Vector3(x=float(time_ms) / 100.0, y=2.0, z=0.0),
        speed_mps=speed_mps,
        acceleration_mps2=0.5,
        heading_rad=0.0,
        lane_id="edge-a_0",
        controller_id="controller-l3",
        action=VehicleAction.KEEP_LANE,
        risk_score=0.1,
        route_id="route-a",
    )


def _frame(sequence: int, time_ms: int, *, include_vehicle: bool) -> SimulationFrame:
    vehicles = (_vehicle(sequence, time_ms, float(sequence + 9)),) if include_vehicle else ()
    return SimulationFrame(
        traffic=TrafficSnapshot(
            experiment_id=EXPERIMENT_ID,
            simulation_time_ms=time_ms,
            sequence=sequence,
            vehicles=vehicles,
            traffic_lights=(
                TrafficLightState(
                    signal_id="signal-a",
                    simulation_time_ms=time_ms,
                    phase="G" if sequence < 3 else "r",
                    remaining_ms=5_000,
                ),
            ),
            collision_vehicle_ids=("veh-1",) if sequence == 2 else (),
        )
    )


def test_parquet_logger_reconstructs_snapshot_deltas_and_removals(tmp_path: Path) -> None:
    root = tmp_path / "artifacts/simulations"
    directory = root / RUN_ID
    logger = ParquetReplayDataLogger(
        directory,
        trajectory_hz=10,
        parquet_batch_rows=2,
        snapshot_interval_ms=10_000,
    )

    async def exercise() -> None:
        await logger.record_frame(_frame(1, 0, include_vehicle=True))
        await logger.record_frame(_frame(2, 1_000, include_vehicle=True))
        await logger.record_frame(_frame(3, 2_000, include_vehicle=False))
        await logger.flush()
        await logger.flush()

    asyncio.run(exercise())

    store = FileSimulationHistoryStore(root)
    first_page = store.get_replay(RUN_ID, from_time_ms=0, limit=2)
    second_page = store.get_replay(RUN_ID, from_time_ms=2_000, limit=2)

    assert [frame.simulation_time_ms for frame in first_page.frames] == [0, 1_000]
    assert first_page.next_time_ms == 2_000
    assert first_page.frames[0].vehicles[0].speed_mps == 10
    assert first_page.frames[1].vehicles[0].speed_mps == 11
    assert first_page.frames[1].collision_vehicle_ids == ("veh-1",)
    assert [frame.simulation_time_ms for frame in second_page.frames] == [2_000]
    assert second_page.frames[0].vehicles == ()
    assert second_page.frames[0].traffic_lights[0].phase == "r"
    assert second_page.next_time_ms is None
    assert (directory / "replay/manifest.json").is_file()


def test_parquet_logger_rejects_append_after_idempotent_flush(tmp_path: Path) -> None:
    logger = ParquetReplayDataLogger(
        tmp_path / RUN_ID,
        trajectory_hz=10,
        parquet_batch_rows=100,
        snapshot_interval_ms=10_000,
    )
    asyncio.run(logger.flush())

    with pytest.raises(RuntimeError, match="after the logger was flushed"):
        asyncio.run(logger.record_frame(_frame(1, 0, include_vehicle=True)))
