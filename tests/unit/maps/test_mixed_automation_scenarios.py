from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from trafficverse.maps.sumo_package import load_sumo_package

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAP_ROOT = REPOSITORY_ROOT / "configs/maps"


@pytest.mark.parametrize(
    "scenario_id",
    (
        "mixed-automation-obstacle",
        "mixed-automation-cutin",
        "mixed-automation-emergency-yield",
        "mixed-automation-occasional-accident",
    ),
)
def test_mixed_automation_package_is_self_contained_and_uses_core_step(
    scenario_id: str,
) -> None:
    config = MAP_ROOT / scenario_id / f"{scenario_id}.sumocfg"

    package = load_sumo_package(config, allowed_root=MAP_ROOT)

    assert package.package_id == scenario_id
    assert package.traffic_demand_mode == "scripted"
    assert package.step_ms == 50
    assert package.network_path.parent == config.parent
    assert package.route_paths == (config.parent / f"{scenario_id}.rou.xml",)


def test_cutin_routes_are_dense_randomly_mixed_and_have_repeated_intrusions() -> None:
    route_path = MAP_ROOT / "mixed-automation-cutin/mixed-automation-cutin.rou.xml"
    root = ElementTree.parse(route_path).getroot()
    vehicles = {vehicle.attrib["id"]: vehicle.attrib for vehicle in root.findall("vehicle")}

    assert {vehicle_type.attrib["id"] for vehicle_type in root.findall("vType")} == {
        f"L{level}" for level in range(6)
    }
    for level in range(6):
        targets = {
            vehicle_id: attributes
            for vehicle_id, attributes in vehicles.items()
            if vehicle_id.startswith(f"cutin_target_L{level}_")
        }
        actors = {
            vehicle_id: attributes
            for vehicle_id, attributes in vehicles.items()
            if vehicle_id.startswith(f"cutin_actor_L{level}_")
        }
        assert len(targets) == 12
        assert len(actors) == 4
        for index in range(4):
            target = targets[f"cutin_target_L{level}_{index:03d}"]
            intruder = actors[f"cutin_actor_L{level}_{index:03d}"]
            assert target["departLane"] == "1"
            assert intruder["departLane"] == "0"
            gap_m = float(intruder["departPos"]) - float(target["departPos"])
            assert gap_m == pytest.approx(13.0, abs=0.01)
        assert {attributes["departSpeed"] for attributes in targets.values()} == {"0"}
        background = [
            attributes
            for vehicle_id, attributes in targets.items()
            if int(vehicle_id.rsplit("_", maxsplit=1)[1]) >= 4
        ]
        assert {attributes["route"] for attributes in background} == {
            "route_loop",
            "route_background_reverse",
        }
        background_lanes = {attributes["departLane"] for attributes in background}
        assert background_lanes == {"0", "1", "2"}
        assert {(attributes["route"], attributes["departLane"]) for attributes in background} == {
            ("route_loop", "2"),
            ("route_background_reverse", "0"),
            ("route_background_reverse", "1"),
        }
        assert sum(attributes["route"] == "route_loop" for attributes in background) == 2
        assert (
            sum(attributes["route"] == "route_background_reverse" for attributes in background) == 6
        )

    background_streams: dict[tuple[str, str], list[tuple[str, dict[str, str]]]] = {}
    for vehicle_id, attributes in vehicles.items():
        if not vehicle_id.startswith("cutin_target_"):
            continue
        if int(vehicle_id.rsplit("_", maxsplit=1)[1]) < 4:
            continue
        key = (attributes["route"], attributes["departLane"])
        background_streams.setdefault(key, []).append((vehicle_id, attributes))
    assert set(background_streams) == {
        ("route_loop", "2"),
        ("route_background_reverse", "0"),
        ("route_background_reverse", "1"),
    }
    for stream_key, stream in background_streams.items():
        ordered_levels = [
            vehicle_id.split("_L", maxsplit=1)[1][0]
            for vehicle_id, _ in sorted(
                stream,
                key=lambda item: float(item[1]["departPos"]),
            )
        ]
        maximum_run_length = 2 if stream_key == ("route_loop", "2") else 3
        assert len(ordered_levels) == maximum_run_length * 6
        assert all(
            len(set(ordered_levels[index : index + maximum_run_length + 1])) > 1
            for index in range(len(ordered_levels) - maximum_run_length)
        )

    followers = {
        vehicle_id: attributes
        for vehicle_id, attributes in vehicles.items()
        if vehicle_id.startswith("cutin_follower_L0_")
    }
    assert len(followers) == 4
    assert {attributes["departLane"] for attributes in followers.values()} == {"1"}

    assert len(vehicles) == 100


