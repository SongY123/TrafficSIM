from PySide6.QtWidgets import QApplication
from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary
from ui.views.traffic_scene_page import TrafficScenePage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _cell_text(page: TrafficScenePage, row: int, column: int) -> str:
    item = page.table.item(row, column)
    assert item is not None
    return item.text()


def test_traffic_scene_page_shows_three_documented_scenarios() -> None:
    _application()
    page = TrafficScenePage()
    maps = tuple(
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

    page.set_maps(maps)

    assert page.table.rowCount() == 3
    assert [_cell_text(page, row, 0) for row in range(3)] == [
        preset.name for preset in TRAFFIC_SCENARIO_PRESETS
    ]
    assert all(_cell_text(page, row, 3) == "可运行" for row in range(3))

    page.close()


def test_traffic_scene_click_emits_complete_preset() -> None:
    _application()
    page = TrafficScenePage()
    preset = TRAFFIC_SCENARIO_PRESETS[0]
    page.set_maps(
        (
            MapSummary(
                map_id=preset.map_id,
                kind="sumo",
                display_name=preset.name,
                validated=True,
                network_schema_version="sumo-net/display-1.0",
                manifest_available=False,
                sumo_config_file=f"{preset.map_id}.sumocfg",
                sumo_step_ms=50,
            ),
        )
    )
    selected: list[object] = []
    page.scene_selected.connect(selected.append)

    page.table.cellClicked.emit(0, 0)

    assert selected == [preset]
    page.close()
