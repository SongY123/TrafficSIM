import math
from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel
from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary
from ui.models.protocol import Vehicle
from ui.models.traffic_scenario import scenario_preview_vehicles
from ui.views.traffic_scene_page import TrafficScenePage
from ui.widgets import MapLibreDeckMapWidget

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _validated_maps() -> tuple[MapSummary, ...]:
    return tuple(
        MapSummary(
            map_id=preset.map_id,
            kind="sumo",
            display_name=preset.name,
            validated=True,
            network_schema_version="sumo-net/display-1.0",
            manifest_available=False,
            sumo_config_file=f"{preset.map_id}.sumocfg",
            sumo_step_ms=50,
        )
        for preset in TRAFFIC_SCENARIO_PRESETS
    )


def test_traffic_scene_page_shows_selected_scenario_details_and_real_preview() -> None:
    _application()
    page = TrafficScenePage(load_web_map=False)
    preset = TRAFFIC_SCENARIO_PRESETS[0]

    assert page.selected_scenario == preset
    assert page.title_label.text() == preset.name
    assert page.incident_label.text() == preset.incident
    assert page.summary_values["vehicles"].text() == f"车辆 · {preset.vehicle_total} 辆"
    assert isinstance(page.map_widget, MapLibreDeckMapWidget)
    assert page.map_widget._pending["setLegendVisible"] is True
    assert page.map_widget.minimumHeight() == 220
    page.resize(1200, 800)
    page.show()
    QApplication.processEvents()
    assert page.preview_panel.height() == 376
    assert page.preview_panel.height() == page.metrics_panel.height()
    assert page.speed_chart.values == {
        "L0": 34.8,
        "L1": 45.4,
        "L2": 57.6,
        "L3": 69.2,
        "L4": 81.4,
        "L5": 82.6,
    }
    assert page.collision_chart.values == {
        "L0": 4,
        "L1": 3,
        "L2": 2,
        "L3": 1,
        "L4": 0,
        "L5": 0,
    }
    assert page.collision_label.text() == "碰撞次数"
    assert tuple(page.level_descriptions) == ("L0", "L1", "L2", "L3", "L4", "L5")
    assert [label.text() for label in page.findChildren(QLabel, "trafficSceneLevel")] == [
        "L0  人工驾驶",
        "L1  辅助驾驶",
        "L2  部分自动驾驶",
        "L3  条件自动驾驶",
        "L4  高度自动驾驶",
        "L5  完全自动驾驶",
    ]
    assert page.findChildren(QLabel, "pageSubtitle") == []
    assert page.findChildren(QLabel, "trafficSceneType") == []
    assert {label.text() for label in page.findChildren(QLabel, "trafficScenePanelTitle")} == {
        "仿真场景预览",
        "性能指标分析",
    }
    assert "二维仿真场景" not in {label.text() for label in page.findChildren(QLabel)}
    assert page.findChildren(QFrame, "trafficSceneSection") == []
    assert len(page.findChildren(QFrame, "trafficSceneLevelCard")) == 6
    assert page.launch_button.isEnabled() is False

    requested_previews: list[str] = []
    page.preview_requested.connect(requested_previews.append)
    page.set_maps(_validated_maps())

    assert page.availability_label.text() == "资源就绪"
    assert requested_previews == [preset.map_id]
    assert page.configure_button.isEnabled() is True
    assert page.launch_button.isEnabled() is True
    page.close()


