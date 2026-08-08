"""Run the bidirectional mixed-automation obstacle scenario with SUMO TraCI."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import shutil
import sys
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import traci  # type: ignore[import-untyped]

LOGGER = logging.getLogger("mixed_automation_obstacle")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIRECTORY = REPOSITORY_ROOT / "configs/maps/mixed-automation-obstacle"
SCENARIO_CONFIG = SCENARIO_DIRECTORY / "mixed-automation-obstacle.sumocfg"
FORWARD_EDGE_ID = "road_fwd"
OBSTACLE_TIME_S = 0.0
OBSTACLE_POSITION_M = 650.0
SIMULATION_END_S = 90.0
BLOCKED_LANE_INDICES = frozenset({0, 1})
OPEN_LANE_INDEX = 2
OBSTACLE_IDS = ("obstacle_right_0", "obstacle_right_1")
CONTROLLED_LANE_CHANGE_MODE = 512
L0_FAILURE_SPEED_MPS = 27.78
RECOVERY_HOLD_S = 6.0
RECOVERY_SPEED_MPS = 8.0
BEHAVIOR_SEED = 20260807
TARGET_ID_PATTERN = re.compile(r"^target_L([0-5])_")


@dataclass(frozen=True, slots=True)
class VehicleBehavior:
    """Per-vehicle randomized response thresholds derived from its stable ID."""

    brake_trigger_distance_m: float | None
    brake_duration_s: float | None
    lane_change_trigger_distance_m: float | None


def _target_level(vehicle_id: str) -> int | None:
    match = TARGET_ID_PATTERN.match(vehicle_id)
    return int(match.group(1)) if match is not None else None


def _collision_counts_by_level(collisions: Collection[str]) -> dict[str, int]:
    """Count unique colliding target vehicles for each automation level."""
    counts = {str(level): 0 for level in range(6)}
    for vehicle_id in collisions:
        level = _target_level(vehicle_id)
        if level is not None:
            counts[str(level)] += 1
    return counts


def _present_target_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            vehicle_id
            for vehicle_id in traci.vehicle.getIDList()
            if _target_level(vehicle_id) is not None
        )
    )


def _bounded_normal(
    rng: random.Random, mean: float, standard_deviation: float, lower: float, upper: float
) -> float:
    return max(lower, min(upper, rng.gauss(mean, standard_deviation)))


def _behavior_for_vehicle(vehicle_id: str, level: int) -> VehicleBehavior:
    """Give vehicles of one level slightly different reaction timing."""
    rng = random.Random(f"{BEHAVIOR_SEED}:{vehicle_id}")
    if level == 0:
        return VehicleBehavior(
            brake_trigger_distance_m=_bounded_normal(rng, 65.0, 25.0, 25.0, 120.0),
            brake_duration_s=_bounded_normal(rng, 1.2, 0.25, 0.6, 2.0),
            lane_change_trigger_distance_m=None,
        )
    if level <= 3:
        mean = (110.0, 150.0, 220.0)[level - 1]
        lower = (60.0, 100.0, 170.0)[level - 1]
        upper = (140.0, 185.0, 270.0)[level - 1]
        duration = (1.0, 3.0, 4.0)[level - 1]
        return VehicleBehavior(
            brake_trigger_distance_m=_bounded_normal(rng, mean, 20.0, lower, upper),
            brake_duration_s=_bounded_normal(rng, duration, 0.4, 0.5, 6.0),
            lane_change_trigger_distance_m=None,
        )
    mean = 180.0 if level == 4 else 260.0
    return VehicleBehavior(
        brake_trigger_distance_m=None,
        brake_duration_s=None,
        lane_change_trigger_distance_m=_bounded_normal(rng, mean, 25.0, 120.0, 330.0),
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sumo-binary",
        default=None,
        help="SUMO executable name or path; defaults to sumo-gui, or sumo with --no-gui.",
    )
    parser.add_argument("--duration-s", type=float, default=SIMULATION_END_S)
    parser.add_argument("--obstacle-time-s", type=float, default=OBSTACLE_TIME_S)
    parser.add_argument(
        "--l0-crash",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep L0 at its original speed after late detection; default is enabled.",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=None,
        help=(
            "GUI delay between simulation steps in milliseconds; default comes from the view file."
        ),
    )
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--port", type=int, default=8813)
    return parser.parse_args(argv)


def _resolve_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise RuntimeError(f"SUMO executable is not available on PATH: {name}")
    return binary


def _ensure_macos_display(use_gui: bool) -> None:
    if use_gui and sys.platform == "darwin":
        os.environ.setdefault("DISPLAY", ":0")


def _start_sumo(binary: str, *, use_gui: bool, port: int, delay_ms: int | None) -> None:
    command = [binary, "-c", str(SCENARIO_CONFIG)]
    if use_gui:
        command.append("--start")
        if delay_ms is not None:
            command.extend(("--delay", str(delay_ms)))
    traci.start(command, port=port)


def _find_present_obstacles() -> tuple[str, ...]:
    present_ids = set(traci.vehicle.getIDList())
    return tuple(obstacle_id for obstacle_id in OBSTACLE_IDS if obstacle_id in present_ids)


def _configure_target_lane_changes(configured_targets: set[str]) -> None:
    """Disable SUMO autonomous lane changes while keeping TraCI safety checks."""
    present_ids = set(traci.vehicle.getIDList())
    for vehicle_id in _present_target_ids():
        if vehicle_id in present_ids and vehicle_id not in configured_targets:
            traci.vehicle.setLaneChangeMode(vehicle_id, CONTROLLED_LANE_CHANGE_MODE)
            configured_targets.add(vehicle_id)


def _apply_l0_failure_behavior(
    *,
    configured_vehicles: set[str],
    acted: set[str],
    frozen_vehicles: set[str],
) -> None:
    """Give each blocked L0 vehicle a late, imperfect brake response."""
    for vehicle_id in _present_target_ids():
        if _target_level(vehicle_id) != 0 or vehicle_id in frozen_vehicles:
            continue
        distance = _distance_to_obstacle(vehicle_id)
        if distance is None or distance <= 0:
            continue
        if vehicle_id not in configured_vehicles:
            traci.vehicle.setSpeedMode(vehicle_id, 0)
            traci.vehicle.setSpeed(vehicle_id, L0_FAILURE_SPEED_MPS)
            configured_vehicles.add(vehicle_id)
            LOGGER.info(
                json.dumps(
                    {
                        "event": "l0_late_detection_mode",
                        "vehicle_id": vehicle_id,
                        "speed_mode": 0,
                        "lane_change_mode": CONTROLLED_LANE_CHANGE_MODE,
                    },
                    ensure_ascii=False,
                )
            )
        behavior = _behavior_for_vehicle(vehicle_id, 0)
        action_key = f"brake:{vehicle_id}"
        if (
            behavior.brake_trigger_distance_m is not None
            and behavior.brake_duration_s is not None
            and distance <= behavior.brake_trigger_distance_m
            and action_key not in acted
        ):
            traci.vehicle.slowDown(vehicle_id, 0.0, behavior.brake_duration_s)
            acted.add(action_key)
            LOGGER.info(
                json.dumps(
                    {
                        "event": "brake_requested",
                        "vehicle_id": vehicle_id,
                        "level": 0,
                        "simulation_time_s": traci.simulation.getTime(),
                        "distance_to_obstacle_m": round(distance, 2),
                        "duration_s": round(behavior.brake_duration_s, 2),
                    },
                    ensure_ascii=False,
                )
            )


def _freeze_collision_vehicles(collision_ids: set[str], frozen_vehicles: set[str]) -> None:
    """Freeze and highlight vehicles at the first detected collision."""
    present_ids = set(traci.vehicle.getIDList())
    for vehicle_id in collision_ids:
        if vehicle_id not in present_ids:
            continue
        traci.vehicle.setSpeedMode(vehicle_id, 0)
        traci.vehicle.setSpeed(vehicle_id, 0.0)
        traci.vehicle.setColor(
            vehicle_id,
            (255, 0, 255, 255) if vehicle_id.startswith("target_") else (255, 80, 0, 255),
        )
        frozen_vehicles.add(vehicle_id)
    if collision_ids:
        LOGGER.warning(
            json.dumps(
                {
                    "event": "collision_frozen",
                    "vehicle_ids": tuple(sorted(collision_ids & present_ids)),
                    "simulation_time_s": traci.simulation.getTime(),
                },
                ensure_ascii=False,
            )
        )


def _maintain_frozen_vehicles(frozen_vehicles: set[str]) -> None:
    """Keep collision vehicles stopped while the GUI remains observable."""
    present_ids = set(traci.vehicle.getIDList())
    for vehicle_id in frozen_vehicles & present_ids:
        traci.vehicle.setSpeedMode(vehicle_id, 0)
        traci.vehicle.setSpeed(vehicle_id, 0.0)


def _distance_to_obstacle(vehicle_id: str) -> float | None:
    lane_id = traci.vehicle.getLaneID(vehicle_id)
    if not lane_id.startswith(f"{FORWARD_EDGE_ID}_"):
        return None
    lane_index = int(lane_id.rsplit("_", maxsplit=1)[1])
    if lane_index not in BLOCKED_LANE_INDICES:
        return None
    lane_position_m = cast(float, traci.vehicle.getLanePosition(vehicle_id))
    return OBSTACLE_POSITION_M - lane_position_m


def _apply_level_behavior(
    vehicle_id: str,
    level: int,
    behavior: VehicleBehavior,
    *,
    acted: set[str],
) -> None:
    if vehicle_id not in traci.vehicle.getIDList():
        return
    distance = _distance_to_obstacle(vehicle_id)
    if distance is None or distance <= 0:
        return

    if behavior.lane_change_trigger_distance_m is not None:
        action_key = f"lane-change:{vehicle_id}"
        current_lane_id = traci.vehicle.getLaneID(vehicle_id)
        if current_lane_id.endswith(f"_{OPEN_LANE_INDEX}"):
            return
        if distance <= behavior.lane_change_trigger_distance_m and action_key not in acted:
            traci.vehicle.changeLane(vehicle_id, OPEN_LANE_INDEX, duration=20.0)
            acted.add(action_key)
            LOGGER.info(
                json.dumps(
                    {
                        "event": "lane_change_requested",
                        "vehicle_id": vehicle_id,
                        "level": level,
                        "simulation_time_s": traci.simulation.getTime(),
                        "target_lane": OPEN_LANE_INDEX,
                    },
                    ensure_ascii=False,
                )
            )
        return

    if behavior.brake_trigger_distance_m is not None and behavior.brake_duration_s is not None:
        action_key = f"brake:{vehicle_id}"
        if distance <= behavior.brake_trigger_distance_m and action_key not in acted:
            traci.vehicle.slowDown(vehicle_id, 0.0, behavior.brake_duration_s)
            acted.add(action_key)
            LOGGER.info(
                json.dumps(
                    {
                        "event": "brake_requested",
                        "vehicle_id": vehicle_id,
                        "level": level,
                        "simulation_time_s": traci.simulation.getTime(),
                        "distance_to_obstacle_m": round(distance, 2),
                        "duration_s": round(behavior.brake_duration_s, 2),
                    },
                    ensure_ascii=False,
                )
            )


def _recover_stopped_vehicle(
    vehicle_id: str,
    level: int,
    *,
    stopped_since_s: dict[str, float],
    recovered: set[str],
    frozen_vehicles: set[str],
    acted: set[str],
) -> None:
    """After waiting, let a stopped low-level vehicle merge into the open lane."""
    if level > 3 or vehicle_id in frozen_vehicles or vehicle_id in recovered:
        return
    if _distance_to_obstacle(vehicle_id) is None:
        stopped_since_s.pop(vehicle_id, None)
        return
    speed_mps = cast(float, traci.vehicle.getSpeed(vehicle_id))
    now_s = traci.simulation.getTime()
    if speed_mps > 0.5:
        stopped_since_s.pop(vehicle_id, None)
        return
    stopped_since_s.setdefault(vehicle_id, now_s)
    if now_s - stopped_since_s[vehicle_id] < RECOVERY_HOLD_S:
        return
    traci.vehicle.changeLane(vehicle_id, OPEN_LANE_INDEX, duration=30.0)
    traci.vehicle.slowDown(vehicle_id, RECOVERY_SPEED_MPS, duration=5.0)
    recovered.add(vehicle_id)
    acted.add(f"recover:{vehicle_id}")
    LOGGER.info(
        json.dumps(
            {
                "event": "stopped_vehicle_recovery",
                "vehicle_id": vehicle_id,
                "level": level,
                "simulation_time_s": now_s,
                "target_lane": OPEN_LANE_INDEX,
            },
            ensure_ascii=False,
        )
    )


def run_scenario(
    *,
    use_gui: bool,
    duration_s: float,
    obstacle_time_s: float,
    port: int,
    sumo_binary: str | None = None,
    delay_ms: int | None = None,
    l0_crash: bool = True,
) -> dict[str, object]:
    """Run the bidirectional scenario and return a deterministic run summary."""
    _ensure_macos_display(use_gui)
    binary = _resolve_binary(sumo_binary or ("sumo-gui" if use_gui else "sumo"))
    obstacle_ids: tuple[str, ...] = ()
    collisions: set[str] = set()
    acted: set[str] = set()
    configured_targets: set[str] = set()
    l0_failure_configured: set[str] = set()
    frozen_collision_vehicles: set[str] = set()
    stopped_since_s: dict[str, float] = {}
    recovered_vehicles: set[str] = set()
    behavior_by_vehicle: dict[str, VehicleBehavior] = {}
    target_ids_seen: set[str] = set()
    minimum_speeds_mps: dict[str, float] = {}
    final_lanes: dict[str, str] = {}
    obstacles_present = False
    obstacle_log_emitted = False
    try:
        _start_sumo(binary, use_gui=use_gui, port=port, delay_ms=delay_ms)
        while traci.simulation.getTime() < duration_s:
            current_time_s = traci.simulation.getTime()
            _configure_target_lane_changes(configured_targets)
            _maintain_frozen_vehicles(frozen_collision_vehicles)
            if not obstacles_present and current_time_s >= obstacle_time_s:
                obstacle_ids = _find_present_obstacles()
                obstacles_present = len(obstacle_ids) == len(OBSTACLE_IDS)
            if obstacles_present and not obstacle_log_emitted:
                LOGGER.info(
                    json.dumps(
                        {
                            "event": "obstacles_present",
                            "simulation_time_s": current_time_s,
                            "obstacle_ids": obstacle_ids,
                            "position_m": OBSTACLE_POSITION_M,
                            "blocked_lanes": tuple(sorted(BLOCKED_LANE_INDICES)),
                        },
                        ensure_ascii=False,
                    )
                )
                obstacle_log_emitted = True
            if obstacles_present:
                if l0_crash:
                    _apply_l0_failure_behavior(
                        configured_vehicles=l0_failure_configured,
                        acted=acted,
                        frozen_vehicles=frozen_collision_vehicles,
                    )
                for vehicle_id in _present_target_ids():
                    level = _target_level(vehicle_id)
                    if level is None:
                        continue
                    target_ids_seen.add(vehicle_id)
                    behavior = behavior_by_vehicle.setdefault(
                        vehicle_id, _behavior_for_vehicle(vehicle_id, level)
                    )
                    if not (l0_crash and level == 0):
                        _apply_level_behavior(
                            vehicle_id,
                            level,
                            behavior,
                            acted=acted,
                        )
                    _recover_stopped_vehicle(
                        vehicle_id,
                        level,
                        stopped_since_s=stopped_since_s,
                        recovered=recovered_vehicles,
                        frozen_vehicles=frozen_collision_vehicles,
                        acted=acted,
                    )
            traci.simulationStep()
            new_collisions = set(traci.simulation.getCollidingVehiclesIDList())
            if new_collisions:
                _freeze_collision_vehicles(new_collisions, frozen_collision_vehicles)
            collisions.update(new_collisions)
            present_ids = set(traci.vehicle.getIDList())
            for vehicle_id in present_ids:
                if _target_level(vehicle_id) is not None:
                    target_ids_seen.add(vehicle_id)
                if _target_level(vehicle_id) is None:
                    continue
                speed_mps = cast(float, traci.vehicle.getSpeed(vehicle_id))
                minimum_speeds_mps[vehicle_id] = min(
                    minimum_speeds_mps.get(vehicle_id, float("inf")), speed_mps
                )
                final_lanes[vehicle_id] = cast(str, traci.vehicle.getLaneID(vehicle_id))
    finally:
        if traci.isLoaded():
            # SUMO-GUI keeps its native window alive after a TraCI close; do not
            # wait for the GUI process here, otherwise the runner cannot return.
            traci.close(False)
    return {
        "scenario": "mixed-automation-obstacle",
        "simulation_end_s": duration_s,
        "obstacles_present": obstacles_present,
        "obstacle_count": len(obstacle_ids),
        "target_count": len(target_ids_seen),
        "blocked_lane_indices": tuple(sorted(BLOCKED_LANE_INDICES)),
        "colliding_vehicle_ids": tuple(sorted(collisions)),
        "collision_counts_by_level": _collision_counts_by_level(collisions),
        "frozen_collision_vehicle_ids": tuple(sorted(frozen_collision_vehicles)),
        "actions": tuple(sorted(acted)),
        "target_min_speed_mps": {
            vehicle_id: round(minimum_speeds_mps[vehicle_id], 2)
            for vehicle_id in sorted(target_ids_seen)
            if vehicle_id in minimum_speeds_mps
        },
        "target_final_lane_ids": final_lanes,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scenario from the command line."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    summary = run_scenario(
        use_gui=not args.no_gui,
        duration_s=args.duration_s,
        obstacle_time_s=args.obstacle_time_s,
        port=args.port,
        sumo_binary=args.sumo_binary,
        delay_ms=args.delay_ms,
        l0_crash=args.l0_crash,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
