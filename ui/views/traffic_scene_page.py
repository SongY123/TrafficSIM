"""Detailed workspace view for directly runnable traffic scenarios."""

from __future__ import annotations

from PySide6.QtCore import Property, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
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

from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary, TrafficScenarioPreset
from ui.models.traffic_scenario import scenario_preview_vehicles
from ui.views.components import PAGE_CONTENT_MARGIN, PAGE_TEXT_MARGIN
from ui.widgets import MapLibreDeckMapWidget

_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
_RESULT_PANEL_HEIGHT = 376
_LEVEL_NAMES = {
    "L0": "人工驾驶",
    "L1": "辅助驾驶",
    "L2": "部分自动驾驶",
    "L3": "条件自动驾驶",
    "L4": "高度自动驾驶",
    "L5": "完全自动驾驶",
}
_SCENARIO_METRICS = {
    "mixed-automation-obstacle": (
        (34.8, 45.4, 57.6, 69.2, 81.4, 82.6),
        (4, 3, 2, 1, 0, 0),
    ),
    "mixed-automation-cutin": (
        (59.0, 63.0, 72.0, 80.6, 87.2, 88.9),
        (12, 6, 4, 2, 0, 0),
    ),
    "mixed-automation-emergency-yield": (
        (41.4, 48.1, 54.7, 61.0, 65.2, 75.8),
        (0, 0, 0, 0, 0, 0),
    ),
}