def test_emergency_routes_are_dense_and_randomly_mix_all_yield_levels() -> None:
    route_path = (
        MAP_ROOT / "mixed-automation-emergency-yield/mixed-automation-emergency-yield.rou.xml"
    )
    root = ElementTree.parse(route_path).getroot()
    vehicles = {vehicle.attrib["id"]: vehicle.attrib for vehicle in root.findall("vehicle")}

    assert "ambulance_L5_0" in vehicles
    assert vehicles["ambulance_L5_0"]["departLane"] == "1"
    for level in range(6):
        level_vehicles = {
            vehicle_id: attributes
            for vehicle_id, attributes in vehicles.items()
            if vehicle_id.startswith(f"yield_L{level}_")
        }
        assert len(level_vehicles) == 12
        assert {attributes["departLane"] for attributes in level_vehicles.values()} == {
            "0",
            "1",
            "2",
        }
        assert {attributes["route"] for attributes in level_vehicles.values()} == {
            "route_fwd",
            "route_rev",
        }
        assert {attributes["departSpeed"] for attributes in level_vehicles.values()} == {"0"}

    ordered_levels = [
        vehicle_id.split("_L", maxsplit=1)[1][0]
        for vehicle_id, attributes in sorted(
            vehicles.items(),
            key=lambda item: float(item[1]["departPos"]),
        )
        if vehicle_id.startswith("yield_")
    ]
    assert len(vehicles) == 73
    assert len(set(ordered_levels[:12])) >= 5


