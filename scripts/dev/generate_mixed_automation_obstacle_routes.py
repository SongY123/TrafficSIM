"""Generate deterministic mixed-traffic routes with normally distributed parameters."""

from __future__ import annotations

import random
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPOSITORY_ROOT / (
    "configs/maps/mixed-automation-obstacle/mixed-automation-obstacle.rou.xml"
)
RANDOM_SEED = 20260807
LEVEL_COUNT = 6
OPPOSING_PLATOON_COUNT = 2
OPPOSING_LANE_OFFSET_M = 40.0
OPPOSING_PLATOON_START_M = (80.0, 490.0)
OPPOSING_LEVEL_GAP_M = 20.0
OPPOSING_POSITION_JITTER_M = 2.0
MAX_SPEED_MPS = 27.78
COLORS = (
    "0,114,189",
    "217,83,25",
    "237,177,32",
    "46,139,87",
    "126,87,194",
    "190,63,63",
)
FORWARD_INCIDENT_TARGETS_BY_LEVEL = (
    ((0, 258.0), (1, 228.0), (0, 218.0), (1, 188.0)),
    ((0, 318.0), (1, 288.0), (0, 288.0)),
    ((0, 378.0), (1, 348.0)),
    ((0, 438.0),),
    (),
    (),
)
FORWARD_BACKGROUND_LEVELS = (1, 2, 2, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5)
FORWARD_BACKGROUND_START_M = 130.0
FORWARD_BACKGROUND_GAP_M = 35.0
FORWARD_BACKGROUND_JITTER_M = 5.0


@dataclass(frozen=True, slots=True)
class BaseKrauss:
    min_gap_m: float
    accel_mps2: float
    decel_mps2: float
    sigma: float
    tau_s: float


BASE_PARAMETERS = (
    BaseKrauss(2.5, 2.6, 4.5, 0.5, 1.0),
    BaseKrauss(2.0, 3.05, 4.5, 0.4, 0.95),
    BaseKrauss(1.5, 3.5, 4.5, 0.3, 0.9),
    BaseKrauss(1.25, 3.6, 4.5, 0.2, 0.8),
    BaseKrauss(0.75, 3.7, 4.5, 0.0, 0.7),
    BaseKrauss(0.5, 3.8, 4.5, 0.0, 0.6),
)


def _bounded_normal(
    rng: random.Random, mean: float, standard_deviation: float, lower: float, upper: float
) -> float:
    return max(lower, min(upper, rng.gauss(mean, standard_deviation)))


def _sample_parameters(rng: random.Random, level: int) -> BaseKrauss:
    base = BASE_PARAMETERS[level]
    return BaseKrauss(
        min_gap_m=_bounded_normal(rng, base.min_gap_m, 0.15, 0.25, 4.0),
        accel_mps2=_bounded_normal(rng, base.accel_mps2, 0.18, 0.5, 5.5),
        decel_mps2=_bounded_normal(rng, base.decel_mps2, 0.35, 2.0, 7.0),
        sigma=_bounded_normal(rng, base.sigma, 0.05, 0.0, 1.0),
        tau_s=_bounded_normal(rng, base.tau_s, 0.06, 0.3, 2.0),
    )


