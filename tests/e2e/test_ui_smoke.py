from __future__ import annotations

from uuid import UUID

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QPoint, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QWidget,
)
from ui.viewmodels import RunViewModel
from ui.views import MainWindow
from ui.widgets import MapLibreDeckMapWidget


class _Rest(QObject):
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, str)


class _Realtime(QObject):
    connection_changed = Signal(str)
    envelope_received = Signal(object)
    protocol_error = Signal(str)


@pytest.mark.e2e
def test_core_run_window_constructs_and_closes_without_backend() -> None:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QCoreApplication)
    viewmodel = RunViewModel(
        _Rest(),  # type: ignore[arg-type]
        _Realtime(),  # type: ignore[arg-type]
        UUID("00000000-0000-0000-0000-000000000042"),
    )

    window = MainWindow(viewmodel, load_web_map=False)

    assert window.windowTitle().startswith("TrafficVerse")
    assert window.minimumWidth() >= 1180

    page_stack = window.findChild(QStackedWidget, "pageStack")
    assert page_stack is not None
    assert page_stack.count() == 7
    assert page_stack.currentWidget().objectName() == "workspacePage"
    assert window.findChild(MapLibreDeckMapWidget) is not None
    assert window.findChild(QWidget, "monitorMapSplitter") is None
    window.show()
    app.processEvents()
    live_button = window.findChild(QPushButton, "nav_live")
    assert live_button is not None
    live_button.click()
    page_title = window.live_page.findChild(QLabel, "pageTitle")
    assert page_title is not None
    live_labels = window.live_page.findChildren(QLabel)
    map_title = next(label for label in live_labels if label.text() == "全局交通态势")
    console_title = next(label for label in live_labels if label.text() == "车辆控制")
    aligned_left_edges = {
        label.mapTo(window, QPoint()).x() for label in (page_title, map_title, console_title)
    }
    assert len(aligned_left_edges) == 1

    brand_logo = window.findChild(QLabel, "brandLogo")
    assert brand_logo is not None
    assert brand_logo.pixmap() is not None
    assert not brand_logo.pixmap().isNull()
    assert not window.windowIcon().isNull()

    live_text = " ".join(label.text() for label in live_labels)
    assert "MapLibre" in live_text
    assert "deck.gl" in live_text
    assert "CARLA" not in live_text
    assert "ROI" not in live_text
    viewmodel.component_health_changed.emit(
        (
            type(
                "Health",
                (),
                {"component": "sumo", "status": "HEALTHY", "message": "connected"},
            )(),
        )
    )
    assert "正常" in {label.text() for label in window.live_page.findChildren(QLabel)}
    visible_text = " ".join(label.text() for label in window.findChildren(QLabel))
    for english_copy in (
        "CONTROL CENTER",
        "SIMULATION OS",
        "CORE RUN CONSOLE",
        "LIVE STATISTICS",
        "VEHICLE COMMAND",
        "Replay library",
        "Timeline",
        "Insights",
    ):
        assert english_copy not in visible_text
    assert window.property("theme") == "dark"

    theme_combo = window.settings_page.findChild(QComboBox, "themeModeCombo")
    assert theme_combo is not None
    theme_combo.setCurrentIndex(theme_combo.findData("light"))
    assert window.property("theme") == "light"

    expected_pages = {
        "workspace": "workspacePage",
        "scene": "sceneConfigurationPage",
        "experiments": "experimentManagementPage",
        "analysis": "dataAnalysisPage",
        "assets": "assetCenterPage",
        "settings": "systemSettingsPage",
        "live": "liveMonitorPage",
    }
    for navigation_key, page_name in expected_pages.items():
        button = window.findChild(QPushButton, f"nav_{navigation_key}")
        assert button is not None
        assert not button.icon().isNull()
        assert button.iconSize().width() == 18
        assert button.iconSize().height() == 18
        button.click()
        assert page_stack.currentWidget().objectName() == page_name

    assets_button = window.findChild(QPushButton, "nav_assets")
    assert assets_button is not None
    assets_button.click()
    assert window.findChild(QLineEdit, "assetSearchInput") is not None
    assert window.findChild(QTreeWidget, "assetDirectoryTree") is not None
    assert window.findChild(QPushButton, "assetImportButton") is not None
    assert window.findChild(QPushButton, "assetPreview2d") is None
    assert window.findChild(QPushButton, "assetPreview3d") is None
    asset_button_texts = {button.text() for button in window.assets_page.findChildren(QPushButton)}
    assert "2D 预览" not in asset_button_texts
    assert "3D 预览" not in asset_button_texts
    assert len(window.assets_page.findChildren(MapLibreDeckMapWidget)) == 1
    window.close()
