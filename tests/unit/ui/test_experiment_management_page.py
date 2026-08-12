"""Tests for the simulation history page."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
from ui.views.experiment_management_page import ExperimentManagementPage


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def test_history_table_does_not_show_data_source_column() -> None:
    _application()
    page = ExperimentManagementPage()

    headers: list[str] = []
    for column in range(page.table.columnCount()):
        item = page.table.horizontalHeaderItem(column)
        assert item is not None
        headers.append(item.text())

    assert headers == ["实验", "状态", "仿真时间"]
    page.close()
