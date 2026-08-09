from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_ROOT = REPOSITORY_ROOT / "configs/maps/mixed-automation-obstacle"
ROUTES_PATH = SCENARIO_ROOT / "mixed-automation-obstacle.rou.xml"
CONFIG_PATH = SCENARIO_ROOT / "mixed-automation-obstacle.sumocfg"


EXPECTED_KRAUSS = {
    "L0": {"minGap": "2.5", "accel": "2.6", "decel": "4.5", "sigma": "0.5", "tau": "1"},
    "L1": {"minGap": "2", "accel": "3.05", "decel": "4.5", "sigma": "0.4", "tau": "0.95"},
    "L2": {"minGap": "1.5", "accel": "3.5", "decel": "4.5", "sigma": "0.3", "tau": "0.9"},
    "L3": {"minGap": "1.25", "accel": "3.6", "decel": "4.5", "sigma": "0.2", "tau": "0.8"},
    "L4": {"minGap": "0.75", "accel": "3.7", "decel": "4.5", "sigma": "0", "tau": "0.7"},
    "L5": {"minGap": "0.5", "accel": "3.8", "decel": "4.5", "sigma": "0", "tau": "0.6"},
}


def _target_level(vehicle_id: str) -> int:
    match = re.match(r"target_L([0-5])_", vehicle_id)
    assert match is not None
    return int(match.group(1))


def test_routes_define_the_supplied_krauss_parameters() -> None:
    root = ElementTree.parse(ROUTES_PATH).getroot()

    actual = {
        element.attrib["id"]: {
            key: element.attrib[key] for key in ("minGap", "accel", "decel", "sigma", "tau")
        }
        for element in root.findall("vType")
        if element.attrib.get("id") in EXPECTED_KRAUSS
    }

    assert actual == EXPECTED_KRAUSS


def test_targets_add_twenty_four_forward_vehicles_behind_the_obstacles() -> None:
    root = ElementTree.parse(ROUTES_PATH).getroot()
    targets = [
        (
            vehicle.attrib["id"],
            vehicle.attrib["route"],
            int(vehicle.attrib["departLane"]),
            float(vehicle.attrib["departPos"]),
        )
        for vehicle in root.findall("vehicle")
        if vehicle.attrib["id"].startswith("target_")
    ]

    assert len(targets) == 60
    assert {lane for _, _, lane, _ in targets} == {0, 1, 2}
    levels = {_target_level(vehicle_id) for vehicle_id, _, _, _ in targets}
    assert levels == set(range(6))
    assert {
        route_id: sum(route == route_id for _, route, _, _ in targets)
        for route_id in ("route_fwd", "route_rev")
    } == {"route_fwd": 24, "route_rev": 36}

    forward_positions = [position for _, route, _, position in targets if route == "route_fwd"]
    assert len(forward_positions) == 24
    assert max(forward_positions) < 650.0
    open_lane_levels = [
        _target_level(vehicle_id)
        for vehicle_id, route, lane, _ in sorted(targets, key=lambda target: target[3])
        if route == "route_fwd" and lane == 2
    ]
    assert len(open_lane_levels) == 14
    assert all(
        current != following
        for current, following in zip(open_lane_levels, open_lane_levels[1:], strict=False)
    )

    expected_forward_lane_counts = (
        {0: 2, 1: 2},
        {0: 2, 1: 1, 2: 1},
        {0: 1, 1: 1, 2: 2},
        {0: 1, 2: 3},
        {2: 4},
        {2: 4},
    )
    for level in range(6):
        level_targets = [target for target in targets if _target_level(target[0]) == level]
        assert len(level_targets) == 10
        assert {
            route_id: sum(route == route_id for _, route, _, _ in level_targets)
            for route_id in ("route_fwd", "route_rev")
        } == {"route_fwd": 4, "route_rev": 6}
        event_vehicles = [
            next(
                vehicle
                for vehicle in root.findall("vehicle")
                if vehicle.attrib["id"] == f"target_L{level}_{index:03d}"
            )
            for index in range(4)
        ]
        assert {vehicle.attrib["route"] for vehicle in event_vehicles} == {"route_fwd"}
        actual_lane_counts = {
            lane_index: sum(
                int(vehicle.attrib["departLane"]) == lane_index for vehicle in event_vehicles
            )
            for lane_index in range(3)
        }
        assert {lane: count for lane, count in actual_lane_counts.items() if count} == (
            expected_forward_lane_counts[level]
        )

    for route_id in ("route_fwd", "route_rev"):
        for lane_index in range(3):
            positions = [
                position_m
                for _, route, lane, position_m in targets
                if route == route_id and lane == lane_index
            ]
            assert len(positions) == len(set(positions))


def test_routes_contain_static_road_obstacles_present_from_simulation_start() -> None:
    root = ElementTree.parse(ROUTES_PATH).getroot()
    obstacles = {
        vehicle.attrib["id"]: vehicle
        for vehicle in root.findall("vehicle")
        if vehicle.attrib["id"].startswith("static_obstacle_")
    }

    assert set(obstacles) == {"static_obstacle_0", "static_obstacle_1"}
    obstacle_type = next(
        element for element in root.findall("vType") if element.attrib["id"] == "static_obstacle"
    )
    assert obstacle_type.attrib["vClass"] == "custom1"
    assert obstacle_type.attrib["guiShape"] == "truck"
    for lane_index in (0, 1):
        vehicle = obstacles[f"static_obstacle_{lane_index}"]
        assert vehicle.attrib["depart"] == "0"
        assert vehicle.attrib["departLane"] == str(lane_index)
        assert vehicle.attrib["departPos"] == "650"
        assert vehicle.attrib["departSpeed"] == "0"
        stop = vehicle.find("stop")
        assert stop is not None
        assert stop.attrib == {
            "lane": f"road_fwd_{lane_index}",
            "endPos": "650",
            "duration": "90",
            "actType": "road_obstacle",
        }


def test_sampled_vehicle_types_vary_around_the_base_levels() -> None:
    root = ElementTree.parse(ROUTES_PATH).getroot()
    samples = [element for element in root.findall("vType") if "_sample_" in element.attrib["id"]]

    assert len(samples) == 60
    assert len({element.attrib["minGap"] for element in samples}) > 12
    assert len({element.attrib["accel"] for element in samples}) > 12
    assert len({element.attrib["tau"] for element in samples}) > 12


def test_scenario_uses_fifty_millisecond_steps_and_generated_network() -> None:
    config = ElementTree.parse(CONFIG_PATH).getroot()

    step_length = config.find("time/step-length")
    assert step_length is not None
    assert step_length.attrib["value"] == "0.05"
    collision_action = config.find("processing/collision.action")
    assert collision_action is not None
    assert collision_action.attrib["value"] == "warn"
    assert (SCENARIO_ROOT / "mixed-automation-obstacle.net.xml").is_file()


def test_generated_network_has_three_lanes_per_direction() -> None:
    network = ElementTree.parse(SCENARIO_ROOT / "mixed-automation-obstacle.net.xml").getroot()
    lanes_by_edge = {
        edge.attrib["id"]: tuple(edge.findall("lane"))
        for edge in network.findall("edge")
        if edge.attrib.get("id") in {"road_fwd", "road_rev"}
    }

    assert {edge_id: len(lanes) for edge_id, lanes in lanes_by_edge.items()} == {
        "road_fwd": 3,
        "road_rev": 3,
    }
