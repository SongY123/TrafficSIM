from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from ui.models import MOCK_REPLAY_RECORDS
from ui.views.data_replay_page import DataReplayPage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def test_replay_page_renders_selected_mock_record_and_updates_all_sections() -> None:
    _application()
    page = DataReplayPage(MOCK_REPLAY_RECORDS[0])

    assert page.objectName() == "dataReplayPage"
    assert page.record_id == MOCK_REPLAY_RECORDS[0].record_id
    assert page.timestamp_badge.text() == "2026-07-22 22:00:10"
    assert [card.value.text() for card in page._metric_cards] == [
        "2457",
        "2318",
        "68.5",
        "14.8",
        "36.2",
        "8.6",
        "24",
    ]
    labels = {label.text() for label in page.findChildren(QLabel)}
    assert {"核心结果指标", "指标趋势", "地图结果"} <= labels

    page.set_record(MOCK_REPLAY_RECORDS[1])

    assert page.record_id == MOCK_REPLAY_RECORDS[1].record_id
    assert page.timestamp_badge.text() == "2026-07-22 21:30:05"
    assert page._summary_values["scenario"].text() == "晚高峰匝道汇流"
    assert page._metric_cards[0].value.text() == "2216"
    page.close()


def test_replay_actions_keep_restart_as_placeholder_and_switch_map_mode() -> None:
    _application()
    page = DataReplayPage(MOCK_REPLAY_RECORDS[0])
    back_requests: list[bool] = []
    page.back_requested.connect(lambda: back_requests.append(True))

    original_record_id = page.record_id
    page.restart_button.click()
    congestion = next(
        button
        for button in page.findChildren(QPushButton, "replayMapModeButton")
        if button.property("mode") == "congestion"
    )
    congestion.click()
    page.back_button.click()

    assert page.record_id == original_record_id
    assert page.map_canvas.mode == "congestion"
    assert congestion.isChecked()
    assert back_requests == [True]
    page.close()
