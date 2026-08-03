from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QPushButton
from ui.models import MapSummary, ReplayResult
from ui.views.data_replay_page import DataReplayPage
from ui.views.scene_configuration_page import SceneConfigurationPage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def test_replay_page_renders_demo_result_and_filters_trends() -> None:
    _application()
    page = DataReplayPage(load_web_map=False)

    assert page.status_badge.text() == "已完成"
    assert page.overview_values["end_status"].text() == "正常结束"
    assert page.overview_values["end_status"].property("statusTone") == "success"
    assert page.overview_values["scenario_name"].text() == "Town04 混合智驾障碍物场景"
    assert not hasattr(page, "history_selector")
    assert len(page.metric_cards) == 7
    assert len(page._result.trend_series) == 4
    assert len(page.result_map._pending["setRoadResults"]) > 4
    assert len(page.result_map._pending["setNetwork"]["features"]) > 4

    assert len(page.trend_charts) == 4
    assert page.trend_charts["平均速度变化"]._series[0].label == "平均速度变化"
    assert page.trend_charts["平均速度变化"]._series[0].unit == "km/h"

    page.close()


def test_replay_page_actions_emit_expected_events() -> None:
    _application()
    page = DataReplayPage(load_web_map=False)
    reruns: list[bool] = []
    returns: list[bool] = []
    exports: list[str] = []
    page.rerun_requested.connect(lambda result: reruns.append(result.status == "已完成"))
    page.return_requested.connect(lambda: returns.append(True))
    page.export_requested.connect(exports.append)

    buttons = {button.text(): button for button in page.findChildren(QPushButton)}
    buttons["重新仿真"].click()
    buttons["返回项目"].click()
    page.findChild(QAction, "exportJsonAction").trigger()
    page.findChild(QAction, "exportImageAction").trigger()

    assert reruns == [True]
    assert returns == [True]
    assert exports == ["json", "image"]

    page.close()


def test_replay_page_accepts_history_selection_from_the_left_navigation() -> None:
    _application()
    page = DataReplayPage(load_web_map=False)

    page.select_history(2)

    assert page.status_badge.text() == "失败"
    assert page.overview_values["started_at"].text() == "08-01 18:42:11"
    assert page.overview_values["end_status"].property("statusTone") == "error"

    page.close()


def test_demo_replay_colors_all_preloaded_network_roads() -> None:
    _application()
    page = DataReplayPage(load_web_map=False)
    network = page.result_map._pending["setNetwork"]

    page.set_network(network)

    assert len(page.result_map._pending["setRoadResults"]) == 275
    assert {road["congestion_level"] for road in page.result_map._pending["setRoadResults"]} == {
        "畅通",
        "较快",
        "一般",
        "缓行",
        "拥堵",
    }
    page.close()


def test_replay_exports_json_and_image(tmp_path) -> None:
    _application()
    page = DataReplayPage(load_web_map=False)
    page.resize(1280, 760)
    page.show()
    QApplication.processEvents()
    json_path = page.export_json(tmp_path / "result.json")
    image_path = page.export_image(tmp_path / "result.png")

    import json

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "trafficverse.replay-result.v1"
    assert payload["result"]["scenario_name"] == "Town04 混合智驾障碍物场景"
    assert len(payload["result"]["trend_series"]) == 4
    assert len(payload["result"]["road_results"]) == 4
    assert "history_results" not in payload
    assert image_path.stat().st_size > 0
    page.close()


def test_demo_result_is_explicitly_ui_only() -> None:
    result = ReplayResult.demo()

    assert result.experiment_id is None
    assert result.status == "已完成"
    assert result.trend_labels[0] == "00:00"


def test_rerun_configuration_restores_history_setup_fields_and_map() -> None:
    _application()
    page = SceneConfigurationPage()
    result = ReplayResult.demo()
    page.set_maps(
        (
            MapSummary(
                map_id=result.map_id,
                kind="core_run",
                display_name=result.map_name,
                validated=True,
                network_schema_version="sumo-net/display-1.0",
                manifest_available=False,
            ),
        )
    )
    selected_maps: list[str] = []
    page.map_selected.connect(selected_maps.append)

    page.set_replay_configuration(result)

    assert page.scene_name.text() == result.scenario_name
    assert page.seed.value() == result.seed
    assert page.description.toPlainText() == result.description
    assert page.map_combo.currentData() == result.map_id
    assert selected_maps == [result.map_id]
    page.close()
