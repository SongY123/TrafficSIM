"""Live MapLibre/deck.gl traffic monitoring page."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.models import ControlAvailability
from ui.views.components import (
    PAGE_CONTENT_MARGIN,
    PANEL_CONTENT_MARGIN,
    metric_card,
    page_header,
    panel,
)
from ui.widgets import MapLibreDeckMapWidget


class LiveMonitorPage(QWidget):
    create_requested = Signal()
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    speed_changed = Signal(float)
    vehicle_speed_requested = Signal(str, float)
    lane_change_requested = Signal(str, str)
    vehicle_stop_requested = Signal(str)

    def __init__(self, *, load_web_map: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("liveMonitorPage")
        self.map_widget = MapLibreDeckMapWidget(load_page=load_web_map)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(
            page_header(
                "实时监控",
                "MapLibre/deck.gl 全宽二维交通态势",
                self._header_actions(),
            )
        )

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(PAGE_CONTENT_MARGIN, 14, PAGE_CONTENT_MARGIN, 16)
        body_layout.setSpacing(12)
        body_layout.addWidget(
            panel("全局交通态势", self.map_widget, kicker="MapLibre / deck.gl"),
            1,
        )
        body_layout.addWidget(self._statistics_panel())
        body_layout.addWidget(self._vehicle_console())
        root.addWidget(body, 1)

        self.map_widget.vehicle_selected.connect(self.set_vehicle_id)

    def _statistics_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)
        kicker = QLabel("实时统计")
        kicker.setObjectName("panelKicker")
        title = QLabel("运行概览")
        title.setObjectName("panelTitle")
        layout.addWidget(kicker)
        layout.addWidget(title)
        layout.addStretch(1)

        self.vehicle_metric = metric_card("全局车辆", "0", "SUMO 实时状态")
        self.sumo_metric = metric_card("SUMO", "未知", "组件健康")
        self.experiment_metric = metric_card("实验状态", "未创建", "核心运行")
        layout.addWidget(self.vehicle_metric)
        layout.addWidget(self.sumo_metric)
        layout.addWidget(self.experiment_metric)
        return frame

    def _vehicle_console(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        grid = QGridLayout(frame)
        grid.setContentsMargins(PANEL_CONTENT_MARGIN, 10, PANEL_CONTENT_MARGIN, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        kicker = QLabel("车辆控制")
        kicker.setObjectName("panelKicker")
        grid.addWidget(kicker, 0, 0)
        grid.addWidget(QLabel("选中车辆"), 1, 0)
        self.vehicle_id = QLineEdit()
        self.vehicle_id.setPlaceholderText("在地图上选择车辆，或输入车辆 ID")
        self.vehicle_id.setMinimumWidth(210)
        grid.addWidget(self.vehicle_id, 1, 1)

        grid.addWidget(QLabel("目标速度"), 1, 2)
        self.desired_speed = QDoubleSpinBox()
        self.desired_speed.setRange(0.0, 60.0)
        self.desired_speed.setValue(8.0)
        self.desired_speed.setSuffix(" m/s")
        grid.addWidget(self.desired_speed, 1, 3)

        self.apply_speed_button = QPushButton("应用车速")
        self.left_button = QPushButton("左换道")
        self.right_button = QPushButton("右换道")
        self.vehicle_stop_button = QPushButton("单车停车")
        self.vehicle_stop_button.setObjectName("dangerButton")
        self.apply_speed_button.clicked.connect(self._emit_vehicle_speed)
        self.left_button.clicked.connect(lambda: self._emit_lane_change("LEFT"))
        self.right_button.clicked.connect(lambda: self._emit_lane_change("RIGHT"))
        self.vehicle_stop_button.clicked.connect(self._emit_vehicle_stop)
        grid.addWidget(self.apply_speed_button, 1, 4)
        grid.addWidget(self.left_button, 1, 5)
        grid.addWidget(self.right_button, 1, 6)
        grid.addWidget(self.vehicle_stop_button, 1, 7)
        grid.setColumnStretch(1, 1)
        return frame

    def _speed_controls(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for value, label in ((0.5, "0.5×"), (1.0, "1×"), (2.0, "2×")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("speedButton")
            button.setProperty("multiplier", value)
            if value == 1.0:
                button.setChecked(True)
            button.clicked.connect(
                lambda checked=False, speed=value: self.speed_changed.emit(speed)
            )
            group.addButton(button)
            row.addWidget(button)
        return widget

    def _create_start_controls(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        self.create_button = QPushButton("创建实验")
        self.start_button = QPushButton("开始运行")
        self.start_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.create_requested)
        self.start_button.clicked.connect(self.start_requested)
        row.addWidget(self.create_button)
        row.addWidget(self.start_button)
        return widget

    def _header_actions(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.connection_label = QLabel("API 连接中")
        self.connection_label.setObjectName("connectionBadge")
        self.time_label = QLabel("00:00:00.000")
        self.time_label.setObjectName("mono")
        self.status_label = QLabel("未创建")
        self.status_label.setObjectName("statusBadge")
        row.addWidget(self.connection_label)
        row.addWidget(self.time_label)
        row.addWidget(self.status_label)
        row.addWidget(self._speed_controls())
        row.addWidget(self._create_start_controls())
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("恢复")
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("dangerButton")
        self.pause_button.clicked.connect(self.pause_requested)
        self.resume_button.clicked.connect(self.resume_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        row.addWidget(self.pause_button)
        row.addWidget(self.resume_button)
        row.addWidget(self.stop_button)
        return widget

    @Slot(str)
    def set_vehicle_id(self, vehicle_id: str) -> None:
        self.vehicle_id.setText(vehicle_id)

    def set_vehicle_count(self, count: int) -> None:
        self._metric_value(self.vehicle_metric).setText(str(count))

    def set_sumo_status(self, status: str, message: str | None = None) -> None:
        self._metric_value(self.sumo_metric).setText(status)
        self.sumo_metric.setToolTip(message or "")

    def set_status(self, status: str) -> None:
        self.status_label.setText(status)
        self._metric_value(self.experiment_metric).setText(status)

    def set_time(self, simulation_time_ms: int) -> None:
        hours, remainder = divmod(simulation_time_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}")

    def set_controls(self, availability: ControlAvailability) -> None:
        self.create_button.setEnabled(availability.can_create)
        self.start_button.setEnabled(availability.can_start)
        self.pause_button.setEnabled(availability.can_pause)
        self.resume_button.setEnabled(availability.can_resume)
        self.stop_button.setEnabled(availability.can_stop)
        for widget in (
            self.apply_speed_button,
            self.left_button,
            self.right_button,
            self.vehicle_stop_button,
        ):
            widget.setEnabled(availability.can_control_vehicle)

    def set_connection(self, state: str) -> None:
        labels = {
            "API_CONNECTED": "API 已连接",
            "CONNECTED": "实时已连接",
            "CONNECTING": "实时连接中",
            "RECONNECTING": "实时重连中",
            "DISCONNECTED": "实时已断开",
        }
        self.connection_label.setText(labels.get(state, state))

    def _emit_vehicle_speed(self) -> None:
        self.vehicle_speed_requested.emit(
            self.vehicle_id.text().strip(), self.desired_speed.value()
        )

    def _emit_lane_change(self, direction: str) -> None:
        self.lane_change_requested.emit(self.vehicle_id.text().strip(), direction)

    def _emit_vehicle_stop(self) -> None:
        self.vehicle_stop_requested.emit(self.vehicle_id.text().strip())

    @staticmethod
    def _metric_value(card: QFrame) -> QLabel:
        values = card.findChildren(QLabel, "metricValue")
        return values[0]
