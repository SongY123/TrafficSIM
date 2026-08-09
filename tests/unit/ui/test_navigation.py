from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from ui.models import MOCK_REPLAY_RECORDS
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


def test_history_navigation_expands_on_main_click_and_opens_selected_replay() -> None:
    app = _application()
    navigation = NavigationRail()
    navigation.resize(236, 720)
    navigation.show()
    requests: list[str] = []
    navigation.replay_requested.connect(requests.append)
    history = navigation.findChild(QPushButton, "nav_experiments")
    children = navigation.findChild(QWidget, "nav_children_experiments")
    entries = [
        button
        for button in navigation.findChildren(QPushButton)
        if button.property("role") == "historyEntry"
    ]

    assert history is not None
    assert children is not None
    assert len(entries) == len(MOCK_REPLAY_RECORDS)
    assert children.isHidden()
    history.click()
    app.processEvents()
    assert not children.isHidden()
    assert children.height() >= 32 * len(MOCK_REPLAY_RECORDS)
    assert all(entry.isVisible() and entry.height() == 32 for entry in entries)
    assert all(entry.text() for entry in entries)

    entries[0].click()
    navigation.set_active("replay")
    navigation.set_history_selection(requests[0])
    row = navigation.findChild(QWidget, "navRow_experiments")

    assert requests == [entries[0].property("recordId")]
    assert entries[0].property("active") is True
    assert row is not None
    assert row.property("active") is True
    navigation.close()


def test_active_project_name_requests_project_detail_page() -> None:
    _application()
    navigation = NavigationRail()
    requests: list[bool] = []
    navigation.project_detail_requested.connect(lambda: requests.append(True))

    navigation.set_workspace("北京亦庄项目")
    project_button = navigation.findChild(QPushButton, "activeWorkspaceName")

    assert project_button is not None
    assert project_button.text() == "北京亦庄项目"
    assert project_button.accessibleName() == "打开项目详情"
    project_button.click()
    assert requests == [True]
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
