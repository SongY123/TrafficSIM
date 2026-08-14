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
        "mixed-automation-low-level-merge",
        "mixed-automation-l5-merge",
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
    right_exit_lane = right_exit.find("lane")
    assert right_exit_lane is not None
    assert len(right_exit.findall("lane")) == 1
    right_exit_shape = right_exit_lane.attrib["shape"]
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
    } == {
        "accident_background_L0_0": 500.0,
        "accident_background_L0_1": 300.0,
        "accident_background_L1_0": 440.0,
        "accident_background_L1_1": 250.0,
        "accident_background_L3_0": 425.0,
        "accident_background_L3_1": 60.0,
        "accident_background_L3_2": 10.0,
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
    mixed_lane_zero_ids = [
        vehicle_id
        for vehicle_id in sorted(
            straight_background_ids.union(background_ids_by_level[5]),
            key=lambda vehicle_id: float(vehicles[vehicle_id]["departPos"]),
            reverse=True,
        )
        if vehicles[vehicle_id]["departLane"] == "0"
    ]
    assert mixed_lane_zero_ids == [
        "accident_background_L5_0",
        "accident_background_L0_1",
        "accident_background_L1_1",
        "accident_background_L5_1",
        "accident_background_L5_2",
        "accident_background_L3_1",
        "accident_background_L3_2",
    ]
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
    assert float(vehicles["accident_parked_L0_0"]["departPos"]) == 71.0
    assert parked_position_m - actor_position_m == pytest.approx(31.0)
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
    minimum_gap_factor = processing.find("collision.mingap-factor")
    assert minimum_gap_factor is not None
    assert minimum_gap_factor.attrib["value"] == "0"


@pytest.mark.parametrize(
    (
        "scenario_id",
        "expected_levels",
        "expected_flow_count",
        "expected_vehicle_count",
        "expected_merge_vehicle_count",
    ),
    (
        ("mixed-automation-low-level-merge", {"L0", "L1", "L2", "L3"}, 28, 155, 14),
        ("mixed-automation-l5-merge", {"L3", "L4", "L5"}, 0, 131, 18),
    ),
)
def test_dense_merge_scenarios_use_three_main_lanes_one_ramp_and_three_opposing_lanes(
    scenario_id: str,
    expected_levels: set[str],
    expected_flow_count: int,
    expected_vehicle_count: int,
    expected_merge_vehicle_count: int,
) -> None:
    directory = MAP_ROOT / scenario_id
    network_root = ElementTree.parse(directory / f"{scenario_id}.net.xml").getroot()
    route_root = ElementTree.parse(directory / f"{scenario_id}.rou.xml").getroot()

    lane_counts = {
        edge.attrib["id"]: len(edge.findall("lane"))
        for edge in network_root.findall("edge")
        if not edge.attrib["id"].startswith(":")
    }
    assert lane_counts == {
        "main_before": 3,
        "main_after": 3,
        "merge_ramp": 1,
        "opposing_before": 3,
        "opposing_after": 3,
    }
    merge_ramp = next(
        edge for edge in network_root.findall("edge") if edge.attrib["id"] == "merge_ramp"
    )
    merge_ramp_lane = merge_ramp.find("lane")
    assert merge_ramp_lane is not None
    assert float(merge_ramp_lane.attrib["length"]) >= 100.0
    assert any(
        connection.attrib.get("from") == "merge_ramp"
        and connection.attrib.get("to") == "main_after"
        and connection.attrib.get("toLane") == "0"
        for connection in network_root.findall("connection")
    )
    routes = {route.attrib["id"]: route.attrib["edges"] for route in route_root.findall("route")}
    expected_routes = {
        "route_main": "main_before main_after",
        "route_merge": "merge_ramp main_after",
        "route_opposing": "opposing_before opposing_after",
    }
    if scenario_id == "mixed-automation-low-level-merge":
        expected_routes["route_opposing_after"] = "opposing_after"
    assert routes == expected_routes
    flows = route_root.findall("flow")
    vehicles = route_root.findall("vehicle")
    assert len(flows) == expected_flow_count
    assert sum(int(flow.attrib["number"]) for flow in flows) + len(vehicles) == (
        expected_vehicle_count
    )
    assert sum(
        int(flow.attrib["number"]) for flow in flows if flow.attrib["route"] == "route_merge"
    ) + sum(vehicle.attrib["route"] == "route_merge" for vehicle in vehicles) == (
        expected_merge_vehicle_count
    )
    departure_times_s = [float(flow.attrib["begin"]) for flow in flows]
    assert departure_times_s == sorted(departure_times_s)
    assert {item.attrib["type"].rsplit("_", maxsplit=1)[-1] for item in (*flows, *vehicles)} == (
        expected_levels
    )
    assert all(
        flow.attrib["departSpeed"] == "max" or float(flow.attrib["departSpeed"]) > 0.0
        for flow in flows
    )
    assert all(flow.attrib["departLane"] in {"0", "1", "2"} for flow in flows)


def test_l5_merge_starts_dense_and_uses_varied_safe_demand() -> None:
    scenario_id = "mixed-automation-l5-merge"
    route_root = ElementTree.parse(MAP_ROOT / scenario_id / f"{scenario_id}.rou.xml").getroot()
    flows = route_root.findall("flow")
    vehicles = route_root.findall("vehicle")
    demand = (*flows, *vehicles)
    counts_by_level = {
        level: sum(
            int(item.attrib.get("number", "1")) for item in demand if item.attrib["type"] == level
        )
        for level in ("L3", "L4", "L5")
    }
    initial_main_by_lane = {
        lane_index: [
            vehicle
            for vehicle in vehicles
            if vehicle.attrib["route"] == "route_main"
            and vehicle.attrib["departLane"] == str(lane_index)
            and float(vehicle.attrib["depart"]) == 0.0
        ]
        for lane_index in range(3)
    }
    initial_opposing_by_lane = {
        lane_index: [
            vehicle
            for vehicle in vehicles
            if vehicle.attrib["route"] == "route_opposing"
            and vehicle.attrib["departLane"] == str(lane_index)
            and float(vehicle.attrib["depart"]) == 0.0
        ]
        for lane_index in range(3)
    }
    main_d1 = [
        vehicle
        for vehicle in vehicles
        if vehicle.attrib["route"] == "route_main" and vehicle.attrib["departLane"] == "0"
    ]
    ramp = [vehicle for vehicle in vehicles if vehicle.attrib["route"] == "route_merge"]

    def unique_gap_count(items: list[ElementTree.Element]) -> int:
        positions_m = sorted(float(item.attrib["departPos"]) for item in items)
        return len(
            {
                round(later - earlier, 2)
                for earlier, later in zip(positions_m, positions_m[1:], strict=False)
            }
        )

    assert counts_by_level["L5"] > counts_by_level["L3"]
    assert counts_by_level["L5"] > counts_by_level["L4"]
    assert min(counts_by_level["L3"], counts_by_level["L4"]) >= 15
    assert {lane_index: len(items) for lane_index, items in initial_main_by_lane.items()} == {
        0: 7,
        1: 9,
        2: 9,
    }
    assert all(
        max(float(item.attrib["departPos"]) for item in items)
        - min(float(item.attrib["departPos"]) for item in items)
        >= 90.0
        for items in initial_main_by_lane.values()
    )
    assert all(unique_gap_count(items) >= 4 for items in initial_main_by_lane.values())
    assert all(
        len({float(item.attrib["departSpeed"]) for item in items}) >= 4
        for items in initial_main_by_lane.values()
    )
    assert all(len(items) == 12 for items in initial_opposing_by_lane.values())
    assert all(
        max(float(item.attrib["departPos"]) for item in items)
        - min(float(item.attrib["departPos"]) for item in items)
        >= 195.0
        for items in initial_opposing_by_lane.values()
    )
    assert all(unique_gap_count(items) >= 4 for items in initial_opposing_by_lane.values())
    assert all(
        len({float(item.attrib["departSpeed"]) for item in items}) >= 4
        for items in initial_opposing_by_lane.values()
    )
    assert len(main_d1) == 19
    assert len(ramp) == 18
    assert {vehicle.attrib["type"] for vehicle in ramp} == {"L4", "L5"}
    assert sum(float(vehicle.attrib["depart"]) == 0.0 for vehicle in ramp) == 6
    assert all(15.2 <= float(item.attrib["departSpeed"]) <= 16.8 for item in demand)
    assert [float(vehicle.attrib["depart"]) for vehicle in main_d1] == sorted(
        float(vehicle.attrib["depart"]) for vehicle in main_d1
    )
    assert [float(vehicle.attrib["depart"]) for vehicle in ramp] == sorted(
        float(vehicle.attrib["depart"]) for vehicle in ramp
    )
    assert [float(vehicle.attrib["depart"]) for vehicle in vehicles] == sorted(
        float(vehicle.attrib["depart"]) for vehicle in vehicles
    )


def test_low_level_merge_uses_continuous_one_and_a_half_second_lane_changes() -> None:
    scenario_id = "mixed-automation-low-level-merge"
    config_root = ElementTree.parse(MAP_ROOT / scenario_id / f"{scenario_id}.sumocfg").getroot()

    processing = config_root.find("processing")
    assert processing is not None
    lane_change_duration = processing.find("lanechange.duration")
    assert lane_change_duration is not None
    assert lane_change_duration.attrib["value"] == "1.5"


def test_low_level_merge_keeps_supplying_ramp_vehicles_for_the_full_run() -> None:
    scenario_id = "mixed-automation-low-level-merge"
    route_root = ElementTree.parse(MAP_ROOT / scenario_id / f"{scenario_id}.rou.xml").getroot()
    ramp_departure_times_s = sorted(
        float(flow.attrib["begin"]) + index * float(flow.attrib["period"])
        for flow in route_root.findall("flow")
        if flow.attrib["route"] == "route_merge"
        for index in range(int(flow.attrib["number"]))
    )

    assert len(ramp_departure_times_s) == 14
    assert ramp_departure_times_s[0] == pytest.approx(0.0)
    assert ramp_departure_times_s[-1] == pytest.approx(26.0)
    assert all(
        later_time_s - earlier_time_s == pytest.approx(2.0)
        for earlier_time_s, later_time_s in zip(
            ramp_departure_times_s,
            ramp_departure_times_s[1:],
            strict=False,
        )
    )


def test_low_level_merge_sources_upper_lanes_from_merge_until_simulation_end() -> None:
    scenario_id = "mixed-automation-low-level-merge"
    route_root = ElementTree.parse(MAP_ROOT / scenario_id / f"{scenario_id}.rou.xml").getroot()
    opposing_flows = [
        flow for flow in route_root.findall("flow") if flow.attrib["route"] == "route_opposing"
    ]

    assert len(opposing_flows) == 12
    assert sum(int(flow.attrib["number"]) for flow in opposing_flows) == 45
    assert all(float(flow.attrib["departPos"]) == pytest.approx(0.0) for flow in opposing_flows)
    all_departure_times_by_lane_s: dict[int, list[float]] = {}
    for lane_index in range(3):
        departure_times_s = sorted(
            float(flow.attrib["begin"]) + index * float(flow.attrib["period"])
            for flow in opposing_flows
            if flow.attrib["departLane"] == str(lane_index)
            for index in range(int(flow.attrib["number"]))
        )
        departure_intervals_s = [
            later_time_s - earlier_time_s
            for earlier_time_s, later_time_s in zip(
                departure_times_s,
                departure_times_s[1:],
                strict=False,
            )
        ]
        assert len(departure_times_s) == 15
        assert departure_times_s[0] <= 2.0
        assert departure_times_s[-1] >= 28.0
        assert max(departure_intervals_s) <= 3.0
        assert max(departure_intervals_s) - min(departure_intervals_s) >= 0.8
        all_departure_times_by_lane_s[lane_index] = departure_times_s
    refresh_batch_sizes: dict[float, int] = {}
    for departure_times_s in all_departure_times_by_lane_s.values():
        for departure_time_s in departure_times_s:
            rounded_time_s = round(departure_time_s, 3)
            refresh_batch_sizes[rounded_time_s] = refresh_batch_sizes.get(rounded_time_s, 0) + 1
    assert set(refresh_batch_sizes.values()) == {1, 2, 3}
    assert max(refresh_batch_sizes.values()) == 3


def test_low_level_merge_starts_with_irregular_moving_upper_lane_traffic() -> None:
    scenario_id = "mixed-automation-low-level-merge"
    route_root = ElementTree.parse(MAP_ROOT / scenario_id / f"{scenario_id}.rou.xml").getroot()
    upper_vehicle_types = [
        vehicle_type
        for vehicle_type in route_root.findall("vType")
        if vehicle_type.attrib["id"].startswith("upper_")
    ]
    initial_upper_vehicles = [
        vehicle
        for vehicle in route_root.findall("vehicle")
        if vehicle.attrib["route"] in {"route_opposing", "route_opposing_after"}
    ]

    assert len(upper_vehicle_types) == 4
    assert all(vehicle_type.attrib["sigma"] == "0" for vehicle_type in upper_vehicle_types)
    assert all(vehicle_type.attrib["speedFactor"] == "1.0" for vehicle_type in upper_vehicle_types)
    assert len(initial_upper_vehicles) == 54
    assert all(float(vehicle.attrib["depart"]) == 0.0 for vehicle in initial_upper_vehicles)
    assert all(float(vehicle.attrib["departSpeed"]) > 0.0 for vehicle in initial_upper_vehicles)
    for lane_index in range(3):
        lane_vehicles = [
            vehicle
            for vehicle in initial_upper_vehicles
            if vehicle.attrib["departLane"] == str(lane_index)
        ]
        positions_m = sorted(
            (
                320.0 - float(vehicle.attrib["departPos"])
                if vehicle.attrib["route"] == "route_opposing"
                else 100.54 - float(vehicle.attrib["departPos"])
            )
            for vehicle in lane_vehicles
        )
        position_intervals_m = [
            later_position_m - earlier_position_m
            for earlier_position_m, later_position_m in zip(
                positions_m,
                positions_m[1:],
                strict=False,
            )
        ]
        assert len(lane_vehicles) == 18
        assert positions_m[0] <= 7.0
        assert positions_m[-1] >= 310.0
        assert positions_m[-1] - positions_m[0] >= 300.0
        assert max(position_intervals_m) - min(position_intervals_m) >= 2.0
        assert len({float(vehicle.attrib["departSpeed"]) for vehicle in lane_vehicles}) == 18


def test_low_level_merge_keeps_lower_main_and_ramp_demands_unchanged() -> None:
    scenario_id = "mixed-automation-low-level-merge"
    route_root = ElementTree.parse(MAP_ROOT / scenario_id / f"{scenario_id}.rou.xml").getroot()
    flows = route_root.findall("flow")

    assert not [
        vehicle
        for vehicle in route_root.findall("vehicle")
        if vehicle.attrib["route"] == "route_main"
    ]
    assert (
        sum(int(flow.attrib["number"]) for flow in flows if flow.attrib["route"] == "route_main")
        == 42
    )
    assert (
        sum(int(flow.attrib["number"]) for flow in flows if flow.attrib["route"] == "route_merge")
        == 14
    )
