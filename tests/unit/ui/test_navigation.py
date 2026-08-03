from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QScrollArea, QWidget
from ui.models import ReplayResult
from ui.views.navigation import NavigationRail
from ui.views.theme import ThemeMode, load_stylesheet


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def test_brand_logo_renders_the_complete_svg_canvas() -> None:
    _application()
    navigation = NavigationRail()
    label = navigation.findChild(QLabel, "brandLogo")

    assert label is not None
    pixmap = label.pixmap()
    assert pixmap is not None
    image = pixmap.toImage()
    corners = (
        (0, 0),
        (image.width() - 1, 0),
        (0, image.height() - 1),
        (image.width() - 1, image.height() - 1),
    )
    assert all(image.pixelColor(x, y).alpha() == 255 for x, y in corners)

    navigation.close()


def test_workspace_navigation_matches_grouped_stitch_structure_and_starts_collapsed() -> None:
    _application()
    navigation = NavigationRail()

    groups = {label.text() for label in navigation.findChildren(QLabel, "navigationGroupLabel")}
    assert groups == {"交通仿真", "资产中心"}
    assert navigation.findChild(QPushButton, "nav_scene") is not None
    assert navigation.findChild(QPushButton, "nav_expand_scene") is None

    for key in ("experiments", "traffic_scenes", "maps", "agents"):
        expand = navigation.findChild(QPushButton, f"nav_expand_{key}")
        children = navigation.findChild(QWidget, f"nav_children_{key}")
        assert expand is not None
        assert children is not None
        assert children.isHidden()
        expand.click()
        assert not children.isHidden()
        expand.click()
        assert children.isHidden()

    assert navigation.findChild(QPushButton, "nav_analysis") is None
    assert navigation.findChild(QPushButton, "nav_live") is None
    navigation.close()


def test_expandable_navigation_row_uses_one_background_for_main_and_arrow() -> None:
    app = _application()
    navigation = NavigationRail()
    navigation.setStyleSheet(load_stylesheet(ThemeMode.DARK))
    navigation.resize(236, 800)
    navigation.show()

    row = navigation.findChild(QWidget, "navRow_experiments")
    assert row is not None
    navigation.set_active("experiments")
    app.processEvents()
    selected = row.grab().toImage()
    assert selected.pixelColor(12, 2) == selected.pixelColor(selected.width() - 12, 2)

    navigation.set_active("scene")
    QTest.mouseMove(row, QPoint(row.width() - 8, row.height() // 2))
    app.processEvents()
    hovered = row.grab().toImage()
    assert hovered.pixelColor(12, 2) == hovered.pixelColor(hovered.width() - 12, 2)

    navigation.close()


def test_history_records_are_rendered_inside_the_expanded_left_navigation() -> None:
    _application()
    navigation = NavigationRail()
    navigation.set_history_results(ReplayResult.demo_records())

    scroll = navigation.findChild(QScrollArea, "navigationScroll")
    assert scroll is not None
    assert scroll.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    history_list = navigation.findChild(QListWidget, "historyReplayList")
    assert history_list is not None
    assert history_list.count() == 5
    assert history_list.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert history_list.item(0).text() == "08-03 13:04:12"
    assert history_list.item(0).toolTip() == "Town04 混合智驾障碍物场景"

    selected: list[int] = []
    navigation.history_record_selected.connect(selected.append)
    history_list.setCurrentRow(4)
    assert selected == [4]
    navigation.close()


def test_selecting_history_main_label_reveals_its_record_list() -> None:
    _application()
    navigation = NavigationRail()
    children = navigation.findChild(QWidget, "nav_children_experiments")
    history_button = navigation.findChild(QPushButton, "nav_experiments")
    assert children is not None
    assert history_button is not None
    assert children.isHidden()

    history_button.click()

    assert not children.isHidden()
    navigation.close()
