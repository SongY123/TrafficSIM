from uuid import UUID

from trafficverse.controllers import MixedAutomationScenarioController
from trafficverse.domain.enums import (
    AutomationLevel,
    LaneChangeDirection,
    VehicleAction,
)
from trafficverse.domain.models import TrafficSnapshot, Vector3, VehicleState


def _vehicle(
    vehicle_id: str,
    *,
    x_m: float,
    lane_index: int = 1,
    speed_mps: float = 20.0,
) -> VehicleState:
    level_text = vehicle_id.split("_L", maxsplit=1)[1][0]
    return VehicleState(
        experiment_id=UUID(int=1),
        vehicle_id=vehicle_id,
        simulation_time_ms=8_000,
        sequence=1,
        automation_level=AutomationLevel(f"L{level_text}"),
        position=Vector3(x=x_m, y=lane_index * 3.5),
        speed_mps=speed_mps,
        acceleration_mps2=0.0,
        heading_rad=0.0,
        lane_id=f"road_fwd_{lane_index}",
        controller_id="sumo",
        action=VehicleAction.KEEP_LANE,
        risk_score=0.0,
    )


def _snapshot(*vehicles: VehicleState, time_ms: int = 8_000) -> TrafficSnapshot:
    return TrafficSnapshot(
        experiment_id=UUID(int=1),
        simulation_time_ms=time_ms,
        sequence=1,
        vehicles=vehicles,
    )


def test_obstacle_scene_keeps_l0_late_and_routes_l5_early() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-obstacle")
    l0 = _vehicle("target_L0_0", x_m=500.0, lane_index=0)
    l5 = _vehicle("target_L5_0", x_m=410.0, lane_index=0)

    commands = controller.step(_snapshot(l0, l5), 0.05)

    assert commands[l0.vehicle_id].desired_speed_mps == 16.0
    assert commands[l0.vehicle_id].safety_checks_override
    assert commands[l5.vehicle_id].lane_change is LaneChangeDirection.LEFT


def test_obstacle_scene_resumes_cruise_after_vehicle_reaches_clear_lane() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-obstacle")
    cleared = _vehicle("target_L2_0", x_m=540.0, lane_index=2, speed_mps=7.0)

    command = controller.step(_snapshot(cleared), 0.05)[cleared.vehicle_id]

    assert command.desired_speed_mps == 20.0


def test_obstacle_scene_scripts_a_descending_collision_target_count() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-obstacle")
    expected_unsafe_counts = (4, 3, 2, 1, 0, 0)

    for level, expected_count in enumerate(expected_unsafe_counts):
        vehicles = tuple(
            _vehicle(f"target_L{level}_{index}", x_m=500.0, lane_index=index % 2)
            for index in range(4)
        )
        commands = controller.step(_snapshot(*vehicles), 0.05)

        assert (
            sum(command.safety_checks_override for command in commands.values()) == expected_count
        )


def test_obstacle_scene_brakes_later_and_more_slowly_at_lower_levels() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-obstacle")
    expected_trigger_distance_m = (25.0, 35.0, 45.0, 50.0)
    expected_deceleration_mps2 = (-1.5, -2.2, -3.0, -4.0)

    for level, (trigger_distance_m, deceleration_mps2) in enumerate(
        zip(expected_trigger_distance_m, expected_deceleration_mps2, strict=True)
    ):
        before_trigger = _vehicle(
            f"target_L{level}_0",
            x_m=650.0 - trigger_distance_m - 1.0,
            lane_index=0,
        )
        braking = _vehicle(
            f"target_L{level}_0",
            x_m=650.0 - trigger_distance_m + 1.0,
            lane_index=1,
        )

        before_command = controller.step(_snapshot(before_trigger), 0.05)[before_trigger.vehicle_id]
        braking_command = controller.step(_snapshot(braking), 0.05)[braking.vehicle_id]

        assert before_command.desired_speed_mps == 16.0 + level * 2.0
        assert before_command.desired_acceleration_mps2 is None
        assert braking_command.desired_speed_mps is None
        assert braking_command.desired_acceleration_mps2 == deceleration_mps2


