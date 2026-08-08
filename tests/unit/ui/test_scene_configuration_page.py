from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QPushButton
from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary
from ui.views.scene_configuration_page import SceneConfigurationPage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def test_scene_configuration_only_lists_direct_sumo_packages() -> None:
    _application()
    page = SceneConfigurationPage(load_web_map=False)
    selected_maps: list[str] = []
    page.map_selected.connect(selected_maps.append)
    page.set_maps(
        (
            MapSummary(
                map_id="town04",
                kind="core_run",
                display_name="Town04",
                carla_map="Town04",
                carla_version="0.9.16",
                validated=True,
                network_schema_version="traffic-network/1.0",
            ),
            MapSummary(
                map_id="image2road",
                kind="sumo",
                display_name="image2road",
                validated=True,
                network_schema_version="sumo-net/display-1.0",
                manifest_available=False,
                sumo_config_file="image2road.sumocfg",
                sumo_step_ms=1000,
            ),
        )
    )

    assert page.map_combo.count() == 1
    assert page.map_combo.itemData(0) == "image2road"
    assert "Town04" not in page.map_combo.itemText(0)
    assert selected_maps == ["image2road"]
    assert page.map_preview_status.text() == "正在加载地图路网预览……"
    assert "▶  开始仿真" in {button.text() for button in page.findChildren(QPushButton)}

    page.close()


def test_scene_configuration_matches_reference_defaults() -> None:
    _application()
    page = SceneConfigurationPage(load_web_map=False)

    assert page.scene_name.text() == ""
    assert page.scene_name.placeholderText() == "请输入场景名称"
    assert page.description.toPlainText() == ""
    assert page.description.placeholderText() == "请输入场景描述"
    assert page.weather_time_combo.currentText() == "晴朗 · 中午"
    assert page.duration_time.time() == QTime(1, 0, 0)
    assert page.save_draft_button.text() == "保存草稿"
    assert page.save_configuration_button.text() == "保存配置"

    page.close()


def test_scene_configuration_adds_levels_and_updates_vehicle_total() -> None:
    _application()
    page = SceneConfigurationPage(load_web_map=False)

    assert len(page.automation_rows) == 1
    assert page.automation_rows[0].level == "L4"
    assert page.automation_rows[0].vehicle_count == 50
    assert page.vehicle_total.text() == "总计：50"

    page.add_automation_button.click()
    added = page.automation_rows[1]
    assert added.level == "L0"
    added.count_input.setValue(200)

    assert page.vehicle_total.text() == "总计：250"

    page.close()


def test_scene_configuration_removes_automation_level() -> None:
    _application()
    page = SceneConfigurationPage(load_web_map=False)
    page.add_automation_button.click()
    removed = page.automation_rows[1]

    page._remove_automation_row(removed)

    assert len(page.automation_rows) == 1
    assert removed not in page.automation_rows
    assert page.add_automation_button.isEnabled()
    assert page.vehicle_total.text() == "总计：50"

    page.close()


def test_scene_configuration_applies_traffic_scenario_preset() -> None:
    _application()
    page = SceneConfigurationPage(load_web_map=False)
    preset = TRAFFIC_SCENARIO_PRESETS[1]
    page.set_maps(
        (
            MapSummary(
                map_id=preset.map_id,
                kind="sumo",
                display_name=preset.name,
                validated=True,
                network_schema_version="sumo-net/display-1.0",
                manifest_available=False,
                sumo_config_file="scenario.sumocfg",
                sumo_step_ms=50,
            ),
        )
    )

    applied = page.apply_traffic_scenario(preset)

    assert applied
    assert page.scene_name.text() == preset.name
    assert page.map_combo.currentData() == preset.map_id
    assert page.duration_time.time() == QTime(0, 1, 0)
    assert [(row.level, row.vehicle_count) for row in page.automation_rows] == list(
        preset.automation_counts
    )

    page.close()
