from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QTreeWidget
from ui.models import MapSummary
from ui.models.assets import AssetDirectoryEntry, AssetFileEntry
from ui.views.map_asset_page import MapAssetPage
from ui.widgets import MapLibreDeckMapWidget
from ui.widgets.asset_directory import AssetDirectoryWidget


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _town04_entry() -> AssetDirectoryEntry:
    return AssetDirectoryEntry(
        asset_id="town04",
        name="Town04",
        validated=True,
        compatibility=("SUMO", "CARLA", "deck.gl", "MapLibre"),
        files=(
            AssetFileEntry("Town04.xodr", ".xodr", ("CARLA",)),
            AssetFileEntry("Town04.net.xml", ".net.xml", ("SUMO",)),
            AssetFileEntry("network.geojson", ".geojson", ("deck.gl", "MapLibre")),
        ),
    )


def test_asset_directory_filters_files_and_emits_parent_asset() -> None:
    app = _application()
    assert isinstance(app, QCoreApplication)
    widget = AssetDirectoryWidget()
    selected: list[str] = []
    widget.asset_selected.connect(selected.append)
    widget.set_assets((_town04_entry(),))

    search = widget.findChild(QLineEdit, "assetSearchInput")
    tree = widget.findChild(QTreeWidget, "assetDirectoryTree")
    assert search is not None
    assert tree is not None
    assert tree.topLevelItemCount() == 1
    directory = tree.topLevelItem(0)
    assert directory is not None
    assert directory.childCount() == 3

    search.setText("geojson")
    visible_files = []
    for index in range(directory.childCount()):
        child = directory.child(index)
        assert child is not None
        if not child.isHidden():
            visible_files.append(child.text(0))
    assert visible_files == ["network.geojson"]

    selected_file = directory.child(2)
    assert selected_file is not None
    tree.setCurrentItem(selected_file)
    assert selected[-1] == "town04"
    widget.close()


def test_asset_directory_searches_platform_and_map_id() -> None:
    _application()
    widget = AssetDirectoryWidget()
    widget.set_assets((_town04_entry(),))
    search = widget.findChild(QLineEdit, "assetSearchInput")
    tree = widget.findChild(QTreeWidget, "assetDirectoryTree")
    assert search is not None
    assert tree is not None

    search.setText("sumo")
    directory = tree.topLevelItem(0)
    assert directory is not None
    assert not directory.isHidden()
    search.setText("missing")
    assert directory.isHidden()
    search.setText("town04")
    assert not directory.isHidden()
    widget.close()


def test_map_asset_preview_hides_vehicle_legend_and_technology_badge() -> None:
    _application()
    page = MapAssetPage(load_web_map=False)
    summary = MapSummary(
        map_id="town04",
        kind="sumo",
        display_name="Town04",
        validated=True,
        network_schema_version="traffic-network/1.0",
        files=("network.geojson",),
    )

    page.set_maps((summary,))
    page._select_asset(summary.map_id)
    page.set_preview_network(summary.map_id, {"type": "FeatureCollection", "features": []})

    preview = page.findChild(MapLibreDeckMapWidget, "assetPreviewMap")
    assert preview is not None
    assert preview._pending["setLegendVisible"] is False
    labels = {label.text() for label in page.findChildren(QLabel)}
    assert not any("deck.gl" in label or "MapLibre" in label for label in labels)
    assert page.preview_status.text() == "已加载标准路网预览"
    page.close()