def test_selecting_scenario_updates_detail_and_actions_emit_current_preset() -> None:
    _application()
    page = TrafficScenePage(load_web_map=False)
    preset = TRAFFIC_SCENARIO_PRESETS[1]
    configured: list[object] = []
    launched: list[object] = []
    page.configuration_requested.connect(configured.append)
    page.scene_selected.connect(launched.append)
    page.set_maps(_validated_maps())

    page.set_scenario(preset)
    page.configure_button.click()
    page.launch_button.click()

    assert page.selected_scenario == preset
    assert page.title_label.text() == preset.name
    assert page.findChildren(QLabel, "trafficSceneBehaviorSummary") == []
    assert page.level_descriptions["L5"].text() == dict(preset.level_behaviors)["L5"]
    assert page.speed_chart.values["L0"] == 59.0
    assert page.speed_chart.values["L5"] == 88.9
    assert page.collision_chart.values["L0"] == 12
    assert page.collision_chart.values["L5"] == 0
    network = {"type": "FeatureCollection", "features": []}
    page.set_preview_network(preset.map_id, network)
    assert page.map_widget._pending["setNetwork"] == network
    preview_payload = page.map_widget._pending["setVehicles"]
    assert isinstance(preview_payload, list)
    assert all(vehicle["vehicle_id"].startswith("cutin_") for vehicle in preview_payload)
    assert configured == [preset]
    assert launched == [preset]
    page.close()


def test_occasional_accident_level_average_speeds_are_close_but_not_identical() -> None:
    _application()
    page = TrafficScenePage(load_web_map=False)

    page.set_scenario(TRAFFIC_SCENARIO_PRESETS[3])

    speeds_kph = tuple(page.speed_chart.values.values())
    assert all(speed_kph > 0.0 for speed_kph in speeds_kph)
    assert max(speeds_kph) - min(speeds_kph) <= 5.0
    assert len(set(speeds_kph)) > 1
    page.close()


@pytest.mark.parametrize(
    ("preset_index", "required_ids", "expected_levels"),
    (
        (0, {"static_obstacle_0", "static_obstacle_1"}, {"L0", "L1", "L2", "L3", "L4", "L5"}),
        (
            1,
            {"cutin_actor_preview_L0_00", "cutin_actor_preview_L5_05"},
            {"L0", "L1", "L2", "L3", "L4", "L5"},
        ),
        (2, {"ambulance_L5_0"}, {"L0", "L1", "L2", "L3", "L4", "L5"}),
        (
            3,
            {"accident_actor_L0_0", "accident_victim_L0_0", "accident_follow_L5_0"},
            {"L0", "L1", "L3", "L5"},
        ),
        (
            4,
            {"merge_preview_main_L0_0", "merge_preview_ramp_L2_2"},
            {"L0", "L1", "L2", "L3"},
        ),
        (
            5,
            {"merge_preview_main_L5_0", "merge_preview_ramp_L5_0"},
            {"L3", "L4", "L5"},
        ),
    ),
)
def test_scenario_preview_is_a_feature_key_frame(
    preset_index: int,
    required_ids: set[str],
    expected_levels: set[str],
) -> None:
    vehicles = scenario_preview_vehicles(TRAFFIC_SCENARIO_PRESETS[preset_index])
    levels = {vehicle.automation_level for vehicle in vehicles}
    vehicle_ids = {vehicle.vehicle_id for vehicle in vehicles}

    assert levels == expected_levels
    assert required_ids <= vehicle_ids
    minimum_lane_count = 7 if preset_index in {4, 5} else 2 if preset_index == 3 else 3
    assert len({vehicle.lane_id for vehicle in vehicles}) >= minimum_lane_count


