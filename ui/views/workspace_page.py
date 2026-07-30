"""Searchable workspace catalog and selected-workspace overview."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.models import WorkspacePage, WorkspaceSummary
from ui.views.components import PAGE_CONTENT_MARGIN, empty_state, page_header


class WorkspacePageWidget(QWidget):
    search_changed = Signal(str)
    workspace_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspacePage")
        self._items: dict[str, QListWidgetItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("工作台", "查找并进入交通仿真项目工作空间"))

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(PAGE_CONTENT_MARGIN, 16, PAGE_CONTENT_MARGIN, 18)
        body_layout.setSpacing(10)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("workspaceSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.addWidget(self._catalog_panel())
        splitter.addWidget(self._detail_panel())
        splitter.setSizes((360, 960))
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        body_layout.addWidget(splitter, 1)
        root.addWidget(body, 1)

    def _catalog_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        frame.setMinimumWidth(300)
        frame.setMaximumWidth(460)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("我的工作台")
        title.setObjectName("panelTitle")
        self.result_count = QLabel("0 个工作台")
        self.result_count.setObjectName("caption")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.result_count)
        layout.addLayout(heading)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("workspaceSearchInput")
        self.search_input.setPlaceholderText("搜索名称或描述")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.search_changed)
        layout.addWidget(self.search_input)

        self.loading_label = QLabel("正在加载工作台……")
        self.loading_label.setObjectName("caption")
        self.loading_label.hide()
        layout.addWidget(self.loading_label)

        self.workspace_list = QListWidget()
        self.workspace_list.setObjectName("workspaceList")
        self.workspace_list.setAlternatingRowColors(True)
        self.workspace_list.setSpacing(2)
        self.workspace_list.itemSelectionChanged.connect(self._emit_selection)
        layout.addWidget(self.workspace_list, 1)
        return frame

    def _detail_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        self.detail_stack = QStackedWidget()
        self.detail_stack.setObjectName("workspaceDetailStack")
        self.empty_detail = empty_state(
            "选择工作台",
            "从左侧列表选择一个工作台，查看项目描述与更新时间。",
            "▦",
        )
        self.detail = QWidget()
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        detail_layout.setSpacing(14)
        self.workspace_name = QLabel()
        self.workspace_name.setObjectName("pageTitle")
        self.workspace_description = QLabel()
        self.workspace_description.setObjectName("workspaceDescription")
        self.workspace_description.setWordWrap(True)
        self.workspace_description.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.workspace_id = QLabel()
        self.workspace_id.setObjectName("mono")
        self.workspace_updated = QLabel()
        self.workspace_updated.setObjectName("caption")
        detail_layout.addWidget(self.workspace_name)
        detail_layout.addWidget(self.workspace_description)
        detail_layout.addSpacing(8)
        detail_layout.addWidget(self.workspace_id)
        detail_layout.addWidget(self.workspace_updated)
        detail_layout.addStretch(1)
        self.detail_stack.addWidget(self.empty_detail)
        self.detail_stack.addWidget(self.detail)
        layout.addWidget(self.detail_stack, 1)
        return frame

    @Slot(object)
    def set_workspaces(self, page: object) -> None:
        if not isinstance(page, WorkspacePage):
            return
        self.workspace_list.clear()
        self._items.clear()
        for workspace in page.items:
            item = QListWidgetItem(workspace.name)
            identifier = str(workspace.workspace_id)
            item.setData(Qt.ItemDataRole.UserRole, identifier)
            item.setToolTip(workspace.description or "暂无描述")
            self.workspace_list.addItem(item)
            self._items[identifier] = item
        self.result_count.setText(f"{page.total} 个工作台")

    @Slot(object)
    def set_selection(self, workspace: object) -> None:
        if workspace is None:
            self.workspace_list.clearSelection()
            self.detail_stack.setCurrentWidget(self.empty_detail)
            return
        if not isinstance(workspace, WorkspaceSummary):
            return
        identifier = str(workspace.workspace_id)
        item = self._items.get(identifier)
        if item is not None and item is not self.workspace_list.currentItem():
            self.workspace_list.setCurrentItem(item)
        self.workspace_name.setText(workspace.name)
        self.workspace_description.setText(workspace.description or "暂无描述")
        self.workspace_id.setText(f"工作台 ID：{identifier}")
        updated = workspace.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self.workspace_updated.setText(f"最近更新：{updated}")
        self.detail_stack.setCurrentWidget(self.detail)

    @Slot(bool)
    def set_loading(self, loading: bool) -> None:
        self.loading_label.setVisible(loading)
        self.search_input.setEnabled(not loading)

    def _emit_selection(self) -> None:
        item = self.workspace_list.currentItem()
        if item is None:
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(identifier, str):
            self.workspace_selected.emit(identifier)
