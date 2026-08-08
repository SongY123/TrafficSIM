"""Fast real-SUMO checks for the three mixed-automation demonstrations."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from trafficverse.adapters.sumo import SumoTrafficEngineAdapter
from trafficverse.config.models import SumoConfig
from trafficverse.controllers import MixedAutomationScenarioController
from trafficverse.domain.models import TrafficSnapshot

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAP_ROOT = REPOSITORY_ROOT / "configs/maps"
LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
LEVEL_PATTERN = re.compile(r"(?:^|_)L([0-5])(?:_|$)")
CAPTURE_TIME_MS = {
    "mixed-automation-obstacle": 32_000,
    "mixed-automation-cutin": 60_000,
    "mixed-automation-emergency-yield": 28_000,
}


@dataclass(frozen=True, slots=True)
class ScenarioMetrics:
    scenario_id: str
    simulation_time_ms: int
    active_vehicle_count: int
    active_vehicle_count_by_level: dict[str, int]
    average_speed_kmh: dict[str, float]
    minimum_speed_kmh: dict[str, float]
    maximum_speed_kmh: dict[str, float]
    slowest_vehicles: dict[str, list[str]]
    collision_vehicle_count: dict[str, int]


def _vehicle_level(vehicle_id: str) -> str | None:
    match = LEVEL_PATTERN.search(vehicle_id)
    return f"L{match.group(1)}" if match is not None else None


def _metrics(scenario_id: str, snapshot: TrafficSnapshot) -> ScenarioMetrics:
    speed_samples: dict[str, list[float]] = {level: [] for level in LEVELS}
    identified_speeds: dict[str, list[tuple[float, str]]] = {level: [] for level in LEVELS}
    for vehicle in snapshot.vehicles:
        level = vehicle.automation_level.value
        if level in speed_samples:
            speed_kmh = vehicle.speed_mps * 3.6
            speed_samples[level].append(speed_kmh)
            identified_speeds[level].append((speed_kmh, vehicle.vehicle_id))
    collision_counts = dict.fromkeys(LEVELS, 0)
    for vehicle_id in snapshot.collision_vehicle_ids:
        collision_level = _vehicle_level(vehicle_id)
        if collision_level in collision_counts:
            collision_counts[collision_level] += 1
    return ScenarioMetrics(
        scenario_id=scenario_id,
        simulation_time_ms=snapshot.simulation_time_ms,
        active_vehicle_count=len(snapshot.vehicles),
        active_vehicle_count_by_level={
            level: len(values) for level, values in speed_samples.items()
        },
        average_speed_kmh={
            level: round(sum(values) / len(values), 1) if values else 0.0
            for level, values in speed_samples.items()
        },
        minimum_speed_kmh={
            level: round(min(values), 1) if values else 0.0
            for level, values in speed_samples.items()
        },
        maximum_speed_kmh={
            level: round(max(values), 1) if values else 0.0
            for level, values in speed_samples.items()
        },
        slowest_vehicles={
            level: [f"{vehicle_id}={speed_kmh:.1f}" for speed_kmh, vehicle_id in sorted(values)[:3]]
            for level, values in identified_speeds.items()
        },
        collision_vehicle_count=collision_counts,
    )


def _validate_level_progression(metrics: ScenarioMetrics) -> None:
    speeds = [metrics.average_speed_kmh[level] for level in LEVELS]
    collisions = [metrics.collision_vehicle_count[level] for level in LEVELS]
    active_counts = [metrics.active_vehicle_count_by_level[level] for level in LEVELS]
    if any(count == 0 for count in active_counts):
        raise AssertionError(f"{metrics.scenario_id}: every automation level must remain visible")
    if any(current >= following for current, following in zip(speeds, speeds[1:], strict=False)):
        raise AssertionError(
            f"{metrics.scenario_id}: average speeds must strictly increase from L0 to L5: {speeds}"
        )
    if any(
        current < following for current, following in zip(collisions, collisions[1:], strict=False)
    ):
        raise AssertionError(
            f"{metrics.scenario_id}: collisions must not increase with automation: {collisions}"
        )
    if any(metrics.collision_vehicle_count[level] for level in ("L4", "L5")):
        raise AssertionError(f"{metrics.scenario_id}: L4-L5 vehicles must avoid collisions")
    if metrics.scenario_id in {"mixed-automation-obstacle", "mixed-automation-cutin"} and any(
        metrics.collision_vehicle_count[level] == 0 for level in ("L0", "L1", "L2", "L3")
    ):
        raise AssertionError(
            f"{metrics.scenario_id}: L0-L3 must include scripted collisions: {collisions}"
        )
    if metrics.scenario_id != "mixed-automation-emergency-yield" and collisions[0] == 0:
        raise AssertionError(f"{metrics.scenario_id}: the L0 incident was not reproduced")
    if metrics.scenario_id != "mixed-automation-obstacle" and any(
        metrics.minimum_speed_kmh[level] <= 0.0 for level in LEVELS
    ):
        raise AssertionError(
            f"{metrics.scenario_id}: traffic must recover instead of staying stopped"
        )


def run_scenario(scenario_id: str) -> ScenarioMetrics:
    capture_time_ms = CAPTURE_TIME_MS[scenario_id]
    config_path = MAP_ROOT / scenario_id / f"{scenario_id}.sumocfg"
    adapter = SumoTrafficEngineAdapter(uuid4())
    controller = MixedAutomationScenarioController(scenario_id)
    previous: TrafficSnapshot | None = None
    try:
        adapter.load(
            SumoConfig(
                launch_mode="managed",
                config_file=str(config_path),
                expected_version=None,
                connect_retries=30,
                freeze_collisions=scenario_id == "mixed-automation-obstacle",
            )
        )
        for simulation_time_ms in range(50, capture_time_ms + 50, 50):
            adapter.apply_controls(controller.step(previous, 0.05))
            previous = adapter.step(simulation_time_ms)
        if previous is None:
            raise RuntimeError("scenario produced no SUMO snapshot")
        metrics = _metrics(scenario_id, previous)
        _validate_level_progression(metrics)
        return metrics
    finally:
        adapter.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scenario_ids",
        nargs="*",
    )
    args = parser.parse_args()
    scenario_ids = tuple(args.scenario_ids) or tuple(CAPTURE_TIME_MS)
    unknown_ids = set(scenario_ids) - set(CAPTURE_TIME_MS)
    if unknown_ids:
        parser.error(f"unknown scenario ids: {', '.join(sorted(unknown_ids))}")
    metrics = [asdict(run_scenario(scenario_id)) for scenario_id in scenario_ids]
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