def test_dense_merge_presets_expose_configured_demand_and_distinct_automation_levels() -> None:
    low_level, l5 = TRAFFIC_SCENARIO_PRESETS[4:6]
    low_level_preview = scenario_preview_vehicles(low_level)
    l5_preview = scenario_preview_vehicles(l5)

    assert low_level.name == "低智驾等级会车（L0-L3）"
    assert l5.name == "L5会车"
    assert low_level.vehicle_total == 155
    assert l5.vehicle_total == 70
    assert low_level.duration_s == 30
    assert dict(low_level.automation_counts) == {"L0": 40, "L1": 41, "L2": 39, "L3": 35}
    assert dict(l5.automation_counts) == {"L3": 10, "L4": 10, "L5": 50}
    assert {
        vehicle.automation_level
        for vehicle in l5_preview
        if vehicle.lane_id.startswith("merge_ramp_")
    } == {"L4", "L5"}
    assert any(vehicle.action == "LANE_CHANGE_LEFT" for vehicle in low_level_preview)
    upper_lane_vehicles = [
        vehicle for vehicle in low_level_preview if vehicle.lane_id.startswith("opposing_")
    ]
    assert len(upper_lane_vehicles) == 54
    assert max(vehicle.position.x for vehicle in upper_lane_vehicles) >= 310.0
    assert all(vehicle.speed_mps > 0.0 for vehicle in upper_lane_vehicles)
    assert len({vehicle.speed_mps for vehicle in upper_lane_vehicles}) >= 8
    for lane_index in range(3):
        lane_positions_m = sorted(
            vehicle.position.x
            for vehicle in upper_lane_vehicles
            if int(vehicle.lane_id.rsplit("_", maxsplit=1)[1]) == lane_index
        )
        position_intervals_m = [
            later_position_m - earlier_position_m
            for earlier_position_m, later_position_m in zip(
                lane_positions_m,
                lane_positions_m[1:],
                strict=False,
            )
        ]
        assert len(lane_positions_m) == 18
        assert lane_positions_m[-1] - lane_positions_m[0] >= 300.0
        assert max(position_intervals_m) - min(position_intervals_m) >= 8.0
        assert (
            len(
                {
                    vehicle.speed_mps
                    for vehicle in upper_lane_vehicles
                    if int(vehicle.lane_id.rsplit("_", maxsplit=1)[1]) == lane_index
                }
            )
            == 18
        )

    l5_preview = scenario_preview_vehicles(l5)
    assert all(vehicle.speed_mps == pytest.approx(16.0) for vehicle in l5_preview)
    assert not any(vehicle.action == "LANE_CHANGE_LEFT" for vehicle in l5_preview)
    assert not any(vehicle.action == "YIELD" for vehicle in l5_preview)


def _distance_to_lane_m(vehicle: Vehicle, lane_shape: str) -> float:
    points = [tuple(float(value) for value in point.split(",")[:2]) for point in lane_shape.split()]
    distances = []
    for start, end in zip(points, points[1:], strict=False):
        delta_x_m = end[0] - start[0]
        delta_y_m = end[1] - start[1]
        length_squared_m2 = delta_x_m**2 + delta_y_m**2
        projection = (
            (vehicle.position.x - start[0]) * delta_x_m
            + (vehicle.position.y - start[1]) * delta_y_m
        ) / length_squared_m2
        ratio = min(1.0, max(0.0, projection))
        distances.append(
            math.hypot(
                vehicle.position.x - (start[0] + ratio * delta_x_m),
                vehicle.position.y - (start[1] + ratio * delta_y_m),
            )
        )
    return min(distances)