class _AutomationLevelChart(QWidget):
    """Provide theme-controlled colors shared by the scene metric charts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level_colors = {
            "L0": QColor(Qt.GlobalColor.red),
            "L1": QColor(Qt.GlobalColor.darkYellow),
            "L2": QColor(Qt.GlobalColor.yellow),
            "L3": QColor(Qt.GlobalColor.blue),
            "L4": QColor(Qt.GlobalColor.green),
            "L5": QColor(Qt.GlobalColor.magenta),
        }

    def _get_level_color(self, level: str) -> QColor:
        return QColor(self._level_colors[level])

    def _set_level_color(self, level: str, color: QColor) -> None:
        self._level_colors[level] = QColor(color)
        self.update()

    l0Color = Property(
        QColor,
        lambda self: self._get_level_color("L0"),
        lambda self, color: self._set_level_color("L0", color),
    )
    l1Color = Property(
        QColor,
        lambda self: self._get_level_color("L1"),
        lambda self, color: self._set_level_color("L1", color),
    )
    l2Color = Property(
        QColor,
        lambda self: self._get_level_color("L2"),
        lambda self, color: self._set_level_color("L2", color),
    )
    l3Color = Property(
        QColor,
        lambda self: self._get_level_color("L3"),
        lambda self, color: self._set_level_color("L3", color),
    )
    l4Color = Property(
        QColor,
        lambda self: self._get_level_color("L4"),
        lambda self, color: self._set_level_color("L4", color),
    )
    l5Color = Property(
        QColor,
        lambda self: self._get_level_color("L5"),
        lambda self, color: self._set_level_color("L5", color),
    )


class _SpeedBarChart(_AutomationLevelChart):
    """Compact horizontal comparison chart matching the Stitch layout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trafficSceneSpeedChart")
        self.setMinimumHeight(154)
        self.values: dict[str, float] = dict.fromkeys(_LEVELS, 0.0)

    def set_values(self, values: dict[str, float]) -> None:
        self.values = {level: float(values.get(level, 0.0)) for level in _LEVELS}
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = self.palette().color(QPalette.ColorRole.Text)
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        track = QColor(muted)
        track.setAlpha(34)
        maximum = max(max(self.values.values()), 1.0)
        row_height = self.height() / len(_LEVELS)
        track_left = 32.0
        track_right = max(track_left + 20.0, self.width() - 66.0)

        for row, level in enumerate(reversed(_LEVELS)):
            center_y = (row + 0.5) * row_height
            painter.setPen(muted)
            painter.drawText(
                QRectF(0.0, center_y - 10.0, 28.0, 20.0), Qt.AlignmentFlag.AlignVCenter, level
            )
            bar_rect = QRectF(track_left, center_y - 4.0, track_right - track_left, 8.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(bar_rect, 3.0, 3.0)
            value = self.values[level]
            value_rect = QRectF(bar_rect)
            value_rect.setWidth(bar_rect.width() * value / maximum)
            painter.setBrush(self._level_colors[level])
            painter.drawRoundedRect(value_rect, 3.0, 3.0)
            painter.setPen(text_color)
            painter.drawText(
                QRectF(track_right + 7.0, center_y - 10.0, 58.0, 20.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                f"{value:.1f}",
            )


class _CollisionBarChart(_AutomationLevelChart):
    """Collision total and per-level distribution in one compact plot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trafficSceneCollisionChart")
        self.setMinimumHeight(116)
        self.values: dict[str, int] = dict.fromkeys(_LEVELS, 0)

    def set_values(self, values: dict[str, int]) -> None:
        self.values = {level: int(values.get(level, 0)) for level in _LEVELS}
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = self.palette().color(QPalette.ColorRole.Text)
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        total = sum(self.values.values())
        maximum = max(max(self.values.values()), 1)

        total_font = painter.font()
        total_font.setPixelSize(30)
        total_font.setBold(True)
        painter.setFont(total_font)
        painter.setPen(self._level_colors["L0"] if total else self._level_colors["L4"])
        painter.drawText(QRectF(0.0, 11.0, 72.0, 38.0), Qt.AlignmentFlag.AlignLeft, str(total))
        label_font = painter.font()
        label_font.setPixelSize(11)
        label_font.setBold(False)
        painter.setFont(label_font)
        painter.setPen(muted)
        painter.drawText(QRectF(0.0, 50.0, 78.0, 34.0), Qt.AlignmentFlag.AlignLeft, "起\n累计碰撞")

        chart_left = 86.0
        chart_width = max(60.0, self.width() - chart_left)
        slot_width = chart_width / len(_LEVELS)
        baseline = self.height() - 22.0
        max_height = max(22.0, self.height() - 38.0)
        painter.setPen(muted)
        painter.drawLine(chart_left, baseline, self.width(), baseline)
        for index, level in enumerate(_LEVELS):
            value = self.values[level]
            height = max_height * value / maximum if value else 2.0
            width = min(24.0, slot_width * 0.5)
            left = chart_left + index * slot_width + (slot_width - width) / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._level_colors[level])
            painter.drawRoundedRect(QRectF(left, baseline - height, width, height), 2.0, 2.0)
            painter.setPen(text_color)
            painter.drawText(
                QRectF(left - 6.0, baseline - height - 18.0, width + 12.0, 16.0),
                Qt.AlignmentFlag.AlignCenter,
                str(value),
            )
            painter.setPen(muted)
            painter.drawText(
                QRectF(chart_left + index * slot_width, baseline + 2.0, slot_width, 18.0),
                Qt.AlignmentFlag.AlignCenter,
                level,
            )


class TrafficScenePage(QWidget):
    """Show one selected traffic scenario with preview, parameters, and actions."""

    scene_selected = Signal(object)
    configuration_requested = Signal(object)
    preview_requested = Signal(str)

    def __init__(
        self,
        *,
        load_web_map: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("trafficScenePage")
        self._load_web_map = load_web_map
        self._available_maps: dict[str, MapSummary] = {}
        self._selected_scenario = TRAFFIC_SCENARIO_PRESETS[0]
        self.level_descriptions: dict[str, QLabel] = {}
        self.summary_values: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._page_header())

        scroll = QScrollArea()
        scroll.setObjectName("trafficSceneScroll")
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("trafficSceneBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 14, PAGE_CONTENT_MARGIN, 22)
        layout.setSpacing(14)
        layout.addWidget(self._hero())
        layout.addWidget(self._behavior_matrix())
        layout.addLayout(self._result_grid())
        layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.set_scenario(self._selected_scenario)

    @property
    def selected_scenario(self) -> TrafficScenarioPreset:
        return self._selected_scenario

    def _page_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("topBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(PAGE_TEXT_MARGIN, 14, PAGE_CONTENT_MARGIN, 14)
        title = QLabel("场景详情")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(self._header_actions())
        return header

    def _header_actions(self) -> QWidget:
        actions = QWidget()
        actions.setObjectName("trafficSceneHeaderActions")
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.configure_button = QPushButton("查看配置")
        self.configure_button.setObjectName("trafficSceneConfigureButton")
        self.configure_button.setAccessibleName("将当前交通场景加载到仿真配置")
        self.configure_button.clicked.connect(self._configure_current)
        layout.addWidget(self.configure_button)
        self.launch_button = QPushButton("▶  开始仿真")
        self.launch_button.setObjectName("trafficSceneLaunchButton")
        self.launch_button.setAccessibleName("启动当前交通场景")
        self.launch_button.clicked.connect(self._launch_current)
        layout.addWidget(self.launch_button)
        return actions

    def _hero(self) -> QFrame:
        self.hero = QFrame()
        self.hero.setObjectName("trafficSceneHero")
        self.hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self.hero)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(4)
        top = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("trafficSceneTitle")
        top.addWidget(self.title_label)
        top.addStretch(1)
        self.availability_label = QLabel()
        self.availability_label.setObjectName("trafficSceneAvailability")
        self.availability_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.availability_label)
        layout.addLayout(top)

        self.incident_label = QLabel()
        self.incident_label.setObjectName("trafficSceneIncident")
        self.incident_label.setWordWrap(True)
        layout.addWidget(self.incident_label)

        metadata = QHBoxLayout()
        metadata.setSpacing(8)
        for key in ("map", "duration", "vehicles", "step"):
            value = QLabel()
            value.setObjectName("trafficSceneMeta")
            metadata.addWidget(value)
            self.summary_values[key] = value
        metadata.addStretch(1)
        layout.addLayout(metadata)
        return self.hero

    def _behavior_matrix(self) -> QWidget:
        section = QWidget()
        section.setObjectName("trafficSceneBehaviorSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("智驾等级行为差异")
        title.setObjectName("trafficSceneContentTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        for column, level in enumerate(_LEVELS):
            card = QFrame()
            card.setObjectName("trafficSceneLevelCard")
            card.setProperty("level", level)
            card.setMinimumHeight(104)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 9, 10, 10)
            card_layout.setSpacing(4)
            heading = QLabel(f"{level}  {_LEVEL_NAMES[level]}")
            heading.setObjectName("trafficSceneLevel")
            heading.setProperty("level", level)
            description = QLabel()
            description.setObjectName("trafficSceneLevelDescription")
            description.setWordWrap(True)
            description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            card_layout.addWidget(heading)
            card_layout.addWidget(description, 1)
            grid.addWidget(card, 0, column)
            grid.setColumnStretch(column, 1)
            self.level_descriptions[level] = description
        layout.addLayout(grid)
        return section

    def _result_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(0)

        self.preview_panel = QFrame()
        self.preview_panel.setObjectName("trafficScenePanel")
        self.preview_panel.setFixedHeight(_RESULT_PANEL_HEIGHT)
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(12, 11, 12, 12)
        preview_layout.setSpacing(8)
        preview_title = QLabel("仿真场景预览")
        preview_title.setObjectName("trafficScenePanelTitle")
        preview_layout.addWidget(preview_title)
        self.map_widget = MapLibreDeckMapWidget(load_page=self._load_web_map)
        self.map_widget.setObjectName("trafficSceneMapPreview")
        self.map_widget.setAccessibleName("可交互交通场景关键帧预览")
        self.map_widget.setMinimumHeight(220)
        preview_layout.addWidget(self.map_widget, 1)
        grid.addWidget(self.preview_panel, 0, 0)

        self.metrics_panel = QFrame()
        self.metrics_panel.setObjectName("trafficScenePanel")
        self.metrics_panel.setFixedHeight(_RESULT_PANEL_HEIGHT)
        metrics_layout = QVBoxLayout(self.metrics_panel)
        metrics_layout.setContentsMargins(14, 11, 14, 12)
        metrics_layout.setSpacing(7)
        metrics_title = QLabel("性能指标分析")
        metrics_title.setObjectName("trafficScenePanelTitle")
        metrics_layout.addWidget(metrics_title)
        speed_label = QLabel("各智驾等级车辆平均速度  ·  km/h")
        speed_label.setObjectName("trafficSceneChartLabel")
        metrics_layout.addWidget(speed_label)
        self.speed_chart = _SpeedBarChart()
        metrics_layout.addWidget(self.speed_chart)
        collision_label = QLabel("碰撞数量")
        collision_label.setObjectName("trafficSceneChartLabel")
        metrics_layout.addWidget(collision_label)
        self.collision_chart = _CollisionBarChart()
        metrics_layout.addWidget(self.collision_chart)
        grid.addWidget(self.metrics_panel, 0, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        return grid

    def set_maps(self, maps: tuple[MapSummary, ...]) -> None:
        self._available_maps = {item.map_id: item for item in maps if item.kind == "sumo"}
        self._sync_availability()
        self._request_selected_preview()

    def set_preview_network(self, map_id: str, network: object) -> None:
        if map_id == self._selected_scenario.map_id:
            self.map_widget.set_network(network)
            self.map_widget.set_vehicles(scenario_preview_vehicles(self._selected_scenario))

    def set_scenario(self, preset: TrafficScenarioPreset) -> None:
        self._selected_scenario = preset
        self.title_label.setText(preset.name)
        self.incident_label.setText(preset.incident)
        self.summary_values["map"].setText(f"SUMO · {preset.map_id}")
        self.summary_values["duration"].setText(f"时长 · {preset.duration_s} s")
        self.summary_values["vehicles"].setText(f"车辆 · {preset.vehicle_total} 辆")
        self.summary_values["step"].setText("步长 · 50 ms")
        self.map_widget.set_network({"type": "FeatureCollection", "features": []})
        self.map_widget.set_vehicles(())
        for level, description in preset.level_behaviors:
            self.level_descriptions[level].setText(description)
        speeds, collisions = _SCENARIO_METRICS[preset.scenario_id]
        self.speed_chart.set_values(dict(zip(_LEVELS, speeds, strict=True)))
        self.collision_chart.set_values(dict(zip(_LEVELS, collisions, strict=True)))
        self._sync_availability()
        self._request_selected_preview()

    def set_theme(self, theme: str) -> None:
        self.map_widget.set_theme(theme)

    def _request_selected_preview(self) -> None:
        if self._selected_scenario.map_id in self._available_maps:
            self.preview_requested.emit(self._selected_scenario.map_id)

    def is_available(self, scenario_id: str) -> bool:
        preset = next(
            (item for item in TRAFFIC_SCENARIO_PRESETS if item.scenario_id == scenario_id),
            None,
        )
        if preset is None:
            return False
        map_summary = self._available_maps.get(preset.map_id)
        return map_summary is not None and map_summary.validated

    def _sync_availability(self) -> None:
        available = self.is_available(self._selected_scenario.scenario_id)
        self.availability_label.setText("资源就绪" if available else "资源缺失")
        self.availability_label.setProperty("state", "ready" if available else "missing")
        self.availability_label.style().unpolish(self.availability_label)
        self.availability_label.style().polish(self.availability_label)
        self.configure_button.setEnabled(available)
        self.launch_button.setEnabled(available)

    def _configure_current(self) -> None:
        if self.is_available(self._selected_scenario.scenario_id):
            self.configuration_requested.emit(self._selected_scenario)

    def _launch_current(self) -> None:
        if self.is_available(self._selected_scenario.scenario_id):
            self.scene_selected.emit(self._selected_scenario)
