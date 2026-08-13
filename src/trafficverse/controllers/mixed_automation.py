"""Deterministic mixed-automation demonstrations for product traffic scenes."""

from __future__ import annotations

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
_ACCIDENT_SECOND_IMPACT_WARNING_DISTANCE_M = 9.0
_ACCIDENT_L5_WAIT_SPEED_MPS = 6.0
_ACCIDENT_L5_LANE_CHANGE_SPEED_MPS = 9.0
_ACCIDENT_L5_LANE_CHANGE_TRIGGER_X_M = 475.0
_ACCIDENT_L1_GAP_OPENING_DECEL_MPS2 = 0.65
_ACCIDENT_L1_EMERGENCY_SPEED_THRESHOLD_MPS = 12.5
_ACCIDENT_L3_EMERGENCY_RESPONSE_DECEL_MPS2 = 2.2
_SCENARIO_IDS = frozenset(
    {
        "mixed-automation-obstacle",
        "mixed-automation-cutin",
        "mixed-automation-emergency-yield",
        "mixed-automation-occasional-accident",
    }
)


class MixedAutomationScenarioController:
    """Translate one documented incident into per-level vehicle intents."""

    def __init__(self, scenario_id: str) -> None:
        if scenario_id not in _SCENARIO_IDS:
            raise ValueError(f"unsupported mixed-automation scenario: {scenario_id}")
        self._scenario_id = scenario_id
        self._accident_l5_lane_change_started = False

    def step(self, previous: TrafficSnapshot | None, dt_s: float) -> Mapping[str, ControlCommand]:
        if previous is None:
            return {}
        if self._scenario_id == "mixed-automation-obstacle":
            return self._obstacle_controls(previous, dt_s)
        if self._scenario_id == "mixed-automation-cutin":
            return self._cutin_controls(previous, dt_s)
        if self._scenario_id == "mixed-automation-emergency-yield":
            return self._emergency_controls(previous, dt_s)
        return self._occasional_accident_controls(previous, dt_s)

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
        l3_vehicle = vehicle_by_id.get("accident_follow_L3_0")
        l3_stopped = pileup_complete and l3_vehicle is not None and l3_vehicle.speed_mps < 0.5
        accident_positions = [
            vehicle_by_id[vehicle_id].position.x
            for vehicle_id in front_collision_ids
            if vehicle_id in vehicle_by_id
        ]
        accident_x_m = max(accident_positions, default=595.0)
        second_impact_imminent = (
            incident_active
            and following_l0 is not None
            and 0.0
            <= accident_x_m - following_l0.position.x
            <= _ACCIDENT_SECOND_IMPACT_WARNING_DISTANCE_M
        )
        l1_response_required = pileup_complete or second_impact_imminent
        l1_emergency_braking = (
            l1_response_required
            and l1_vehicle is not None
            and (
                l1_vehicle.acceleration_mps2 <= -6.0
                or l1_vehicle.speed_mps < _ACCIDENT_L1_EMERGENCY_SPEED_THRESHOLD_MPS
            )
        )
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
                    desired_speed_mps={0: 16.0, 1: 15.2, 3: 13.0, 5: 12.0}[level],
                    safety_checks_override=level in {0, 1, 3},
                )
                continue
            if level == 0:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=16.0,
                    safety_checks_override=True,
                )
            elif level == 5:
                near_right_turn = (
                    vehicle.lane_id.startswith("road_approach_")
                    and vehicle.position.x >= _ACCIDENT_L5_LANE_CHANGE_TRIGGER_X_M
                )
                start_lane_change = (
                    l3_stopped
                    and near_right_turn
                    and _lane_index(vehicle.lane_id) == 1
                    and not self._accident_l5_lane_change_started
                )
                if start_lane_change:
                    self._accident_l5_lane_change_started = True
                lane_change_in_progress = (
                    self._accident_l5_lane_change_started and vehicle.lane_id == "road_approach_1"
                )
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps=(
                        _ACCIDENT_L5_LANE_CHANGE_SPEED_MPS
                        if lane_change_in_progress
                        else 12.0
                        if l3_stopped
                        else _ACCIDENT_L5_WAIT_SPEED_MPS
                    ),
                    lane_change=(
                        LaneChangeDirection.RIGHT if start_lane_change else LaneChangeDirection.NONE
                    ),
                    lane_change_duration_s=1.0,
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
                    else ControlCommand(desired_speed_mps=15.2, safety_checks_override=True)
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
                    else ControlCommand(desired_speed_mps=13.0, safety_checks_override=True)
                )
            else:
                commands[vehicle.vehicle_id] = ControlCommand(
                    desired_speed_mps={1: 15.2, 3: 13.0}.get(level, 16.0)
                )
        return _lock_lane_changes(commands, snapshot, prefixes, mode=0)


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
