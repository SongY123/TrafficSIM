"""Read-only result analysis page backed by one formal simulation artifact."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.models import ReplayMetric, ReplayRecord, ReplayRoadResult, ReplayTrend
from ui.views.components import PAGE_CONTENT_MARGIN

_MAP_MODES = (
    ("average_speed", "道路平均速度分布"),
    ("congestion", "道路拥堵分布"),
    ("traffic_flow", "道路交通流量分布"),
    ("queue", "道路排队长度分布"),
)
_TREND_KEYS = (
    ("vehicle_count", "车辆数量变化", "veh"),
    ("average_speed_mps", "平均速度变化", "m/s"),
    ("queue_length_veh", "排队车辆数量变化", "veh"),
    ("average_waiting_time_s", "平均等待时间变化", "s"),
    ("completed_total", "完成行程车辆数变化", "veh"),
)
_STATUS_LABELS = {
    "CREATED": "已创建",
    "PREPARING": "准备中",
    "READY": "已就绪",
    "RUNNING": "运行中",
    "PAUSED": "已暂停",
    "STOPPING": "停止中",
    "COMPLETED": "已完成",
    "FAILED": "失败",
}


def _accent_color(index: int) -> QColor:
    hues = (0.62, 0.51, 0.035, 0.105, 0.985)
    return QColor.fromHsvF(hues[index % len(hues)], 0.78, 0.98)


class _TrendChart(QFrame):
    """Render source-aligned trend values with local visual normalization."""

    def __init__(
        self,
        trend: ReplayTrend,
        color_index: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("replayTrendChart")
        self.setMinimumHeight(120)
        self._trend = trend
        self._color_index = color_index

    def set_trend(self, trend: ReplayTrend) -> None:
        self._trend = trend
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        samples = self._trend.samples
        if len(samples) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = QRectF(self.rect()).adjusted(42.0, 10.0, -18.0, -24.0)
        grid_color = self.palette().mid().color()
        grid_color.setAlpha(105)
        painter.setPen(QPen(grid_color, 1.0))
        for index in range(4):
            y = plot.top() + (plot.height() * index / 3)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())
        painter.drawLine(plot.bottomLeft(), plot.topLeft())

        values = tuple(sample.value for sample in samples)
        minimum = min(values)
        span = max(values) - minimum
        first_time_ms = samples[0].simulation_time_ms
        time_span_ms = max(1, samples[-1].simulation_time_ms - first_time_ms)
        path = QPainterPath()
        for index, sample in enumerate(samples):
            x = plot.left() + plot.width() * (
                (sample.simulation_time_ms - first_time_ms) / time_span_ms
            )
            ratio = 0.5 if span == 0.0 else (sample.value - minimum) / span
            y = plot.bottom() - plot.height() * ratio
            path.moveTo(x, y) if index == 0 else path.lineTo(x, y)

        color = _accent_color(self._color_index)
        fill = QColor(color)
        fill.setAlpha(42)
        area = QPainterPath(path)
        area.lineTo(plot.right(), plot.bottom())
        area.lineTo(plot.left(), plot.bottom())
        area.closeSubpath()
        painter.fillPath(area, fill)
        painter.setPen(QPen(color, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)


class _RoadResultCanvas(QFrame):
    """Draw actual SUMO lane geometry colored by parsed edge results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("replayRoadCanvas")
        self.setMinimumHeight(360)
        self._mode = _MAP_MODES[0][0]
        self._roads: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = ()
        self._results: dict[str, ReplayRoadResult] = {}

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_network(self, geojson: object) -> None:
        roads: list[tuple[str, tuple[tuple[float, float], ...]]] = []
        if isinstance(geojson, Mapping):
            features = geojson.get("features")
            if isinstance(features, list):
                for feature in features:
                    road = self._road_feature(feature)
                    if road is not None:
                        roads.append(road)
        self._roads = tuple(roads)
        self.update()

    def set_results(self, results: tuple[ReplayRoadResult, ...]) -> None:
        self._results = {result.edge_id: result for result in results}
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        canvas = QRectF(self.rect()).adjusted(18.0, 18.0, -18.0, -38.0)
        if not self._roads:
            painter.setPen(self.palette().mid().color())
            painter.drawText(canvas, Qt.AlignmentFlag.AlignCenter, "暂无可用的实际路网结果")
            return
        values = {
            edge_id: value
            for edge_id in {road[0] for road in self._roads}
            if (value := self._result_value(edge_id)) is not None
        }
        minimum = min(values.values(), default=0.0)
        maximum = max(values.values(), default=1.0)
        span = max(maximum - minimum, 1e-9)
        transform = self._transform(canvas)
        for edge_id, points in self._roads:
            path = QPainterPath(transform(points[0]))
            for point in points[1:]:
                path.lineTo(transform(point))
            value = values.get(edge_id)
            ratio = 0.0 if value is None else (value - minimum) / span
            if self._mode == "average_speed":
                ratio = 1.0 - ratio
            painter.setPen(
                QPen(
                    QColor.fromHsvF(0.33 * (1.0 - ratio), 0.82, 0.96),
                    3.0,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(path)
        painter.setPen(self.palette().text().color())
        label = next(label for mode, label in _MAP_MODES if mode == self._mode)
        painter.drawText(
            QRectF(canvas.left(), canvas.bottom() + 8.0, canvas.width(), 22.0),
            Qt.AlignmentFlag.AlignLeft,
            label,
        )

    def _transform(self, canvas: QRectF) -> Callable[[tuple[float, float]], QPointF]:
        points = tuple(point for _, road in self._roads for point in road)
        minimum_x = min(point[0] for point in points)
        maximum_x = max(point[0] for point in points)
        minimum_y = min(point[1] for point in points)
        maximum_y = max(point[1] for point in points)
        width = max(maximum_x - minimum_x, 1.0)
        height = max(maximum_y - minimum_y, 1.0)
        scale = min(canvas.width() / width, canvas.height() / height)
        offset_x = canvas.left() + (canvas.width() - width * scale) / 2.0
        offset_y = canvas.top() + (canvas.height() - height * scale) / 2.0

        def apply(point: tuple[float, float]) -> QPointF:
            return QPointF(
                offset_x + (point[0] - minimum_x) * scale,
                offset_y + (maximum_y - point[1]) * scale,
            )

        return apply

    def _result_value(self, edge_id: str) -> float | None:
        result = self._results.get(edge_id)
        if result is None:
            return None
        return {
            "average_speed": result.average_speed_mps,
            "congestion": result.congestion_ratio,
            "traffic_flow": result.traffic_flow_veh_per_hour,
            "queue": result.queue_length_m,
        }[self._mode]

    @staticmethod
    def _road_feature(
        feature: object,
    ) -> tuple[str, tuple[tuple[float, float], ...]] | None:
        if not isinstance(feature, Mapping):
            return None
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, Mapping) or not isinstance(geometry, Mapping):
            return None
        edge_id = properties.get("sumo_edge_id")
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "LineString" or not isinstance(edge_id, str):
            return None
        if not isinstance(coordinates, list):
            return None
        points: list[tuple[float, float]] = []
        for coordinate in coordinates:
            if (
                isinstance(coordinate, list)
                and len(coordinate) >= 2
                and isinstance(coordinate[0], (int, float))
                and isinstance(coordinate[1], (int, float))
            ):
                points.append((float(coordinate[0]), float(coordinate[1])))
        return (edge_id, tuple(points)) if len(points) >= 2 else None


class _ReplayMetricCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("replayMetricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(118)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        self.label = QLabel()
        self.label.setObjectName("replayMetricLabel")
        self.value = QLabel("—")
        self.value.setObjectName("replayMetricValue")
        self.unit = QLabel()
        self.unit.setObjectName("replayMetricUnit")
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.unit)

    def set_metric(self, metric: ReplayMetric) -> None:
        value, unit = self._display(metric)
        self.label.setText(metric.label)
        self.value.setText(value)
        self.unit.setText(unit)

    @staticmethod
    def _display(metric: ReplayMetric) -> tuple[str, str]:
        if metric.value is None:
            return "—", metric.unit
        if metric.key in {"vehicle_total", "completed_total", "maximum_queue_length_veh"}:
            return f"{metric.value:.0f}", metric.unit
        if metric.key == "average_speed_mps":
            return f"{metric.value * 3.6:.1f}", "km/h"
        if metric.key == "average_travel_time_s":
            return f"{metric.value / 60.0:.1f}", "min"
        return f"{metric.value:.1f}", metric.unit


class DataReplayPage(QWidget):
    """Present actual SUMO output, export, and structured replay availability."""

    back_requested = Signal()
    playback_requested = Signal(str)
    export_requested = Signal(str)

    def __init__(
        self,
        record: ReplayRecord | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dataReplayPage")
        self._record: ReplayRecord | None = None
        self._summary_values: dict[str, QLabel] = {}
        self._metric_cards: list[_ReplayMetricCard] = []
        self._trend_charts: list[_TrendChart] = []
        self._trend_titles: list[QLabel] = []
        self._trend_ranges: list[QLabel] = []
        self._mode_buttons: dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())
        scroll = QScrollArea()
        scroll.setObjectName("replayScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body = QWidget()
        body.setObjectName("replayBody")
        body.setMinimumWidth(980)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(PAGE_CONTENT_MARGIN, 14, PAGE_CONTENT_MARGIN, 16)
        body_layout.setSpacing(12)
        body_layout.addWidget(self._summary_bar())
        body_layout.addWidget(self._metrics_section())
        results = QHBoxLayout()
        results.setSpacing(12)
        results.addWidget(self._trends_section(), 3)
        results.addWidget(self._map_section(), 2)
        body_layout.addLayout(results, 1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        if record is not None:
            self.set_record(record)

    @property
    def record_id(self) -> str:
        return self._record.run_id if self._record is not None else ""

    def set_record(self, record: ReplayRecord) -> None:
        self._record = record
        self.timestamp_badge.setText(self._datetime_text(record.created_at))
        status = _STATUS_LABELS[record.status.value]
        self.status_badge.setText(f"●  {status}")
        self.status_badge.setProperty("status", record.status.value)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        actual_duration_ms = record.simulation_time_ms
        summary = {
            "map": record.map_name,
            "scenario": record.scene_name,
            "started": self._datetime_text(record.started_at),
            "ended": self._datetime_text(record.ended_at),
            "duration": self._duration_text(actual_duration_ms),
            "status": status,
        }
        for key, value in summary.items():
            self._summary_values[key].setText(value)
        for index, card in enumerate(self._metric_cards):
            if index < len(record.metrics):
                card.set_metric(record.metrics[index])
        trends = {trend.key: trend for trend in record.trends}
        for index, (key, label, unit) in enumerate(_TREND_KEYS):
            trend = trends.get(
                key,
                ReplayTrend(key=key, label=label, unit=unit, samples=()),
            )
            self._trend_charts[index].set_trend(trend)
            self._trend_titles[index].setText(trend.label)
            maximum_ms = trend.samples[-1].simulation_time_ms if trend.samples else 0
            self._trend_ranges[index].setText(f"0 – {self._duration_text(maximum_ms)}")
        self.map_canvas.set_results(record.road_results)
        self.playback_button.setEnabled(record.replay_available)
        self.playback_button.setToolTip(
            "读取结构化快照与增量，不会重新运行 SUMO"
            if record.replay_available
            else "该历史记录未包含结构化回放数据"
        )
        self.export_button.setEnabled(record.export_available)

    @Slot(object)
    def set_network(self, geojson: object) -> None:
        self.map_canvas.set_network(geojson)

    def _header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 12, PAGE_CONTENT_MARGIN, 12)
        layout.setSpacing(12)
        title = QLabel("历史仿真结果")
        title.setObjectName("pageTitle")
        self.timestamp_badge = QLabel("等待选择记录")
        self.timestamp_badge.setObjectName("replayTimestamp")
        self.status_badge = QLabel("●  未加载")
        self.status_badge.setObjectName("replayStatusBadge")
        layout.addWidget(title)
        layout.addWidget(self.timestamp_badge)
        layout.addWidget(self.status_badge)
        layout.addStretch(1)
        self.playback_button = QPushButton("▶  仿真回放")
        self.playback_button.setObjectName("replayPlaybackButton")
        self.playback_button.setEnabled(False)
        self.playback_button.clicked.connect(self._request_playback)
        self.back_button = QPushButton("←  返回项目")
        self.back_button.setObjectName("replayBackButton")
        self.back_button.clicked.connect(self.back_requested)
        self.export_button = QPushButton("⇩  导出结果")
        self.export_button.setObjectName("replayExportButton")
        self.export_button.setProperty("role", "primaryAction")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._request_export)
        layout.addWidget(self.playback_button)
        layout.addWidget(self.back_button)
        layout.addWidget(self.export_button)
        return frame

    def _summary_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("replaySummaryBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        items = (
            ("map", "实际使用地图"),
            ("scenario", "仿真场景"),
            ("started", "开始时间"),
            ("ended", "结束时间"),
            ("duration", "实际仿真时长"),
            ("status", "当前状态"),
        )
        for key, label in items:
            item = QWidget()
            item.setObjectName("replaySummaryItem")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(14, 9, 14, 9)
            item_layout.setSpacing(3)
            name = QLabel(label)
            name.setObjectName("replaySummaryLabel")
            value = QLabel("—")
            value.setObjectName("replaySummaryValue")
            value.setProperty("summaryKey", key)
            self._summary_values[key] = value
            item_layout.addWidget(name)
            item_layout.addWidget(value)
            layout.addWidget(item, 2 if key in {"scenario", "started", "ended"} else 1)
        return frame

    def _metrics_section(self) -> QFrame:
        section, layout = self._section("核心结果指标")
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        for _ in range(7):
            card = _ReplayMetricCard()
            self._metric_cards.append(card)
            metrics.addWidget(card)
        layout.addLayout(metrics)
        return section

    def _trends_section(self) -> QFrame:
        section, layout = self._section("指标趋势")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, (key, label, unit) in enumerate(_TREND_KEYS):
            trend = ReplayTrend(key=key, label=label, unit=unit, samples=())
            card = QFrame()
            card.setObjectName("replayChartCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            heading = QHBoxLayout()
            title = QLabel(label)
            title.setObjectName("replayChartTitle")
            range_label = QLabel("0 – 00:00:00")
            range_label.setObjectName("replayChartRange")
            heading.addWidget(title)
            heading.addStretch(1)
            heading.addWidget(range_label)
            chart = _TrendChart(trend, index, card)
            self._trend_titles.append(title)
            self._trend_ranges.append(range_label)
            self._trend_charts.append(chart)
            card_layout.addLayout(heading)
            card_layout.addWidget(chart, 1)
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid, 1)
        return section

    def _map_section(self) -> QFrame:
        section, layout = self._section("地图结果", with_title=False)
        heading = QHBoxLayout()
        title = QLabel("地图结果")
        title.setObjectName("replaySectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (mode, label) in enumerate(_MAP_MODES):
            button = QPushButton(label)
            button.setObjectName("replayMapModeButton")
            button.setProperty("mode", mode)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, value=mode: self._set_map_mode(value))
            group.addButton(button)
            self._mode_buttons[mode] = button
            heading.addWidget(button)
        layout.addLayout(heading)
        self.map_canvas = _RoadResultCanvas()
        layout.addWidget(self.map_canvas, 1)
        return section

    def _request_playback(self) -> None:
        if self._record is not None and self._record.replay_available:
            self.playback_requested.emit(self._record.run_id)

    def _request_export(self) -> None:
        if self._record is not None and self._record.export_available:
            self.export_requested.emit(self._record.run_id)

    def _set_map_mode(self, mode: str) -> None:
        self.map_canvas.set_mode(mode)

    @staticmethod
    def _datetime_text(value: datetime | None) -> str:
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S") if value is not None else "—"

    @staticmethod
    def _duration_text(duration_ms: int) -> str:
        hours, remainder = divmod(duration_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds = remainder // 1_000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _section(
        title: str,
        *,
        with_title: bool = True,
    ) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("replaySection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        if with_title:
            label = QLabel(title)
            label.setObjectName("replaySectionTitle")
            layout.addWidget(label)
        return section, layout