def test_occasional_accident_preview_shows_a_lane_aligned_three_car_two_impact_scene() -> None:
    vehicles = {
        vehicle.vehicle_id: vehicle
        for vehicle in scenario_preview_vehicles(TRAFFIC_SCENARIO_PRESETS[3])
    }
    collision_ids = {
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
    }
    background_ids_by_level = {
        level: {
            vehicle_id
            for vehicle_id in vehicles
            if vehicle_id.startswith(f"accident_background_{level}_")
        }
        for level in ("L0", "L1", "L3", "L5")
    }

    assert "accident_parked_L0_0" in vehicles
    assert vehicles["accident_parked_L0_0"].speed_mps == 0.0
    assert vehicles["accident_parked_L0_0"].lane_id.endswith("_0")
    assert all(vehicles[vehicle_id].speed_mps == 0.0 for vehicle_id in collision_ids)
    assert vehicles["accident_follow_L5_0"].lane_id == "right_exit_0"
    assert vehicles["accident_follow_L5_0"].speed_mps > 0.0
    assert {level: len(ids) for level, ids in background_ids_by_level.items()} == {
        "L0": 2,
        "L1": 2,
        "L3": 3,
        "L5": 3,
    }
    assert all(
        vehicles[vehicle_id].lane_id == "right_exit_0"
        for vehicle_id in background_ids_by_level["L5"]
    )
    assert {
        vehicle_id: vehicles[vehicle_id].lane_id
        for vehicle_id in {
            "accident_background_L0_0",
            "accident_background_L1_0",
            "accident_background_L3_0",
            "accident_background_L0_1",
            "accident_background_L1_1",
            "accident_background_L3_1",
            "accident_background_L3_2",
        }
    } == {
        "accident_background_L0_0": "road_curve_0",
        "accident_background_L1_0": "road_curve_0",
        "accident_background_L3_0": "road_curve_1",
        "accident_background_L0_1": "road_curve_1",
        "accident_background_L1_1": "road_curve_0",
        "accident_background_L3_1": "road_curve_1",
        "accident_background_L3_2": "road_curve_0",
    }
    network_path = (
        REPOSITORY_ROOT
        / "configs/maps/mixed-automation-occasional-accident"
        / "mixed-automation-occasional-accident.net.xml"
    )
    network_root = ElementTree.parse(network_path).getroot()
    lane_shapes = {
        lane.attrib["id"]: lane.attrib["shape"]
        for edge in network_root.findall("edge")
        for lane in edge.findall("lane")
    }
    assert all(
        _distance_to_lane_m(vehicle, lane_shapes[vehicle.lane_id]) <= 2.0
        for vehicle in vehicles.values()
    )
    victim = vehicles["accident_victim_L0_0"]
    actor = vehicles["accident_actor_L0_0"]
    l0_follower = vehicles["accident_follow_L0_0"]
    actor_victim_distance_m = math.hypot(
        actor.position.x - victim.position.x,
        actor.position.y - victim.position.y,
    )
    follower_actor_distance_m = math.hypot(
        l0_follower.position.x - actor.position.x,
        l0_follower.position.y - actor.position.y,
    )
    follower_victim_distance_m = math.hypot(
        l0_follower.position.x - victim.position.x,
        l0_follower.position.y - victim.position.y,
    )
    assert actor_victim_distance_m == pytest.approx(3.0, abs=0.4)
    assert follower_actor_distance_m == pytest.approx(4.55, abs=0.35)
    assert follower_victim_distance_m > 6.0
    l1 = vehicles["accident_follow_L1_0"]
    l3 = vehicles["accident_follow_L3_0"]
    l1_body_gap_m = (
        math.hypot(
            l0_follower.position.x - l1.position.x,
            l0_follower.position.y - l1.position.y,
        )
        - (4.55 + 5.0) / 2
    )
    l3_body_gap_m = (
        math.hypot(
            l1.position.x - l3.position.x,
            l1.position.y - l3.position.y,
        )
        - 5.0
    )
    assert l1_body_gap_m == pytest.approx(4.55, abs=0.5)
    assert l3_body_gap_m == pytest.approx(4.55, abs=1.0)


def test_occasional_accident_page_marks_the_three_collided_preview_vehicles() -> None:
    _application()
    page = TrafficScenePage(load_web_map=False)
    preset = TRAFFIC_SCENARIO_PRESETS[3]
    page.set_scenario(preset)

    page.set_preview_network(preset.map_id, {"type": "FeatureCollection", "features": []})

    assert page.map_widget._pending["setCollisionVehicleIds"] == [
        "accident_actor_L0_0",
        "accident_follow_L0_0",
        "accident_victim_L0_0",
    ]
    assert page.collision_chart.values == {
        "L0": 2,
        "L1": 0,
        "L2": 0,
        "L3": 0,
        "L4": 0,
        "L5": 0,
    }
    assert page.collision_label.text() == "碰撞次数 · 3辆事故车"
    page.close()
