"""Generate dense, reproducible route assets for the cut-in and emergency scenes."""

from __future__ import annotations

import random
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAP_ROOT = REPOSITORY_ROOT / "configs/maps"
CUTIN_OUTPUT_PATH = MAP_ROOT / "mixed-automation-cutin/mixed-automation-cutin.rou.xml"
EMERGENCY_OUTPUT_PATH = MAP_ROOT / (
    "mixed-automation-emergency-yield/mixed-automation-emergency-yield.rou.xml"
)
RANDOM_SEED = 20260808
LEVEL_COUNT = 6
CUTIN_TARGETS_PER_LEVEL = 12
CUTIN_ACTORS_PER_LEVEL = 4
CUTIN_L0_FOLLOWER_COUNT = 4
EMERGENCY_VEHICLES_PER_LEVEL = 12


@dataclass(frozen=True, slots=True)
class VehicleType:
    min_gap_m: float
    accel_mps2: float
    decel_mps2: float
    sigma: float
    tau_s: float
    color: str


VEHICLE_TYPES = (
    VehicleType(1.5, 2.4, 4.0, 0.5, 1.2, "245,108,108"),
    VehicleType(1.5, 2.6, 4.5, 0.35, 1.0, "230,162,60"),
    VehicleType(1.4, 2.8, 5.0, 0.2, 0.9, "245,205,80"),
    VehicleType(1.3, 3.0, 5.0, 0.1, 0.8, "64,158,255"),
    VehicleType(1.2, 3.2, 5.0, 0.05, 0.7, "103,194,58"),
    VehicleType(1.0, 3.4, 5.0, 0.0, 0.6, "167,139,250"),
)


