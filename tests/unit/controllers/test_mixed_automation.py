from uuid import UUID

import pytest

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
    acceleration_mps2: float = 0.0,
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
        acceleration_mps2=acceleration_mps2,
        heading_rad=0.0,
        lane_id=f"road_fwd_{lane_index}",
        controller_id="sumo",
        action=VehicleAction.KEEP_LANE,
        risk_score=0.0,
    )


def _snapshot(
    *vehicles: VehicleState,
    time_ms: int = 8_000,
    collision_vehicle_ids: tuple[str, ...] = (),
) -> TrafficSnapshot:
    return TrafficSnapshot(
        experiment_id=UUID(int=1),
        simulation_time_ms=time_ms,
        sequence=1,
        vehicles=vehicles,
        collision_vehicle_ids=collision_vehicle_ids,
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
        _vehicle("accident_follow_L1_0", x_m=420.0),
        _vehicle("accident_follow_L5_0", x_m=370.0),
        _vehicle("accident_background_L0_0", x_m=340.0),
        _vehicle("accident_background_L5_0", x_m=320.0, lane_index=0),
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
    accident = MixedAutomationScenarioController("mixed-automation-occasional-accident").step(
        _snapshot(vehicles[4], vehicles[5], vehicles[6], vehicles[7], time_ms=1_000),
        0.05,
    )

    assert obstacle[vehicles[0].vehicle_id].desired_speed_mps == 0.0
    assert cutin[vehicles[1].vehicle_id].desired_speed_mps == 0.0
    assert emergency[vehicles[2].vehicle_id].desired_speed_mps == 0.0
    assert emergency[vehicles[3].vehicle_id].desired_speed_mps == 0.0
    assert accident[vehicles[4].vehicle_id].desired_speed_mps == 0.0
    assert accident[vehicles[5].vehicle_id].desired_speed_mps == 0.0
    assert accident[vehicles[6].vehicle_id].desired_speed_mps == 0.0
    assert accident[vehicles[7].vehicle_id].desired_speed_mps == 0.0


def test_occasional_accident_background_traffic_changes_lanes_after_incident_then_brakes() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    backgrounds = (
        _vehicle("accident_background_L0_0", x_m=500.0, lane_index=1, speed_mps=8.0),
        _vehicle("accident_background_L1_0", x_m=440.0, lane_index=1, speed_mps=8.0),
        _vehicle("accident_background_L3_0", x_m=425.0, lane_index=1, speed_mps=8.0),
        _vehicle("accident_background_L0_1", x_m=385.0, lane_index=0, speed_mps=8.0),
        _vehicle("accident_background_L1_1", x_m=370.0, lane_index=0, speed_mps=8.0),
        _vehicle("accident_background_L3_1", x_m=355.0, lane_index=0, speed_mps=8.0),
        _vehicle("accident_background_L3_2", x_m=340.0, lane_index=0, speed_mps=8.0),
    )

    cruising = controller.step(_snapshot(*backgrounds, time_ms=4_000), 0.05)
    near_targets = tuple(
        vehicle.model_copy(
            update={
                "lane_id": f"road_curve_{target_lane_index}",
                "position": Vector3(x=target_x_m - 6.0, y=target_y_m),
            }
        )
        for vehicle, (target_x_m, target_y_m, target_lane_index) in zip(
            backgrounds,
            (
                (556.0, 145.56, 0),
                (549.0, 141.36, 0),
                (538.0, 138.84, 1),
                (531.0, 134.64, 1),
                (542.0, 137.16, 0),
                (524.0, 130.44, 1),
                (535.0, 132.96, 0),
            ),
            strict=True,
        )
    )
    braking = controller.step(
        _snapshot(
            *near_targets,
            time_ms=9_000,
            collision_vehicle_ids=("accident_actor_L0_0", "accident_victim_L0_0"),
        ),
        0.05,
    )
    almost_stopped_l0 = near_targets[0].model_copy(
        update={"position": Vector3(x=556.0, y=145.56), "speed_mps": 0.04}
    )
    stopped = controller.step(
        _snapshot(
            almost_stopped_l0,
            time_ms=8_000,
            collision_vehicle_ids=("accident_actor_L0_0", "accident_victim_L0_0"),
        ),
        0.05,
    )

    assert all(command.desired_speed_mps == 8.0 for command in cruising.values())
    assert all(command.lane_change is LaneChangeDirection.NONE for command in cruising.values())
    assert all(command.desired_acceleration_mps2 == -1.5 for command in braking.values())
    assert all(command.lane_change is LaneChangeDirection.NONE for command in braking.values())
    assert stopped[almost_stopped_l0.vehicle_id].desired_speed_mps == 0.0


def test_occasional_accident_background_lane_changes_follow_queue_and_curve_triggers() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    collision_ids = ("accident_actor_L0_0", "accident_victim_L0_0")
    front_l3 = _vehicle(
        "accident_follow_L3_0",
        x_m=540.0,
        lane_index=1,
        speed_mps=0.0,
    )
    first_l0_far = _vehicle(
        "accident_background_L0_0",
        x_m=480.0,
        lane_index=1,
        speed_mps=8.0,
    )
    following_l1 = _vehicle(
        "accident_background_L1_0",
        x_m=440.0,
        lane_index=1,
        speed_mps=8.0,
    )
    staying_l3 = _vehicle(
        "accident_background_L3_0",
        x_m=425.0,
        lane_index=1,
        speed_mps=8.0,
    )
    later_l0 = _vehicle(
        "accident_background_L0_1",
        x_m=385.0,
        lane_index=0,
        speed_mps=8.0,
    )
    later_l3 = _vehicle(
        "accident_background_L3_1",
        x_m=355.0,
        lane_index=0,
        speed_mps=8.0,
    )

    before_triggers = controller.step(
        _snapshot(
            front_l3,
            first_l0_far,
            following_l1,
            staying_l3,
            later_l0,
            later_l3,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )
    first_l0_near = first_l0_far.model_copy(update={"position": Vector3(x=510.0, y=3.5)})
    first_l0_change = controller.step(
        _snapshot(
            front_l3,
            first_l0_near,
            following_l1,
            staying_l3,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )
    first_l0_in_target_lane = first_l0_near.model_copy(
        update={"lane_id": "road_curve_0", "position": Vector3(x=520.0, y=0.0)}
    )
    following_l1_near = following_l1.model_copy(
        update={"lane_id": "road_curve_1", "position": Vector3(x=490.0, y=3.5)}
    )
    following_l1_change = controller.step(
        _snapshot(
            front_l3,
            first_l0_in_target_lane,
            following_l1_near,
            staying_l3,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )
    later_l0_on_curve = later_l0.model_copy(
        update={"lane_id": "road_approach_0", "position": Vector3(x=500.0, y=0.0)}
    )
    later_l3_on_curve = later_l3.model_copy(update={"lane_id": "road_curve_0"})
    curve_changes = controller.step(
        _snapshot(
            later_l0_on_curve,
            later_l3_on_curve,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )

    assert all(
        command.lane_change is LaneChangeDirection.NONE for command in before_triggers.values()
    )
    assert first_l0_change[first_l0_near.vehicle_id].lane_change is LaneChangeDirection.RIGHT
    assert following_l1_change[following_l1_near.vehicle_id].lane_change is (
        LaneChangeDirection.RIGHT
    )
    assert following_l1_change[staying_l3.vehicle_id].lane_change is LaneChangeDirection.NONE
    assert curve_changes[later_l0_on_curve.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert curve_changes[later_l3_on_curve.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert all(
        command.lane_change_mode == 512
        for command in (
            first_l0_change[first_l0_near.vehicle_id],
            following_l1_change[following_l1_near.vehicle_id],
            curve_changes[later_l0_on_curve.vehicle_id],
            curve_changes[later_l3_on_curve.vehicle_id],
        )
    )


def test_occasional_accident_background_l5_keeps_constant_speed_on_right_turn_route() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    l5 = _vehicle(
        "accident_background_L5_0",
        x_m=490.0,
        lane_index=0,
        speed_mps=12.0,
    ).model_copy(update={"lane_id": "road_approach_0"})

    command = controller.step(
        _snapshot(
            l5,
            time_ms=5_000,
            collision_vehicle_ids=("accident_actor_L0_0", "accident_victim_L0_0"),
        ),
        0.05,
    )[l5.vehicle_id]

    assert command.desired_speed_mps == 12.0
    assert command.lane_change is LaneChangeDirection.NONE
    assert command.safety_checks_override


def test_occasional_accident_scripts_right_to_left_collision_then_stops_both_cars() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    parked = _vehicle("accident_parked_L0_0", x_m=595.0, lane_index=0, speed_mps=0.0)
    actor = _vehicle("accident_actor_L0_0", x_m=540.0, lane_index=0, speed_mps=14.0)
    victim = _vehicle("accident_victim_L0_0", x_m=555.0, lane_index=1, speed_mps=10.0)

    approaching = controller.step(_snapshot(parked, actor, victim, time_ms=5_000), 0.05)
    actor_near_parked = actor.model_copy(update={"position": Vector3(x=560.0, y=0.0)})
    moving = controller.step(_snapshot(parked, actor_near_parked, victim, time_ms=7_000), 0.05)
    collided_actor = actor_near_parked.model_copy(update={"lane_id": "road_1"})
    stopped = controller.step(
        _snapshot(
            parked,
            collided_actor,
            victim,
            time_ms=9_000,
            collision_vehicle_ids=(actor.vehicle_id, victim.vehicle_id),
        ),
        0.05,
    )

    assert approaching[parked.vehicle_id].desired_speed_mps == 0.0
    assert approaching[actor.vehicle_id].lane_change is LaneChangeDirection.NONE
    assert approaching[actor.vehicle_id].desired_speed_mps == 10.0
    assert moving[actor.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert moving[actor.vehicle_id].desired_speed_mps == 11.0
    assert moving[actor.vehicle_id].lane_change_duration_s == 2.0
    assert moving[actor.vehicle_id].safety_checks_override
    assert stopped[actor.vehicle_id].desired_speed_mps == 0.0
    assert stopped[actor.vehicle_id].lane_change is LaneChangeDirection.NONE
    assert stopped[victim.vehicle_id].desired_speed_mps == 0.0


def test_occasional_accident_keeps_followers_moving_until_the_front_collision_occurs() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    l0 = _vehicle("accident_follow_L0_0", x_m=510.0, lane_index=1)
    l1 = _vehicle("accident_follow_L1_0", x_m=520.0, lane_index=1)
    l3 = _vehicle("accident_follow_L3_0", x_m=480.0, lane_index=1)
    l5 = _vehicle("accident_follow_L5_0", x_m=400.0, lane_index=1)

    commands = controller.step(_snapshot(l0, l1, l3, l5, time_ms=8_000), 0.05)

    assert commands[l0.vehicle_id].desired_speed_mps == 16.0
    assert commands[l0.vehicle_id].safety_checks_override
    assert commands[l1.vehicle_id].desired_speed_mps == 12.0
    assert commands[l1.vehicle_id].safety_checks_override
    assert commands[l3.vehicle_id].desired_speed_mps == 8.0
    assert commands[l3.vehicle_id].safety_checks_override
    assert commands[l5.vehicle_id].desired_speed_mps == 12.0
    assert all(command.lane_change is LaneChangeDirection.NONE for command in commands.values())


def test_occasional_accident_opens_a_safe_gap_after_the_front_collision() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    l0 = _vehicle("accident_follow_L0_0", x_m=510.0, lane_index=1)
    l1 = _vehicle("accident_follow_L1_0", x_m=500.0, lane_index=1)
    l3 = _vehicle("accident_follow_L3_0", x_m=430.0, lane_index=1)
    l5 = _vehicle("accident_follow_L5_0", x_m=350.0, lane_index=0)

    commands = controller.step(
        _snapshot(
            l0,
            l1,
            l3,
            l5,
            time_ms=9_000,
            collision_vehicle_ids=("accident_actor_L0_0", "accident_victim_L0_0"),
        ),
        0.05,
    )
    decelerating_l1 = l1.model_copy(update={"speed_mps": 14.8, "acceleration_mps2": -8.0})
    coordinated_commands = controller.step(
        _snapshot(
            l0,
            decelerating_l1,
            l3,
            l5,
            time_ms=9_050,
            collision_vehicle_ids=("accident_actor_L0_0", "accident_victim_L0_0"),
        ),
        0.05,
    )

    assert commands[l0.vehicle_id].desired_speed_mps == 6.5
    assert commands[l1.vehicle_id].desired_acceleration_mps2 == -0.65
    assert commands[l1.vehicle_id].safety_checks_override
    assert commands[l3.vehicle_id].desired_speed_mps == 8.0
    assert commands[l3.vehicle_id].safety_checks_override
    assert commands[l5.vehicle_id].desired_speed_mps == 12.0
    assert commands[l5.vehicle_id].lane_change is LaneChangeDirection.NONE
    assert commands[l5.vehicle_id].safety_checks_override
    assert coordinated_commands[l3.vehicle_id].desired_acceleration_mps2 == -0.65


def test_occasional_accident_l5_changes_near_turn_after_incident_starts() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    l5 = _vehicle(
        "accident_follow_L5_0",
        x_m=410.0,
        lane_index=1,
        speed_mps=12.0,
    ).model_copy(update={"lane_id": "road_approach_1"})
    near_turn_l5 = l5.model_copy(update={"position": Vector3(x=480.0, y=0.0)})
    moving_l3 = _vehicle("accident_follow_L3_0", x_m=500.0, lane_index=1, speed_mps=3.0)
    stopped_l3 = moving_l3.model_copy(update={"speed_mps": 0.0})
    collision_ids = (
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
    )

    waiting = controller.step(
        _snapshot(
            l5,
            moving_l3,
            time_ms=6_000,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )[l5.vehicle_id]
    approaching_turn = controller.step(
        _snapshot(
            l5,
            stopped_l3,
            time_ms=15_000,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )[l5.vehicle_id]
    changing = controller.step(
        _snapshot(
            near_turn_l5,
            stopped_l3,
            time_ms=17_000,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )[l5.vehicle_id]
    continuing_change = controller.step(
        _snapshot(
            near_turn_l5,
            stopped_l3,
            time_ms=17_050,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )[l5.vehicle_id]
    lower_lane_l5 = near_turn_l5.model_copy(update={"lane_id": "road_approach_0"})
    changed = controller.step(
        _snapshot(
            lower_lane_l5,
            stopped_l3,
            time_ms=18_000,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )[l5.vehicle_id]

    assert waiting.lane_change is LaneChangeDirection.NONE
    assert waiting.desired_speed_mps == 12.0
    assert approaching_turn.lane_change is LaneChangeDirection.NONE
    assert approaching_turn.desired_speed_mps == 12.0
    assert changing.lane_change is LaneChangeDirection.RIGHT
    assert changing.lane_change_duration_s == 1.0
    assert changing.desired_speed_mps == 12.0
    assert continuing_change.lane_change is LaneChangeDirection.NONE
    assert continuing_change.desired_speed_mps == 12.0
    assert changed.desired_speed_mps == 12.0


def test_occasional_accident_l5_switches_directly_to_constant_cruise_speed() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    accelerating_l5 = _vehicle(
        "accident_follow_L5_0",
        x_m=430.0,
        lane_index=1,
        speed_mps=2.0,
    )
    cruising_l5 = accelerating_l5.model_copy(update={"speed_mps": 12.0})

    accelerating = controller.step(_snapshot(accelerating_l5, time_ms=3_500), 0.05)
    cruising = controller.step(_snapshot(cruising_l5, time_ms=4_000), 0.05)

    assert accelerating[accelerating_l5.vehicle_id].desired_speed_mps == 12.0
    assert accelerating[accelerating_l5.vehicle_id].safety_checks_override
    assert cruising[cruising_l5.vehicle_id].desired_speed_mps == 12.0
    assert cruising[cruising_l5.vehicle_id].safety_checks_override


def test_occasional_accident_stages_l1_emergency_brake_before_l3_gentle_brake() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    collided_l0 = _vehicle("accident_follow_L0_0", x_m=560.0, lane_index=1, speed_mps=0.0)
    l1 = _vehicle("accident_follow_L1_0", x_m=540.0, lane_index=1, speed_mps=15.2)
    l3 = _vehicle("accident_follow_L3_0", x_m=508.0, lane_index=1, speed_mps=13.0)
    collision_ids = (
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
    )

    immediate = controller.step(
        _snapshot(
            collided_l0,
            l1,
            l3,
            time_ms=9_000,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )
    braking_l1 = l1.model_copy(update={"speed_mps": 14.8, "acceleration_mps2": -8.0})
    delayed = controller.step(
        _snapshot(
            collided_l0,
            braking_l1,
            l3,
            time_ms=9_050,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )
    stopped_l1 = braking_l1.model_copy(update={"speed_mps": 0.0, "acceleration_mps2": 0.0})
    sustained = controller.step(
        _snapshot(
            collided_l0,
            stopped_l1,
            l3,
            time_ms=9_100,
            collision_vehicle_ids=collision_ids,
        ),
        0.05,
    )

    assert immediate[l1.vehicle_id].desired_acceleration_mps2 == -8.0
    assert immediate[l1.vehicle_id].safety_checks_override
    assert immediate[l3.vehicle_id].desired_speed_mps == 8.0
    assert delayed[l3.vehicle_id].desired_acceleration_mps2 == -1.75
    assert delayed[l3.vehicle_id].takeover_requested
    assert delayed[l3.vehicle_id].safety_checks_override
    assert sustained[l3.vehicle_id].desired_acceleration_mps2 == -1.75


def test_occasional_accident_l1_brakes_when_the_second_impact_is_imminent() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    actor = _vehicle("accident_actor_L0_0", x_m=580.0, lane_index=1, speed_mps=0.0)
    victim = _vehicle("accident_victim_L0_0", x_m=582.0, lane_index=1, speed_mps=0.0)
    approaching_l0 = _vehicle("accident_follow_L0_0", x_m=573.5, lane_index=1)
    l1 = _vehicle("accident_follow_L1_0", x_m=550.0, lane_index=1, speed_mps=15.2)

    commands = controller.step(
        _snapshot(
            actor,
            victim,
            approaching_l0,
            l1,
            time_ms=8_000,
            collision_vehicle_ids=(actor.vehicle_id, victim.vehicle_id),
        ),
        0.05,
    )

    assert commands[l1.vehicle_id].desired_acceleration_mps2 == -8.0
    assert commands[l1.vehicle_id].takeover_requested


def test_occasional_accident_stops_l0_after_it_reaches_the_pileup() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-occasional-accident")
    follower = _vehicle("accident_follow_L0_0", x_m=550.0, lane_index=1)

    command = controller.step(
        _snapshot(
            follower,
            time_ms=12_000,
            collision_vehicle_ids=("accident_follow_L0_0",),
        ),
        0.05,
    )[follower.vehicle_id]

    assert command.desired_speed_mps == 0.0
    assert command.safety_checks_override


def test_low_level_merge_keeps_all_streams_stable_before_ten_seconds() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=84.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    d2 = _vehicle("merge_main_L1_lane1.0", x_m=76.0, lane_index=1, speed_mps=15.1).model_copy(
        update={"lane_id": "main_before_1"}
    )
    d3 = _vehicle("merge_main_L2_lane2.0", x_m=68.0, lane_index=2, speed_mps=15.4).model_copy(
        update={"lane_id": "main_before_2"}
    )
    ramp = _vehicle("merge_ramp_L3.0", x_m=70.0, lane_index=0, speed_mps=14.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(d1, d2, d3, ramp, time_ms=9_950), 0.05)

    assert commands[d1.vehicle_id].desired_speed_mps == pytest.approx(14.8)
    assert commands[d2.vehicle_id].desired_speed_mps == pytest.approx(15.1)
    assert commands[d3.vehicle_id].desired_speed_mps == pytest.approx(15.4)
    assert commands[ramp.vehicle_id].desired_speed_mps == pytest.approx(14.0)
    assert all(command.desired_acceleration_mps2 is None for command in commands.values())
    assert all(command.lane_change is LaneChangeDirection.NONE for command in commands.values())


def test_low_level_merge_slows_a_near_ramp_vehicle_before_d1_reacts() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    ramp = _vehicle("merge_ramp_L3.0", x_m=82.0, lane_index=0, speed_mps=14.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(d1, ramp, time_ms=9_950), 0.05)

    assert commands[d1.vehicle_id].desired_speed_mps == pytest.approx(14.8)
    assert commands[ramp.vehicle_id].desired_acceleration_mps2 == pytest.approx(-4.5)


def test_low_level_merge_does_not_react_to_a_distant_ramp_vehicle_after_ten_seconds() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=70.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    ramp = _vehicle("merge_ramp_L3.0", x_m=70.0, lane_index=0, speed_mps=14.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(d1, ramp, time_ms=15_000), 0.05)

    assert commands[d1.vehicle_id].desired_speed_mps == pytest.approx(14.8)
    assert commands[ramp.vehicle_id].desired_speed_mps == pytest.approx(14.0)
    assert all(command.lane_change is LaneChangeDirection.NONE for command in commands.values())


def test_low_level_merge_does_not_slow_d1_without_an_arriving_ramp_vehicle() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    d2 = _vehicle("merge_main_L1_lane1.0", x_m=76.0, lane_index=1, speed_mps=15.1).model_copy(
        update={"lane_id": "main_before_1"}
    )

    commands = controller.step(_snapshot(d1, d2, time_ms=15_000), 0.05)

    assert commands[d1.vehicle_id].desired_speed_mps == pytest.approx(14.8)
    assert commands[d2.vehicle_id].desired_speed_mps == pytest.approx(15.1)
    assert all(command.desired_acceleration_mps2 is None for command in commands.values())


def test_low_level_merge_disturbance_propagates_from_d1_to_d2_then_d3() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    d2 = _vehicle("merge_main_L1_lane1.0", x_m=60.0, lane_index=1, speed_mps=15.1).model_copy(
        update={"lane_id": "main_before_1"}
    )
    d3 = _vehicle("merge_main_L2_lane2.0", x_m=68.0, lane_index=2, speed_mps=15.4).model_copy(
        update={"lane_id": "main_before_2"}
    )
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    first = controller.step(_snapshot(d1, d2, d3, ramp, time_ms=12_000), 0.05)
    middle = controller.step(_snapshot(d1, d2, d3, ramp, time_ms=12_550), 0.05)
    propagated = controller.step(_snapshot(d1, d2, d3, ramp, time_ms=13_250), 0.05)

    assert first[d1.vehicle_id].desired_acceleration_mps2 == pytest.approx(-3.5)
    assert first[d2.vehicle_id].desired_speed_mps == pytest.approx(15.1)
    assert first[d3.vehicle_id].desired_speed_mps == pytest.approx(15.4)
    assert first[ramp.vehicle_id].desired_acceleration_mps2 == pytest.approx(-4.5)
    assert middle[d2.vehicle_id].desired_acceleration_mps2 == pytest.approx(-3.5)
    assert middle[d3.vehicle_id].desired_speed_mps == pytest.approx(15.4)
    assert propagated[d2.vehicle_id].desired_acceleration_mps2 == pytest.approx(-3.5)
    assert propagated[d3.vehicle_id].desired_acceleration_mps2 == pytest.approx(-2.4)


def test_low_level_merge_requests_more_d1_to_d2_changes_than_d2_to_d3_changes() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    d2 = _vehicle("merge_main_L1_lane1.0", x_m=60.0, lane_index=1, speed_mps=15.1).model_copy(
        update={"lane_id": "main_before_1"}
    )
    d3_front = _vehicle("merge_main_L2_lane2.0", x_m=65.0, lane_index=2, speed_mps=15.4).model_copy(
        update={"lane_id": "main_before_2"}
    )
    d3_rear = _vehicle("merge_main_L3_lane2.0", x_m=55.0, lane_index=2, speed_mps=15.5).model_copy(
        update={"lane_id": "main_before_2"}
    )
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    first = controller.step(_snapshot(d1, d2, d3_front, d3_rear, ramp, time_ms=12_000), 0.05)
    propagated = controller.step(
        _snapshot(d1, d2, d3_front, d3_rear, ramp, time_ms=13_850),
        0.05,
    )

    assert first[d1.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert first[d1.vehicle_id].lane_change_mode == 512
    assert propagated[d2.vehicle_id].lane_change is LaneChangeDirection.NONE
    assert all(not command.safety_checks_override for command in propagated.values())


def test_low_level_merge_assigns_distinct_upper_lane_cruise_speeds() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    vehicles = (
        _vehicle("merge_opposing_L0_lane0.100", x_m=310.0, lane_index=0).model_copy(
            update={"lane_id": "opposing_before_0"}
        ),
        _vehicle("merge_opposing_L1_lane0.101", x_m=220.0, lane_index=0).model_copy(
            update={"lane_id": "opposing_before_0"}
        ),
        _vehicle("merge_opposing_L2_lane0.120", x_m=80.0, lane_index=0).model_copy(
            update={"lane_id": "opposing_after_0"}
        ),
        _vehicle("merge_opposing_L3_lane0.0", x_m=319.0, lane_index=0).model_copy(
            update={"lane_id": "opposing_before_0"}
        ),
    )

    commands = controller.step(_snapshot(*vehicles, time_ms=5_000), 0.05)
    speeds_mps = {commands[vehicle.vehicle_id].desired_speed_mps for vehicle in vehicles}

    assert None not in speeds_mps
    assert len(speeds_mps) == len(vehicles)


def test_low_level_merge_allows_a_sparse_d2_to_d3_change_when_safe() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    d2 = _vehicle("merge_main_L0_lane1.0", x_m=70.0, lane_index=1, speed_mps=15.0).model_copy(
        update={"lane_id": "main_before_1"}
    )
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    controller.step(_snapshot(d1, d2, ramp, time_ms=12_000), 0.05)
    commands = controller.step(_snapshot(d1, d2, ramp, time_ms=13_850), 0.05)

    assert commands[d2.vehicle_id].lane_change is LaneChangeDirection.LEFT
    assert commands[d2.vehicle_id].lane_change_mode == 512


def test_low_level_merge_waits_for_a_safe_target_lane_gap() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    blocking_d2 = _vehicle(
        "merge_main_L1_lane1.0", x_m=77.0, lane_index=1, speed_mps=15.1
    ).model_copy(update={"lane_id": "main_before_1"})
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(d1, blocking_d2, ramp, time_ms=12_000), 0.05)

    assert commands[d1.vehicle_id].desired_acceleration_mps2 == pytest.approx(-4.5)
    assert commands[d1.vehicle_id].lane_change is LaneChangeDirection.NONE


def test_low_level_merge_rejects_a_marginal_seven_meter_lane_change_gap() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    close_d2 = _vehicle("merge_main_L1_lane1.0", x_m=69.0, lane_index=1, speed_mps=15.1).model_copy(
        update={"lane_id": "main_before_1"}
    )
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(d1, close_d2, ramp, time_ms=12_000), 0.05)

    assert commands[d1.vehicle_id].desired_acceleration_mps2 == pytest.approx(-4.5)
    assert commands[d1.vehicle_id].lane_change is LaneChangeDirection.NONE


def test_low_level_merge_rejects_a_target_lane_vehicle_that_crosses_during_change() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.0).model_copy(
        update={"lane_id": "main_before_0"}
    )
    crossing_d2 = _vehicle(
        "merge_main_L1_lane1.0", x_m=68.0, lane_index=1, speed_mps=30.0
    ).model_copy(update={"lane_id": "main_before_1"})
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(d1, crossing_d2, ramp, time_ms=12_000), 0.05)

    assert commands[d1.vehicle_id].desired_acceleration_mps2 == pytest.approx(-4.5)
    assert commands[d1.vehicle_id].lane_change is LaneChangeDirection.NONE


def test_low_level_merge_accounts_for_candidate_braking_during_lane_change() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.0).model_copy(
        update={"lane_id": "main_before_0"}
    )
    following_d2 = _vehicle(
        "merge_main_L1_lane1.0", x_m=68.0, lane_index=1, speed_mps=14.0
    ).model_copy(update={"lane_id": "main_before_1"})
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(d1, following_d2, ramp, time_ms=12_000), 0.05)

    assert commands[d1.vehicle_id].desired_acceleration_mps2 == pytest.approx(-4.5)
    assert commands[d1.vehicle_id].lane_change is LaneChangeDirection.NONE


def test_low_level_merge_does_not_spread_slowdown_far_from_the_conflict() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    d1 = _vehicle("merge_main_L0_lane0.0", x_m=76.0, lane_index=0, speed_mps=14.8).model_copy(
        update={"lane_id": "main_before_0"}
    )
    distant_d2 = _vehicle(
        "merge_main_L1_lane1.0", x_m=25.0, lane_index=1, speed_mps=15.1
    ).model_copy(update={"lane_id": "main_before_1"})
    distant_d3 = _vehicle(
        "merge_main_L2_lane2.0", x_m=10.0, lane_index=2, speed_mps=15.4
    ).model_copy(update={"lane_id": "main_before_2"})
    ramp = _vehicle("merge_ramp_L3.0", x_m=88.0, lane_index=0, speed_mps=8.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    controller.step(_snapshot(d1, distant_d2, distant_d3, ramp, time_ms=12_000), 0.05)
    commands = controller.step(
        _snapshot(d1, distant_d2, distant_d3, ramp, time_ms=13_850),
        0.05,
    )

    assert commands[distant_d2.vehicle_id].desired_speed_mps == pytest.approx(15.1)
    assert commands[distant_d3.vehicle_id].desired_speed_mps == pytest.approx(15.4)


def test_low_level_merge_stops_lane_changes_and_recovers_after_twenty_two_seconds() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-low-level-merge")
    changed_d1 = _vehicle(
        "merge_main_L0_lane0.0", x_m=105.0, lane_index=1, speed_mps=7.0
    ).model_copy(update={"lane_id": "main_after_1"})
    changed_d2 = _vehicle(
        "merge_main_L0_lane1.0", x_m=100.0, lane_index=2, speed_mps=10.0
    ).model_copy(update={"lane_id": "main_after_2"})
    remaining_ramp = _vehicle("merge_ramp_L1.0", x_m=95.0, lane_index=0, speed_mps=5.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(
        _snapshot(changed_d1, changed_d2, remaining_ramp, time_ms=22_000),
        0.05,
    )

    assert commands[changed_d1.vehicle_id].desired_speed_mps == pytest.approx(15.0)
    assert commands[changed_d2.vehicle_id].desired_speed_mps == pytest.approx(15.2)
    assert commands[remaining_ramp.vehicle_id].desired_speed_mps == pytest.approx(12.0)
    assert all(command.lane_change is LaneChangeDirection.NONE for command in commands.values())
    assert all(command.lane_change_mode == 0 for command in commands.values())


def test_l5_merge_keeps_mixed_levels_at_constant_speed_and_locks_lane_changes() -> None:
    controller = MixedAutomationScenarioController("mixed-automation-l5-merge")
    main_l3 = _vehicle(
        "merge_main_L3_lane0.0",
        x_m=90.0,
        lane_index=0,
        speed_mps=16.0,
    ).model_copy(update={"lane_id": "main_before_0"})
    main_l4 = _vehicle(
        "merge_main_L4_lane1.0",
        x_m=70.0,
        lane_index=1,
        speed_mps=16.0,
    ).model_copy(update={"lane_id": "main_before_1"})
    ramp_l5 = _vehicle("merge_ramp_L5.1", x_m=110.0, lane_index=0, speed_mps=16.0).model_copy(
        update={"lane_id": "merge_ramp_0"}
    )

    commands = controller.step(_snapshot(main_l3, main_l4, ramp_l5, time_ms=10_000), 0.05)

    assert set(commands) == {main_l3.vehicle_id, main_l4.vehicle_id, ramp_l5.vehicle_id}
    assert all(command.desired_speed_mps == 16.0 for command in commands.values())
    assert all(command.lane_change is LaneChangeDirection.NONE for command in commands.values())
    assert all(command.lane_change_mode == 0 for command in commands.values())
    assert not any(command.safety_checks_override for command in commands.values())
