"""Directory-based map asset catalog with MapLibre preview."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ui.models import MapManifest, MapSummary
from ui.models.assets import AssetDirectoryEntry, map_asset_entry
from ui.views.components import PAGE_CONTENT_MARGIN, page_header
from ui.widgets import AssetDirectoryWidget, MapLibreDeckMapWidget


class AssetCenterPage(QWidget):
    """Manage reusable map packages and preview their standardized network."""

    import_requested = Signal()
    preview_requested = Signal(str)

    def __init__(self, *, load_web_map: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assetCenterPage")
        self._maps: dict[str, MapSummary] = {}
        self._manifests: dict[str, MapManifest] = {}
        self._selected_asset_id: str | None = None

        self.directory = AssetDirectoryWidget()
        self.directory.asset_selected.connect(self._select_asset)
        self.map_widget = MapLibreDeckMapWidget(load_page=load_web_map)
        self.map_widget.setObjectName("assetPreviewMap")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(
            page_header(
                "资产中心",
                "统一管理 OpenDRIVE 编译源、SUMO 地图包与 Web 可视化资源",
                self._header_actions(),
            )
        )

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(PAGE_CONTENT_MARGIN, 16, PAGE_CONTENT_MARGIN, 18)
        body_layout.setSpacing(10)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("assetCatalogSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.directory.setMinimumWidth(300)
        self.directory.setMaximumWidth(460)
        self.splitter.addWidget(self.directory)
        self.splitter.addWidget(self._preview_panel())
        self.splitter.setSizes((340, 980))
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        body_layout.addWidget(self.splitter, 1)
        root.addWidget(body, 1)

    def _header_actions(self) -> QWidget:
        actions = QWidget()
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.import_button = QPushButton("新增地图包")
        self.import_button.setObjectName("assetImportButton")
        self.import_button.setProperty("role", "primaryAction")
        self.import_button.setToolTip(
            "当前可导入 OpenDRIVE .xodr；编译后的地图包会自动生成目录与预览资源"
        )
        self.import_button.clicked.connect(self.import_requested)
        layout.addWidget(self.import_button)
        return actions

    def _preview_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        self.asset_name = QLabel("选择地图资产")
        self.asset_name.setObjectName("panelTitle")
        self.asset_id = QLabel("从左侧目录选择地图包或文件")
        self.asset_id.setObjectName("caption")
        title_stack.addWidget(self.asset_name)
        title_stack.addWidget(self.asset_id)
        heading.addLayout(title_stack)
        heading.addStretch(1)
        self.compatibility = QLabel("OpenDRIVE · SUMO · deck.gl · MapLibre")
        self.compatibility.setObjectName("compatibilityTag")
        self.status = QLabel("等待选择")
        self.status.setObjectName("assetStatusBadge")
        heading.addWidget(self.compatibility)
        heading.addWidget(self.status)
        layout.addLayout(heading)

        self.map_widget.setMinimumHeight(420)
        layout.addWidget(self.map_widget, 1)

        footer = QHBoxLayout()
        self.preview_status = QLabel("选择已验证地图包后加载标准 network.geojson")
        self.preview_status.setObjectName("caption")
        self.file_count = QLabel("0 个文件")
        self.file_count.setObjectName("caption")
        footer.addWidget(self.preview_status)
        footer.addStretch(1)
        footer.addWidget(self.file_count)
        layout.addLayout(footer)
        formats = QLabel(
            "可收录格式：.xodr、.net.xml、.sumocfg、.rou.xml、.geojson、.json、"
            ".fbx、.glb、.gltf、.bin、.yaml；.xodr 是 OpenDRIVE/SUMO 编译源。"
        )
        formats.setObjectName("caption")
        formats.setWordWrap(True)
        layout.addWidget(formats)
        return frame

    def set_maps(self, maps: tuple[MapSummary, ...]) -> None:
        self._maps = {item.map_id: item for item in maps}
        self._refresh_directory()

    def set_manifest(self, map_id: str, manifest: MapManifest) -> None:
        if map_id not in self._maps:
            return
        self._manifests[map_id] = manifest
        self._refresh_directory()

    def set_preview_network(self, map_id: str, network: object) -> None:
        if map_id != self._selected_asset_id:
            return
        self.map_widget.set_network(network)
        self.preview_status.setText("已加载 MapLibre/deck.gl 标准路网预览")

    def _refresh_directory(self) -> None:
        entries = tuple(
            map_asset_entry(summary, self._manifests.get(summary.map_id))
            for summary in self._maps.values()
        )
        self.directory.set_assets(entries)
        if self._selected_asset_id in self._maps:
            self.directory.select_asset(self._selected_asset_id)
            assert self._selected_asset_id is not None
            self._show_asset(self._selected_asset_id)

    @Slot(str)
    def _select_asset(self, map_id: str) -> None:
        if map_id not in self._maps:
            return
        self._selected_asset_id = map_id
        self._show_asset(map_id)
        self.preview_status.setText("正在加载地图可视化资源……")
        self.preview_requested.emit(map_id)

    def _show_asset(self, map_id: str) -> None:
        summary = self._maps[map_id]
        manifest = self._manifests.get(map_id)
        entry: AssetDirectoryEntry = map_asset_entry(summary, manifest)
        self.asset_name.setText(map_id)
        self.asset_id.setText(
            f"地图 ID：{map_id}  ·  SUMO {summary.sumo_version}  ·  "
            f"{summary.network_schema_version}"
        )
        self.status.setText("已验证" if summary.validated else "待验证")
        self.compatibility.setText(" · ".join(entry.compatibility) or "正在加载清单")
        self.file_count.setText(f"{len(entry.files)} 个文件")
