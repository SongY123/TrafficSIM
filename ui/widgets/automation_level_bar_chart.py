"""Compact native Qt bar chart for L0-L5 live simulation metrics."""

from __future__ import annotations

import math
from collections.abc import Mapping

from PySide6.QtCore import Property, QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")


class AutomationLevelBarChart(QWidget):
    """Render six stable bars without adding a heavyweight chart dependency."""

    def __init__(
        self,
        *,
        unit: str,
        integer_values: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._unit = unit
        self._integer_values = integer_values
        self._values = dict.fromkeys(LEVELS, 0.0)
        self._level_colors = {
            "L0": QColor(Qt.GlobalColor.red),
            "L1": QColor(Qt.GlobalColor.darkYellow),
            "L2": QColor(Qt.GlobalColor.yellow),
            "L3": QColor(Qt.GlobalColor.blue),
            "L4": QColor(Qt.GlobalColor.green),
            "L5": QColor(Qt.GlobalColor.magenta),
        }
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

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

    @property
    def values(self) -> Mapping[str, float]:
        return self._values.copy()

    def set_values(self, values: Mapping[str, float | int]) -> None:
        self._values = {level: max(0.0, float(values.get(level, 0.0))) for level in LEVELS}
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont(self.font().family(), 8))

        plot = QRectF(42.0, 10.0, max(1.0, self.width() - 54.0), max(1.0, self.height() - 38.0))
        maximum = self._axis_maximum()
        palette = self.palette()
        grid_pen = QPen(palette.color(QPalette.ColorRole.Mid), 1.0)
        label_pen = QPen(palette.color(QPalette.ColorRole.PlaceholderText))
        value_pen = QPen(palette.color(QPalette.ColorRole.Text))
        for tick in range(5):
            ratio = tick / 4.0
            y = plot.bottom() - plot.height() * ratio
            painter.setPen(grid_pen)
            painter.drawLine(QLineF(plot.left(), y, plot.right(), y))
            painter.setPen(label_pen)
            tick_value = maximum * ratio
            label = str(round(tick_value)) if self._integer_values else f"{tick_value:.0f}"
            painter.drawText(
                QRectF(0.0, y - 8.0, 36.0, 16.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

        slot_width = plot.width() / len(LEVELS)
        bar_width = min(34.0, slot_width * 0.55)
        value_font = QFont(self.font().family(), 8)
        value_font.setBold(True)
        for index, level in enumerate(LEVELS):
            value = self._values[level]
            ratio = min(1.0, value / maximum)
            height = plot.height() * ratio
            x = plot.left() + slot_width * index + (slot_width - bar_width) / 2.0
            bar = QRectF(x, plot.bottom() - height, bar_width, height)
            color = self._level_colors[level]
            painter.fillRect(bar, color)

            painter.setPen(value_pen)
            painter.setFont(value_font)
            value_text = str(round(value)) if self._integer_values else f"{value:.1f}"
            painter.drawText(
                QRectF(x - slot_width * 0.2, max(0.0, bar.top() - 19.0), slot_width * 1.4, 17.0),
                Qt.AlignmentFlag.AlignCenter,
                value_text,
            )
            painter.setFont(QFont(self.font().family(), 8))
            painter.setPen(label_pen)
            painter.drawText(
                QRectF(plot.left() + slot_width * index, plot.bottom() + 5.0, slot_width, 18.0),
                Qt.AlignmentFlag.AlignCenter,
                level,
            )

        painter.setPen(label_pen)
        painter.drawText(
            QRectF(plot.left(), 0.0, plot.width(), 14.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            self._unit,
        )

    def _axis_maximum(self) -> float:
        maximum = max(self._values.values(), default=0.0)
        if self._integer_values:
            return float(max(4, math.ceil(maximum / 4.0) * 4))
        return float(max(20, math.ceil(maximum / 20.0) * 20))
