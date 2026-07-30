"""Persistent navigation rail for the desktop shell."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.views.element_plus_icons import ICON_SIZE, render_element_plus_icon, render_svg_pixmap
from ui.views.theme import ThemeMode, load_icon_colors

_NAVIGATION = (
    ("workspace", "data-board.svg", "工作台"),
    ("live", "monitor.svg", "实时监控"),
    ("scene", "set-up.svg", "场景配置"),
    ("experiments", "data-board.svg", "实验管理"),
    ("analysis", "trend-charts.svg", "数据分析"),
    ("assets", "box.svg", "资产中心"),
    ("settings", "setting.svg", "系统设置"),
)
_ICON_ROOT = Path(__file__).resolve().parents[1] / "assets/icons/element-plus"
_BRAND_LOGO = Path(__file__).resolve().parents[1] / "assets/icons/logo.svg"


class NavigationRail(QWidget):
    page_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navigationRail")
        self.setFixedWidth(236)
        self._buttons: dict[str, QPushButton] = {}
        self._icon_paths: dict[str, Path] = {}
        self._theme = ThemeMode.DARK

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(6)
        layout.addLayout(self._brand())
        layout.addSpacing(28)

        section = QLabel("控制中心")
        section.setObjectName("sectionLabel")
        layout.addWidget(section)
        layout.addSpacing(5)
        for key, icon, label in _NAVIGATION[:-1]:
            layout.addWidget(self._nav_button(key, icon, label))

        layout.addStretch(1)
        section = QLabel("系统")
        section.setObjectName("sectionLabel")
        layout.addWidget(section)
        layout.addWidget(self._nav_button(*_NAVIGATION[-1]))

        divider = QFrame()
        divider.setObjectName("navigationDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)
        version = QLabel("TrafficVerse  ·  v0.1\n核心运行控制台")
        version.setObjectName("brandCaption")
        version.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(version)
        self.set_active("workspace")

    def set_active(self, key: str) -> None:
        for button_key, button in self._buttons.items():
            button.setProperty("active", button_key == key)
            button.style().unpolish(button)
            button.style().polish(button)
        self.refresh_icons()

    def refresh_icons(self, theme: ThemeMode | None = None) -> None:
        if theme is not None:
            self._theme = theme
        colors = load_icon_colors(self._theme)
        for key, button in self._buttons.items():
            color_name = colors["active"] if button.property("active") else colors["normal"]
            color = QColor(color_name)
            button.setIcon(render_element_plus_icon(self._icon_paths[key], color))
            button.setIconSize(ICON_SIZE)

    def _brand(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setPixmap(
            render_svg_pixmap(
                _BRAND_LOGO,
                QSize(40, 40),
            )
        )
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel("TrafficVerse")
        name.setObjectName("brandName")
        caption = QLabel("交通仿真系统")
        caption.setObjectName("brandCaption")
        text.addWidget(name)
        text.addWidget(caption)
        row.addWidget(logo)
        row.addLayout(text)
        row.addStretch(1)
        return row

    def _nav_button(self, key: str, icon_file: str, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setProperty("navKey", key)
        button.setAccessibleName(label)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda checked=False, page=key: self.page_selected.emit(page))
        self._buttons[key] = button
        self._icon_paths[key] = _ICON_ROOT / icon_file
        button.setObjectName(f"nav_{key}")
        button.setProperty("role", "navigation")
        return button
