"""Read-only data replay page for a completed simulation record."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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

from ui.models.replay import ReplayMetric, ReplayRecord, ReplayTrend
from ui.views.components import PAGE_CONTENT_MARGIN

_MAP_MODES = (
    ("average_speed", "道路平均速度分布"),
    ("congestion", "道路拥堵分布"),
    ("traffic_flow", "道路交通流量分布"),
    ("queue", "排队情况分布"),
)


def _accent_color(index: int) -> QColor:
    hues = (0.62, 0.51, 0.035, 0.105, 0.985)
    return QColor.fromHsvF(hues[index % len(hues)], 0.78, 0.98)


class _TrendChart(QFrame):
    """Render a small normalized series without introducing a chart dependency."""

    def __init__(self, trend: ReplayTrend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("replayTrendChart")
        self.setMinimumHeight(120)
        self._trend = trend

    def set_trend(self, trend: ReplayTrend) -> None:
        self._trend = trend
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if len(self._trend.values) < 2:
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

        values = self._trend.values
        path = QPainterPath()
        for index, value in enumerate(values):
            x = plot.left() + plot.width() * index / (len(values) - 1)
            y = plot.bottom() - plot.height() * value
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        color = _accent_color(self._trend.color_index)
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
    """Draw an illustrative road result layer for the selected distribution mode."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("replayRoadCanvas")
        self.setMinimumHeight(360)
        self._mode = _MAP_MODES[0][0]

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        canvas = QRectF(self.rect()).adjusted(16.0, 14.0, -16.0, -14.0)
        self._draw_grid(painter, canvas)
        self._draw_roads(painter, canvas)
        self._draw_legend(painter, canvas)

    def _draw_grid(self, painter: QPainter, canvas: QRectF) -> None:
        dot_color = self.palette().mid().color()
        dot_color.setAlpha(85)
        painter.setPen(QPen(dot_color, 1.0))
        x = canvas.left()
        while x <= canvas.right():
            y = canvas.top()
            while y <= canvas.bottom():
                painter.drawPoint(QPointF(x, y))
                y += 20.0
            x += 20.0

    def _draw_roads(self, painter: QPainter, canvas: QRectF) -> None:
        def point(x_ratio: float, y_ratio: float) -> QPointF:
            return QPointF(
                canvas.left() + canvas.width() * x_ratio,
                canvas.top() + canvas.height() * y_ratio,
            )

        roads: tuple[tuple[QPointF, ...], ...] = (
            (
                point(0.18, 0.16),
                point(0.37, 0.39),
                point(0.52, 0.57),
                point(0.72, 0.77),
                point(0.87, 0.90),
            ),
            (
                point(0.15, 0.79),
                point(0.34, 0.62),
                point(0.49, 0.48),
                point(0.68, 0.29),
                point(0.88, 0.20),
            ),
            (point(0.50, 0.05), point(0.50, 0.31), point(0.51, 0.55)),
            (point(0.51, 0.55), point(0.51, 0.73), point(0.52, 0.95)),
            (
                point(0.50, 0.50),
                point(0.46, 0.55),
                point(0.47, 0.64),
                point(0.54, 0.67),
                point(0.58, 0.60),
                point(0.56, 0.52),
                point(0.50, 0.50),
            ),
        )
        mode_offset = next(
            (index for index, (mode, _) in enumerate(_MAP_MODES) if mode == self._mode),
            0,
        )
        outline = self.palette().shadow().color()
        outline.setAlpha(210)
        for index, road in enumerate(roads):
            path = QPainterPath(road[0])
            for current in road[1:]:
                path.lineTo(current)
            painter.setPen(QPen(outline, 15.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(path)
            painter.setPen(
                QPen(
                    _accent_color(index + mode_offset),
                    7.0,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(path)

    def _draw_legend(self, painter: QPainter, canvas: QRectF) -> None:
        labels_by_mode = {
            "average_speed": ("畅通", "较快", "一般", "缓行", "拥堵"),
            "congestion": ("低", "较低", "中等", "较高", "严重"),
            "traffic_flow": ("稀疏", "较少", "适中", "较多", "饱和"),
            "queue": ("无排队", "短队列", "一般", "较长", "严重"),
        }
        legend = QRectF(canvas.left() + 2.0, canvas.top() + 2.0, 82.0, 150.0)
        background = self.palette().window().color()
        background.setAlpha(232)
        painter.setPen(QPen(self.palette().mid().color(), 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(legend, 5.0, 5.0)
        painter.setPen(self.palette().text().color())
        painter.drawText(
            legend.adjusted(12.0, 8.0, -8.0, -8.0),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            "图例",
        )
        for index, label in enumerate(labels_by_mode[self._mode]):
            y = legend.top() + 38.0 + index * 21.0
            painter.setBrush(_accent_color(index))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(legend.left() + 17.0, y), 5.0, 5.0)
            painter.setPen(self.palette().text().color())
            painter.drawText(
                QRectF(legend.left() + 30.0, y - 8.0, 48.0, 16.0),
                Qt.AlignmentFlag.AlignVCenter,
                label,
            )


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
        self.value = QLabel()
        self.value.setObjectName("replayMetricValue")
        self.unit = QLabel()
        self.unit.setObjectName("replayMetricUnit")
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.unit)

    def set_metric(self, metric: ReplayMetric) -> None:
        self.label.setText(metric.label)
        self.value.setText(metric.value)
        self.value.setProperty("tone", metric.tone)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)
        self.unit.setText(metric.unit)


class DataReplayPage(QWidget):
    """Present one immutable replay record with fabricated aggregate data."""

    back_requested = Signal()

    def __init__(self, record: ReplayRecord, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dataReplayPage")
        self._record = record
        self._summary_values: dict[str, QLabel] = {}
        self._metric_cards: list[_ReplayMetricCard] = []
        self._trend_charts: list[_TrendChart] = []
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
        body_layout.setContentsMargins(
            PAGE_CONTENT_MARGIN,
            14,
            PAGE_CONTENT_MARGIN,
            PAGE_CONTENT_MARGIN,
        )
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
        self.set_record(record)

    @property
    def record_id(self) -> str:
        return self._record.record_id

    def set_record(self, record: ReplayRecord) -> None:
        self._record = record
        self.timestamp_badge.setText(record.occurred_at)
        summary = {
            "map": record.map_name,
            "scenario": record.scenario_name,
            "started": record.started_at,
            "ended": record.ended_at,
            "duration": record.duration,
            "status": f"●  {record.status}",
        }
        for key, value in summary.items():
            self._summary_values[key].setText(value)
        for card, metric in zip(self._metric_cards, record.metrics, strict=True):
            card.set_metric(metric)
        for chart, trend in zip(self._trend_charts, record.trends, strict=True):
            chart.set_trend(trend)
            parent = chart.parentWidget()
            title = parent.findChild(QLabel, "replayChartTitle") if parent is not None else None
            if title is not None:
                title.setText(trend.title)

    def _header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 12, PAGE_CONTENT_MARGIN, 12)
        layout.setSpacing(12)
        title = QLabel("数据回放")
        title.setObjectName("pageTitle")
        self.timestamp_badge = QLabel()
        self.timestamp_badge.setObjectName("replayTimestamp")
        layout.addWidget(title)
        layout.addWidget(self.timestamp_badge)
        layout.addStretch(1)

        self.restart_button = QPushButton("↻  重新仿真")
        self.restart_button.setObjectName("replayRestartButton")
        self.restart_button.setToolTip("占位按钮，暂未关联重新仿真逻辑")
        self.back_button = QPushButton("←  返回项目")
        self.back_button.setObjectName("replayBackButton")
        self.back_button.clicked.connect(self.back_requested)
        self.export_button = QPushButton("⇩  导出结果")
        self.export_button.setObjectName("replayExportButton")
        self.export_button.setProperty("role", "primaryAction")
        self.export_button.setToolTip("占位按钮，导出能力待接入")
        layout.addWidget(self.restart_button)
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
            ("map", "使用的地图"),
            ("scenario", "使用的场景"),
            ("started", "开始时间"),
            ("ended", "结束时间"),
            ("duration", "仿真时长"),
            ("status", "结束状态"),
        )
        for key, label in items:
            item = QWidget()
            item.setObjectName("replaySummaryItem")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(14, 9, 14, 9)
            item_layout.setSpacing(3)
            name = QLabel(label)
            name.setObjectName("replaySummaryLabel")
            value = QLabel()
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
        for index, trend in enumerate(self._record.trends):
            card = QFrame()
            card.setObjectName("replayChartCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)
            heading = QHBoxLayout()
            title = QLabel(trend.title)
            title.setObjectName("replayChartTitle")
            range_label = QLabel("0  –  40 min")
            range_label.setObjectName("replayChartRange")
            heading.addWidget(title)
            heading.addStretch(1)
            heading.addWidget(range_label)
            chart = _TrendChart(trend, card)
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

    def _set_map_mode(self, mode: str) -> None:
        self.map_canvas.set_mode(mode)

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