def test_obstacle_scene_brakes_for_a_stopped_collision_queue() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-obstacle")
    follower = _vehicle("target_L0_0", x_m=580.0, lane_index=0, speed_mps=16.0)
    stopped_leader = _vehicle("target_L1_0", x_m=609.0, lane_index=0, speed_mps=0.0)

    command = controller.step(_snapshot(follower, stopped_leader), 0.05)[follower.vehicle_id]

    assert command.desired_speed_mps is None
    assert command.desired_acceleration_mps2 == -1.5


def test_cutin_scene_gives_higher_levels_faster_controlled_gaps() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-cutin")
    l4_target = _vehicle("cutin_target_L4_0", x_m=500.0)
    l4_actor = _vehicle("cutin_actor_L4_0", x_m=540.0, lane_index=0)
    l5_target = _vehicle("cutin_target_L5_0", x_m=700.0)
    l5_actor = _vehicle("cutin_actor_L5_0", x_m=740.0, lane_index=0)

    commands = controller.step(
        _snapshot(l4_target, l4_actor, l5_target, l5_actor),
        0.05,
    )

    assert commands[l4_target.vehicle_id].desired_speed_mps == 22.0
    assert commands[l5_target.vehicle_id].desired_speed_mps == 24.0
    assert commands[l4_actor.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert commands[l5_actor.vehicle_id].lane_change is LaneChangeDirection.LEFT


def test_cutin_scene_uses_level_speeds_for_distributed_backgrounds() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-cutin")
    l0_background = _vehicle("cutin_target_L0_008", x_m=300.0, lane_index=2)
    l5_background = _vehicle("cutin_target_L5_008", x_m=700.0, lane_index=2)

    commands = controller.step(_snapshot(l0_background, l5_background), 0.05)

    assert commands[l0_background.vehicle_id].desired_speed_mps == 8.0
    assert commands[l5_background.vehicle_id].desired_speed_mps == 27.5
    assert not commands[l0_background.vehicle_id].safety_checks_override
    assert not commands[l5_background.vehicle_id].safety_checks_override


def test_cutin_scene_keeps_speed_ordered_background_safety_enabled() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-cutin")
    background = _vehicle("cutin_target_L3_006", x_m=500.0, lane_index=2)

    command = controller.step(_snapshot(background), 0.05)[background.vehicle_id]

    assert command.desired_speed_mps == 23.0
    assert not command.safety_checks_override


def test_cutin_scene_triggers_multiple_intruders_at_short_intervals() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-cutin")
    first_target = _vehicle("cutin_target_L0_000", x_m=500.0)
    first_actor = _vehicle("cutin_actor_L0_000", x_m=518.0, lane_index=0)
    next_target = _vehicle("cutin_target_L1_000", x_m=700.0)
    next_actor = _vehicle("cutin_actor_L1_000", x_m=718.0, lane_index=0)

    commands = controller.step(
        _snapshot(first_target, first_actor, next_target, next_actor, time_ms=5_700),
        0.05,
    )

    assert commands[first_actor.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert commands[next_actor.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert commands[first_target.vehicle_id].safety_checks_override


def test_cutin_scene_restores_pair_speed_after_event_window() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-cutin")
    target = _vehicle("cutin_target_L2_000", x_m=500.0, speed_mps=9.0)
    actor = _vehicle("cutin_actor_L2_000", x_m=520.0, lane_index=1, speed_mps=12.0)
    follower = _vehicle("cutin_follower_L0_000", x_m=480.0, speed_mps=10.0)

    commands = controller.step(_snapshot(target, actor, follower, time_ms=14_000), 0.05)

    assert commands[target.vehicle_id].desired_speed_mps == 22.0
    assert commands[actor.vehicle_id].desired_speed_mps == 22.0
    assert commands[follower.vehicle_id].desired_speed_mps == 22.0


def test_cutin_scene_hardcodes_descending_unsafe_pair_counts() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-cutin")
    vehicles = tuple(
        vehicle
        for level in range(6)
        for vehicle in (
            _vehicle(f"cutin_target_L{level}_003", x_m=500.0 + level * 100.0),
            _vehicle(
                f"cutin_actor_L{level}_003",
                x_m=513.0 + level * 100.0,
                lane_index=0,
            ),
        )
    )

    commands = controller.step(_snapshot(*vehicles, time_ms=11_000), 0.05)

    assert commands["cutin_actor_L0_003"].safety_checks_override
    assert not commands["cutin_actor_L4_003"].safety_checks_override
    assert not commands["cutin_actor_L5_003"].safety_checks_override


def test_emergency_scene_orders_l5_to_yield_before_lower_levels() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-emergency-yield")
    ambulance = _vehicle("ambulance_L5_0", x_m=50.0, speed_mps=28.0)
    l0 = _vehicle("yield_L0_0", x_m=200.0, speed_mps=10.0)
    l5 = _vehicle("yield_L5_0", x_m=220.0, speed_mps=10.0)

    commands = controller.step(_snapshot(ambulance, l0, l5), 0.05)

    assert commands[l0.vehicle_id].lane_change is LaneChangeDirection.NONE
    assert commands[l0.vehicle_id].desired_speed_mps == 10.0
    assert commands[l5.vehicle_id].lane_change is LaneChangeDirection.RIGHT
    assert commands[ambulance.vehicle_id].desired_speed_mps == 26.0


def test_emergency_scene_resumes_speed_after_ambulance_has_passed() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-emergency-yield")
    ambulance = _vehicle("ambulance_L5_0", x_m=400.0, speed_mps=28.0)
    passed_vehicle = _vehicle("yield_L2_0", x_m=250.0, lane_index=0, speed_mps=7.0)

    command = controller.step(_snapshot(ambulance, passed_vehicle), 0.05)[passed_vehicle.vehicle_id]

    assert command.desired_speed_mps == 16.0
    assert command.lane_change is LaneChangeDirection.LEFT


def test_emergency_scene_makes_l0_wait_until_ambulance_is_immediately_behind() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-emergency-yield")
    ambulance = _vehicle("ambulance_L5_0", x_m=100.0, speed_mps=28.0)
    l0_far = _vehicle("yield_L0_0", x_m=109.0, speed_mps=10.0)
    l0_close = _vehicle("yield_L0_1", x_m=107.5, speed_mps=10.0)
    l5 = _vehicle("yield_L5_0", x_m=290.0, speed_mps=25.0)

    commands = controller.step(_snapshot(ambulance, l0_far, l0_close, l5), 0.05)

    assert commands[l0_far.vehicle_id].lane_change is LaneChangeDirection.NONE
    assert commands[l0_close.vehicle_id].lane_change is LaneChangeDirection.RIGHT
    assert commands[l0_close.vehicle_id].lane_change_duration_s == 0.4
    assert commands[l5.vehicle_id].lane_change is LaneChangeDirection.RIGHT
    assert commands[ambulance.vehicle_id].desired_speed_mps == 8.0


def test_all_scenes_hold_vehicles_during_initial_layout() -> None:
    vehicles = (
        _vehicle("target_L2_0", x_m=200.0),
        _vehicle("cutin_target_L3_0", x_m=300.0),
        _vehicle("yield_L4_0", x_m=400.0),
        _vehicle("ambulance_L5_0", x_m=50.0),
    )

    obstacle = MixedAutomationScenarioController("mixed-automation-obstacle").step(
        _snapshot(vehicles[0], time_ms=1_000),
        0.05,
    )
    cutin = MixedAutomationScenarioController("mixed-automation-cutin").step(
        _snapshot(vehicles[1], time_ms=1_000),
        0.05,
    )
    emergency = MixedAutomationScenarioController("mixed-automation-emergency-yield").step(
        _snapshot(vehicles[2], vehicles[3], time_ms=1_000),
        0.05,
    )

    assert obstacle[vehicles[0].vehicle_id].desired_speed_mps == 0.0
    assert cutin[vehicles[1].vehicle_id].desired_speed_mps == 0.0
    assert emergency[vehicles[2].vehicle_id].desired_speed_mps == 0.0
    assert emergency[vehicles[3].vehicle_id].desired_speed_mps == 0.0
