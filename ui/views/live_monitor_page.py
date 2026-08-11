"""Live two-dimensional simulation monitoring and control page."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.models import ControlAvailability, LiveMetrics, ReplayFrame
from ui.views.components import (
    PAGE_CONTENT_MARGIN,
    metric_card,
    page_header,
    panel,
)
from ui.widgets import AutomationLevelBarChart, MapLibreDeckMapWidget


class LiveMonitorPage(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    restart_requested = Signal()
    speed_changed = Signal(float)

    def __init__(self, *, load_web_map: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("liveMonitorPage")
        self._replay_mode = False
        self._replay_seen_vehicle_ids: set[str] = set()
        self._replay_active_vehicle_ids: set[str] = set()
        self._replay_entered_at_ms: dict[str, int] = {}
        self._replay_vehicle_levels: dict[str, str] = {}
        self._replay_completed_time_total_ms = 0
        self._replay_completed_vehicle_count = 0
        self._replay_last_time_ms: int | None = None
        self.map_widget = MapLibreDeckMapWidget(load_page=load_web_map)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = page_header("仿真运行", "SUMO 二维交通态势与实时运行控制", self._header_actions())
        page_title = header.findChild(QLabel, "pageTitle")
        page_subtitle = header.findChild(QLabel, "pageSubtitle")
        if page_title is None or page_subtitle is None:
            raise RuntimeError("live page header labels were not created")
        self.page_title: QLabel = page_title
        self.page_subtitle: QLabel = page_subtitle
        root.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        body_layout.setContentsMargins(PAGE_CONTENT_MARGIN, 14, PAGE_CONTENT_MARGIN, 16)
        body_layout.setSpacing(12)
        body_layout.addWidget(self._workspace(), 1)
        body_layout.addWidget(self._level_metrics_panel())
        body_layout.addWidget(self._simulation_controls())
        scroll = QScrollArea()
        scroll.setObjectName("liveMonitorScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def _workspace(self) -> QWidget:
        self.map_panel = panel(
            "二维仿真场景",
            self.map_widget,
            kicker="SUMO 实时路网",
        )
        self.map_widget.setMinimumHeight(300)
        self.map_panel.setFixedHeight(400)
        stats_panel = self._statistics_panel()

        workspace = QWidget()
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.map_panel, 1)
        layout.addWidget(stats_panel)
        return workspace

    def _statistics_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        frame.setProperty("role", "liveMetrics")
        frame.setMinimumWidth(340)
        frame.setMaximumWidth(390)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)
        kicker = QLabel("实时统计")
        kicker.setObjectName("panelKicker")
        title = QLabel("运行概览")
        title.setObjectName("panelTitle")
        layout.addWidget(kicker)
        layout.addWidget(title)

        self.current_vehicle_metric = metric_card("当前车辆数", "0 辆")
        self.total_vehicle_metric = metric_card("车辆总数", "0 辆")
        self.average_speed_metric = metric_card("平均速度", "0.0 km/h")
        self.average_travel_time_metric = metric_card("平均通过时间", "—")
        metrics_grid = QGridLayout()
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(8)
        metrics_grid.setVerticalSpacing(8)
        for index, card in enumerate(
            (
                self.current_vehicle_metric,
                self.total_vehicle_metric,
                self.average_speed_metric,
                self.average_travel_time_metric,
            )
        ):
            metrics_grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(metrics_grid, 1)
        return frame

    def _simulation_controls(self) -> QFrame:
        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.start_button = QPushButton("启动")
        self.start_button.setObjectName("primaryButton")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("dangerButton")
        self.restart_button = QPushButton("重新开始")
        self.restart_button.setObjectName("restartButton")

        self.start_button.clicked.connect(self.start_requested)
        self.pause_button.clicked.connect(self.pause_requested)
        self.resume_button.clicked.connect(self.resume_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.restart_button.clicked.connect(self.restart_requested)

        for button in (
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.stop_button,
            self.restart_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(self._speed_controls())
        return panel("运行控制", content, kicker="仿真生命周期")

    def _level_metrics_panel(self) -> QFrame:
        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)

        self.level_speed_chart = AutomationLevelBarChart(unit="km/h")
        self.level_collision_chart = AutomationLevelBarChart(
            unit="辆",
            integer_values=True,
        )
        row.addWidget(
            self._chart_group("各智驾等级车辆平均速度", self.level_speed_chart),
            1,
        )
        row.addWidget(
            self._chart_group("各智驾等级碰撞车辆数", self.level_collision_chart),
            1,
        )
        frame = panel("分级实时指标", content, kicker="L0-L5")
        frame.setMaximumHeight(210)
        return frame

    @staticmethod
    def _chart_group(title: str, chart: AutomationLevelBarChart) -> QWidget:
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("metricLabel")
        layout.addWidget(label)
        layout.addWidget(chart)
        return group

    def _speed_controls(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        caption_label = QLabel("播放倍率")
        caption_label.setObjectName("caption")
        row.addWidget(caption_label)
        self.speed_group = QButtonGroup(self)
        self.speed_group.setExclusive(True)
        for value, button_text in ((0.5, "0.5×"), (1.0, "1×"), (2.0, "2×")):
            button = QPushButton(button_text)
            button.setCheckable(True)
            button.setObjectName("speedButton")
            button.setProperty("multiplier", value)
            if value == 1.0:
                button.setChecked(True)
            button.clicked.connect(
                lambda checked=False, speed=value: self.speed_changed.emit(speed)
            )
            self.speed_group.addButton(button)
            row.addWidget(button)
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
        row.addWidget(self.status_label)
        row.addWidget(self.time_label)
        return widget

    @Slot(object)
    def set_metrics(self, metrics: object) -> None:
        if not isinstance(metrics, LiveMetrics):
            return
        self._metric_value(self.current_vehicle_metric).setText(
            f"{metrics.current_vehicle_count} 辆"
        )
        self._metric_value(self.total_vehicle_metric).setText(f"{metrics.total_vehicle_count} 辆")
        self._metric_value(self.average_speed_metric).setText(
            f"{metrics.average_speed_mps * 3.6:.1f} km/h"
        )
        self.level_speed_chart.set_values(
            {level: speed_mps * 3.6 for level, speed_mps in metrics.level_average_speed_mps}
        )
        self.level_collision_chart.set_values(dict(metrics.level_collision_counts))
        travel_time = (
            "—"
            if metrics.average_travel_time_ms is None
            else f"{metrics.average_travel_time_ms / 1000.0:.1f} s"
        )
        self._metric_value(self.average_travel_time_metric).setText(travel_time)

    def set_replay_mode(self, active: bool) -> None:
        """Reuse the live page as a read-only structured playback surface."""
        self._replay_mode = active
        if active:
            self._reset_replay_metrics()
            self.page_title.setText("仿真回放")
            self.page_subtitle.setText("读取结构化快照与增量，不重新运行仿真器")
            self.connection_label.setText("离线结构化记录")
            self.start_button.setText("播放")
            self.pause_button.setText("暂停")
            self.resume_button.setText("继续")
            self.stop_button.setText("退出回放")
            self.restart_button.setText("从头播放")
            self.set_replay_state("PAUSED")
            return
        self.page_title.setText("仿真运行")
        self.page_subtitle.setText("SUMO 二维交通态势与实时运行控制")
        self.connection_label.setText("API 连接中")
        self.start_button.setText("启动")
        self.pause_button.setText("暂停")
        self.resume_button.setText("继续")
        self.stop_button.setText("停止")
        self.restart_button.setText("重新开始")

    @Slot(object)
    def set_replay_frame(self, value: object) -> None:
        if not self._replay_mode or not isinstance(value, ReplayFrame):
            return
        if (
            self._replay_last_time_ms is not None
            and value.simulation_time_ms < self._replay_last_time_ms
        ):
            self._reset_replay_metrics()
        self.map_widget.set_vehicles(value.vehicles)
        self.map_widget.set_traffic_lights(value.traffic_lights)
        self.set_time(value.simulation_time_ms)
        speeds_by_level: dict[str, list[float]] = {}
        for vehicle in value.vehicles:
            speeds_by_level.setdefault(vehicle.automation_level, []).append(vehicle.speed_mps)
            self._replay_vehicle_levels[vehicle.vehicle_id] = vehicle.automation_level
            self._replay_entered_at_ms.setdefault(vehicle.vehicle_id, value.simulation_time_ms)
        current_vehicle_ids = {vehicle.vehicle_id for vehicle in value.vehicles}
        self._replay_seen_vehicle_ids.update(current_vehicle_ids)
        for vehicle_id in self._replay_active_vehicle_ids - current_vehicle_ids:
            entered_at_ms = self._replay_entered_at_ms.pop(vehicle_id, None)
            if entered_at_ms is not None:
                self._replay_completed_time_total_ms += max(
                    0, value.simulation_time_ms - entered_at_ms
                )
                self._replay_completed_vehicle_count += 1
        self._replay_active_vehicle_ids = current_vehicle_ids
        self._replay_last_time_ms = value.simulation_time_ms
        average_speed_mps = (
            sum(vehicle.speed_mps for vehicle in value.vehicles) / len(value.vehicles)
            if value.vehicles
            else 0.0
        )
        self.set_metrics(
            LiveMetrics(
                current_vehicle_count=len(value.vehicles),
                total_vehicle_count=len(self._replay_seen_vehicle_ids),
                average_speed_mps=average_speed_mps,
                average_travel_time_ms=(
                    self._replay_completed_time_total_ms / self._replay_completed_vehicle_count
                    if self._replay_completed_vehicle_count
                    else None
                ),
                level_average_speed_mps=tuple(
                    (
                        level,
                        sum(speeds_by_level.get(level, ())) / len(speeds_by_level.get(level, ()))
                        if speeds_by_level.get(level)
                        else 0.0,
                    )
                    for level in ("L0", "L1", "L2", "L3", "L4", "L5")
                ),
                level_collision_counts=self._replay_collision_counts(value.collision_vehicle_ids),
            )
        )

    @Slot(str)
    def set_replay_state(self, state: str) -> None:
        if not self._replay_mode:
            return
        labels = {
            "PAUSED": "回放已暂停",
            "RUNNING": "回放中",
            "COMPLETED": "回放完成",
            "EMPTY": "无回放帧",
        }
        self.set_status(labels.get(state, state))
        running = state == "RUNNING"
        has_frames = state != "EMPTY"
        resumable = state == "PAUSED"
        self.start_button.setEnabled(resumable)
        self.pause_button.setEnabled(running)
        self.resume_button.setEnabled(resumable)
        self.stop_button.setEnabled(True)
        self.restart_button.setEnabled(has_frames)
        for button in self.speed_group.buttons():
            button.setEnabled(has_frames)

    def set_status(self, status: str) -> None:
        self.status_label.setText(status)

    def set_time(self, simulation_time_ms: int) -> None:
        hours, remainder = divmod(simulation_time_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}")

    def set_controls(self, availability: ControlAvailability) -> None:
        self.start_button.setEnabled(availability.can_start)
        self.pause_button.setEnabled(availability.can_pause)
        self.resume_button.setEnabled(availability.can_resume)
        self.stop_button.setEnabled(availability.can_stop)
        self.restart_button.setEnabled(availability.can_restart)
        for button in self.speed_group.buttons():
            button.setEnabled(availability.can_set_speed)

    def set_connection(self, state: str) -> None:
        if self._replay_mode:
            return
        labels = {
            "API_CONNECTED": "API 已连接",
            "CONNECTED": "实时已连接",
            "CONNECTING": "实时连接中",
            "RECONNECTING": "实时重连中",
            "DISCONNECTED": "实时已断开",
        }
        self.connection_label.setText(labels.get(state, state))

    def _reset_replay_metrics(self) -> None:
        self._replay_seen_vehicle_ids.clear()
        self._replay_active_vehicle_ids.clear()
        self._replay_entered_at_ms.clear()
        self._replay_vehicle_levels.clear()
        self._replay_completed_time_total_ms = 0
        self._replay_completed_vehicle_count = 0
        self._replay_last_time_ms = None

    def _replay_collision_counts(
        self, collision_vehicle_ids: tuple[str, ...]
    ) -> tuple[tuple[str, int], ...]:
        levels = ("L0", "L1", "L2", "L3", "L4", "L5")
        counts = dict.fromkeys(levels, 0)
        for vehicle_id in collision_vehicle_ids:
            level = self._replay_vehicle_levels.get(vehicle_id)
            if level in counts:
                counts[level] += 1
        return tuple((level, counts[level]) for level in levels)

    @staticmethod
    def _metric_value(card: QFrame) -> QLabel:
        values = card.findChildren(QLabel, "metricValue")
        return values[0]
