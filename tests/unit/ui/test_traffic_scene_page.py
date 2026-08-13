import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel
from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary
from ui.models.traffic_scenario import scenario_preview_vehicles
from ui.views.traffic_scene_page import TrafficScenePage
from ui.widgets import MapLibreDeckMapWidget


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


@pytest.mark.parametrize(
    ("preset_index", "required_ids"),
    (
        (0, {"static_obstacle_0", "static_obstacle_1"}),
        (1, {"cutin_actor_preview_L0_00", "cutin_actor_preview_L5_05"}),
        (2, {"ambulance_L5_0"}),
    ),
)
def test_scenario_preview_is_a_feature_key_frame(
    preset_index: int,
    required_ids: set[str],
) -> None:
    vehicles = scenario_preview_vehicles(TRAFFIC_SCENARIO_PRESETS[preset_index])
    levels = {vehicle.automation_level for vehicle in vehicles}
    vehicle_ids = {vehicle.vehicle_id for vehicle in vehicles}

    assert levels == {"L0", "L1", "L2", "L3", "L4", "L5"}
    assert required_ids <= vehicle_ids
    assert len({vehicle.lane_id for vehicle in vehicles}) >= 3
