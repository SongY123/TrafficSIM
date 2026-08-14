from __future__ import annotations

import math
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest

from trafficverse.adapters.sumo import SumoTrafficEngineAdapter
from trafficverse.config.models import SumoConfig
from trafficverse.controllers import MixedAutomationScenarioController
from trafficverse.domain.enums import LaneChangeDirection
from trafficverse.domain.models import VehicleState
from trafficverse.maps.sumo_package import load_sumo_package, stage_sumo_package

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMAGE2ROAD_CONFIG = REPOSITORY_ROOT / "configs/maps/image2road/image2road.sumocfg"
ACCIDENT_CONFIG = (
    REPOSITORY_ROOT
    / "configs/maps/mixed-automation-occasional-accident"
    / "mixed-automation-occasional-accident.sumocfg"
)
LOW_LEVEL_MERGE_CONFIG = (
    REPOSITORY_ROOT
    / "configs/maps/mixed-automation-low-level-merge"
    / "mixed-automation-low-level-merge.sumocfg"
)
L5_MERGE_CONFIG = (
    REPOSITORY_ROOT / "configs/maps/mixed-automation-l5-merge" / "mixed-automation-l5-merge.sumocfg"
)

pytestmark = [pytest.mark.integration, pytest.mark.traffic]


@dataclass(frozen=True, slots=True)
class _DenseMergeResult:
    seen_vehicle_ids: frozenset[str] = field(repr=False)
    forward_arrived_vehicle_ids: frozenset[str] = field(repr=False)
    merged_ramp_vehicle_ids: frozenset[str] = field(repr=False)
    collision_vehicle_ids: frozenset[str] = field(repr=False)
    automation_levels: frozenset[int]
    forward_average_speed_mps: float
    main_lane_speed_ranges_mps: tuple[float, float, float]
    ramp_speed_range_mps: float
    merge_entry_streams: tuple[str, ...]
    first_inner_vehicle_passed_merge: bool
    first_inner_vehicle_recovered_speed: bool
    initial_inner_to_ramp_gap_m: float | None
    first_inner_pre_merge_speed_drop_mps: float
    ramp_crossing_max_speed_mps: float
    ramp_disturbance_crossing_max_speed_mps: float
    final_ramp_states: tuple[tuple[str, str, float, float], ...]
    lane_change_request_observed: bool
    lane_change_observed: bool
    cascade_slowdown_lane_indices: frozenset[int]
    ramp_seen_vehicle_ids: frozenset[str] = field(repr=False)
    opposing_seen_vehicle_ids: frozenset[str] = field(repr=False)
    peak_ramp_vehicle_count: int
    peak_main_before_vehicle_count: int
    ramp_last_new_vehicle_time_ms: int
    opposing_last_new_vehicle_time_ms: int
    opposing_source_first_positions_x_m: tuple[float, ...]
    opposing_source_refresh_batch_sizes: frozenset[int]
    initial_opposing_lane_counts: tuple[int, int, int]
    initial_opposing_position_spans_m: tuple[float, float, float]
    initial_opposing_lane_unique_speed_counts: tuple[int, int, int]
    minimum_moving_opposing_vehicle_count: int
    minimum_opposing_speed_mps: float
    ramp_zone_average_speeds_mps: tuple[float, float, float]
    ramp_recovered_speed_observed: bool
    phase_lane_average_speeds_mps: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    lane_change_request_times_ms: tuple[int, ...]
    d1_to_d2_request_vehicle_ids: frozenset[str]
    d2_to_d3_request_vehicle_ids: frozenset[str]
    d1_to_d2_observed_vehicle_ids: frozenset[str]
    d2_to_d3_observed_vehicle_ids: frozenset[str]
    lane_change_intermediate_pose_vehicle_ids: frozenset[str]
    lane_change_heading_vehicle_ids: frozenset[str]
    first_ramp_near_time_ms: int | None
    first_d1_slowdown_time_ms: int | None
    first_d1_slowdown_position_x_m: float | None
    ramp_merge_times_ms: tuple[tuple[str, int], ...]
    final_main_before_states: tuple[tuple[str, str, float, float], ...]
    ramp_free_flow_average_speed_mps: float
    pre_merge_peak_lane_vehicle_counts: tuple[int, int, int]
    phase_main_before_average_vehicle_counts: tuple[float, float, float]


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
    background_fast_ids = {
        "accident_background_L0_1",
        "accident_background_L1_1",
        "accident_background_L3_1",
        "accident_background_L3_2",
    }
    background_cruise_speed_mps = {
        vehicle_id: 16.0 if vehicle_id in background_fast_ids else 8.0
        for vehicle_id in background_straight_ids
    }
    background_l5_ids = {
        "accident_background_L5_0",
        "accident_background_L5_1",
        "accident_background_L5_2",
    }
    background_ids = background_straight_ids | background_l5_ids
    observed_background_ids: set[str] = set()
    background_initial_max_speed_mps = dict.fromkeys(background_ids, 0.0)
    background_running_max_speed_mps = dict.fromkeys(background_straight_ids, 0.0)
    background_minimum_acceleration_mps2 = dict.fromkeys(background_straight_ids, 0.0)
    background_straight_lane_ids: dict[str, set[str]] = {
        vehicle_id: set() for vehicle_id in background_straight_ids
    }
    background_lane_change_command_ids: set[str] = set()
    background_lane_change_command_lane_ids: dict[str, str] = {}
    background_lane_change_command_positions_x_m: dict[str, float] = {}
    background_stop_order: list[str] = []
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
        for target_time_ms in range(package.step_ms, 45_001, package.step_ms):
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
            background_lane_change_command_ids.update(
                vehicle_id
                for vehicle_id in background_straight_ids
                if (command := controls.get(vehicle_id)) is not None
                and command.lane_change is not LaneChangeDirection.NONE
            )
            if previous is not None:
                previous_by_id = {vehicle.vehicle_id: vehicle for vehicle in previous.vehicles}
                for vehicle_id in background_straight_ids:
                    command = controls.get(vehicle_id)
                    if (
                        command is not None
                        and command.lane_change is not LaneChangeDirection.NONE
                        and vehicle_id not in background_lane_change_command_lane_ids
                        and vehicle_id in previous_by_id
                    ):
                        background_lane_change_command_lane_ids[vehicle_id] = previous_by_id[
                            vehicle_id
                        ].lane_id
                        background_lane_change_command_positions_x_m[vehicle_id] = previous_by_id[
                            vehicle_id
                        ].position.x
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
                    background_running_max_speed_mps[vehicle.vehicle_id] = max(
                        background_running_max_speed_mps[vehicle.vehicle_id],
                        vehicle.speed_mps,
                    )
                    background_minimum_acceleration_mps2[vehicle.vehicle_id] = min(
                        background_minimum_acceleration_mps2[vehicle.vehicle_id],
                        vehicle.acceleration_mps2,
                    )
                    background_straight_lane_ids[vehicle.vehicle_id].add(vehicle.lane_id)
                    if (
                        first_collision_time_ms is not None
                        and vehicle.speed_mps < 0.5
                        and vehicle.vehicle_id not in background_stop_order
                    ):
                        background_stop_order.append(vehicle.vehicle_id)
                    if (
                        first_collision_time_ms is not None
                        and vehicle.speed_mps
                        == pytest.approx(
                            background_cruise_speed_mps[vehicle.vehicle_id],
                            abs=0.05,
                        )
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
    collision_midpoint_x_m = (
        vehicles["accident_actor_L0_0"].position.x + vehicles["accident_victim_L0_0"].position.x
    ) / 2.0
    collision_midpoint_y_m = (
        vehicles["accident_actor_L0_0"].position.y + vehicles["accident_victim_L0_0"].position.y
    ) / 2.0
    parked_to_collision_distance_m = math.hypot(
        vehicles["accident_parked_L0_0"].position.x - collision_midpoint_x_m,
        vehicles["accident_parked_L0_0"].position.y - collision_midpoint_y_m,
    )
    assert parked_to_collision_distance_m == pytest.approx(14.0, abs=0.75)
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
        background_running_max_speed_mps[vehicle_id]
        == pytest.approx(background_cruise_speed_mps[vehicle_id], abs=0.05)
        for vehicle_id in background_straight_ids
    )
    expected_background_deceleration_mps2 = {
        vehicle_id: -6.0 if vehicle_id in background_fast_ids else -1.5
        for vehicle_id in background_straight_ids
    }
    assert all(
        background_minimum_acceleration_mps2[vehicle_id]
        == pytest.approx(expected_background_deceleration_mps2[vehicle_id], abs=0.1)
        for vehicle_id in background_straight_ids
    )
    background_lane_0_ids = {
        "accident_background_L0_0",
        "accident_background_L1_0",
        "accident_background_L1_1",
        "accident_background_L3_2",
    }
    background_lane_1_ids = background_straight_ids - background_lane_0_ids
    expected_lane_change_ids = {
        "accident_background_L0_0",
        "accident_background_L1_0",
        "accident_background_L0_1",
        "accident_background_L3_1",
    }
    assert background_lane_change_command_ids == expected_lane_change_ids
    assert set(background_stop_order) == background_straight_ids
    original_front_stop_order = [
        vehicle_id
        for vehicle_id in background_stop_order
        if vehicle_id
        in {
            "accident_background_L0_0",
            "accident_background_L1_0",
            "accident_background_L3_0",
        }
    ]
    assert original_front_stop_order == [
        "accident_background_L0_0",
        "accident_background_L1_0",
        "accident_background_L3_0",
    ]
    for vehicle_id in ("accident_background_L0_1", "accident_background_L3_1"):
        lane_id = background_lane_change_command_lane_ids[vehicle_id]
        position_x_m = background_lane_change_command_positions_x_m[vehicle_id]
        assert lane_id == "road_curve_0" or (lane_id == "road_approach_0" and position_x_m >= 500.0)
    assert all(
        len(
            {
                lane_id.rsplit("_", maxsplit=1)[-1]
                for lane_id in background_straight_lane_ids[vehicle_id]
                if lane_id.rsplit("_", maxsplit=1)[-1] in {"0", "1"}
            }
        )
        == 2
        for vehicle_id in expected_lane_change_ids
    )
    assert all(
        vehicles[vehicle_id].lane_id == "road_curve_0" for vehicle_id in background_lane_0_ids
    )
    assert all(
        vehicles[vehicle_id].lane_id == "road_curve_1" for vehicle_id in background_lane_1_ids
    )
    queue_target_xy_m = {
        "accident_background_L0_0": (556.0, 145.56),
        "accident_background_L1_0": (549.0, 141.36),
        "accident_background_L3_0": (538.0, 138.84),
        "accident_background_L0_1": (531.0, 134.64),
        "accident_background_L1_1": (542.0, 137.16),
        "accident_background_L3_1": (524.0, 130.44),
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
            "accident_background_L0_0",
            "accident_background_L1_0",
            "accident_background_L1_1",
            "accident_background_L3_2",
        ),
        (
            "accident_follow_L3_0",
            "accident_background_L3_0",
            "accident_background_L0_1",
            "accident_background_L3_1",
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


def _run_dense_merge_scenario(
    config_file: Path,
    output_directory: Path,
    experiment_id: UUID,
) -> _DenseMergeResult:
    package = load_sumo_package(
        config_file,
        allowed_root=REPOSITORY_ROOT / "configs/maps",
    )
    staged_config = stage_sumo_package(package, output_directory / "package")
    adapter = SumoTrafficEngineAdapter(experiment_id)
    controller = MixedAutomationScenarioController(package.package_id)
    first_inner_vehicle_id = (
        "merge_main_L5_lane0.0"
        if package.package_id == "mixed-automation-l5-merge"
        else "merge_main_L0_lane0.0"
    )
    first_ramp_vehicle_id = (
        "merge_ramp_L5.0"
        if package.package_id == "mixed-automation-l5-merge"
        else "merge_ramp_L0.0"
    )
    previous = None
    seen_vehicle_ids: set[str] = set()
    arrived_vehicle_ids: set[str] = set()
    merged_ramp_vehicle_ids: set[str] = set()
    forward_speed_samples_mps: list[float] = []
    main_lane_speed_samples_mps: tuple[list[float], list[float], list[float]] = ([], [], [])
    first_inner_vehicle_passed_merge = False
    first_inner_vehicle_recovered_speed = False
    initial_inner_to_ramp_gap_m: float | None = None
    first_inner_pre_merge_speeds_mps: list[float] = []
    ramp_crossing_speeds_mps: list[float] = []
    ramp_disturbance_crossing_speeds_mps: list[float] = []
    lane_change_request_observed = False
    lane_change_observed = False
    cascade_slowdown_lane_indices: set[int] = set()
    ramp_seen_vehicle_ids: set[str] = set()
    opposing_seen_vehicle_ids: set[str] = set()
    opposing_source_first_position_x_by_vehicle_id: dict[str, float] = {}
    opposing_source_refresh_batch_sizes: set[int] = set()
    peak_ramp_vehicle_count = 0
    peak_main_before_vehicle_count = 0
    ramp_last_new_vehicle_time_ms = 0
    opposing_last_new_vehicle_time_ms = 0
    initial_opposing_lane_counts = (0, 0, 0)
    initial_opposing_position_spans_m = (0.0, 0.0, 0.0)
    initial_opposing_lane_unique_speed_counts = (0, 0, 0)
    minimum_moving_opposing_vehicle_count = 1_000_000
    minimum_opposing_speed_mps = float("inf")
    ramp_zone_speed_samples_mps: tuple[list[float], list[float], list[float]] = ([], [], [])
    ramp_recovered_speed_observed = False
    phase_lane_speed_samples_mps: tuple[
        tuple[list[float], list[float], list[float]],
        tuple[list[float], list[float], list[float]],
        tuple[list[float], list[float], list[float]],
    ] = (([], [], []), ([], [], []), ([], [], []))
    lane_change_request_times_ms: list[int] = []
    d1_to_d2_request_vehicle_ids: set[str] = set()
    d2_to_d3_request_vehicle_ids: set[str] = set()
    d1_to_d2_observed_vehicle_ids: set[str] = set()
    d2_to_d3_observed_vehicle_ids: set[str] = set()
    lane_change_request_metadata: dict[str, tuple[int, float, float]] = {}
    lane_change_pose_samples: dict[str, list[tuple[float, float]]] = {}
    first_ramp_near_time_ms: int | None = None
    first_d1_slowdown_time_ms: int | None = None
    first_d1_slowdown_position_x_m: float | None = None
    ramp_merge_time_by_vehicle_id: dict[str, int] = {}
    merge_entry_time_by_vehicle_id: dict[str, int] = {}
    ramp_speed_samples_mps: list[float] = []
    ramp_free_flow_speed_samples_mps: list[float] = []
    pre_merge_peak_lane_vehicle_counts = [0, 0, 0]
    phase_main_before_vehicle_count_samples: tuple[list[int], list[int], list[int]] = (
        [],
        [],
        [],
    )
    try:
        adapter.load(
            SumoConfig(
                launch_mode="managed",
                config_file=str(staged_config),
                step_ms=package.step_ms,
                begin_time_ms=package.begin_time_ms,
                expected_version=None,
                output_directory=str(output_directory / "sumo"),
                connect_retries=30,
            )
        )
        end_time_ms = package.end_time_ms or 20_000
        for target_time_ms in range(package.step_ms, end_time_ms + 1, package.step_ms):
            controls = controller.step(previous, package.step_ms / 1000.0)
            if package.package_id == "mixed-automation-low-level-merge" and previous is not None:
                vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in previous.vehicles}
                lane_change_request_observed = lane_change_request_observed or any(
                    command.lane_change is LaneChangeDirection.LEFT for command in controls.values()
                )
                for vehicle_id, command in controls.items():
                    vehicle = vehicles_by_id.get(vehicle_id)
                    if vehicle is not None and command.lane_change is LaneChangeDirection.LEFT:
                        lane_change_request_times_ms.append(previous.simulation_time_ms)
                        if vehicle.lane_id == "main_before_0":
                            d1_to_d2_request_vehicle_ids.add(vehicle_id)
                            target_y_m = 14.75
                        elif vehicle.lane_id == "main_before_1":
                            d2_to_d3_request_vehicle_ids.add(vehicle_id)
                            target_y_m = 18.25
                        else:
                            continue
                        lane_change_request_metadata.setdefault(
                            vehicle_id,
                            (previous.simulation_time_ms, vehicle.position.y, target_y_m),
                        )
                        lane_change_pose_samples.setdefault(vehicle_id, []).append(
                            (vehicle.position.y, vehicle.heading_rad)
                        )
                    if (
                        vehicle is None
                        or command.desired_acceleration_mps2 is None
                        or command.desired_acceleration_mps2 >= 0.0
                    ):
                        continue
                    if first_d1_slowdown_time_ms is None and vehicle.lane_id == "main_before_0":
                        first_d1_slowdown_time_ms = previous.simulation_time_ms
                        first_d1_slowdown_position_x_m = vehicle.position.x
                    lane_index_text = vehicle.lane_id.rsplit("_", maxsplit=1)[-1]
                    if lane_index_text in {"1", "2"}:
                        cascade_slowdown_lane_indices.add(int(lane_index_text))
            adapter.apply_controls(controls)
            previous = adapter.step(target_time_ms)
            arrived_vehicle_ids.update(adapter.diagnostics().arrived_vehicle_ids)
            vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in previous.vehicles}
            for vehicle_id, (
                request_time_ms,
                _source_y_m,
                _target_y_m,
            ) in lane_change_request_metadata.items():
                vehicle = vehicles_by_id.get(vehicle_id)
                if (
                    vehicle is not None
                    and target_time_ms <= request_time_ms + 1_500
                    and vehicle.lane_id.startswith("main_before_")
                ):
                    lane_change_pose_samples.setdefault(vehicle_id, []).append(
                        (vehicle.position.y, vehicle.heading_rad)
                    )
            current_ramp_vehicles = tuple(
                vehicle
                for vehicle in previous.vehicles
                if vehicle.vehicle_id.startswith("merge_ramp_")
            )
            new_ramp_vehicle_ids = {
                vehicle.vehicle_id for vehicle in current_ramp_vehicles
            } - ramp_seen_vehicle_ids
            if new_ramp_vehicle_ids:
                ramp_last_new_vehicle_time_ms = target_time_ms
                ramp_seen_vehicle_ids.update(new_ramp_vehicle_ids)
            current_opposing_vehicles = tuple(
                vehicle
                for vehicle in previous.vehicles
                if vehicle.vehicle_id.startswith("merge_opposing_")
            )
            new_opposing_vehicle_ids = {
                vehicle.vehicle_id for vehicle in current_opposing_vehicles
            } - opposing_seen_vehicle_ids
            if new_opposing_vehicle_ids:
                opposing_last_new_vehicle_time_ms = target_time_ms
                opposing_seen_vehicle_ids.update(new_opposing_vehicle_ids)
                new_source_vehicle_ids = {
                    vehicle_id
                    for vehicle_id in new_opposing_vehicle_ids
                    if int(vehicle_id.rsplit(".", maxsplit=1)[1]) < 100
                }
                if new_source_vehicle_ids:
                    opposing_source_refresh_batch_sizes.add(len(new_source_vehicle_ids))
                opposing_source_first_position_x_by_vehicle_id.update(
                    {
                        vehicle.vehicle_id: vehicle.position.x
                        for vehicle in current_opposing_vehicles
                        if vehicle.vehicle_id in new_opposing_vehicle_ids
                        and int(vehicle.vehicle_id.rsplit(".", maxsplit=1)[1]) < 100
                    }
                )
            minimum_moving_opposing_vehicle_count = min(
                minimum_moving_opposing_vehicle_count,
                sum(vehicle.speed_mps > 0.05 for vehicle in current_opposing_vehicles),
            )
            if current_opposing_vehicles:
                minimum_opposing_speed_mps = min(
                    minimum_opposing_speed_mps,
                    *(vehicle.speed_mps for vehicle in current_opposing_vehicles),
                )
            if target_time_ms == package.step_ms:
                initial_opposing_lane_vehicles = tuple(
                    tuple(
                        vehicle
                        for vehicle in current_opposing_vehicles
                        if vehicle.lane_id.endswith(f"_{lane_index}")
                        and int(vehicle.vehicle_id.rsplit(".", maxsplit=1)[1]) >= 100
                    )
                    for lane_index in range(3)
                )
                initial_opposing_lane_counts = (
                    len(initial_opposing_lane_vehicles[0]),
                    len(initial_opposing_lane_vehicles[1]),
                    len(initial_opposing_lane_vehicles[2]),
                )
                initial_opposing_spans_m = [
                    max(vehicle.position.x for vehicle in lane_vehicles)
                    - min(vehicle.position.x for vehicle in lane_vehicles)
                    if lane_vehicles
                    else 0.0
                    for lane_vehicles in initial_opposing_lane_vehicles
                ]
                initial_opposing_position_spans_m = (
                    initial_opposing_spans_m[0],
                    initial_opposing_spans_m[1],
                    initial_opposing_spans_m[2],
                )
                initial_opposing_lane_unique_speed_counts = (
                    len({vehicle.speed_mps for vehicle in initial_opposing_lane_vehicles[0]}),
                    len({vehicle.speed_mps for vehicle in initial_opposing_lane_vehicles[1]}),
                    len({vehicle.speed_mps for vehicle in initial_opposing_lane_vehicles[2]}),
                )
            peak_ramp_vehicle_count = max(peak_ramp_vehicle_count, len(current_ramp_vehicles))
            if first_ramp_near_time_ms is None and any(
                vehicle.lane_id == "merge_ramp_0" and vehicle.position.x >= 80.0
                for vehicle in current_ramp_vehicles
            ):
                first_ramp_near_time_ms = target_time_ms
            peak_main_before_vehicle_count = max(
                peak_main_before_vehicle_count,
                sum(
                    vehicle.lane_id.startswith("main_before_")
                    for vehicle in previous.vehicles
                    if vehicle.vehicle_id.startswith("merge_main_")
                ),
            )
            if package.package_id == "mixed-automation-low-level-merge":
                current_main_before_counts = [
                    sum(
                        vehicle.lane_id == f"main_before_{lane_index}"
                        for vehicle in previous.vehicles
                        if vehicle.vehicle_id.startswith("merge_main_")
                    )
                    for lane_index in range(3)
                ]
                if 8_000 <= target_time_ms < 10_000:
                    pre_merge_peak_lane_vehicle_counts = [
                        max(previous_peak, current_count)
                        for previous_peak, current_count in zip(
                            pre_merge_peak_lane_vehicle_counts,
                            current_main_before_counts,
                            strict=True,
                        )
                    ]
                if target_time_ms < 10_000:
                    density_phase_index = 0
                elif target_time_ms < 22_000:
                    density_phase_index = 1
                elif target_time_ms >= 27_000:
                    density_phase_index = 2
                else:
                    density_phase_index = None
                if density_phase_index is not None:
                    phase_main_before_vehicle_count_samples[density_phase_index].append(
                        sum(current_main_before_counts)
                    )
            first_inner = vehicles_by_id.get(first_inner_vehicle_id)
            first_ramp = vehicles_by_id.get(first_ramp_vehicle_id)
            if (
                initial_inner_to_ramp_gap_m is None
                and first_inner is not None
                and first_ramp is not None
            ):
                initial_inner_to_ramp_gap_m = abs(first_inner.position.x - first_ramp.position.x)
            if first_inner is not None and first_inner.lane_id.startswith("main_before_"):
                first_inner_pre_merge_speeds_mps.append(first_inner.speed_mps)
            for vehicle in previous.vehicles:
                seen_vehicle_ids.add(vehicle.vehicle_id)
                lane_change_observed = lane_change_observed or (
                    "_lane0." in vehicle.vehicle_id
                    and vehicle.lane_id in {"main_before_1", "main_after_1"}
                )
                if (
                    vehicle.vehicle_id.startswith("merge_main_")
                    and "_lane0." in vehicle.vehicle_id
                    and vehicle.lane_id
                    in {"main_before_1", "main_after_1", "main_before_2", "main_after_2"}
                ):
                    d1_to_d2_observed_vehicle_ids.add(vehicle.vehicle_id)
                if (
                    vehicle.vehicle_id.startswith("merge_main_")
                    and "_lane1." in vehicle.vehicle_id
                    and vehicle.lane_id in {"main_before_2", "main_after_2"}
                ):
                    d2_to_d3_observed_vehicle_ids.add(vehicle.vehicle_id)
                if vehicle.vehicle_id.startswith("merge_ramp_") and vehicle.lane_id.startswith(
                    ":merge"
                ):
                    ramp_crossing_speeds_mps.append(vehicle.speed_mps)
                    if target_time_ms < 22_000:
                        ramp_disturbance_crossing_speeds_mps.append(vehicle.speed_mps)
                if vehicle.vehicle_id.startswith("merge_ramp_"):
                    ramp_speed_samples_mps.append(vehicle.speed_mps)
                    if vehicle.lane_id == "merge_ramp_0":
                        if target_time_ms < 10_000 and vehicle.position.x < 80.0:
                            ramp_free_flow_speed_samples_mps.append(vehicle.speed_mps)
                        zone_index = (
                            0
                            if vehicle.position.x < 35.0
                            else 1
                            if vehicle.position.x < 70.0
                            else 2
                        )
                        ramp_zone_speed_samples_mps[zone_index].append(vehicle.speed_mps)
                    elif vehicle.lane_id == "main_after_0" and vehicle.speed_mps >= 10.0:
                        ramp_recovered_speed_observed = True
                if vehicle.vehicle_id == first_inner_vehicle_id and vehicle.lane_id.startswith(
                    "main_after_"
                ):
                    first_inner_vehicle_passed_merge = True
                    first_inner_vehicle_recovered_speed = (
                        first_inner_vehicle_recovered_speed or vehicle.speed_mps >= 12.0
                    )
                if (
                    vehicle.vehicle_id.startswith("merge_ramp_")
                    and vehicle.lane_id == "main_after_0"
                ):
                    merged_ramp_vehicle_ids.add(vehicle.vehicle_id)
                    ramp_merge_time_by_vehicle_id.setdefault(vehicle.vehicle_id, target_time_ms)
                if vehicle.lane_id == "main_after_0" and vehicle.vehicle_id.startswith(
                    ("merge_main_", "merge_ramp_")
                ):
                    merge_entry_time_by_vehicle_id.setdefault(vehicle.vehicle_id, target_time_ms)
                if target_time_ms < 5_000 or not vehicle.vehicle_id.startswith(
                    ("merge_main_", "merge_ramp_")
                ):
                    continue
                forward_speed_samples_mps.append(vehicle.speed_mps)
                if vehicle.vehicle_id.startswith("merge_main_") and vehicle.lane_id.startswith(
                    "main_"
                ):
                    lane_index = int(vehicle.lane_id.rsplit("_", maxsplit=1)[1])
                    main_lane_speed_samples_mps[lane_index].append(vehicle.speed_mps)
                    if (
                        vehicle.lane_id.startswith("main_before_")
                        and 40.0 <= vehicle.position.x <= 115.0
                    ):
                        if target_time_ms < 10_000:
                            phase_index = 0
                        elif target_time_ms < 22_000:
                            phase_index = 1
                        elif target_time_ms >= 27_000:
                            phase_index = 2
                        else:
                            continue
                        phase_lane_speed_samples_mps[phase_index][lane_index].append(
                            vehicle.speed_mps
                        )
    finally:
        adapter.close()

    assert previous is not None
    assert forward_speed_samples_mps
    assert all(main_lane_speed_samples_mps), tuple(
        len(samples) for samples in main_lane_speed_samples_mps
    )
    assert initial_inner_to_ramp_gap_m is not None
    assert first_inner_pre_merge_speeds_mps
    main_lane_speed_ranges_mps = tuple(
        max(samples) - min(samples) for samples in main_lane_speed_samples_mps
    )

    def phase_lane_average_speeds_mps(
        samples_by_lane: tuple[list[float], list[float], list[float]],
    ) -> tuple[float, float, float]:
        averages_mps = [
            sum(samples) / len(samples) if samples else 0.0 for samples in samples_by_lane
        ]
        return averages_mps[0], averages_mps[1], averages_mps[2]

    phase_main_before_average_vehicle_counts = [
        sum(samples) / len(samples) if samples else 0.0
        for samples in phase_main_before_vehicle_count_samples
    ]
    lane_change_intermediate_pose_vehicle_ids: set[str] = set()
    for vehicle_id, samples in lane_change_pose_samples.items():
        _request_time_ms, source_y_m, target_y_m = lane_change_request_metadata[vehicle_id]
        if any(
            min(source_y_m, target_y_m) + 0.1 < sample_y_m < max(source_y_m, target_y_m) - 0.1
            for sample_y_m, _heading_rad in samples
        ):
            lane_change_intermediate_pose_vehicle_ids.add(vehicle_id)
    lane_change_heading_vehicle_ids = {
        vehicle_id
        for vehicle_id, samples in lane_change_pose_samples.items()
        if any(abs(heading_rad) >= math.radians(1.0) for _sample_y_m, heading_rad in samples)
    }

    return _DenseMergeResult(
        seen_vehicle_ids=frozenset(seen_vehicle_ids),
        forward_arrived_vehicle_ids=frozenset(
            vehicle_id
            for vehicle_id in arrived_vehicle_ids
            if vehicle_id.startswith(("merge_main_", "merge_ramp_"))
        ),
        merged_ramp_vehicle_ids=frozenset(merged_ramp_vehicle_ids),
        collision_vehicle_ids=frozenset(previous.collision_vehicle_ids),
        automation_levels=frozenset(
            int(vehicle_id.partition("_L")[2].split("_", maxsplit=1)[0].split(".", maxsplit=1)[0])
            for vehicle_id in seen_vehicle_ids
        ),
        forward_average_speed_mps=sum(forward_speed_samples_mps) / len(forward_speed_samples_mps),
        main_lane_speed_ranges_mps=(
            main_lane_speed_ranges_mps[0],
            main_lane_speed_ranges_mps[1],
            main_lane_speed_ranges_mps[2],
        ),
        ramp_speed_range_mps=(
            max(ramp_speed_samples_mps) - min(ramp_speed_samples_mps)
            if ramp_speed_samples_mps
            else 0.0
        ),
        merge_entry_streams=tuple(
            "ramp" if vehicle_id.startswith("merge_ramp_") else "main"
            for vehicle_id, _time_ms in sorted(
                merge_entry_time_by_vehicle_id.items(),
                key=lambda item: (item[1], item[0]),
            )
        ),
        first_inner_vehicle_passed_merge=first_inner_vehicle_passed_merge,
        first_inner_vehicle_recovered_speed=first_inner_vehicle_recovered_speed,
        initial_inner_to_ramp_gap_m=initial_inner_to_ramp_gap_m,
        first_inner_pre_merge_speed_drop_mps=(
            max(first_inner_pre_merge_speeds_mps) - min(first_inner_pre_merge_speeds_mps)
        ),
        ramp_crossing_max_speed_mps=max(ramp_crossing_speeds_mps, default=0.0),
        ramp_disturbance_crossing_max_speed_mps=max(
            ramp_disturbance_crossing_speeds_mps,
            default=0.0,
        ),
        final_ramp_states=tuple(
            sorted(
                (
                    vehicle.vehicle_id,
                    vehicle.lane_id,
                    vehicle.position.x,
                    vehicle.speed_mps,
                )
                for vehicle in previous.vehicles
                if vehicle.vehicle_id.startswith("merge_ramp_")
            )
        ),
        lane_change_request_observed=lane_change_request_observed,
        lane_change_observed=lane_change_observed,
        cascade_slowdown_lane_indices=frozenset(cascade_slowdown_lane_indices),
        ramp_seen_vehicle_ids=frozenset(ramp_seen_vehicle_ids),
        opposing_seen_vehicle_ids=frozenset(opposing_seen_vehicle_ids),
        peak_ramp_vehicle_count=peak_ramp_vehicle_count,
        peak_main_before_vehicle_count=peak_main_before_vehicle_count,
        ramp_last_new_vehicle_time_ms=ramp_last_new_vehicle_time_ms,
        opposing_last_new_vehicle_time_ms=opposing_last_new_vehicle_time_ms,
        opposing_source_first_positions_x_m=tuple(
            opposing_source_first_position_x_by_vehicle_id.values()
        ),
        opposing_source_refresh_batch_sizes=frozenset(opposing_source_refresh_batch_sizes),
        initial_opposing_lane_counts=initial_opposing_lane_counts,
        initial_opposing_position_spans_m=initial_opposing_position_spans_m,
        initial_opposing_lane_unique_speed_counts=initial_opposing_lane_unique_speed_counts,
        minimum_moving_opposing_vehicle_count=minimum_moving_opposing_vehicle_count,
        minimum_opposing_speed_mps=minimum_opposing_speed_mps,
        ramp_zone_average_speeds_mps=(
            (
                sum(ramp_zone_speed_samples_mps[0]) / len(ramp_zone_speed_samples_mps[0])
                if ramp_zone_speed_samples_mps[0]
                else 0.0
            ),
            (
                sum(ramp_zone_speed_samples_mps[1]) / len(ramp_zone_speed_samples_mps[1])
                if ramp_zone_speed_samples_mps[1]
                else 0.0
            ),
            (
                sum(ramp_zone_speed_samples_mps[2]) / len(ramp_zone_speed_samples_mps[2])
                if ramp_zone_speed_samples_mps[2]
                else 0.0
            ),
        ),
        ramp_recovered_speed_observed=ramp_recovered_speed_observed,
        phase_lane_average_speeds_mps=(
            phase_lane_average_speeds_mps(phase_lane_speed_samples_mps[0]),
            phase_lane_average_speeds_mps(phase_lane_speed_samples_mps[1]),
            phase_lane_average_speeds_mps(phase_lane_speed_samples_mps[2]),
        ),
        lane_change_request_times_ms=tuple(lane_change_request_times_ms),
        d1_to_d2_request_vehicle_ids=frozenset(d1_to_d2_request_vehicle_ids),
        d2_to_d3_request_vehicle_ids=frozenset(d2_to_d3_request_vehicle_ids),
        d1_to_d2_observed_vehicle_ids=frozenset(d1_to_d2_observed_vehicle_ids),
        d2_to_d3_observed_vehicle_ids=frozenset(d2_to_d3_observed_vehicle_ids),
        lane_change_intermediate_pose_vehicle_ids=frozenset(
            lane_change_intermediate_pose_vehicle_ids
        ),
        lane_change_heading_vehicle_ids=frozenset(lane_change_heading_vehicle_ids),
        first_ramp_near_time_ms=first_ramp_near_time_ms,
        first_d1_slowdown_time_ms=first_d1_slowdown_time_ms,
        first_d1_slowdown_position_x_m=first_d1_slowdown_position_x_m,
        ramp_merge_times_ms=tuple(sorted(ramp_merge_time_by_vehicle_id.items())),
        final_main_before_states=tuple(
            sorted(
                (
                    vehicle.vehicle_id,
                    vehicle.lane_id,
                    vehicle.position.x,
                    vehicle.speed_mps,
                )
                for vehicle in previous.vehicles
                if vehicle.vehicle_id.startswith("merge_main_")
                and vehicle.lane_id.startswith("main_before_")
            )
        ),
        ramp_free_flow_average_speed_mps=(
            sum(ramp_free_flow_speed_samples_mps) / len(ramp_free_flow_speed_samples_mps)
            if ramp_free_flow_speed_samples_mps
            else 0.0
        ),
        pre_merge_peak_lane_vehicle_counts=(
            pre_merge_peak_lane_vehicle_counts[0],
            pre_merge_peak_lane_vehicle_counts[1],
            pre_merge_peak_lane_vehicle_counts[2],
        ),
        phase_main_before_average_vehicle_counts=(
            phase_main_before_average_vehicle_counts[0],
            phase_main_before_average_vehicle_counts[1],
            phase_main_before_average_vehicle_counts[2],
        ),
    )