def _format(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _add_vtype(
    routes: ElementTree.Element,
    *,
    type_id: str,
    level: int,
    parameters: BaseKrauss,
) -> None:
    ElementTree.SubElement(
        routes,
        "vType",
        {
            "id": type_id,
            "vClass": "passenger",
            "length": "5.0",
            "minGap": _format(parameters.min_gap_m),
            "accel": _format(parameters.accel_mps2),
            "decel": _format(parameters.decel_mps2),
            "sigma": _format(parameters.sigma),
            "tau": _format(parameters.tau_s),
            "maxSpeed": _format(MAX_SPEED_MPS),
            "color": COLORS[level],
            "lcStrategic": "0",
            "lcCooperative": "0",
            "lcSpeedGain": "0",
            "lcKeepRight": "0",
        },
    )


def _add_vehicle(
    *,
    vehicle_id: str,
    type_id: str,
    route_id: str,
    lane_index: int,
    position_m: float,
) -> ElementTree.Element:
    return ElementTree.Element(
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


def generate_routes() -> None:
    rng = random.Random(RANDOM_SEED)
    routes = ElementTree.Element("routes")
    routes.append(
        ElementTree.Comment(f"Generated with seed {RANDOM_SEED}; per-vehicle Krauss samples.")
    )

    for level, parameters in enumerate(BASE_PARAMETERS):
        _add_vtype(routes, type_id=f"L{level}", level=level, parameters=parameters)

    vehicle_elements: list[ElementTree.Element] = []
    target_specs: list[tuple[int, str, int, float]] = []

    for level, targets in enumerate(FORWARD_INCIDENT_TARGETS_BY_LEVEL):
        target_specs.extend(
            (level, "route_fwd", lane_index, position_m) for lane_index, position_m in targets
        )
    layout_rng = random.Random(RANDOM_SEED + 101)
    background_levels = list(FORWARD_BACKGROUND_LEVELS)
    for _attempt in range(100):
        layout_rng.shuffle(background_levels)
        if all(
            current != following
            for current, following in zip(background_levels, background_levels[1:], strict=False)
        ):
            break
    else:
        raise RuntimeError("unable to interleave forward background automation levels")
    for slot_index, level in enumerate(background_levels):
        target_specs.append(
            (
                level,
                "route_fwd",
                2,
                FORWARD_BACKGROUND_START_M
                + slot_index * FORWARD_BACKGROUND_GAP_M
                + layout_rng.uniform(
                    -FORWARD_BACKGROUND_JITTER_M,
                    FORWARD_BACKGROUND_JITTER_M,
                ),
            )
        )
    for lane_index in range(3):
        for platoon_index in range(OPPOSING_PLATOON_COUNT):
            platoon_start_m = (
                OPPOSING_PLATOON_START_M[platoon_index] + lane_index * OPPOSING_LANE_OFFSET_M
            )
            for level in range(LEVEL_COUNT):
                target_specs.append(
                    (
                        level,
                        "route_rev",
                        lane_index,
                        platoon_start_m
                        + level * OPPOSING_LEVEL_GAP_M
                        + rng.uniform(
                            -OPPOSING_POSITION_JITTER_M,
                            OPPOSING_POSITION_JITTER_M,
                        ),
                    )
                )
    target_indices = [0] * LEVEL_COUNT
    for sample_index, (level, route_id, lane_index, position_m) in enumerate(target_specs):
        vehicle_index = target_indices[level]
        target_indices[level] += 1
        type_id = f"L{level}_sample_{sample_index:03d}"
        _add_vtype(routes, type_id=type_id, level=level, parameters=_sample_parameters(rng, level))
        vehicle_elements.append(
            _add_vehicle(
                vehicle_id=f"target_L{level}_{vehicle_index:03d}",
                type_id=type_id,
                route_id=route_id,
                lane_index=lane_index,
                position_m=position_m,
            )
        )
    ElementTree.SubElement(
        routes,
        "vType",
        {
            "id": "static_obstacle",
            "vClass": "custom1",
            "length": "6.0",
            "minGap": "0.1",
            "accel": "2.0",
            "decel": "9.0",
            "maxSpeed": _format(MAX_SPEED_MPS),
            "color": "255,190,40",
            "guiShape": "truck",
        },
    )
    ElementTree.SubElement(routes, "route", {"id": "route_fwd", "edges": "road_fwd"})
    ElementTree.SubElement(routes, "route", {"id": "route_rev", "edges": "road_rev"})
    for lane_index in (0, 1):
        vehicle = ElementTree.Element(
            "vehicle",
            {
                "id": f"static_obstacle_{lane_index}",
                "type": "static_obstacle",
                "route": "route_fwd",
                "depart": "0",
                "departLane": str(lane_index),
                "departPos": "650",
                "departSpeed": "0",
            },
        )
        ElementTree.SubElement(
            vehicle,
            "stop",
            {
                "lane": f"road_fwd_{lane_index}",
                "endPos": "650",
                "duration": "90",
                "actType": "road_obstacle",
            },
        )
        vehicle_elements.append(vehicle)

    # Vehicles sharing one departure time are written rear-to-front per lane. This
    # lets SUMO insert the designed distribution without a front vehicle blocking it.
    for vehicle in sorted(
        vehicle_elements,
        key=lambda item: (
            float(item.attrib["depart"]),
            item.attrib["route"],
            -int(item.attrib["departLane"]),
            float(item.attrib["departPos"]),
        ),
    ):
        routes.append(vehicle)

    ElementTree.indent(routes, space="    ")
    OUTPUT_PATH.write_text(
        ElementTree.tostring(routes, encoding="unicode", xml_declaration=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate_routes()
