"""System settings presentation page."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.views.components import PAGE_CONTENT_MARGIN, page_header, panel


class SystemSettingsPage(QWidget):
    theme_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("systemSettingsPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        save = QPushButton("保存设置")
        save.setObjectName("primaryButton")
        save.setEnabled(False)
        save.setToolTip("设置写入接口尚未接入")
        root.addWidget(page_header("系统设置", "运行环境、连接与日志偏好", save))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 16, PAGE_CONTENT_MARGIN, 18)
        layout.setSpacing(12)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self._general(), 1)
        columns.addWidget(self._engine(), 1)
        layout.addLayout(columns)
        layout.addWidget(self._storage())
        note = QLabel("主题选择即时生效；其余权威部署参数仍来自类型化 YAML 与环境变量。")
        note.setObjectName("caption")
        layout.addWidget(note)
        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _general(self) -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        language = QComboBox()
        language.addItem("简体中文")
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeModeCombo")
        self.theme_combo.addItem("深色模式", "dark")
        self.theme_combo.addItem("浅色模式", "light")
        self.theme_combo.currentIndexChanged.connect(self._emit_theme)
        start_page = QComboBox()
        start_page.addItems(("实时监控", "实验管理"))
        form.addRow("语言", language)
        form.addRow("界面主题", self.theme_combo)
        form.addRow("启动页面", start_page)
        return panel("通用设置", content, kicker="通用")

    @Slot(int)
    def _emit_theme(self, index: int) -> None:
        theme = self.theme_combo.itemData(index)
        if isinstance(theme, str):
            self.theme_changed.emit(theme)

    @staticmethod
    def _engine() -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        api = QLineEdit("http://127.0.0.1:8000")
        api.setReadOnly(True)
        step = QSpinBox()
        step.setRange(50, 50)
        step.setValue(50)
        step.setSuffix(" ms")
        form.addRow("API 地址", api)
        form.addRow("固定步长", step)
        return panel("SUMO 仿真引擎", content, kicker="运行环境")

    @staticmethod
    def _storage() -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        trajectory = QLineEdit("Parquet")
        trajectory.setReadOnly(True)
        metadata = QLineEdit("PostgreSQL")
        metadata.setReadOnly(True)
        logging = QComboBox()
        logging.addItems(("INFO", "DEBUG", "WARNING"))
        form.addRow("高频轨迹", trajectory)
        form.addRow("关系元数据", metadata)
        form.addRow("日志级别", logging)
        return panel("存储与日志", content, kicker="数据")
