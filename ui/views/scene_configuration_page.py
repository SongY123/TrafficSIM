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

from ui.models import MapSummary
from ui.views.components import PAGE_CONTENT_MARGIN, empty_state, page_header, panel


class SceneConfigurationPage(QWidget):
    map_selected = Signal(str)
    import_requested = Signal()
    create_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sceneConfigurationPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("场景配置", "配置核心运行实验并选择已验证地图", self._actions()))

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
        self.import_button = QPushButton("导入 OpenDRIVE .xodr")
        self.create_button = QPushButton("创建实验")
        self.create_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(self.import_requested)
        self.create_button.clicked.connect(self.create_requested)
        row.addWidget(self.import_button)
        row.addWidget(self.create_button)
        return widget

    def _steps(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        steps = ("01  基础信息", "02  地图与道路", "03  交通需求", "04  行为参数", "05  确认创建")
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
        self.scene_name = QLineEdit("Town04 核心运行")
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
        layout.addWidget(QLabel("已验证地图"))
        layout.addWidget(self.map_combo)
        preview = empty_state(
            "等待地图",
            "从列表选择由 OpenDRIVE 编译、已校验的 SUMO 地图。",
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
        layout.addWidget(QLabel("核心运行基线"), 0, 0)
        detail = QLabel("50 ms 固定步长  ·  SUMO 全局交通真值  ·  MapLibre/deck.gl 实时监控")
        detail.setObjectName("caption")
        layout.addWidget(detail, 1, 0)
        return frame

    def set_maps(self, maps: tuple[MapSummary, ...]) -> None:
        self.map_combo.blockSignals(True)
        self.map_combo.clear()
        for item in maps:
            self.map_combo.addItem(
                f"{item.map_id}  ·  SUMO {item.sumo_version}",
                item.map_id,
            )
        self.map_combo.blockSignals(False)
        if self.map_combo.count():
            self.map_combo.setCurrentIndex(0)

    def set_create_enabled(self, enabled: bool) -> None:
        self.create_button.setEnabled(enabled)

    @Slot(int)
    def _select_map(self, index: int) -> None:
        map_id = self.map_combo.itemData(index)
        if isinstance(map_id, str):
            self.map_selected.emit(map_id)