def _format(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _add_vehicle_types(routes: ElementTree.Element) -> None:
    for level, vehicle_type in enumerate(VEHICLE_TYPES):
        ElementTree.SubElement(
            routes,
            "vType",
            {
                "id": f"L{level}",
                "vClass": "passenger",
                "length": "5",
                "minGap": _format(vehicle_type.min_gap_m),
                "accel": _format(vehicle_type.accel_mps2),
                "decel": _format(vehicle_type.decel_mps2),
                "sigma": _format(vehicle_type.sigma),
                "tau": _format(vehicle_type.tau_s),
                "maxSpeed": "27.78",
                "color": vehicle_type.color,
                "lcStrategic": "0",
                "lcCooperative": "0",
                "lcSpeedGain": "0",
                "lcKeepRight": "0",
            },
        )


def _add_vehicle(
    routes: ElementTree.Element,
    *,
    vehicle_id: str,
    type_id: str,
    route_id: str = "route_fwd",
    lane_index: int,
    position_m: float,
) -> None:
    ElementTree.SubElement(
        routes,
        "vehicle",
        {
            "id": vehicle_id,
            "type": type_id,
            "route": route_id,
            "depart": "0",
            "departLane": str(lane_index),
            "departPos": _format(position_m),
            "departSpeed": "0",
        },
    )


def _write_routes(routes: ElementTree.Element, output_path: Path) -> None:
    vehicles = list(routes.findall("vehicle"))
    for vehicle in vehicles:
        routes.remove(vehicle)
    vehicles.sort(
        key=lambda vehicle: (
            float(vehicle.attrib["depart"]),
            vehicle.attrib["route"],
            -int(vehicle.attrib["departLane"]),
            float(vehicle.attrib["departPos"]),
        )
    )
    routes.extend(vehicles)
    ElementTree.indent(routes, space="    ")
    output_path.write_text(
        ElementTree.tostring(routes, encoding="unicode", xml_declaration=True) + "\n",
        encoding="utf-8",
    )


def generate_cutin_routes() -> None:
    rng = random.Random(RANDOM_SEED)
    routes = ElementTree.Element("routes")
    routes.append(
        ElementTree.Comment(
            f"Generated with seed {RANDOM_SEED}; 24 cut-ins are distributed across dense traffic."
        )
    )
    _add_vehicle_types(routes)
    ElementTree.SubElement(routes, "route", {"id": "route_fwd", "edges": "road_fwd"})
    ElementTree.SubElement(
        routes,
        "route",
        {"id": "route_loop", "edges": "road_fwd road_rev road_fwd road_rev"},
    )
    ElementTree.SubElement(
        routes,
        "route",
        {"id": "route_background_reverse", "edges": "road_rev"},
    )

    # Four event groups each contain L0-L5. Higher levels sit farther ahead so
    # deliberate low-level impacts do not cascade into the other demonstrations.
    for pair_index, group_base_m in enumerate((80.0, 410.0, 740.0, 1070.0)):
        for level in range(LEVEL_COUNT):
            position_m = group_base_m + level * 30.0 + rng.uniform(-1.0, 1.0)
            _add_vehicle(
                routes,
                vehicle_id=f"cutin_target_L{level}_{pair_index:03d}",
                type_id=f"L{level}",
                lane_index=1,
                position_m=position_m,
            )
            _add_vehicle(
                routes,
                vehicle_id=f"cutin_actor_L{level}_{pair_index:03d}",
                type_id=f"L{level}",
                lane_index=0,
                position_m=position_m + 13.0,
            )
            if level == 0 and pair_index < CUTIN_L0_FOLLOWER_COUNT:
                _add_vehicle(
                    routes,
                    vehicle_id=f"cutin_follower_L0_{pair_index:03d}",
                    type_id="L0",
                    lane_index=1,
                    position_m=position_m - 10.5,
                )

    # Three independent streams spread every level across both directions. Faster
    # levels stay ahead inside each stream, preserving the intended speed gradient
    # without secondary impacts on the loop's shared U-turn lane.
    background_streams = (
        ("route_loop", 2, 2, 80.0, 80.0),
        ("route_background_reverse", 0, 3, 30.0, 50.0),
        ("route_background_reverse", 1, 3, 100.0, 48.0),
    )
    background_indices = [CUTIN_ACTORS_PER_LEVEL] * LEVEL_COUNT
    for route_id, lane_index, copies_per_level, start_m, gap_m in background_streams:
        for level in range(LEVEL_COUNT):
            for copy_index in range(copies_per_level):
                vehicle_index = background_indices[level]
                background_indices[level] += 1
                stream_slot = level * copies_per_level + copy_index
                _add_vehicle(
                    routes,
                    vehicle_id=f"cutin_target_L{level}_{vehicle_index:03d}",
                    type_id=f"L{level}",
                    route_id=route_id,
                    lane_index=lane_index,
                    position_m=start_m + stream_slot * gap_m + rng.uniform(-3.0, 3.0),
                )
    _write_routes(routes, CUTIN_OUTPUT_PATH)


def generate_emergency_routes() -> None:
    rng = random.Random(RANDOM_SEED + 1)
    routes = ElementTree.Element("routes")
    routes.append(
        ElementTree.Comment(
            f"Generated with seed {RANDOM_SEED + 1}; dense mixed traffic precedes the ambulance."
        )
    )
    _add_vehicle_types(routes)
    ElementTree.SubElement(
        routes,
        "vType",
        {
            "id": "ambulance",
            "vClass": "emergency",
            "guiShape": "emergency",
            "length": "6",
            "minGap": "1",
            "accel": "4",
            "decel": "7",
            "sigma": "0",
            "tau": "0.5",
            "maxSpeed": "33.33",
            "color": "255,45,145",
            "lcStrategic": "0",
            "lcCooperative": "0",
            "lcSpeedGain": "0",
            "lcKeepRight": "0",
        },
    )
    ElementTree.SubElement(routes, "route", {"id": "route_fwd", "edges": "road_fwd"})
    ElementTree.SubElement(routes, "route", {"id": "route_rev", "edges": "road_rev"})
    _add_vehicle(
        routes,
        vehicle_id="ambulance_L5_0",
        type_id="ambulance",
        lane_index=1,
        position_m=50.0,
    )

    level_indices = [0] * LEVEL_COUNT
    for group_base_m in (190.0, 590.0, 990.0):
        for level in range(LEVEL_COUNT):
            vehicle_index = level_indices[level]
            level_indices[level] += 1
            _add_vehicle(
                routes,
                vehicle_id=f"yield_L{level}_{vehicle_index:03d}",
                type_id=f"L{level}",
                lane_index=1,
                position_m=group_base_m + level * 34.0 + rng.uniform(-1.0, 1.0),
            )

    # Nine vehicles per level form four dense, bidirectional streams. The streams
    # are independent of the ambulance corridor, so each level can retain its
    # visible cruise-speed advantage without a low-level queue blocking the rest.
    background_streams = (
        ("route_fwd", 2, (40.0, 380.0, 720.0)),
        ("route_rev", 0, (50.0, 500.0)),
        ("route_rev", 1, (90.0, 540.0)),
        ("route_rev", 2, (130.0, 580.0)),
    )
    for route_id, lane_index, group_bases_m in background_streams:
        for group_base_m in group_bases_m:
            for level in range(LEVEL_COUNT):
                vehicle_index = level_indices[level]
                level_indices[level] += 1
                _add_vehicle(
                    routes,
                    vehicle_id=f"yield_L{level}_{vehicle_index:03d}",
                    type_id=f"L{level}",
                    route_id=route_id,
                    lane_index=lane_index,
                    position_m=group_base_m + level * 20.0 + rng.uniform(-1.0, 1.0),
                )
    _write_routes(routes, EMERGENCY_OUTPUT_PATH)


def generate_routes() -> None:
    generate_cutin_routes()
    generate_emergency_routes()


if __name__ == "__main__":
    generate_routes()
