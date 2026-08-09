from __future__ import annotations

import platform

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QPushButton,
    QStyle,
    QStyleOptionSpinBox,
)
from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary
from ui.views.scene_configuration_page import SceneConfigurationPage
from ui.views.theme import ThemeMode, load_stylesheet


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
    assert page.duration_time.time() == QTime(1, 0, 0)
    assert page.findChild(QComboBox, "simulationWeatherTimeCombo") is None
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


def test_macos_automation_count_uses_large_stepper_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application()
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    page = SceneConfigurationPage(load_web_map=False)
    count_input = page.automation_rows[0].count_input

    assert count_input.property("macosStepper") is True
    assert count_input.minimumHeight() == 48
    for theme in (ThemeMode.LIGHT, ThemeMode.DARK):
        stylesheet = load_stylesheet(theme)
        assert 'QSpinBox#automationVehicleCount[macosStepper="true"]::up-button' in stylesheet
        assert 'QSpinBox#automationVehicleCount[macosStepper="true"]::down-button' in stylesheet
        assert "width: 40px;" in stylesheet

    previous_stylesheet = application.styleSheet()
    application.setStyleSheet(load_stylesheet(ThemeMode.DARK))
    page.show()
    application.processEvents()
    option = QStyleOptionSpinBox()
    count_input.initStyleOption(option)
    up_button = count_input.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox,
        option,
        QStyle.SubControl.SC_SpinBoxUp,
        count_input,
    )
    down_button = count_input.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox,
        option,
        QStyle.SubControl.SC_SpinBoxDown,
        count_input,
    )

    assert up_button.width() >= 40
    assert down_button.width() >= 40
    assert up_button.height() >= 24
    assert down_button.height() >= 24

    page.close()
    application.setStyleSheet(previous_stylesheet)


def test_windows_automation_stepper_renders_explicit_arrow_icons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application()
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    previous_stylesheet = application.styleSheet()
    application.setStyleSheet(load_stylesheet(ThemeMode.DARK))
    page = SceneConfigurationPage(load_web_map=False)
    page.show()
    application.processEvents()
    count_input = page.automation_rows[0].count_input
    assert count_input.property("arrowColor").name() == "#cfd3dc"
    pixmap = count_input.grab()
    image = pixmap.toImage()
    pixel_ratio = pixmap.devicePixelRatio()
    option = QStyleOptionSpinBox()
    count_input.initStyleOption(option)

    for subcontrol in (
        QStyle.SubControl.SC_SpinBoxUp,
        QStyle.SubControl.SC_SpinBoxDown,
    ):
        button = count_input.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            subcontrol,
            count_input,
        )
        bright_pixels = sum(
            image.pixelColor(x, y).lightness() >= 150
            for x in range(
                round(button.left() * pixel_ratio),
                round((button.right() + 1) * pixel_ratio),
            )
            for y in range(
                round(button.top() * pixel_ratio),
                round((button.bottom() + 1) * pixel_ratio),
            )
        )
        assert bright_pixels >= 4

    page.close()
    application.setStyleSheet(previous_stylesheet)
