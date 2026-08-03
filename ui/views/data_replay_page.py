"""Historical simulation result replay page."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ui.models import ReplayResult, ReplayRoadResult, ReplayTrendSeries
from ui.views.components import PAGE_CONTENT_MARGIN, metric_card, page_header, panel
from ui.widgets.maplibre_deck_map import MapLibreDeckMapWidget


class _TrendChart(QWidget):
    """Lightweight Qt chart that keeps the replay page free of a new chart dependency."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._labels: tuple[str, ...] = ()
        self._series: tuple[ReplayTrendSeries, ...] = ()

    def set_data(self, labels: tuple[str, ...], series: tuple[ReplayTrendSeries, ...]) -> None:
        self._labels = labels
        self._series = series
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = QRectF(12, 12, max(1, self.width() - 24), max(1, self.height() - 24))
        painter.setPen(QPen(QColor("#363b45"), 1))
        for row in range(5):
            y = plot.top() + plot.height() * row / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        if not self._series or len(self._labels) < 2:
            painter.end()
            return

        maximum = max((max(series.values, default=0.0) for series in self._series), default=1.0)
        maximum = max(maximum, 1.0)
        for series in self._series:
            color = QColor(series.color)
            path = QPainterPath()
            for index, value in enumerate(series.values):
                x = plot.left() + plot.width() * index / max(1, len(self._labels) - 1)
                y = plot.bottom() - plot.height() * value / maximum
                point = QPointF(x, y)
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            fill = QPainterPath(path)
            fill.lineTo(plot.right(), plot.bottom())
            fill.lineTo(plot.left(), plot.bottom())
            fill.closeSubpath()
            painter.fillPath(fill, QColor(color.red(), color.green(), color.blue(), 32))
            painter.setPen(QPen(color, 2.5))
            painter.drawPath(path)
        painter.end()


