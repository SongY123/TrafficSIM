from __future__ import annotations

import math
import os
import shutil
from pathlib import Path
from uuid import UUID

import pytest

from trafficverse.adapters.sumo import SumoTrafficEngineAdapter
from trafficverse.config.models import SumoConfig
from trafficverse.controllers import MixedAutomationScenarioController
from trafficverse.domain.models import VehicleState
from trafficverse.maps.sumo_package import load_sumo_package, stage_sumo_package

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMAGE2ROAD_CONFIG = REPOSITORY_ROOT / "configs/maps/image2road/image2road.sumocfg"
ACCIDENT_CONFIG = (
    REPOSITORY_ROOT
    / "configs/maps/mixed-automation-occasional-accident"
    / "mixed-automation-occasional-accident.sumocfg"
)

pytestmark = [pytest.mark.integration, pytest.mark.traffic]


def _lateral_separation_m(first: VehicleState, second: VehicleState) -> float:
    delta_x_m = first.position.x - second.position.x
    delta_y_m = first.position.y - second.position.y
    return abs(-math.sin(second.heading_rad) * delta_x_m + math.cos(second.heading_rad) * delta_y_m)


def _longitudinal_separation_m(first: VehicleState, second: VehicleState) -> float:
    delta_x_m = first.position.x - second.position.x
    delta_y_m = first.position.y - second.position.y
    return abs(math.cos(second.heading_rad) * delta_x_m + math.sin(second.heading_rad) * delta_y_m)


def _body_gap_m(
    first: VehicleState,
    first_length_m: float,
    second: VehicleState,
    second_length_m: float,
) -> float:
    return _longitudinal_separation_m(first, second) - (first_length_m + second_length_m) / 2


@pytest.mark.skipif(
    os.getenv("TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION") != "1" or shutil.which("sumo") is None,
    reason="set TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION=1 with host SUMO available",
)
def test_image2road_managed_package_uses_host_sumo_and_cleans_up(tmp_path: Path) -> None:
    package = load_sumo_package(
        IMAGE2ROAD_CONFIG,
        allowed_root=REPOSITORY_ROOT / "configs/maps",
    )
    output_directory = tmp_path / "sumo"
    staged_config = stage_sumo_package(package, output_directory / "package")
    adapter = SumoTrafficEngineAdapter(UUID(int=1))
    try:
        adapter.load(
            SumoConfig(
                launch_mode="managed",
                config_file=str(staged_config),
                step_ms=package.step_ms,
                begin_time_ms=package.begin_time_ms,
                expected_version=None,
                output_directory=str(output_directory),
                connect_retries=30,
            )
        )

        snapshot = adapter.step(package.begin_time_ms + package.step_ms)

        assert snapshot.simulation_time_ms == 1000
        assert adapter.diagnostics().version is not None
        assert snapshot.vehicles
        assert snapshot.traffic_lights
        assert all(light.signal_id.startswith("sumo-tls:") for light in snapshot.traffic_lights)
    finally:
        adapter.close()

    assert not adapter.diagnostics().connected


