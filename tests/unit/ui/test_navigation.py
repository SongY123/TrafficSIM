from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QWidget
from ui.models import TRAFFIC_SCENARIO_PRESETS, ExperimentStatus, ReplaySummary
from ui.views.navigation import NavigationRail
from ui.views.theme import ThemeMode, load_stylesheet


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _history() -> tuple[ReplaySummary, ...]:
    return tuple(
        ReplaySummary(
            run_id=run_id,
            status=ExperimentStatus.COMPLETED,
            created_at=datetime(2026, 8, 11, 9, index, tzinfo=timezone.utc),
            scene_name=f"Scenario {index}",
            map_id="town04",
            map_name="Town04",
            configured_duration_ms=60_000,
            simulation_time_ms=60_000,
            replay_available=index == 0,
            export_available=True,
        )
        for index, run_id in enumerate(("2026-08-11-09-08-07", "2026-08-11-08-07-06"))
    )


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
    records = _history()
    navigation.set_history(records)
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
    assert len(entries) == len(records)
    assert children.isHidden()
    history.click()
    app.processEvents()
    assert not children.isHidden()
    assert children.height() >= 32 * len(records)
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


def test_traffic_scene_navigation_lists_and_selects_each_scenario() -> None:
    app = _application()
    navigation = NavigationRail()
    navigation.resize(236, 760)
    navigation.show()
    requests: list[str] = []
    navigation.traffic_scene_requested.connect(requests.append)
    traffic_scenes = navigation.findChild(QPushButton, "nav_traffic_scenes")
    children = navigation.findChild(QWidget, "nav_children_traffic_scenes")
    entries = [
        button
        for button in navigation.findChildren(QPushButton)
        if button.property("role") == "scenarioEntry"
    ]

    assert traffic_scenes is not None
    assert children is not None
    assert len(entries) == len(TRAFFIC_SCENARIO_PRESETS)
    assert children.isHidden()
    traffic_scenes.click()
    app.processEvents()

    assert not children.isHidden()
    assert children.height() >= 32 * len(TRAFFIC_SCENARIO_PRESETS)
    assert [entry.text() for entry in entries] == [
        preset.name for preset in TRAFFIC_SCENARIO_PRESETS
    ]

    entries[1].click()
    navigation.set_active("traffic_scenes")
    navigation.set_traffic_scene_selection(requests[0])
    row = navigation.findChild(QWidget, "navRow_traffic_scenes")

    assert requests == [TRAFFIC_SCENARIO_PRESETS[1].scenario_id]
    assert entries[1].property("active") is True
    assert row is not None
    assert row.property("active") is True
    navigation.close()


def test_navigation_middle_area_accepts_wheel_scrolling_when_groups_expand() -> None:
    app = _application()
    navigation = NavigationRail()
    navigation.resize(236, 480)
    navigation.show()
    for key in ("experiments", "traffic_scenes", "maps", "agents"):
        expand = navigation.findChild(QPushButton, f"nav_expand_{key}")
        assert expand is not None
        expand.click()
    app.processEvents()

    scroll = navigation.findChild(QScrollArea, "navigationScroll")
    assert scroll is not None
    scroll_bar = scroll.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    wheel = QWheelEvent(
        QPointF(12.0, 12.0),
        QPointF(12.0, 12.0),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(scroll.viewport(), wheel)
    app.processEvents()

    assert scroll_bar.value() > 0
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
