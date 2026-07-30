from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLineEdit, QTreeWidget
from ui.models.assets import AssetDirectoryEntry, AssetFileEntry
from ui.widgets.asset_directory import AssetDirectoryWidget


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _town04_entry() -> AssetDirectoryEntry:
    return AssetDirectoryEntry(
        asset_id="town04-sumo-1.27.1-v2",
        name="Town04",
        validated=True,
        compatibility=("SUMO", "deck.gl", "MapLibre"),
        files=(
            AssetFileEntry("Town04.xodr", ".xodr", ("SUMO",)),
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
    assert tree.topLevelItem(0).childCount() == 3

    search.setText("geojson")
    visible_files = [
        tree.topLevelItem(0).child(index).text(0)
        for index in range(tree.topLevelItem(0).childCount())
        if not tree.topLevelItem(0).child(index).isHidden()
    ]
    assert visible_files == ["network.geojson"]

    tree.setCurrentItem(tree.topLevelItem(0).child(2))
    assert selected[-1] == "town04-sumo-1.27.1-v2"
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
    assert not tree.topLevelItem(0).isHidden()
    search.setText("missing")
    assert tree.topLevelItem(0).isHidden()
    search.setText("town04")
    assert not tree.topLevelItem(0).isHidden()
    widget.close()
