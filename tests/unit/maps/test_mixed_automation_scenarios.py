from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from trafficverse.maps.sumo_package import load_sumo_package

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAP_ROOT = REPOSITORY_ROOT / "configs/maps"


@pytest.mark.parametrize(
    "scenario_id",
    ("mixed-automation-cutin", "mixed-automation-emergency-yield"),
)
def test_mixed_automation_package_is_self_contained_and_uses_core_step(
    scenario_id: str,
) -> None:
    config = MAP_ROOT / scenario_id / f"{scenario_id}.sumocfg"

    package = load_sumo_package(config, allowed_root=MAP_ROOT)

    assert package.package_id == scenario_id
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