@pytest.mark.skipif(
    os.getenv("TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION") != "1" or shutil.which("sumo") is None,
    reason="set TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION=1 with host SUMO available",
)
def test_occasional_accident_produces_real_collisions_and_level_responses(
    tmp_path: Path,
) -> None:
    package = load_sumo_package(
        ACCIDENT_CONFIG,
        allowed_root=REPOSITORY_ROOT / "configs/maps",
    )
    staged_config = stage_sumo_package(package, tmp_path / "package")
    adapter = SumoTrafficEngineAdapter(UUID(int=2))
    controller = MixedAutomationScenarioController(package.package_id)
    previous = None
    first_collision_vehicles = None
    first_collision_time_ms: int | None = None
    front_post_collision_speeds_mps: tuple[float, float] | None = None
    follower_collision_time_ms: int | None = None
    follower_post_collision_speed_mps: float | None = None
    actor_lane_ids: set[str] = set()
    parked_max_speed_mps = 0.0
    minimum_acceleration_mps2 = {"accident_follow_L1_0": 0.0, "accident_follow_L3_0": 0.0}
    l1_emergency_brake_time_ms: int | None = None
    l3_gentle_brake_time_ms: int | None = None
    all_front_vehicles_stopped_time_ms: int | None = None
    l5_right_turn_time_ms: int | None = None
    l5_right_turn_speed_mps: float | None = None
    l5_lower_lane_time_ms: int | None = None
    l5_lower_lane_position_x_m: float | None = None
    l5_lane_change_command_count = 0
    l5_lane_change_command_position_x_m: float | None = None
    initial_l5_lane_id: str | None = None
    l5_initial_max_speed_mps = 0.0
    l5_running_min_speed_mps = float("inf")
    l5_running_max_speed_mps = 0.0
    background_straight_ids = {
        "accident_background_L0_0",
        "accident_background_L0_1",
        "accident_background_L1_0",
        "accident_background_L1_1",
        "accident_background_L3_0",
        "accident_background_L3_1",
        "accident_background_L3_2",
    }
    background_l5_ids = {
        "accident_background_L5_0",
        "accident_background_L5_1",
        "accident_background_L5_2",
    }
    background_ids = background_straight_ids | background_l5_ids
    observed_background_ids: set[str] = set()
    background_initial_max_speed_mps = dict.fromkeys(background_ids, 0.0)
    background_minimum_acceleration_mps2 = dict.fromkeys(background_straight_ids, 0.0)
    background_straight_lane_ids = {vehicle_id: set() for vehicle_id in background_straight_ids}
    background_post_incident_cruise_ids: set[str] = set()
    background_l5_initial_lane_ids: dict[str, str] = {}
    background_l5_right_turn_ids: set[str] = set()
    background_l5_running_speed_range_mps = {
        vehicle_id: [float("inf"), 0.0] for vehicle_id in background_l5_ids
    }
    front_vehicle_ids = {
        "accident_parked_L0_0",
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
        "accident_follow_L1_0",
        "accident_follow_L3_0",
    }

    try:
        adapter.load(
            SumoConfig(
                launch_mode="managed",
                config_file=str(staged_config),
                step_ms=package.step_ms,
                begin_time_ms=package.begin_time_ms,
                expected_version=None,
                output_directory=str(tmp_path / "sumo"),
                connect_retries=30,
                freeze_collisions=True,
            )
        )
        for target_time_ms in range(package.step_ms, 35_001, package.step_ms):
            controls = controller.step(previous, package.step_ms / 1000.0)
            l5_command = controls.get("accident_follow_L5_0")
            if (
                l5_command is not None
                and l5_command.lane_change.value != "NONE"
                and previous is not None
            ):
                commanded_l5 = next(
                    vehicle
                    for vehicle in previous.vehicles
                    if vehicle.vehicle_id == "accident_follow_L5_0"
                )
                l5_lane_change_command_count += 1
                l5_lane_change_command_position_x_m = commanded_l5.position.x
            adapter.apply_controls(controls)
            previous = adapter.step(target_time_ms)
            vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in previous.vehicles}
            l5 = vehicles_by_id.get("accident_follow_L5_0")
            if l5 is not None:
                initial_l5_lane_id = initial_l5_lane_id or l5.lane_id
                if target_time_ms <= 3_000:
                    l5_initial_max_speed_mps = max(l5_initial_max_speed_mps, l5.speed_mps)
                else:
                    l5_running_min_speed_mps = min(l5_running_min_speed_mps, l5.speed_mps)
                    l5_running_max_speed_mps = max(l5_running_max_speed_mps, l5.speed_mps)
                if l5.lane_id == "road_approach_0":
                    l5_lower_lane_time_ms = l5_lower_lane_time_ms or target_time_ms
                    l5_lower_lane_position_x_m = l5_lower_lane_position_x_m or l5.position.x
            if l5 is not None and l5.lane_id == "right_exit_0":
                l5_right_turn_time_ms = l5_right_turn_time_ms or target_time_ms
                l5_right_turn_speed_mps = l5_right_turn_speed_mps or l5.speed_mps
            if (
                all_front_vehicles_stopped_time_ms is None
                and "accident_follow_L0_0" in previous.collision_vehicle_ids
                and front_vehicle_ids <= vehicles_by_id.keys()
                and all(
                    vehicles_by_id[vehicle_id].speed_mps < 0.5 for vehicle_id in front_vehicle_ids
                )
            ):
                all_front_vehicles_stopped_time_ms = target_time_ms
            actor = next(
                (
                    vehicle
                    for vehicle in previous.vehicles
                    if vehicle.vehicle_id == "accident_actor_L0_0"
                ),
                None,
            )
            if actor is not None:
                actor_lane_ids.add(actor.lane_id)
            for vehicle in previous.vehicles:
                if vehicle.vehicle_id in background_ids:
                    observed_background_ids.add(vehicle.vehicle_id)
                    if target_time_ms <= 3_000:
                        background_initial_max_speed_mps[vehicle.vehicle_id] = max(
                            background_initial_max_speed_mps[vehicle.vehicle_id],
                            vehicle.speed_mps,
                        )
                if vehicle.vehicle_id in background_straight_ids:
                    background_minimum_acceleration_mps2[vehicle.vehicle_id] = min(
                        background_minimum_acceleration_mps2[vehicle.vehicle_id],
                        vehicle.acceleration_mps2,
                    )
                    background_straight_lane_ids[vehicle.vehicle_id].add(vehicle.lane_id)
                    if (
                        first_collision_time_ms is not None
                        and vehicle.speed_mps == pytest.approx(8.0, abs=0.05)
                        and abs(vehicle.acceleration_mps2) <= 0.05
                    ):
                        background_post_incident_cruise_ids.add(vehicle.vehicle_id)
                if vehicle.vehicle_id in background_l5_ids:
                    background_l5_initial_lane_ids.setdefault(
                        vehicle.vehicle_id,
                        vehicle.lane_id,
                    )
                    if target_time_ms > 3_000:
                        speed_range_mps = background_l5_running_speed_range_mps[vehicle.vehicle_id]
                        speed_range_mps[0] = min(speed_range_mps[0], vehicle.speed_mps)
                        speed_range_mps[1] = max(speed_range_mps[1], vehicle.speed_mps)
                    if vehicle.lane_id == "right_exit_0":
                        background_l5_right_turn_ids.add(vehicle.vehicle_id)
                if vehicle.vehicle_id == "accident_parked_L0_0":
                    parked_max_speed_mps = max(parked_max_speed_mps, vehicle.speed_mps)
                if vehicle.vehicle_id in minimum_acceleration_mps2:
                    minimum_acceleration_mps2[vehicle.vehicle_id] = min(
                        minimum_acceleration_mps2[vehicle.vehicle_id],
                        vehicle.acceleration_mps2,
                    )
                if (
                    vehicle.vehicle_id == "accident_follow_L1_0"
                    and vehicle.acceleration_mps2 <= -7.5
                ):
                    l1_emergency_brake_time_ms = l1_emergency_brake_time_ms or target_time_ms
                if (
                    vehicle.vehicle_id == "accident_follow_L3_0"
                    and vehicle.acceleration_mps2 <= -1.5
                ):
                    l3_gentle_brake_time_ms = l3_gentle_brake_time_ms or target_time_ms
            if previous.collision_vehicle_ids and first_collision_time_ms is None:
                first_collision_time_ms = target_time_ms
                first_collision_vehicles = {
                    vehicle.vehicle_id: vehicle for vehicle in previous.vehicles
                }
            elif first_collision_time_ms is not None and front_post_collision_speeds_mps is None:
                vehicle_by_id = {vehicle.vehicle_id: vehicle for vehicle in previous.vehicles}
                front_post_collision_speeds_mps = (
                    vehicle_by_id["accident_actor_L0_0"].speed_mps,
                    vehicle_by_id["accident_victim_L0_0"].speed_mps,
                )
            if "accident_follow_L0_0" in previous.collision_vehicle_ids:
                if follower_collision_time_ms is None:
                    follower_collision_time_ms = target_time_ms
                elif follower_post_collision_speed_mps is None:
                    follower_post_collision_speed_mps = next(
                        vehicle.speed_mps
                        for vehicle in previous.vehicles
                        if vehicle.vehicle_id == "accident_follow_L0_0"
                    )
    finally:
        adapter.close()

    assert previous is not None
    collision_ids = set(previous.collision_vehicle_ids)
    assert collision_ids == {
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
    }
    assert first_collision_time_ms is not None
    assert front_post_collision_speeds_mps is not None
    assert max(front_post_collision_speeds_mps) < 0.5
    assert 4_000 <= first_collision_time_ms <= 10_000
    assert {"road_curve_0", "road_curve_1"} <= actor_lane_ids
    assert first_collision_vehicles is not None
    moving_follower_ids = {
        "accident_follow_L0_0",
        "accident_follow_L1_0",
        "accident_follow_L3_0",
        "accident_follow_L5_0",
    }
    assert all(
        first_collision_vehicles[vehicle_id].speed_mps > 3.0 for vehicle_id in moving_follower_ids
    )
    first_actor = first_collision_vehicles["accident_actor_L0_0"]
    first_victim = first_collision_vehicles["accident_victim_L0_0"]
    first_follow_l0 = first_collision_vehicles["accident_follow_L0_0"]
    first_l1 = first_collision_vehicles["accident_follow_L1_0"]
    first_l3 = first_collision_vehicles["accident_follow_L3_0"]
    first_lateral_separation_m = _lateral_separation_m(first_actor, first_victim)
    assert 0.8 <= first_lateral_separation_m <= 3.0, first_lateral_separation_m
    assert _body_gap_m(first_follow_l0, 4.55, first_l1, 5.0) > 0.0
    assert _body_gap_m(first_l1, 5.0, first_l3, 5.0) > 0.0
    assert follower_collision_time_ms is not None
    assert follower_collision_time_ms - first_collision_time_ms == pytest.approx(
        4_150 / 3,
        abs=100,
    )
    assert follower_post_collision_speed_mps is not None
    assert follower_post_collision_speed_mps < 0.5

    vehicles = {vehicle.vehicle_id: vehicle for vehicle in previous.vehicles}
    assert vehicles["accident_parked_L0_0"].speed_mps < 0.5
    assert parked_max_speed_mps < 0.5
    assert "accident_parked_L0_0" not in collision_ids
    assert "accident_follow_L1_0" not in collision_ids
    assert "accident_follow_L3_0" not in collision_ids
    assert "accident_follow_L5_0" not in collision_ids
    assert vehicles["accident_actor_L0_0"].speed_mps < 0.5
    assert vehicles["accident_victim_L0_0"].speed_mps < 0.5
    assert vehicles["accident_follow_L0_0"].speed_mps < 0.5
    final_lateral_separation_m = _lateral_separation_m(
        vehicles["accident_actor_L0_0"],
        vehicles["accident_victim_L0_0"],
    )
    assert 0.8 <= final_lateral_separation_m <= 2.0, final_lateral_separation_m
    assert (
        _longitudinal_separation_m(
            vehicles["accident_actor_L0_0"],
            vehicles["accident_victim_L0_0"],
        )
        <= 4.75
    )
    assert (
        _longitudinal_separation_m(
            vehicles["accident_follow_L0_0"],
            vehicles["accident_actor_L0_0"],
        )
        <= 4.75
    )
    assert vehicles["accident_follow_L1_0"].speed_mps < 0.5
    assert vehicles["accident_follow_L3_0"].speed_mps < 0.5
    assert vehicles["accident_follow_L1_0"].position.x > vehicles["accident_follow_L3_0"].position.x
    assert _body_gap_m(
        vehicles["accident_follow_L0_0"],
        4.55,
        vehicles["accident_follow_L1_0"],
        5.0,
    ) == pytest.approx(4.55, abs=1.5)
    assert _body_gap_m(
        vehicles["accident_follow_L1_0"],
        5.0,
        vehicles["accident_follow_L3_0"],
        5.0,
    ) == pytest.approx(4.55, abs=1.5)
    assert minimum_acceleration_mps2["accident_follow_L1_0"] <= -7.5
    assert -2.5 <= minimum_acceleration_mps2["accident_follow_L3_0"] <= -1.5
    assert l1_emergency_brake_time_ms is not None
    assert l3_gentle_brake_time_ms is not None
    assert l3_gentle_brake_time_ms > l1_emergency_brake_time_ms
    assert initial_l5_lane_id == "road_approach_1"
    assert l5_initial_max_speed_mps < 0.5
    assert l5_lower_lane_time_ms is not None
    assert l5_lower_lane_position_x_m is not None
    assert 470.0 <= l5_lower_lane_position_x_m < 510.0
    assert l5_lane_change_command_count == 1
    assert l5_lane_change_command_position_x_m is not None
    assert 475.0 <= l5_lane_change_command_position_x_m < 500.0
    assert first_collision_time_ms is not None
    assert all_front_vehicles_stopped_time_ms is not None
    assert l5_lower_lane_time_ms > first_collision_time_ms
    assert l5_right_turn_time_ms is not None
    assert l5_right_turn_speed_mps is not None
    assert l5_right_turn_time_ms > first_collision_time_ms
    assert l5_running_min_speed_mps == pytest.approx(12.0, abs=0.05)
    assert l5_running_max_speed_mps == pytest.approx(12.0, abs=0.05)
    assert l5_right_turn_speed_mps == pytest.approx(12.0, abs=0.05)
    assert observed_background_ids == background_ids
    assert max(background_initial_max_speed_mps.values()) < 0.5
    assert background_straight_ids <= vehicles.keys()
    assert all(vehicles[vehicle_id].speed_mps < 0.5 for vehicle_id in background_straight_ids), {
        vehicle_id: vehicles[vehicle_id].speed_mps for vehicle_id in background_straight_ids
    }
    assert background_post_incident_cruise_ids == background_straight_ids
    assert all(
        -1.6 <= acceleration_mps2 <= -1.4
        for acceleration_mps2 in background_minimum_acceleration_mps2.values()
    )
    background_lane_0_ids = {
        "accident_background_L0_1",
        "accident_background_L1_1",
        "accident_background_L3_1",
        "accident_background_L3_2",
    }
    background_lane_1_ids = background_straight_ids - background_lane_0_ids
    assert all(
        background_straight_lane_ids[vehicle_id] <= {"road_approach_0", ":turn_1_0", "road_curve_0"}
        for vehicle_id in background_lane_0_ids
    )
    assert all(
        background_straight_lane_ids[vehicle_id] <= {"road_approach_1", ":turn_1_1", "road_curve_1"}
        for vehicle_id in background_lane_1_ids
    )
    assert all(
        vehicles[vehicle_id].lane_id == "road_curve_0" for vehicle_id in background_lane_0_ids
    )
    assert all(
        vehicles[vehicle_id].lane_id == "road_curve_1" for vehicle_id in background_lane_1_ids
    )
    queue_target_xy_m = {
        "accident_background_L0_0": (538.0, 138.84),
        "accident_background_L1_0": (531.0, 134.64),
        "accident_background_L3_0": (524.0, 130.44),
        "accident_background_L0_1": (556.0, 145.56),
        "accident_background_L1_1": (549.0, 141.36),
        "accident_background_L3_1": (542.0, 137.16),
        "accident_background_L3_2": (535.0, 132.96),
    }
    queue_target_errors_m = {
        vehicle_id: math.hypot(
            vehicles[vehicle_id].position.x - target_xy_m[0],
            vehicles[vehicle_id].position.y - target_xy_m[1],
        )
        for vehicle_id, target_xy_m in queue_target_xy_m.items()
    }
    assert max(queue_target_errors_m.values()) <= 1.2, queue_target_errors_m
    vehicle_lengths_m = {
        "accident_follow_L3_0": 5.0,
        "accident_background_L0_0": 4.55,
        "accident_background_L0_1": 4.55,
        "accident_background_L1_0": 5.0,
        "accident_background_L1_1": 5.0,
        "accident_background_L3_0": 5.0,
        "accident_background_L3_1": 5.0,
        "accident_background_L3_2": 5.0,
    }
    queue_ids_by_lane = (
        (
            "accident_background_L0_1",
            "accident_background_L1_1",
            "accident_background_L3_1",
            "accident_background_L3_2",
        ),
        (
            "accident_follow_L3_0",
            "accident_background_L0_0",
            "accident_background_L1_0",
            "accident_background_L3_0",
        ),
    )
    queue_body_gaps_m = [
        _body_gap_m(
            vehicles[front_id],
            vehicle_lengths_m[front_id],
            vehicles[rear_id],
            vehicle_lengths_m[rear_id],
        )
        for queue_ids in queue_ids_by_lane
        for front_id, rear_id in zip(queue_ids, queue_ids[1:], strict=False)
    ]
    assert all(1.5 <= gap_m <= 5.5 for gap_m in queue_body_gaps_m), queue_body_gaps_m
    assert set(background_l5_initial_lane_ids.values()) == {"road_approach_0"}
    assert background_l5_right_turn_ids == background_l5_ids
    assert all(
        minimum_speed_mps == pytest.approx(12.0, abs=0.05)
        and maximum_speed_mps == pytest.approx(12.0, abs=0.05)
        for minimum_speed_mps, maximum_speed_mps in background_l5_running_speed_range_mps.values()
    )
