from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from ui.models import (
    ExperimentStatus,
    ReplayMetric,
    ReplayRecord,
    ReplayRoadResult,
    ReplayTrend,
    ReplayTrendSample,
)
from ui.views.data_replay_page import DataReplayPage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _record(*, run_id: str = "2026-08-11-09-08-07") -> ReplayRecord:
    metrics = (
        ReplayMetric(
            key="vehicle_total", label="车辆总数", value=2457, unit="veh", source="summary.loaded"
        ),
        ReplayMetric(
            key="completed_total",
            label="完成车辆数",
            value=2318,
            unit="veh",
            source="summary.arrived",
        ),
        ReplayMetric(
            key="average_speed_mps",
            label="平均速度",
            value=19.0278,
            unit="m/s",
            source="summary.meanSpeed",
        ),
        ReplayMetric(
            key="average_travel_time_s",
            label="平均行程时间",
            value=888,
            unit="s",
            source="tripinfo.duration",
        ),
        ReplayMetric(
            key="average_waiting_time_s",
            label="平均等待时间",
            value=36.2,
            unit="s",
            source="tripinfo.waitingTime",
        ),
        ReplayMetric(
            key="average_queue_length_veh",
            label="平均排队长度",
            value=8.6,
            unit="veh",
            source="summary.halting",
        ),
        ReplayMetric(
            key="maximum_queue_length_veh",
            label="最大排队长度",
            value=24,
            unit="veh",
            source="summary.halting",
        ),
    )
    trends = tuple(
        ReplayTrend(
            key=key,
            label=label,
            unit=unit,
            samples=(
                ReplayTrendSample(simulation_time_ms=0, value=0),
                ReplayTrendSample(simulation_time_ms=60_000, value=float(index + 1)),
            ),
        )
        for index, (key, label, unit) in enumerate(
            (
                ("vehicle_count", "车辆数量变化", "veh"),
                ("average_speed_mps", "平均速度变化", "m/s"),
                ("queue_length_veh", "排队车辆数变化", "veh"),
                ("average_waiting_time_s", "平均等待时间变化", "s"),
                ("completed_total", "完成车辆数变化", "veh"),
            )
        )
    )
    return ReplayRecord(
        run_id=run_id,
        status=ExperimentStatus.COMPLETED,
        created_at=datetime(2026, 8, 11, 9, 8, 7, tzinfo=timezone.utc),
        started_at=datetime(2026, 8, 11, 9, 8, 8, tzinfo=timezone.utc),
        ended_at=datetime(2026, 8, 11, 9, 9, 8, tzinfo=timezone.utc),
        scene_name="Morning validation",
        map_id="town04",
        map_name="Town04",
        configured_duration_ms=60_000,
        simulation_time_ms=60_000,
        replay_available=True,
        export_available=True,
        metrics=metrics,
        trends=trends,
        road_results=(
            ReplayRoadResult(
                edge_id="edge-a",
                average_speed_mps=10,
                congestion_ratio=0.5,
                traffic_flow_veh_per_hour=720,
                queue_length_m=17.5,
            ),
        ),
    )


def test_replay_page_renders_api_record_status_metrics_and_actual_network() -> None:
    _application()
    record = _record()
    page = DataReplayPage(record)
    page.set_network(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"sumo_edge_id": "edge-a"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 0, 0], [100, 0, 0]],
                    },
                }
            ],
        }
    )

    assert page.objectName() == "dataReplayPage"
    assert page.record_id == record.run_id
    assert page.status_badge.property("status") == "COMPLETED"
    assert page._summary_values["scenario"].text() == "Morning validation"
    assert page._summary_values["map"].text() == "Town04"
    assert page._summary_values["duration"].text() == "00:01:00"
    assert [card.value.text() for card in page._metric_cards] == [
        "2457",
        "2318",
        "68.5",
        "14.8",
        "36.2",
        "8.6",
        "24",
    ]
    assert page.findChildren(QLabel, "replayMetricSource") == []
    assert page.map_canvas._roads == (("edge-a", ((0.0, 0.0), (100.0, 0.0))),)
    page.close()


def test_replay_page_emits_playback_export_back_and_switches_map_mode() -> None:
    _application()
    record = _record()
    page = DataReplayPage(record)
    playback: list[str] = []
    exports: list[str] = []
    back_requests: list[bool] = []
    page.playback_requested.connect(playback.append)
    page.export_requested.connect(exports.append)
    page.back_requested.connect(lambda: back_requests.append(True))

    page.playback_button.click()
    page.export_button.click()
    congestion = next(
        button
        for button in page.findChildren(QPushButton, "replayMapModeButton")
        if button.property("mode") == "congestion"
    )
    congestion.click()
    page.back_button.click()

    assert playback == [record.run_id]
    assert exports == [record.run_id]
    assert page.map_canvas.mode == "congestion"
    assert congestion.isChecked()
    assert back_requests == [True]
    page.close()