def test_occasional_accident_uses_a_curved_one_way_two_lane_road_and_ordered_cars() -> None:
    scenario_id = "mixed-automation-occasional-accident"
    directory = MAP_ROOT / scenario_id
    network_root = ElementTree.parse(directory / f"{scenario_id}.net.xml").getroot()
    node_root = ElementTree.parse(directory / f"{scenario_id}.nod.xml").getroot()
    route_root = ElementTree.parse(directory / f"{scenario_id}.rou.xml").getroot()
    config_root = ElementTree.parse(directory / f"{scenario_id}.sumocfg").getroot()

    road = next(edge for edge in network_root.findall("edge") if edge.attrib["id"] == "road_curve")
    lanes = road.findall("lane")
    assert len(lanes) == 2
    lane_shape = lanes[0].attrib["shape"]
    assert len({point.split(",")[1] for point in lane_shape.split()}) >= 3
    right_exit = next(
        edge for edge in network_root.findall("edge") if edge.attrib["id"] == "right_exit"
    )
    assert len(right_exit.findall("lane")) == 1
    right_exit_shape = right_exit.find("lane").attrib["shape"]
    right_exit_y = [float(point.split(",")[1]) for point in right_exit_shape.split()]
    assert right_exit_y[-1] < right_exit_y[0]

    vehicles = {vehicle.attrib["id"]: vehicle.attrib for vehicle in route_root.findall("vehicle")}
    vehicle_types = {
        vehicle_type.attrib["id"]: vehicle_type.attrib
        for vehicle_type in route_root.findall("vType")
    }
    routes = {route.attrib["id"]: route.attrib["edges"] for route in route_root.findall("route")}
    assert set(vehicles) == {
        "accident_parked_L0_0",
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
        "accident_follow_L1_0",
        "accident_follow_L3_0",
        "accident_follow_L5_0",
        "accident_background_L0_0",
        "accident_background_L0_1",
        "accident_background_L1_0",
        "accident_background_L1_1",
        "accident_background_L3_0",
        "accident_background_L3_1",
        "accident_background_L3_2",
        "accident_background_L5_0",
        "accident_background_L5_1",
        "accident_background_L5_2",
    }
    assert vehicles["accident_actor_L0_0"]["departLane"] == "0"
    assert vehicles["accident_parked_L0_0"]["departLane"] == "0"
    assert vehicles["accident_victim_L0_0"]["departLane"] == "1"
    assert vehicles["accident_follow_L5_0"]["departLane"] == "1"
    assert vehicles["accident_follow_L5_0"]["departSpeed"] == "0"
    assert routes[vehicles["accident_follow_L0_0"]["route"]] == "road_curve"
    assert routes[vehicles["accident_follow_L1_0"]["route"]] == "road_curve"
    assert routes[vehicles["accident_follow_L5_0"]["route"]].endswith("right_exit")
    assert routes[vehicles["accident_follow_L3_0"]["route"]] == "road_curve"
    background_ids_by_level = {
        level: sorted(
            vehicle_id
            for vehicle_id in vehicles
            if vehicle_id.startswith(f"accident_background_L{level}_")
        )
        for level in (0, 1, 3, 5)
    }
    assert {level: len(ids) for level, ids in background_ids_by_level.items()} == {
        0: 2,
        1: 2,
        3: 3,
        5: 3,
    }
    straight_background_ids = {
        vehicle_id for level in (0, 1, 3) for vehicle_id in background_ids_by_level[level]
    }
    assert all(
        routes[vehicles[vehicle_id]["route"]] == "road_approach road_curve"
        for vehicle_id in straight_background_ids
    )
    expected_straight_lanes = {
        "accident_background_L0_0": "1",
        "accident_background_L1_0": "1",
        "accident_background_L3_0": "1",
        "accident_background_L0_1": "0",
        "accident_background_L1_1": "0",
        "accident_background_L3_1": "0",
        "accident_background_L3_2": "0",
    }
    assert {
        vehicle_id: vehicles[vehicle_id]["departLane"] for vehicle_id in straight_background_ids
    } == expected_straight_lanes
    assert {
        vehicle_id: float(vehicles[vehicle_id]["departPos"])
        for vehicle_id in straight_background_ids
        if expected_straight_lanes[vehicle_id] == "0"
    } == {
        "accident_background_L0_1": 385.0,
        "accident_background_L1_1": 370.0,
        "accident_background_L3_1": 355.0,
        "accident_background_L3_2": 340.0,
    }
    assert all(
        routes[vehicles[vehicle_id]["route"]] == "road_approach right_exit"
        and vehicles[vehicle_id]["departLane"] == "0"
        for vehicle_id in background_ids_by_level[5]
    )
    assert all(
        vehicles[vehicle_id]["departSpeed"] == "0"
        for vehicle_id in straight_background_ids.union(background_ids_by_level[5])
    )
    assert {
        vehicles[vehicle_id]["departLane"]
        for vehicle_id in straight_background_ids.union(background_ids_by_level[5])
    } == {"0", "1"}
    assert vehicle_types["L0"]["length"] == "4.55"
    assert vehicle_types["L0"]["color"] == "168,162,158"
    assert vehicle_types["L5"]["color"] == "0,0,0"
    assert float(vehicles["accident_parked_L0_0"]["departPos"]) > float(
        vehicles["accident_actor_L0_0"]["departPos"]
    )
    turn_x_m = float(
        next(node for node in node_root.findall("node") if node.attrib["id"] == "turn").attrib["x"]
    )
    approach_length_m = turn_x_m
    assert turn_x_m == 510.0

    def global_position_m(attributes: dict[str, str]) -> float:
        position_m = float(attributes["departPos"])
        return (
            position_m + approach_length_m
            if routes[attributes["route"]] == "road_curve"
            else position_m
        )

    follower_positions = []
    for level in (0, 1, 3, 5):
        attributes = vehicles[f"accident_follow_L{level}_0"]
        follower_positions.append(global_position_m(attributes))
    assert follower_positions == sorted(follower_positions, reverse=True)
    assert (
        follower_positions[-1]
        < follower_positions[0]
        < float(vehicles["accident_actor_L0_0"]["departPos"]) + approach_length_m
    )
    parked_position_m = global_position_m(vehicles["accident_parked_L0_0"])
    actor_position_m = global_position_m(vehicles["accident_actor_L0_0"])
    assert parked_position_m - actor_position_m <= 50.0
    assert actor_position_m - follower_positions[0] <= 75.0
    assert follower_positions == [528.4, 521.6, 510.0, 460.4]
    compressed_gaps_m = [
        leading_position_m - following_position_m
        for leading_position_m, following_position_m in zip(
            follower_positions[:-1],
            follower_positions[1:],
            strict=True,
        )
    ]
    assert compressed_gaps_m[:2] == pytest.approx([17.0 * 0.4, 29.0 * 0.4])
    assert compressed_gaps_m[2] == pytest.approx(49.6)
    assert actor_position_m - turn_x_m == pytest.approx(40.0)
    victim_position_m = global_position_m(vehicles["accident_victim_L0_0"])
    accident_group_center_m = (actor_position_m + victim_position_m) / 2.0
    assert accident_group_center_m - follower_positions[0] == pytest.approx(72.5 / 3.0, abs=0.1)
    assert turn_x_m - follower_positions[-1] == pytest.approx(49.6)
    processing = config_root.find("processing")
    assert processing is not None
    assert processing.find("collision.mingap-factor").attrib["value"] == "0"
