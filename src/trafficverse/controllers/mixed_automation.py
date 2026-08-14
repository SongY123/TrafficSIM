"""Deterministic mixed-automation demonstrations for product traffic scenes."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

from trafficverse.domain.enums import LaneChangeDirection
from trafficverse.domain.models import ControlCommand, TrafficSnapshot, VehicleState

_LEVEL_PATTERN = re.compile(r"(?:^|_)L([0-5])(?:_|$)")
_OBSTACLE_TARGET_PATTERN = re.compile(r"^target_L([0-5])_(\d+)$")
_CUTIN_ACTOR_PATTERN = re.compile(r"^cutin_actor_L([0-5])_(\d+)$")
_CUTIN_TARGET_PATTERN = re.compile(r"^cutin_target_L([0-5])_(\d+)$")
_CUTIN_FOLLOWER_PATTERN = re.compile(r"^cutin_follower_L([0-5])_(\d+)$")
_YIELD_PATTERN = re.compile(r"^yield_L([0-5])_(\d+)$")
_ACCIDENT_FOLLOWER_PATTERN = re.compile(r"^accident_follow_L([0135])_(\d+)$")
_ACCIDENT_BACKGROUND_PATTERN = re.compile(r"^accident_background_L([0135])_(\d+)$")
_MERGE_VEHICLE_PATTERN = re.compile(
    r"^merge_(main|ramp|opposing)_L([0-5])(?:_lane([0-2]))?\.(\d+)$"
)
_AUTOMATION_LEVEL_COUNT = 6
_UNSAFE_CUTIN_PAIRS_BY_LEVEL = (4, 3, 2, 1, 0, 0)
_UNSAFE_OBSTACLE_TARGETS_BY_LEVEL = (4, 3, 2, 1, 0, 0)
_UNSAFE_OBSTACLE_BRAKE_TRIGGER_M = (25.0, 35.0, 45.0, 50.0, 0.0, 0.0)
_UNSAFE_OBSTACLE_DECEL_MPS2 = (1.5, 2.2, 3.0, 4.0, 0.0, 0.0)
_INITIAL_LAYOUT_DURATION_MS = 3_000
_OBSTACLE_CRUISE_SPEED_MPS = (16.0, 18.0, 20.0, 22.0, 24.0, 26.0)
_CUTIN_CRUISE_SPEED_MPS = (14.0, 16.0, 18.0, 20.0, 22.0, 24.0)
_CUTIN_BACKGROUND_SPEED_MPS = (8.0, 13.0, 18.0, 23.0, 26.0, 27.5)
_CUTIN_POST_EVENT_SPEED_MPS = 22.0
_EMERGENCY_CRUISE_SPEED_MPS = (10.0, 13.0, 16.0, 19.0, 22.0, 25.0)
_EMERGENCY_BACKGROUND_SPEED_MPS = (12.0, 13.5, 15.0, 16.5, 18.0, 21.0)
_ACCIDENT_L1_BRAKE_TRIGGER_DISTANCE_M = 13.0
_ACCIDENT_L5_CRUISE_SPEED_MPS = 12.0
_ACCIDENT_PRE_INCIDENT_SPEED_MPS = {0: 16.0, 1: 12.0, 3: 8.0, 5: _ACCIDENT_L5_CRUISE_SPEED_MPS}
_ACCIDENT_FOLLOWING_L0_POST_INCIDENT_SPEED_MPS = 6.5
_ACCIDENT_L5_LANE_CHANGE_TRIGGER_X_M = 475.0
_ACCIDENT_L5_LANE_CHANGE_DURATION_S = 1.0
_ACCIDENT_L1_GAP_OPENING_DECEL_MPS2 = 0.65
_ACCIDENT_L3_EMERGENCY_RESPONSE_DECEL_MPS2 = 1.75
_ACCIDENT_BACKGROUND_STRAIGHT_SPEED_MPS = 8.0
_ACCIDENT_BACKGROUND_BRAKING_DECEL_MPS2 = 1.5
_ACCIDENT_BACKGROUND_STOPPED_SPEED_MPS = 0.05
_ACCIDENT_BACKGROUND_BRAKING_BUFFER_M = 0.25
_ACCIDENT_BACKGROUND_QUEUE_TARGET_XY_M = {
    "accident_background_L0_0": (538.0, 138.84),
    "accident_background_L1_0": (531.0, 134.64),
    "accident_background_L3_0": (524.0, 130.44),
    "accident_background_L0_1": (556.0, 145.56),
    "accident_background_L1_1": (549.0, 141.36),
    "accident_background_L3_1": (542.0, 137.16),
    "accident_background_L3_2": (535.0, 132.96),
}
_LOW_MERGE_STABLE_END_MS = 10_000
_LOW_MERGE_DISTURBANCE_END_MS = 22_000
_LOW_MERGE_RAMP_CRUISE_SPEED_MPS = 14.0
_LOW_MERGE_RAMP_CONFLICT_SPEED_MPS = 3.2
_LOW_MERGE_RAMP_RECOVERY_SPEED_MPS = 12.0
_LOW_MERGE_RAMP_NEAR_X_M = 80.0
_LOW_MERGE_CLOSE_GAP_M = 8.0
_LOW_MERGE_D1_SPEED_MPS = 1.5
_LOW_MERGE_D1_DECEL_MPS2 = 4.5
_LOW_MERGE_RAMP_DECEL_MPS2 = 4.5
_LOW_MERGE_CASCADE_RADIUS_M = {1: 42.0, 2: 60.0}
_LOW_MERGE_CASCADE_DELAY_MS = {1: 500, 2: 1_200}
_LOW_MERGE_CASCADE_SPEED_MPS = {1: 6.0, 2: 5.2}
_LOW_MERGE_CASCADE_DECEL_MPS2 = {1: 3.5, 2: 2.4}
_LOW_MERGE_LANE_CHANGE_DURATION_S = 1.0
_LOW_MERGE_LANE_CHANGE_CLEARANCE_M = {1: 7.5, 2: 9.0}
_LOW_MERGE_LANE_CHANGE_ZONE_X_M = {1: (58.0, 94.0), 2: (58.0, 98.0)}
_L5_MERGE_MAIN_SPEED_MPS = 20.0
_L5_MERGE_RAMP_SPEED_MPS = 19.0
_L5_MERGE_GAP_SPEED_MPS = 8.0
_L5_MERGE_RAMP_NEAR_X_M = 78.0
_L5_MERGE_GAP_ZONE_X_M = (20.0, 120.0)
_SCENARIO_IDS = frozenset(
    {
        "mixed-automation-obstacle",
        "mixed-automation-cutin",
        "mixed-automation-emergency-yield",
        "mixed-automation-occasional-accident",
        "mixed-automation-low-level-merge",
        "mixed-automation-l5-merge",
    }
)


class MixedAutomationScenarioController:
    """Translate one documented incident into per-level vehicle intents."""

    def __init__(self, scenario_id: str) -> None:
        if scenario_id not in _SCENARIO_IDS:
            raise ValueError(f"unsupported mixed-automation scenario: {scenario_id}")
        self._scenario_id = scenario_id
        self._accident_l1_emergency_observed = False
        self._accident_l5_lane_change_started = False
        self._accident_background_braking_ids: set[str] = set()
        self._low_merge_gap_provider_id: str | None = None
        self._low_merge_served_ramp_id: str | None = None
        self._low_merge_conflict_started_ms: int | None = None
        self._low_merge_lane_change_requested_ids: set[str] = set()
        self._low_merge_d1_lane_change_request_count = 0
        self._low_merge_d2_lane_change_requested = False
        self._l5_merge_gap_provider_id: str | None = None
        self._l5_merge_served_ramp_id: str | None = None

    def step(self, previous: TrafficSnapshot | None, dt_s: float) -> Mapping[str, ControlCommand]:
        if previous is None:
            return {}
        if self._scenario_id == "mixed-automation-obstacle":
            return self._obstacle_controls(previous, dt_s)
        if self._scenario_id == "mixed-automation-cutin":
            return self._cutin_controls(previous, dt_s)
        if self._scenario_id == "mixed-automation-emergency-yield":
            return self._emergency_controls(previous, dt_s)
        if self._scenario_id == "mixed-automation-occasional-accident":
            return self._occasional_accident_controls(previous, dt_s)
        if self._scenario_id == "mixed-automation-low-level-merge":
            return self._low_level_merge_controls(previous, dt_s)
        return self._l5_merge_controls(previous, dt_s)

    @staticmethod
    def _obstacle_controls(snapshot: TrafficSnapshot, dt_s: float) -> dict[str, ControlCommand]:
        if snapshot.simulation_time_ms < _INITIAL_LAYOUT_DURATION_MS:
            return _hold_vehicles(snapshot, ("target_", "opposing_"))
        commands: dict[str, ControlCommand] = {}
        del dt_s
        trigger_distance_m = (0.0, 75.0, 120.0, 180.0, 250.0, 330.0)
        response_speed_mps = (16.0, 8.0, 13.0, 18.0, 23.0, 26.0)
        for vehicle in snapshot.vehicles:
            level = _level(vehicle.vehicle_id)
            lane_index = _lane_index(vehicle.lane_id)
            if level is None:
                continue
            cruise_speed_mps = _OBSTACLE_CRUISE_SPEED_MPS[level]
            if not vehicle.vehicle_id.startswith("target_"):
                continue
            target_match = _OBSTACLE_TARGET_PATTERN.match(vehicle.vehicle_id)
            if target_match is None:
                continue
            target_index = int(target_match.group(2))
            if target_index >= 4:
                commands[vehicle.vehicle_id] = ControlCommand(desired_speed_mps=cruise_speed_mps)
                continue
            distance_m = _nearest_obstacle_distance_m(snapshot, vehicle)
            if target_index < _UNSAFE_OBSTACLE_TARGETS_BY_LEVEL[level]:
                if (
                    lane_index in {0, 1}
                    and 0.0 < distance_m <= _UNSAFE_OBSTACLE_BRAKE_TRIGGER_M[level]
                ):
                    commands[vehicle.vehicle_id] = ControlCommand(
                        desired_acceleration_mps2=-_UNSAFE_OBSTACLE_DECEL_MPS2[level],
                        safety_checks_override=True,
                    )
                else:
                    commands[vehicle.vehicle_id] = ControlCommand(
                        desired_speed_mps=cruise_speed_mps,
                        safety_checks_override=(lane_index in {0, 1} and distance_m > 0.0),
                    )
                continue
            if lane_index == 2 or distance_m <= 0.0:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=cruise_speed_mps,
                )
            elif lane_index in {0, 1} and distance_m <= trigger_distance_m[level]:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=response_speed_mps[level],
                    lane_change=LaneChangeDirection.LEFT,
                    lane_change_duration_s=2.5,
                    takeover_requested=level == 3,
                )
            else:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=cruise_speed_mps,
                )
        return _lock_lane_changes(commands, snapshot, ("target_",), mode=0)

    @staticmethod
    def _cutin_controls(snapshot: TrafficSnapshot, dt_s: float) -> dict[str, ControlCommand]:
        if snapshot.simulation_time_ms < _INITIAL_LAYOUT_DURATION_MS:
            return _hold_vehicles(
                snapshot,
                ("cutin_target_", "cutin_actor_", "cutin_follower_"),
            )
        commands: dict[str, ControlCommand] = {}
        del dt_s
        elapsed_s = snapshot.simulation_time_ms / 1000.0
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in snapshot.vehicles}
        for vehicle in snapshot.vehicles:
            target_match = _CUTIN_TARGET_PATTERN.match(vehicle.vehicle_id)
            actor_match = _CUTIN_ACTOR_PATTERN.match(vehicle.vehicle_id)
            follower_match = _CUTIN_FOLLOWER_PATTERN.match(vehicle.vehicle_id)
            match = target_match or actor_match or follower_match
            if match is None:
                continue
            level = int(match.group(1))
            pair_index = int(match.group(2))
            if target_match is not None and pair_index >= 4:
                desired_speed_mps = _CUTIN_BACKGROUND_SPEED_MPS[level]
            else:
                desired_speed_mps = _CUTIN_CRUISE_SPEED_MPS[level]
            commands[vehicle.vehicle_id] = ControlCommand(
                desired_speed_mps=desired_speed_mps,
                safety_checks_override=not (target_match is not None and pair_index >= 4),
            )
        for intruder in snapshot.vehicles:
            match = _CUTIN_ACTOR_PATTERN.match(intruder.vehicle_id)
            if match is None:
                continue
            level = int(match.group(1))
            pair_index_text = match.group(2)
            pair_index = int(pair_index_text)
            target = vehicles.get(f"cutin_target_L{level}_{pair_index_text}")
            if target is None:
                continue
            event_time_s = 3.5 + (pair_index * _AUTOMATION_LEVEL_COUNT + level) * 0.32
            time_since_event_s = elapsed_s - event_time_s
            if time_since_event_s > 4.5:
                commands[target.vehicle_id] = ControlCommand(
                    desired_speed_mps=_CUTIN_POST_EVENT_SPEED_MPS,
                    safety_checks_override=True,
                )
                commands[intruder.vehicle_id] = ControlCommand(
                    desired_speed_mps=_CUTIN_POST_EVENT_SPEED_MPS,
                    safety_checks_override=True,
                )
                follower = vehicles.get(f"cutin_follower_L0_{pair_index_text}")
                if follower is not None:
                    commands[follower.vehicle_id] = ControlCommand(
                        desired_speed_mps=_CUTIN_POST_EVENT_SPEED_MPS,
                        safety_checks_override=True,
                    )
                continue
            unsafe_event = pair_index < _UNSAFE_CUTIN_PAIRS_BY_LEVEL[level]
            anticipation_s = (0.0, 0.0, 0.0, 0.0, 2.2, 3.0)[level]
            target_response_speed_mps = _CUTIN_CRUISE_SPEED_MPS[level]
            if time_since_event_s >= -anticipation_s:
                commands[target.vehicle_id] = ControlCommand(
                    desired_speed_mps=target_response_speed_mps,
                    safety_checks_override=True,
                    takeover_requested=level == 3,
                )
            if time_since_event_s < 0.0:
                continue
            intruder_lane_index = _lane_index(intruder.lane_id)
            merge_speed_mps = (
                (6.0, 8.0, 10.0, 12.0)[level] if unsafe_event else _CUTIN_CRUISE_SPEED_MPS[level]
            )
            commands[intruder.vehicle_id] = ControlCommand(
                desired_speed_mps=merge_speed_mps,
                safety_checks_override=unsafe_event,
                lane_change=(
                    LaneChangeDirection.LEFT
                    if intruder_lane_index == 0
                    else LaneChangeDirection.NONE
                ),
                lane_change_duration_s=2.0,
            )
            follower = vehicles.get(f"cutin_follower_L0_{pair_index_text}")
            if follower is not None and 0.0 <= time_since_event_s <= 4.5:
                commands[follower.vehicle_id] = ControlCommand(
                    desired_speed_mps=20.0,
                    safety_checks_override=True,
                )
        return _lock_lane_changes(
            commands,
            snapshot,
            ("cutin_target_", "cutin_actor_", "cutin_follower_"),
            mode=0,
        )

    @staticmethod
    def _emergency_controls(snapshot: TrafficSnapshot, dt_s: float) -> dict[str, ControlCommand]:
        if snapshot.simulation_time_ms < _INITIAL_LAYOUT_DURATION_MS:
            return _hold_vehicles(snapshot, ("yield_", "ambulance_"))
        commands: dict[str, ControlCommand] = {}
        del dt_s
        ambulance = next(
            (vehicle for vehicle in snapshot.vehicles if vehicle.vehicle_id == "ambulance_L5_0"),
            None,
        )
        if ambulance is None:
            return commands
        trigger_distance_m = (8.0, 18.0, 35.0, 70.0, 120.0, 200.0)
        lane_change_duration_s = (0.4, 0.7, 1.0, 1.4, 1.9, 2.4)
        response_speed_mps = (8.0, 11.0, 15.0, 19.0, 23.0, 26.0)
        yielding_speeds_mps: list[float] = []
        for vehicle in snapshot.vehicles:
            match = _YIELD_PATTERN.match(vehicle.vehicle_id)
            if match is None or int(match.group(2)) >= 3 or _lane_index(vehicle.lane_id) != 1:
                continue
            level = int(match.group(1))
            gap_m = vehicle.position.x - ambulance.position.x
            if 0.0 < gap_m <= trigger_distance_m[level]:
                yielding_speeds_mps.append(response_speed_mps[level])
        commands[ambulance.vehicle_id] = ControlCommand(
            desired_speed_mps=min((28.0, *yielding_speeds_mps)),
            lane_change_mode=0,
            safety_checks_override=True,
        )
        for vehicle in snapshot.vehicles:
            match = _YIELD_PATTERN.match(vehicle.vehicle_id)
            if match is None:
                continue
            level = int(match.group(1))
            vehicle_index = int(match.group(2))
            if vehicle_index >= 3:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=_EMERGENCY_BACKGROUND_SPEED_MPS[level]
                )
                continue
            cruise_speed_mps = _EMERGENCY_CRUISE_SPEED_MPS[level]
            gap_m = vehicle.position.x - ambulance.position.x
            lane_index = _lane_index(vehicle.lane_id)
            if gap_m < -70.0:
                commands[vehicle.vehicle_id] = (
                    ControlCommand(
                        desired_speed_mps=cruise_speed_mps,
                        lane_change=LaneChangeDirection.LEFT,
                        lane_change_duration_s=2.5,
                    )
                    if lane_index == 0
                    else ControlCommand(desired_speed_mps=cruise_speed_mps)
                )
            elif not 0.0 < gap_m <= trigger_distance_m[level]:
                commands[vehicle.vehicle_id] = ControlCommand(desired_speed_mps=cruise_speed_mps)
            elif lane_index == 1:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=response_speed_mps[level],
                    lane_change=LaneChangeDirection.RIGHT,
                    lane_change_duration_s=lane_change_duration_s[level],
                    takeover_requested=level in {1, 3},
                )
            elif lane_index == 0:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=response_speed_mps[level]
                )
            else:
                commands[vehicle.vehicle_id] = ControlCommand(desired_speed_mps=cruise_speed_mps)
        return _lock_lane_changes(commands, snapshot, ("yield_",), mode=0)

    def _occasional_accident_controls(
        self,
        snapshot: TrafficSnapshot,
        dt_s: float,
    ) -> dict[str, ControlCommand]:
        prefixes = (
            "accident_parked_",
            "accident_actor_",
            "accident_victim_",
            "accident_follow_",
            "accident_background_",
        )
        if snapshot.simulation_time_ms < _INITIAL_LAYOUT_DURATION_MS:
            return _hold_vehicles(snapshot, prefixes)
        del dt_s
        commands: dict[str, ControlCommand] = {}
        collision_ids = set(snapshot.collision_vehicle_ids)
        front_collision_ids = {"accident_actor_L0_0", "accident_victim_L0_0"}
        incident_active = front_collision_ids <= collision_ids
        pileup_complete = "accident_follow_L0_0" in collision_ids
        vehicle_by_id = {vehicle.vehicle_id: vehicle for vehicle in snapshot.vehicles}
        parked = vehicle_by_id.get("accident_parked_L0_0")
        actor = vehicle_by_id.get("accident_actor_L0_0")
        following_l0 = vehicle_by_id.get("accident_follow_L0_0")
        l1_vehicle = vehicle_by_id.get("accident_follow_L1_0")
        accident_positions = [
            vehicle_by_id[vehicle_id].position.x
            for vehicle_id in front_collision_ids
            if vehicle_id in vehicle_by_id
        ]
        accident_x_m = max(accident_positions, default=595.0)
        l1_response_required = pileup_complete or (
            incident_active
            and following_l0 is not None
            and 0.0
            <= accident_x_m - following_l0.position.x
            <= _ACCIDENT_L1_BRAKE_TRIGGER_DISTANCE_M
        )
        l1_emergency_braking_now = (
            l1_response_required and l1_vehicle is not None and l1_vehicle.acceleration_mps2 <= -6.0
        )
        if l1_emergency_braking_now:
            self._accident_l1_emergency_observed = True
        l1_emergency_braking = self._accident_l1_emergency_observed
        l1_decelerating = (
            incident_active
            and l1_vehicle is not None
            and (l1_vehicle.acceleration_mps2 <= -0.5 or l1_vehicle.speed_mps < 15.0)
        )
        parked_distance_m = (
            parked.position.x - actor.position.x
            if parked is not None and actor is not None
            else float("inf")
        )
        maneuver_started = parked_distance_m <= 38.0

        for vehicle in snapshot.vehicles:
            if vehicle.vehicle_id == "accident_parked_L0_0":
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=0.0,
                    safety_checks_override=True,
                )
                continue
            if vehicle.vehicle_id == "accident_actor_L0_0":
                commands[vehicle.vehicle_id] = (
                    ControlCommand(
                        desired_speed_mps=0.0,
                        safety_checks_override=True,
                    )
                    if vehicle.vehicle_id in collision_ids
                    else ControlCommand(
                        desired_speed_mps=11.0 if maneuver_started else 10.0,
                        lane_change=(
                            LaneChangeDirection.LEFT
                            if maneuver_started and _lane_index(vehicle.lane_id) == 0
                            else LaneChangeDirection.NONE
                        ),
                        lane_change_duration_s=2.0,
                        safety_checks_override=True,
                    )
                )
                continue
            if vehicle.vehicle_id == "accident_victim_L0_0":
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=(0.0 if vehicle.vehicle_id in collision_ids else 9.0),
                    safety_checks_override=True,
                )
                continue

            background_match = _ACCIDENT_BACKGROUND_PATTERN.match(vehicle.vehicle_id)
            if background_match is not None:
                level = int(background_match.group(1))
                if level == 5:
                    commands[vehicle.vehicle_id] = ControlCommand(
                        desired_speed_mps=_ACCIDENT_L5_CRUISE_SPEED_MPS,
                        safety_checks_override=True,
                    )
                elif not incident_active:
                    commands[vehicle.vehicle_id] = ControlCommand(
                        desired_speed_mps=_ACCIDENT_BACKGROUND_STRAIGHT_SPEED_MPS,
                        safety_checks_override=True,
                    )
                else:
                    commands[vehicle.vehicle_id] = self._accident_background_queue_command(vehicle)
                continue

            match = _ACCIDENT_FOLLOWER_PATTERN.match(vehicle.vehicle_id)
            if match is None:
                continue
            level = int(match.group(1))
            distance_m = max(0.0, accident_x_m - vehicle.position.x)
            if vehicle.vehicle_id in collision_ids:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=0.0,
                    safety_checks_override=True,
                )
                continue
            if not incident_active:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=_ACCIDENT_PRE_INCIDENT_SPEED_MPS[level],
                    safety_checks_override=level in {0, 1, 3, 5},
                )
                continue
            if level == 0:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=_ACCIDENT_FOLLOWING_L0_POST_INCIDENT_SPEED_MPS,
                    safety_checks_override=True,
                )
            elif level == 5:
                near_right_turn = (
                    vehicle.lane_id.startswith("road_approach_")
                    and vehicle.position.x >= _ACCIDENT_L5_LANE_CHANGE_TRIGGER_X_M
                )
                start_lane_change = (
                    incident_active
                    and near_right_turn
                    and _lane_index(vehicle.lane_id) == 1
                    and not self._accident_l5_lane_change_started
                )
                if start_lane_change:
                    self._accident_l5_lane_change_started = True
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=_ACCIDENT_L5_CRUISE_SPEED_MPS,
                    lane_change=(
                        LaneChangeDirection.RIGHT if start_lane_change else LaneChangeDirection.NONE
                    ),
                    lane_change_duration_s=_ACCIDENT_L5_LANE_CHANGE_DURATION_S,
                    safety_checks_override=True,
                )
            elif level == 1:
                commands[vehicle.vehicle_id] = (
                    ControlCommand(
                        desired_acceleration_mps2=-8.0,
                        takeover_requested=True,
                        safety_checks_override=True,
                    )
                    if l1_response_required and distance_m <= 100.0
                    else ControlCommand(
                        desired_acceleration_mps2=-_ACCIDENT_L1_GAP_OPENING_DECEL_MPS2,
                        safety_checks_override=True,
                    )
                    if incident_active
                    else ControlCommand(
                        desired_speed_mps=_ACCIDENT_PRE_INCIDENT_SPEED_MPS[1],
                        safety_checks_override=True,
                    )
                )
            elif level == 3:
                commands[vehicle.vehicle_id] = (
                    ControlCommand(
                        desired_acceleration_mps2=-_ACCIDENT_L3_EMERGENCY_RESPONSE_DECEL_MPS2,
                        takeover_requested=True,
                        safety_checks_override=True,
                    )
                    if l1_emergency_braking and distance_m <= 180.0
                    else ControlCommand(
                        desired_acceleration_mps2=-_ACCIDENT_L1_GAP_OPENING_DECEL_MPS2,
                        takeover_requested=True,
                        safety_checks_override=True,
                    )
                    if l1_decelerating and distance_m <= 180.0
                    else ControlCommand(
                        desired_speed_mps=_ACCIDENT_PRE_INCIDENT_SPEED_MPS[3],
                        safety_checks_override=True,
                    )
                )
            else:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps={1: 15.2, 3: 13.0}.get(level, 16.0)
                )
        return _lock_lane_changes(commands, snapshot, prefixes, mode=0)

    def _accident_background_queue_command(self, vehicle: VehicleState) -> ControlCommand:
        target_xy_m = _ACCIDENT_BACKGROUND_QUEUE_TARGET_XY_M.get(vehicle.vehicle_id)
        if target_xy_m is None:
            return ControlCommand(
                desired_speed_mps=_ACCIDENT_BACKGROUND_STRAIGHT_SPEED_MPS,
                safety_checks_override=True,
            )
        distance_to_target_m = math.hypot(
            target_xy_m[0] - vehicle.position.x,
            target_xy_m[1] - vehicle.position.y,
        )
        if vehicle.speed_mps <= _ACCIDENT_BACKGROUND_STOPPED_SPEED_MPS:
            return ControlCommand(desired_speed_mps=0.0, safety_checks_override=True)
        braking_distance_m = vehicle.speed_mps**2 / (2.0 * _ACCIDENT_BACKGROUND_BRAKING_DECEL_MPS2)
        braking_started = (
            vehicle.vehicle_id in self._accident_background_braking_ids
            or vehicle.speed_mps < _ACCIDENT_BACKGROUND_STRAIGHT_SPEED_MPS - 0.05
            or distance_to_target_m <= braking_distance_m + _ACCIDENT_BACKGROUND_BRAKING_BUFFER_M
        )
        if braking_started:
            self._accident_background_braking_ids.add(vehicle.vehicle_id)
            return ControlCommand(
                desired_acceleration_mps2=-_ACCIDENT_BACKGROUND_BRAKING_DECEL_MPS2,
                safety_checks_override=True,
            )
        return ControlCommand(
            desired_speed_mps=_ACCIDENT_BACKGROUND_STRAIGHT_SPEED_MPS,
            safety_checks_override=True,
        )

    def _low_level_merge_controls(
        self,
        snapshot: TrafficSnapshot,
        dt_s: float,
    ) -> dict[str, ControlCommand]:
        del dt_s
        disturbance_active = (
            _LOW_MERGE_STABLE_END_MS <= snapshot.simulation_time_ms < _LOW_MERGE_DISTURBANCE_END_MS
        )
        active_ramp_vehicles = tuple(
            vehicle
            for vehicle in snapshot.vehicles
            if disturbance_active
            and _is_active_merge_ramp_vehicle(vehicle)
            and vehicle.position.x >= _LOW_MERGE_RAMP_NEAR_X_M
        )
        active_ramp_ids = {vehicle.vehicle_id for vehicle in active_ramp_vehicles}
        if self._low_merge_served_ramp_id not in active_ramp_ids:
            self._low_merge_gap_provider_id = None
            self._low_merge_served_ramp_id = None
            self._low_merge_conflict_started_ms = None
        if self._low_merge_served_ramp_id is None and active_ramp_vehicles:
            leading_ramp = max(active_ramp_vehicles, key=lambda vehicle: vehicle.position.x)
            gap_candidates = tuple(
                vehicle
                for vehicle in snapshot.vehicles
                if vehicle.vehicle_id.startswith("merge_main_")
                and vehicle.lane_id == "main_before_0"
                and vehicle.position.x <= leading_ramp.position.x - _LOW_MERGE_CLOSE_GAP_M
            )
            if gap_candidates:
                lane_change_candidates = tuple(
                    vehicle
                    for vehicle in gap_candidates
                    if _low_merge_vehicle_is_selected_for_lane_change(vehicle, lane_index=0)
                )
                gap_provider = max(
                    lane_change_candidates or gap_candidates,
                    key=lambda vehicle: vehicle.position.x,
                )
                self._low_merge_gap_provider_id = gap_provider.vehicle_id
                self._low_merge_served_ramp_id = leading_ramp.vehicle_id
                self._low_merge_conflict_started_ms = snapshot.simulation_time_ms
        current_gap_provider = next(
            (
                vehicle
                for vehicle in snapshot.vehicles
                if vehicle.vehicle_id == self._low_merge_gap_provider_id
            ),
            None,
        )
        cascade_lane_by_vehicle_id = _low_merge_cascade_lane_by_vehicle_id(
            snapshot,
            current_gap_provider,
            self._low_merge_conflict_started_ms,
        )
        commands: dict[str, ControlCommand] = {}
        for vehicle in snapshot.vehicles:
            match = _MERGE_VEHICLE_PATTERN.match(vehicle.vehicle_id)
            if match is None:
                continue
            stream, level_text, lane_text, sequence_text = match.groups()
            level = int(level_text)
            sequence = int(sequence_text)
            if stream == "opposing":
                actual_lane_index = _lane_index(vehicle.lane_id)
                lane_index = (
                    actual_lane_index if actual_lane_index is not None else int(lane_text or 0)
                )
                desired_speed_mps = _low_merge_opposing_cruise_speed_mps(
                    lane_index,
                    level,
                    sequence,
                    starts_after_merge=vehicle.lane_id.startswith("opposing_after_"),
                )
            elif stream == "ramp":
                if vehicle.lane_id == "main_after_0":
                    desired_speed_mps = _low_merge_main_cruise_speed_mps(0, level)
                elif vehicle.lane_id == "merge_ramp_0":
                    if (
                        snapshot.simulation_time_ms < _LOW_MERGE_DISTURBANCE_END_MS
                        and vehicle.position.x >= _LOW_MERGE_RAMP_NEAR_X_M
                    ):
                        commands[vehicle.vehicle_id] = _low_merge_slowdown_command(
                            vehicle,
                            target_speed_mps=_LOW_MERGE_RAMP_CONFLICT_SPEED_MPS,
                            deceleration_mps2=_LOW_MERGE_RAMP_DECEL_MPS2,
                        )
                        continue
                    desired_speed_mps = (
                        _LOW_MERGE_RAMP_RECOVERY_SPEED_MPS
                        if snapshot.simulation_time_ms >= _LOW_MERGE_DISTURBANCE_END_MS
                        else _LOW_MERGE_RAMP_CRUISE_SPEED_MPS
                    )
                else:
                    target_speed_mps = (
                        _LOW_MERGE_RAMP_CONFLICT_SPEED_MPS
                        if snapshot.simulation_time_ms < _LOW_MERGE_DISTURBANCE_END_MS
                        else _LOW_MERGE_RAMP_RECOVERY_SPEED_MPS
                    )
                    commands[vehicle.vehicle_id] = _low_merge_slowdown_command(
                        vehicle,
                        target_speed_mps=target_speed_mps,
                        deceleration_mps2=_LOW_MERGE_RAMP_DECEL_MPS2,
                    )
                    continue
            else:
                actual_lane_index = _lane_index(vehicle.lane_id)
                lane_index = (
                    actual_lane_index if actual_lane_index is not None else int(lane_text or 0)
                )
                if disturbance_active and vehicle.vehicle_id == self._low_merge_gap_provider_id:
                    command = (
                        _low_merge_cascade_command(vehicle, 1)
                        if vehicle.vehicle_id in self._low_merge_lane_change_requested_ids
                        and vehicle.lane_id == "main_before_0"
                        else _low_merge_slowdown_command(
                            vehicle,
                            target_speed_mps=_LOW_MERGE_D1_SPEED_MPS,
                            deceleration_mps2=_LOW_MERGE_D1_DECEL_MPS2,
                        )
                    )
                    if (
                        vehicle.lane_id == "main_before_0"
                        and self._low_merge_d1_lane_change_request_count < 2
                        and vehicle.vehicle_id not in self._low_merge_lane_change_requested_ids
                        and _low_merge_should_change_lane(0, level, sequence)
                        and _low_merge_lane_change_is_safe(snapshot, vehicle, target_lane_index=1)
                    ):
                        self._low_merge_lane_change_requested_ids.add(vehicle.vehicle_id)
                        self._low_merge_d1_lane_change_request_count += 1
                        command = _low_merge_cascade_command(vehicle, 1).model_copy(
                            update={
                                "lane_change": LaneChangeDirection.LEFT,
                                "lane_change_duration_s": _LOW_MERGE_LANE_CHANGE_DURATION_S,
                                "lane_change_mode": 512,
                            }
                        )
                    commands[vehicle.vehicle_id] = command
                    continue
                if (
                    disturbance_active
                    and self._low_merge_conflict_started_ms is not None
                    and vehicle.lane_id == "main_before_0"
                    and _low_merge_should_change_lane(0, level, sequence)
                    and (
                        vehicle.vehicle_id in self._low_merge_lane_change_requested_ids
                        or self._low_merge_d1_lane_change_request_count < 2
                    )
                ):
                    command = _low_merge_cascade_command(vehicle, 1)
                    if vehicle.vehicle_id in self._low_merge_lane_change_requested_ids:
                        commands[vehicle.vehicle_id] = command
                        continue
                    if _low_merge_lane_change_is_safe(snapshot, vehicle, target_lane_index=1):
                        self._low_merge_lane_change_requested_ids.add(vehicle.vehicle_id)
                        self._low_merge_d1_lane_change_request_count += 1
                        commands[vehicle.vehicle_id] = command.model_copy(
                            update={
                                "lane_change": LaneChangeDirection.LEFT,
                                "lane_change_duration_s": _LOW_MERGE_LANE_CHANGE_DURATION_S,
                                "lane_change_mode": 512,
                            }
                        )
                        continue
                if (
                    disturbance_active
                    and self._low_merge_conflict_started_ms is not None
                    and snapshot.simulation_time_ms - self._low_merge_conflict_started_ms
                    >= _LOW_MERGE_CASCADE_DELAY_MS[2]
                    and vehicle.lane_id == "main_before_1"
                    and not self._low_merge_d2_lane_change_requested
                ):
                    command = _low_merge_cascade_command(vehicle, 2)
                    if vehicle.vehicle_id in self._low_merge_lane_change_requested_ids:
                        commands[vehicle.vehicle_id] = command
                        continue
                    if _low_merge_lane_change_is_safe(snapshot, vehicle, target_lane_index=2):
                        self._low_merge_lane_change_requested_ids.add(vehicle.vehicle_id)
                        self._low_merge_d2_lane_change_requested = True
                        commands[vehicle.vehicle_id] = command.model_copy(
                            update={
                                "lane_change": LaneChangeDirection.LEFT,
                                "lane_change_duration_s": _LOW_MERGE_LANE_CHANGE_DURATION_S,
                                "lane_change_mode": 512,
                            }
                        )
                        continue
                cascade_lane_index = cascade_lane_by_vehicle_id.get(vehicle.vehicle_id)
                if disturbance_active and cascade_lane_index is not None:
                    command = _low_merge_cascade_command(
                        vehicle,
                        (
                            2
                            if cascade_lane_index == 1
                            and vehicle.vehicle_id in self._low_merge_lane_change_requested_ids
                            else cascade_lane_index
                        ),
                    )
                    if (
                        cascade_lane_index == 1
                        and not self._low_merge_d2_lane_change_requested
                        and vehicle.vehicle_id not in self._low_merge_lane_change_requested_ids
                        and _low_merge_should_change_lane(1, level, sequence)
                        and _low_merge_lane_change_is_safe(snapshot, vehicle, target_lane_index=2)
                    ):
                        self._low_merge_lane_change_requested_ids.add(vehicle.vehicle_id)
                        self._low_merge_d2_lane_change_requested = True
                        command = command.model_copy(
                            update={
                                "lane_change": LaneChangeDirection.LEFT,
                                "lane_change_duration_s": _LOW_MERGE_LANE_CHANGE_DURATION_S,
                                "lane_change_mode": 512,
                            }
                        )
                    commands[vehicle.vehicle_id] = command
                    continue
                desired_speed_mps = _low_merge_main_cruise_speed_mps(lane_index, level)
            commands[vehicle.vehicle_id] = ControlCommand(
                desired_speed_mps=desired_speed_mps,
                lane_change_mode=0,
            )
        return commands

    def _l5_merge_controls(
        self,
        snapshot: TrafficSnapshot,
        dt_s: float,
    ) -> dict[str, ControlCommand]:
        del dt_s
        active_ramp_vehicles = tuple(
            vehicle
            for vehicle in snapshot.vehicles
            if _is_active_merge_ramp_vehicle(vehicle)
            and vehicle.position.x >= _L5_MERGE_RAMP_NEAR_X_M
        )
        active_ramp_ids = {vehicle.vehicle_id for vehicle in active_ramp_vehicles}
        if self._l5_merge_served_ramp_id not in active_ramp_ids:
            self._l5_merge_gap_provider_id = None
            self._l5_merge_served_ramp_id = None
        if self._l5_merge_served_ramp_id is None and active_ramp_vehicles:
            ramp_vehicle = max(active_ramp_vehicles, key=lambda vehicle: vehicle.position.x)
            gap_candidates = tuple(
                vehicle
                for vehicle in snapshot.vehicles
                if vehicle.vehicle_id.startswith("merge_main_L5_lane0")
                and vehicle.lane_id == "main_before_0"
                and _L5_MERGE_GAP_ZONE_X_M[0] <= vehicle.position.x < _L5_MERGE_GAP_ZONE_X_M[1]
                and vehicle.position.x <= ramp_vehicle.position.x - 15.0
            )
            if gap_candidates:
                gap_provider = min(
                    gap_candidates,
                    key=lambda vehicle: abs(vehicle.position.x - ramp_vehicle.position.x),
                )
                self._l5_merge_gap_provider_id = gap_provider.vehicle_id
                self._l5_merge_served_ramp_id = ramp_vehicle.vehicle_id
        commands: dict[str, ControlCommand] = {}
        for vehicle in snapshot.vehicles:
            match = _MERGE_VEHICLE_PATTERN.match(vehicle.vehicle_id)
            if match is None:
                continue
            stream, _level_text, _lane_text, _sequence_text = match.groups()
            desired_speed_mps = _L5_MERGE_MAIN_SPEED_MPS
            if stream == "ramp":
                desired_speed_mps = _L5_MERGE_RAMP_SPEED_MPS
            elif stream == "main" and vehicle.vehicle_id == self._l5_merge_gap_provider_id:
                desired_speed_mps = _L5_MERGE_GAP_SPEED_MPS
            commands[vehicle.vehicle_id] = ControlCommand(
                desired_speed_mps=desired_speed_mps,
                lane_change_mode=0,
            )
        return commands


def controller_for_sumo_package(
    package_id: str,
) -> MixedAutomationScenarioController | None:
    """Return a controller only for product-owned mixed-automation packages."""
    if package_id not in _SCENARIO_IDS:
        return None
    return MixedAutomationScenarioController(package_id)


def _level(vehicle_id: str) -> int | None:
    match = _LEVEL_PATTERN.search(vehicle_id)
    return int(match.group(1)) if match is not None else None


def _lane_index(lane_id: str) -> int | None:
    try:
        return int(lane_id.rsplit("_", maxsplit=1)[1])
    except (IndexError, ValueError):
        return None


def _nearest_obstacle_distance_m(snapshot: TrafficSnapshot, vehicle: VehicleState) -> float:
    distances_m = [650.0 - vehicle.position.x]
    for other in snapshot.vehicles:
        if (
            other.vehicle_id == vehicle.vehicle_id
            or other.lane_id != vehicle.lane_id
            or other.position.x <= vehicle.position.x
            or other.speed_mps >= vehicle.speed_mps - 0.5
        ):
            continue
        distances_m.append(other.position.x - vehicle.position.x - 5.0)
    return max(0.0, min(distances_m))


def _low_merge_main_cruise_speed_mps(lane_index: int, level: int) -> float:
    base_speed_mps = (14.8, 15.0, 15.2)[lane_index]
    return base_speed_mps + level * 0.1


def _low_merge_opposing_cruise_speed_mps(
    lane_index: int,
    level: int,
    sequence: int,
    *,
    starts_after_merge: bool,
) -> float:
    if sequence >= 100:
        rank = (
            10 + (sequence - 120) * 4 + level
            if starts_after_merge
            else (sequence - 100) * 4 + level
        )
    else:
        rank = 24 + level * 4 + sequence
    return 13.4 + lane_index * 0.05 + rank * 0.035


def _low_merge_slowdown_command(
    vehicle: VehicleState,
    *,
    target_speed_mps: float,
    deceleration_mps2: float,
) -> ControlCommand:
    if vehicle.speed_mps > target_speed_mps + 0.1:
        return ControlCommand(
            desired_acceleration_mps2=-deceleration_mps2,
            lane_change_mode=0,
        )
    return ControlCommand(
        desired_speed_mps=target_speed_mps,
        lane_change_mode=0,
    )


def _low_merge_cascade_lane_by_vehicle_id(
    snapshot: TrafficSnapshot,
    gap_provider: VehicleState | None,
    conflict_started_ms: int | None,
) -> dict[str, int]:
    if gap_provider is None or conflict_started_ms is None:
        return {}
    elapsed_ms = snapshot.simulation_time_ms - conflict_started_ms
    affected: dict[str, int] = {}
    for vehicle in snapshot.vehicles:
        if not vehicle.vehicle_id.startswith("merge_main_"):
            continue
        lane_index = _lane_index(vehicle.lane_id)
        if lane_index not in _LOW_MERGE_CASCADE_SPEED_MPS:
            continue
        if elapsed_ms < _LOW_MERGE_CASCADE_DELAY_MS[lane_index]:
            continue
        if (
            abs(vehicle.position.x - gap_provider.position.x)
            > _LOW_MERGE_CASCADE_RADIUS_M[lane_index]
        ):
            continue
        affected[vehicle.vehicle_id] = lane_index
    return affected


def _low_merge_lane_change_is_safe(
    snapshot: TrafficSnapshot,
    vehicle: VehicleState,
    *,
    target_lane_index: int,
) -> bool:
    minimum_x_m, maximum_x_m = _LOW_MERGE_LANE_CHANGE_ZONE_X_M[target_lane_index]
    if not minimum_x_m <= vehicle.position.x <= maximum_x_m:
        return False
    target_lane_id = f"main_before_{target_lane_index}"
    clearance_m = _LOW_MERGE_LANE_CHANGE_CLEARANCE_M[target_lane_index]
    projected_vehicle_x_m = (
        vehicle.position.x
        + vehicle.speed_mps * _LOW_MERGE_LANE_CHANGE_DURATION_S
        - 0.5
        * _LOW_MERGE_CASCADE_DECEL_MPS2[target_lane_index]
        * _LOW_MERGE_LANE_CHANGE_DURATION_S**2
    )
    for other in snapshot.vehicles:
        if other.vehicle_id == vehicle.vehicle_id or other.lane_id != target_lane_id:
            continue
        current_delta_m = other.position.x - vehicle.position.x
        projected_delta_m = (
            other.position.x
            + other.speed_mps * _LOW_MERGE_LANE_CHANGE_DURATION_S
            - projected_vehicle_x_m
        )
        stays_ahead = current_delta_m >= clearance_m and projected_delta_m >= clearance_m
        stays_behind = current_delta_m <= -clearance_m and projected_delta_m <= -clearance_m
        if not (stays_ahead or stays_behind):
            return False
    return True


def _low_merge_should_change_lane(lane_index: int, level: int, sequence: int) -> bool:
    if lane_index == 0:
        return (level + sequence) % 4 != 3
    if lane_index == 1:
        return (level + sequence) % 4 == 0
    return False


def _low_merge_vehicle_is_selected_for_lane_change(
    vehicle: VehicleState,
    *,
    lane_index: int,
) -> bool:
    match = _MERGE_VEHICLE_PATTERN.match(vehicle.vehicle_id)
    if match is None:
        return False
    _stream, level_text, _lane_text, sequence_text = match.groups()
    return _low_merge_should_change_lane(lane_index, int(level_text), int(sequence_text))


def _low_merge_cascade_command(
    vehicle: VehicleState,
    lane_index: int,
) -> ControlCommand:
    target_speed_mps = _LOW_MERGE_CASCADE_SPEED_MPS[lane_index]
    if vehicle.speed_mps > target_speed_mps + 0.1:
        return ControlCommand(
            desired_acceleration_mps2=-_LOW_MERGE_CASCADE_DECEL_MPS2[lane_index],
            lane_change_mode=0,
        )
    return ControlCommand(desired_speed_mps=target_speed_mps, lane_change_mode=0)


def _is_active_merge_ramp_vehicle(vehicle: VehicleState) -> bool:
    match = _MERGE_VEHICLE_PATTERN.match(vehicle.vehicle_id)
    return match is not None and match.group(1) == "ramp" and vehicle.lane_id != "main_after_0"


def _lock_lane_changes(
    commands: dict[str, ControlCommand],
    snapshot: TrafficSnapshot,
    prefixes: tuple[str, ...],
    *,
    mode: int = 512,
) -> dict[str, ControlCommand]:
    for vehicle in snapshot.vehicles:
        if not vehicle.vehicle_id.startswith(prefixes):
            continue
        command = commands.get(vehicle.vehicle_id)
        commands[vehicle.vehicle_id] = (
            ControlCommand(lane_change_mode=mode)
            if command is None
            else command.model_copy(update={"lane_change_mode": mode})
        )
    return commands


def _hold_vehicles(
    snapshot: TrafficSnapshot,
    prefixes: tuple[str, ...],
) -> dict[str, ControlCommand]:
    return {
        vehicle.vehicle_id: ControlCommand(desired_speed_mps=0.0, lane_change_mode=0)
        for vehicle in snapshot.vehicles
        if vehicle.vehicle_id.startswith(prefixes)
    }
