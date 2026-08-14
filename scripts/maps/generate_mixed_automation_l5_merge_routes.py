"""Generate deterministic dense demand for the L5 merge demonstration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trafficverse.controllers.merge_profiles import l5_merge_cruise_speed_mps

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = (
    REPOSITORY_ROOT / "configs/maps/mixed-automation-l5-merge" / "mixed-automation-l5-merge.rou.xml"
)
LEVEL_SEQUENCE = (5, 5, 4, 5, 3, 5, 4, 5)
MAIN_INITIAL_POSITIONS_M = {
    0: (2.5, 18.3, 34.8, 50.1, 66.7, 82.6, 98.0),
    1: (3.2, 14.1, 25.8, 37.0, 48.9, 60.0, 71.8, 83.1, 95.4),
    2: (1.8, 13.4, 24.2, 36.6, 47.5, 59.7, 70.6, 82.8, 94.0),
}
RAMP_INITIAL_POSITIONS_M = (12.5, 28.5, 44.5, 60.5, 76.5, 92.5)
OPPOSING_INITIAL_POSITIONS_M = {
    0: (4.0, 21.0, 39.5, 56.0, 74.5, 91.0, 109.5, 126.0, 145.0, 162.0, 181.0, 202.0),
    1: (2.5, 20.5, 37.0, 55.8, 72.2, 90.7, 108.5, 125.2, 143.7, 161.3, 180.1, 201.0),
    2: (5.5, 23.2, 40.1, 58.5, 75.4, 93.6, 111.0, 129.4, 146.2, 164.8, 183.0, 203.5),
}


@dataclass(frozen=True, slots=True)
class VehicleDemand:
    vehicle_id: str
    level: int
    route_id: str
    depart_s: float
    lane_index: int
    position_m: float
    insertion_checks_none: bool = False


def _level(index: int, offset: int = 0) -> int:
    return LEVEL_SEQUENCE[(index + offset) % len(LEVEL_SEQUENCE)]


def _vehicle_id(stream: str, level: int, lane_index: int, sequence: int) -> str:
    if stream == "ramp":
        return f"merge_ramp_L{level}.{sequence}"
    return f"merge_{stream}_L{level}_lane{lane_index}.{sequence}"


def _demand(
    stream: str,
    level: int,
    lane_index: int,
    sequence: int,
    *,
    route_id: str,
    depart_s: float,
    position_m: float,
    insertion_checks_none: bool = False,
) -> VehicleDemand:
    return VehicleDemand(
        vehicle_id=_vehicle_id(stream, level, lane_index, sequence),
        level=level,
        route_id=route_id,
        depart_s=depart_s,
        lane_index=lane_index,
        position_m=position_m,
        insertion_checks_none=insertion_checks_none,
    )


def build_demand() -> tuple[VehicleDemand, ...]:
    """Build dense initial traffic plus sustained sources with reproducible jitter."""
    demand: list[VehicleDemand] = []
    for lane_index, positions_m in MAIN_INITIAL_POSITIONS_M.items():
        demand.extend(
            _demand(
                "main",
                _level(index, lane_index * 2),
                lane_index,
                100 + index,
                route_id="route_main",
                depart_s=0.0,
                position_m=position_m,
                insertion_checks_none=True,
            )
            for index, position_m in enumerate(positions_m)
        )
    demand.extend(
        _demand(
            "ramp",
            _level(index, 1),
            0,
            100 + index,
            route_id="route_merge",
            depart_s=0.0,
            position_m=position_m,
            insertion_checks_none=True,
        )
        for index, position_m in enumerate(RAMP_INITIAL_POSITIONS_M)
    )
    for lane_index, positions_m in OPPOSING_INITIAL_POSITIONS_M.items():
        demand.extend(
            _demand(
                "opposing",
                _level(index, lane_index + 3),
                lane_index,
                100 + index,
                route_id="route_opposing",
                depart_s=0.0,
                position_m=position_m,
                insertion_checks_none=True,
            )
            for index, position_m in enumerate(positions_m)
        )

    demand.extend(
        _demand(
            "ramp",
            _level(index),
            0,
            index,
            route_id="route_merge",
            depart_s=0.1 + index,
            position_m=0.0,
        )
        for index in range(12)
    )
    demand.extend(
        _demand(
            "main",
            _level(index),
            0,
            index,
            route_id="route_main",
            depart_s=0.65 + index,
            position_m=0.0,
        )
        for index in range(12)
    )
    for lane_index in (1, 2):
        demand.extend(
            _demand(
                "main",
                _level(index, lane_index + 1),
                lane_index,
                index,
                route_id="route_main",
                depart_s=0.45 + lane_index * 0.2 + index * 1.2,
                position_m=0.0,
            )
            for index in range(8)
        )
    for lane_index in range(3):
        demand.extend(
            _demand(
                "opposing",
                _level(index, lane_index + 5),
                lane_index,
                index,
                route_id="route_opposing",
                depart_s=0.5 + lane_index * 0.18 + index * 1.1,
                position_m=0.0,
            )
            for index in range(8)
        )
    return tuple(
        sorted(
            demand,
            key=lambda item: (
                item.depart_s,
                item.route_id,
                item.lane_index,
                item.position_m,
                item.vehicle_id,
            ),
        )
    )


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _vehicle_type_xml(level: int, color: str) -> str:
    return (
        f'    <vType id="L{level}" vClass="passenger" length="4.8" minGap="0.3"'
        ' accel="3.4" decel="5.0" emergencyDecel="8.0" sigma="0" tau="0.05"'
        f' maxSpeed="22.22" color="{color}" lcStrategic="0" lcCooperative="1"'
        ' lcSpeedGain="0" lcKeepRight="0" />'
    )


def render_routes(demand: tuple[VehicleDemand, ...]) -> str:
    """Render SUMO route XML in stable order."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Generated by scripts/maps/generate_mixed_automation_l5_merge_routes.py. -->",
        "<routes>",
        _vehicle_type_xml(3, "192,38,211"),
        _vehicle_type_xml(4, "120,53,15"),
        _vehicle_type_xml(5, "0,0,0"),
        "",
        '    <route id="route_main" edges="main_before main_after" />',
        '    <route id="route_merge" edges="merge_ramp main_after" />',
        '    <route id="route_opposing" edges="opposing_before opposing_after" />',
        "",
    ]
    for item in demand:
        insertion_checks = ' insertionChecks="none"' if item.insertion_checks_none else ""
        lines.append(
            f'    <vehicle id="{item.vehicle_id}" type="L{item.level}" '
            f'route="{item.route_id}" depart="{_number(item.depart_s)}" '
            f'departLane="{item.lane_index}" departPos="{_number(item.position_m)}" '
            f'departSpeed="{_number(l5_merge_cruise_speed_mps(item.vehicle_id))}"'
            f"{insertion_checks} />"
        )
    lines.extend(("</routes>", ""))
    return "\n".join(lines)


def main() -> None:
    """Regenerate the tracked route file."""
    OUTPUT_PATH.write_text(render_routes(build_demand()), encoding="utf-8")


if __name__ == "__main__":
    main()