@pytest.mark.skipif(
    os.getenv("TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION") != "1" or shutil.which("sumo") is None,
    reason="set TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION=1 with host SUMO available",
)
def test_dense_merge_scenarios_preserve_safe_distinct_merge_behaviors(
    tmp_path: Path,
) -> None:
    low_level = _run_dense_merge_scenario(
        LOW_LEVEL_MERGE_CONFIG,
        tmp_path / "low-level",
        UUID(int=3),
    )
    l5 = _run_dense_merge_scenario(
        L5_MERGE_CONFIG,
        tmp_path / "l5",
        UUID(int=4),
    )

    assert len(low_level.seen_vehicle_ids) == 155, (low_level, l5)
    assert len(l5.seen_vehicle_ids) == 131, (low_level, l5)
    assert not low_level.collision_vehicle_ids
    assert not l5.collision_vehicle_ids
    assert low_level.ramp_free_flow_average_speed_mps >= 12.0, (low_level, l5)
    assert low_level.peak_ramp_vehicle_count >= 13, (low_level, l5)
    assert len(low_level.ramp_seen_vehicle_ids) == 14, (low_level, l5)
    assert low_level.ramp_last_new_vehicle_time_ms >= 28_000, (low_level, l5)
    assert len(low_level.opposing_seen_vehicle_ids) == 99, (low_level, l5)
    assert low_level.opposing_last_new_vehicle_time_ms >= 28_300, (low_level, l5)
    assert low_level.opposing_source_first_positions_x_m
    assert min(low_level.opposing_source_first_positions_x_m) >= 318.0, (low_level, l5)
    assert max(low_level.opposing_source_first_positions_x_m) <= 320.0, (low_level, l5)
    assert low_level.opposing_source_refresh_batch_sizes == {1, 2, 3}, (low_level, l5)
    assert low_level.initial_opposing_lane_counts == (18, 18, 18), (low_level, l5)
    assert min(low_level.initial_opposing_position_spans_m) >= 300.0, (low_level, l5)
    assert low_level.initial_opposing_lane_unique_speed_counts == (18, 18, 18), (
        low_level,
        l5,
    )
    assert low_level.minimum_moving_opposing_vehicle_count >= 3, (low_level, l5)
    assert low_level.minimum_opposing_speed_mps > 0.5, (low_level, l5)
    assert min(low_level.pre_merge_peak_lane_vehicle_counts) >= 5, (low_level, l5)
    assert len(low_level.merged_ramp_vehicle_ids) >= 4, (low_level, l5)
    assert (
        sum(
            lane_id != "main_after_0"
            for _vehicle_id, lane_id, _position_x_m, _speed_mps in low_level.final_ramp_states
        )
        >= 8
    ), (low_level, l5)
    assert len(l5.ramp_seen_vehicle_ids) == 18, (low_level, l5)
    assert len(l5.merged_ramp_vehicle_ids) == 18, (
        low_level,
        l5,
    )

    stable_speeds_mps, disturbance_speeds_mps, recovery_speeds_mps = (
        low_level.phase_lane_average_speeds_mps
    )
    assert stable_speeds_mps[0] >= 9.0, (low_level, l5)
    assert min(stable_speeds_mps[1:]) >= 12.0, (low_level, l5)
    assert disturbance_speeds_mps[0] < disturbance_speeds_mps[1], (low_level, l5)
    assert disturbance_speeds_mps[1] < disturbance_speeds_mps[2], (low_level, l5)
    assert max(disturbance_speeds_mps) <= 10.0, (low_level, l5)
    assert 0.0 < low_level.ramp_disturbance_crossing_max_speed_mps <= 3.5, (low_level, l5)
    assert recovery_speeds_mps[0] > 1.5, (low_level, l5)
    assert all(
        recovered_speed_mps > disturbed_speed_mps
        for recovered_speed_mps, disturbed_speed_mps in zip(
            recovery_speeds_mps[1:],
            disturbance_speeds_mps[1:],
            strict=True,
        )
    ), (
        f"stable={stable_speeds_mps}, disturbance={disturbance_speeds_mps}, "
        f"recovery={recovery_speeds_mps}, merges={low_level.ramp_merge_times_ms}, "
        f"final={low_level.final_main_before_states}"
    )

    assert low_level.first_ramp_near_time_ms is not None
    assert 5_000 <= low_level.first_ramp_near_time_ms <= 6_000, (low_level, l5)
    assert low_level.first_d1_slowdown_time_ms is not None
    assert low_level.first_d1_slowdown_time_ms >= 10_000, (low_level, l5)
    assert low_level.first_d1_slowdown_time_ms >= low_level.first_ramp_near_time_ms, (
        low_level,
        l5,
    )
    assert low_level.first_d1_slowdown_position_x_m is not None
    assert 65.0 <= low_level.first_d1_slowdown_position_x_m <= 95.0, (low_level, l5)
    assert low_level.lane_change_request_times_ms, (low_level, l5)
    assert all(10_000 <= time_ms < 22_000 for time_ms in low_level.lane_change_request_times_ms)
    assert low_level.d2_to_d3_request_vehicle_ids, (low_level, l5)
    assert len(low_level.d2_to_d3_request_vehicle_ids) <= 1, (low_level, l5)
    assert len(low_level.d1_to_d2_request_vehicle_ids) >= len(
        low_level.d2_to_d3_request_vehicle_ids
    ), (low_level, l5)
    assert low_level.d1_to_d2_observed_vehicle_ids, (low_level, l5)
    assert low_level.d2_to_d3_observed_vehicle_ids, (low_level, l5)
    assert len(low_level.d1_to_d2_observed_vehicle_ids) >= len(
        low_level.d2_to_d3_observed_vehicle_ids
    ), (low_level, l5)
    requested_lane_change_vehicle_ids = (
        low_level.d1_to_d2_request_vehicle_ids | low_level.d2_to_d3_request_vehicle_ids
    )
    assert (
        requested_lane_change_vehicle_ids <= low_level.lane_change_intermediate_pose_vehicle_ids
    ), (low_level, l5)
    assert requested_lane_change_vehicle_ids <= low_level.lane_change_heading_vehicle_ids, (
        low_level,
        l5,
    )
    _stable_density, disturbance_density, recovery_density = (
        low_level.phase_main_before_average_vehicle_counts
    )
    assert recovery_density < disturbance_density * 0.7, (low_level, l5)
    assert l5.automation_levels == {3, 4, 5}, (low_level, l5)
    assert l5.peak_main_before_vehicle_count >= 25, (low_level, l5)
    assert l5.forward_average_speed_mps >= 14.5, (low_level, l5)
    assert max(l5.main_lane_speed_ranges_mps) <= 3.0, (low_level, l5)
    assert l5.ramp_speed_range_mps <= 1.0, (low_level, l5)
    assert not l5.lane_change_request_observed, (low_level, l5)
    assert not l5.lane_change_observed, (low_level, l5)
    assert not l5.d1_to_d2_observed_vehicle_ids, (low_level, l5)
    assert not l5.d2_to_d3_observed_vehicle_ids, (low_level, l5)
    first_l5_merge_entries = l5.merge_entry_streams[:24]
    assert first_l5_merge_entries.count("ramp") >= 10, (low_level, l5)
    assert not any(
        first == second == third
        for first, second, third in zip(
            first_l5_merge_entries,
            first_l5_merge_entries[1:],
            first_l5_merge_entries[2:],
            strict=False,
        )
    ), (low_level, l5)