class DataReplayPage(QWidget):
    """Present historical simulation results and expose replay actions."""

    rerun_requested = Signal(object)
    return_requested = Signal()
    export_requested = Signal(str)

    def __init__(self, *, load_web_map: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dataReplayPage")
        self._history_results = ReplayResult.demo_records()
        self._result = self._history_results[0]
        self._has_network = False
        self._network: dict[str, object] | None = None
        self._build_ui(load_web_map)
        self.set_history_results(self._history_results)

    def _build_ui(self, load_web_map: bool) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("数据回放", "", self._header_actions()))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 16, PAGE_CONTENT_MARGIN, 18)
        layout.setSpacing(12)
        layout.addWidget(self._overview_panel())
        layout.addWidget(self._metrics_panel())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        trend_panel = self._trend_panel()
        map_panel = self._map_result_panel(load_web_map)
        splitter.addWidget(trend_panel)
        splitter.addWidget(map_panel)
        splitter.setSizes([620, 720])
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        self._trend_export_widget = trend_panel
        self._map_export_widget = map_panel
        layout.addWidget(splitter, 1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _header_actions(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.record_date = QLabel()
        self.record_date.setObjectName("replayRecordDate")
        self.record_date.setMinimumWidth(150)
        row.addWidget(self.record_date)
        self.status_badge = QLabel("已完成")
        self.status_badge.setObjectName("statusBadge")
        self.status_badge.hide()
        rerun = QPushButton("重新仿真")
        rerun.setObjectName("primaryButton")
        rerun.clicked.connect(lambda: self.rerun_requested.emit(self._result))
        back = QPushButton("返回项目")
        back.clicked.connect(self.return_requested)
        export_result = QPushButton("导出结果")
        export_result.setObjectName("primaryButton")
        export_menu = QMenu(export_result)
        export_json = export_menu.addAction("导出 JSON")
        export_json.setObjectName("exportJsonAction")
        export_json.triggered.connect(lambda: self.export_requested.emit("json"))
        export_image = export_menu.addAction("导出图片")
        export_image.setObjectName("exportImageAction")
        export_image.triggered.connect(lambda: self.export_requested.emit("image"))
        export_result.setMenu(export_menu)
        row.addWidget(rerun)
        row.addWidget(back)
        row.addWidget(export_result)
        self._rerun_button = rerun
        self._export_menu = export_menu
        return widget

    def _overview_panel(self) -> QFrame:
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.overview_values: dict[str, QLabel] = {}
        values = (
            ("使用的地图", "map_name"),
            ("使用的场景", "scenario_name"),
            ("开始时间", "started_at"),
            ("结束时间", "finished_at"),
            ("仿真时长", "duration"),
            ("结束状态", "end_status"),
        )
        frame = QFrame()
        frame.setObjectName("replayOverview")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(0)
        for index, (label, key) in enumerate(values):
            if index:
                divider = QFrame()
                divider.setFrameShape(QFrame.Shape.VLine)
                divider.setObjectName("replayOverviewDivider")
                row.addWidget(divider)
            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(12, 0, 12, 0)
            item_layout.setSpacing(3)
            item_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            caption = QLabel(label)
            caption.setObjectName("replayFieldLabel")
            caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            value = QLabel("—")
            value.setObjectName("replayFieldValue")
            value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            value.setWordWrap(True)
            self.overview_values[key] = value
            item_layout.addWidget(caption)
            item_layout.addWidget(value)
            row.addWidget(item, 1)
        return frame

    def _metrics_panel(self) -> QFrame:
        body = QWidget()
        self.metric_grid = QGridLayout(body)
        self.metric_grid.setContentsMargins(0, 0, 0, 0)
        self.metric_grid.setHorizontalSpacing(10)
        self.metric_grid.setVerticalSpacing(8)
        self.metric_cards: list[QFrame] = []
        return panel("核心结果指标", body)

    def _trend_panel(self) -> QFrame:
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.trend_charts: dict[str, _TrendChart] = {}
        for index, series in enumerate(self._result.trend_series):
            card = self._trend_card(series)
            grid.addWidget(card, index // 2, index % 2)
        return panel("指标趋势", body)

    def _trend_card(self, series: ReplayTrendSeries) -> QFrame:
        card = QFrame()
        card.setObjectName("trendCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title = QLabel(series.label)
        title.setObjectName("metricLabel")
        range_label = QLabel(f"{self._result.trend_labels[0]}  ·  {self._result.trend_labels[-1]}")
        range_label.setObjectName("trendRange")
        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(range_label)
        chart = _TrendChart()
        chart.setMinimumHeight(128)
        chart.set_data(self._result.trend_labels, (series,))
        self.trend_charts[series.label] = chart
        layout.addLayout(heading)
        layout.addWidget(chart, 1)
        return card

    def _map_result_panel(self, load_web_map: bool) -> QFrame:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        modes = (
            "道路平均速度分布",
            "道路拥堵分布",
            "道路交通量分布",
            "拥堵情况分布",
        )
        mode_row = QHBoxLayout()
        mode_row.setSpacing(5)
        self.map_mode_buttons: list[QPushButton] = []
        for index, mode in enumerate(modes):
            button = QPushButton(mode)
            button.setObjectName("replayMapModeButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, selected=index: self._select_map_mode(selected)
            )
            mode_row.addWidget(button)
            self.map_mode_buttons.append(button)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)
        self._select_map_mode(0)
        self.result_map = MapLibreDeckMapWidget(load_page=load_web_map, page_mode="replay")
        self.result_map.setMinimumHeight(300)
        layout.addWidget(self.result_map, 1)
        return panel("地图结果", body)

    def _select_map_mode(self, selected: int) -> None:
        for index, button in enumerate(self.map_mode_buttons):
            button.setChecked(index == selected)

    def set_result(self, result: ReplayResult) -> None:
        self._result = result
        self.status_badge.setText(result.status)
        self.record_date.setText(result.started_at.strftime("%Y-%m-%d %H:%M:%S"))
        self.record_date.setToolTip(result.scenario_name)
        self.overview_values["scenario_name"].setText(result.scenario_name)
        self.overview_values["map_name"].setText(result.map_name)
        self.overview_values["started_at"].setText(_format_datetime(result.started_at))
        self.overview_values["finished_at"].setText(_format_datetime(result.finished_at))
        self.overview_values["duration"].setText(f"{result.duration_s:.1f} s")
        self.overview_values["end_status"].setText(result.end_status)
        status_value = self.overview_values["end_status"]
        status_value.setProperty(
            "statusTone", "success" if result.end_status == "正常结束" else "error"
        )
        status_value.style().unpolish(status_value)
        status_value.style().polish(status_value)

        for card in self.metric_cards:
            card.deleteLater()
        self.metric_cards.clear()
        for index, metric in enumerate(result.metrics):
            card = metric_card(metric.label, metric.value, metric.detail)
            self.metric_cards.append(card)
            self.metric_grid.addWidget(card, index // 7, index % 7)

        for series in result.trend_series:
            chart = self.trend_charts.get(series.label)
            if chart is not None:
                chart.set_data(result.trend_labels, (series,))
        display_road_results = result.road_results
        if result.experiment_id is None:
            demo_network = self._network
            if demo_network is None:
                demo_network = _load_demo_network()
                self._network = demo_network
                self._has_network = True
                self.result_map.set_network(demo_network)
            display_road_results = _expand_demo_road_results(result.road_results, demo_network)
        self.result_map.set_road_results(display_road_results)
        del display_road_results

    def set_network(self, geojson: object) -> None:
        self._has_network = isinstance(geojson, dict)
        self._network = geojson if isinstance(geojson, dict) else None
        self.result_map.set_network(geojson)
        if self._result.experiment_id is None and isinstance(geojson, dict):
            display_road_results = _expand_demo_road_results(self._result.road_results, geojson)
            self.result_map.set_road_results(display_road_results)

    def set_history_results(self, results: tuple[ReplayResult, ...]) -> None:
        self._history_results = results or ReplayResult.demo_records()
        self.set_result(self._history_results[0])

    @property
    def history_results(self) -> tuple[ReplayResult, ...]:
        return self._history_results

    def select_history(self, index: int) -> None:
        if 0 <= index < len(self._history_results):
            self.set_result(self._history_results[index])

    def set_status(self, status: str) -> None:
        self.status_badge.setText(status)

    def set_simulation_time(self, simulation_time_ms: int) -> None:
        del simulation_time_ms

    def export_json(self, path: str | Path) -> Path:
        """Write the selected replay result as a portable JSON document."""

        target = Path(path)
        payload = {
            "schema_version": "trafficverse.replay-result.v1",
            "result": asdict(self._result),
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
            encoding="utf-8",
        )
        return target

    def export_image(self, path: str | Path) -> Path:
        """Write the trend and map result panels as one PNG image."""

        target = Path(path)
        trend = self._trend_export_widget.grab()
        map_result = self._map_export_widget.grab()
        if trend.isNull() or map_result.isNull():
            raise OSError("回放结果面板尚未完成渲染")

        gap = 12
        canvas = QPixmap(
            trend.width() + gap + map_result.width(), max(trend.height(), map_result.height())
        )
        canvas.fill(QColor("#141414"))
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, trend)
        painter.drawPixmap(trend.width() + gap, 0, map_result)
        painter.end()
        if not canvas.save(str(target), "PNG"):
            raise OSError(f"无法写入图片文件: {target}")
        return target


def _format_datetime(value: datetime) -> str:
    return value.strftime("%m-%d %H:%M:%S")


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported replay export value: {type(value).__name__}")


def _load_demo_network() -> dict[str, object]:
    """Load the checked-in Town04 display network for the UI-only replay fixture."""

    path = Path(__file__).resolve().parents[2] / "configs/maps/town04/network.geojson"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("Town04 replay network must be a GeoJSON FeatureCollection")
    return payload


def _expand_demo_road_results(
    seed_results: tuple[ReplayRoadResult, ...], network: dict[str, object]
) -> tuple[ReplayRoadResult, ...]:
    """Give the UI-only Town04 fixture a visible result color for every display road."""

    existing = {_normalize_road_result_id(item.road_id): item for item in seed_results}
    features = network.get("features", ())
    road_ids = sorted(
        {
            road_id
            for feature in features
            if isinstance(feature, dict)
            and isinstance(feature.get("properties"), dict)
            and (
                road_id := _normalize_road_result_id(
                    feature.get("properties", {}).get("road_id")
                    or feature.get("properties", {}).get("edge_id")
                    or feature.get("properties", {}).get("sumo_edge_id")
                )
            )
            is not None
        }
    )
    levels = ("畅通", "较快", "一般", "缓行", "拥堵")
    expanded: list[ReplayRoadResult] = []
    for index, road_id in enumerate(road_ids):
        if road_id in existing:
            expanded.append(existing[road_id])
            continue
        level = levels[index % len(levels)]
        expanded.append(
            ReplayRoadResult(
                road_id=road_id,
                average_speed_mps=(13.2, 11.0, 9.0, 7.4, 3.1)[index % 5],
                congestion_level=level,
                flow_veh_per_h=360.0 + (index % 5) * 65.0,
                queue_length=(1.0, 3.0, 5.0, 8.0, 22.0)[index % 5],
            )
        )
    return tuple(expanded)


def _normalize_road_result_id(value: object) -> str | None:
    if value is None:
        return None
    road_id = str(value)
    if road_id.startswith(":"):
        return None
    if road_id.startswith("road:"):
        road_id = road_id.removeprefix("road:")
    road_id = road_id.removeprefix("-")
    return road_id or None
