"""Scenario configuration page grounded in the current REST capabilities."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.models import MapSummary, ReplayResult
from ui.views.components import PAGE_CONTENT_MARGIN, empty_state, page_header, panel


class SceneConfigurationPage(QWidget):
    map_selected = Signal(str)
    launch_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sceneConfigurationPage")
        self._pending_replay_configuration: ReplayResult | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(
            page_header(
                "仿真配置",
                "配置运行参数并启动工作区仿真",
                self._actions(),
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 16, PAGE_CONTENT_MARGIN, 18)
        layout.setSpacing(12)
        layout.addWidget(self._steps())

        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self._basic_information(), 3)
        columns.addWidget(self._map_selection(), 2)
        layout.addLayout(columns, 1)
        layout.addWidget(self._summary())
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _actions(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        self.create_button = QPushButton("开始仿真")
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.launch_requested)
        row.addWidget(self.create_button)
        return widget

    def _steps(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        steps = ("01  基础信息", "02  地图与道路", "03  交通需求", "04  行为参数", "05  开始仿真")
        for index, text in enumerate(steps):
            label = QLabel(text)
            label.setObjectName("panelKicker" if index == 0 else "caption")
            layout.addWidget(label)
            if index < len(steps) - 1:
                layout.addWidget(QLabel("—"))
        layout.addStretch(1)
        return frame

    def _basic_information(self) -> QFrame:
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)
        self.scene_name = QLineEdit("SUMO 二维仿真")
        self.scene_name.setPlaceholderText("场景名称")
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setValue(42)
        self.description = QTextEdit()
        self.description.setPlaceholderText("记录本次实验目标和变量说明")
        self.description.setMaximumHeight(110)
        form.addRow("场景名称", self.scene_name)
        form.addRow("随机种子", self.seed)
        form.addRow("说明", self.description)
        read_only = QLabel(
            "当前版本由配置文件提供权威场景参数。此处保留原型表单，"
            "创建时仍使用已加载的场景 ID 与地图。"
        )
        read_only.setObjectName("caption")
        read_only.setWordWrap(True)
        form.addRow("运行约束", read_only)
        return panel("基础信息", content, kicker="步骤 01")

    def _map_selection(self) -> QFrame:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.map_combo = QComboBox()
        self.map_combo.setMinimumContentsLength(24)
        self.map_combo.currentIndexChanged.connect(self._select_map)
        layout.addWidget(QLabel("SUMO 场景包"))
        layout.addWidget(self.map_combo)
        preview = empty_state(
            "等待场景",
            "从列表选择由 .sumocfg 自动发现并校验的 SUMO 场景包。",
            "⌁",
        )
        preview.setMinimumHeight(180)
        layout.addWidget(preview, 1)
        return panel("地图与道路", content, kicker="步骤 02")

    def _summary(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panelAccent")
        layout = QGridLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(QLabel("SUMO 二维运行基线"), 0, 0)
        detail = QLabel("场景自带步长  ·  SUMO 全局真值  ·  托管本机进程  ·  CARLA 禁用")
        detail.setObjectName("caption")
        layout.addWidget(detail, 1, 0)
        return frame

    def set_maps(self, maps: tuple[MapSummary, ...]) -> None:
        self.map_combo.blockSignals(True)
        self.map_combo.clear()
        for item in maps:
            replay_map = (
                self._pending_replay_configuration is not None
                and item.map_id == self._pending_replay_configuration.map_id
            )
            if item.kind != "sumo" and not replay_map:
                continue
            name = item.display_name or item.carla_map or item.map_id
            runtime = f"SUMO · {item.sumo_step_ms} ms" if item.sumo_step_ms is not None else "SUMO"
            self.map_combo.addItem(f"{name}  ·  {runtime}", item.map_id)
        self.map_combo.blockSignals(False)
        if self.map_combo.count():
            self.map_combo.setCurrentIndex(0)
        if self._pending_replay_configuration is not None:
            self._apply_replay_configuration(self._pending_replay_configuration)

    def set_replay_configuration(self, result: ReplayResult) -> None:
        """Fill the setup form from a selected historical run before rerunning it."""

        self._pending_replay_configuration = result
        self._apply_replay_configuration(result)

    def _apply_replay_configuration(self, result: ReplayResult) -> None:
        self.scene_name.setText(result.scenario_name)
        self.seed.setValue(result.seed)
        self.description.setPlainText(result.description)
        index = self.map_combo.findData(result.map_id)
        self.map_combo.blockSignals(True)
        if index < 0:
            self.map_combo.addItem(f"{result.map_name} · 历史配置", result.map_id)
            index = self.map_combo.findData(result.map_id)
        if index >= 0:
            self.map_combo.setCurrentIndex(index)
        self.map_combo.blockSignals(False)
        if index >= 0:
            self.map_selected.emit(result.map_id)

    def set_create_enabled(self, enabled: bool) -> None:
        self.create_button.setEnabled(enabled)

    @Slot(int)
    def _select_map(self, index: int) -> None:
        map_id = self.map_combo.itemData(index)
        if isinstance(map_id, str):
            self.map_selected.emit(map_id)
