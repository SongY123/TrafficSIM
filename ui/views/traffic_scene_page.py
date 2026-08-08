"""Workspace catalog of directly runnable traffic scenarios."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary
from ui.views.components import PAGE_CONTENT_MARGIN, page_header, panel


class TrafficScenePage(QWidget):
    """Show validated SUMO packages separately from per-run configuration."""

    scene_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trafficScenePage")
        self._available_maps: dict[str, MapSummary] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("交通场景", "管理工作区内可复用的交通场景包"))

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 16, PAGE_CONTENT_MARGIN, 18)
        layout.setSpacing(12)
        hint = QLabel("单击场景即可自动应用仿真配置、创建实验并进入“仿真运行”。")
        hint.setObjectName("caption")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("trafficSceneTable")
        self.table.setHorizontalHeaderLabels(("场景名称", "突发事件", "L0-L5 差异表现", "状态"))
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.cellClicked.connect(self._select_row)
        layout.addWidget(panel("场景列表", self.table, kicker="工作区资源"), 1)
        root.addWidget(body, 1)

    def set_maps(self, maps: tuple[MapSummary, ...]) -> None:
        self._available_maps = {item.map_id: item for item in maps if item.kind == "sumo"}
        self.table.setRowCount(len(TRAFFIC_SCENARIO_PRESETS))
        for row, preset in enumerate(TRAFFIC_SCENARIO_PRESETS):
            item = self._available_maps.get(preset.map_id)
            available = item is not None and item.validated
            values = (
                preset.name,
                preset.incident,
                preset.behavior_summary,
                "可运行" if available else "资源缺失",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                cell.setData(Qt.ItemDataRole.UserRole, preset.scenario_id)
                if not available:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, column, cell)
            self.table.setRowHeight(row, 82)

    def _select_row(self, row: int, column: int) -> None:
        del column
        if not 0 <= row < len(TRAFFIC_SCENARIO_PRESETS):
            return
        preset = TRAFFIC_SCENARIO_PRESETS[row]
        map_summary = self._available_maps.get(preset.map_id)
        if map_summary is not None and map_summary.validated:
            self.scene_selected.emit(preset)
