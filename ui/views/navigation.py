"""Persistent navigation rail for the desktop shell."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QEnterEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.models import ReplayResult, WorkspaceSummary
from ui.views.element_plus_icons import ICON_SIZE, render_element_plus_icon, render_svg_pixmap
from ui.views.theme import ThemeMode, load_icon_colors

_NAVIGATION_GROUPS = (
    (
        "交通仿真",
        (
            ("scene", "set-up.svg", "仿真配置", None),
            ("experiments", "data-board.svg", "历史仿真", "仿真记录"),
            ("traffic_scenes", "monitor.svg", "交通场景", "场景列表"),
        ),
    ),
    (
        "资产中心",
        (
            ("maps", "box.svg", "地图", "地图资产"),
            ("agents", "trend-charts.svg", "智能体", "API 配置"),
        ),
    ),
)
_SETTINGS_NAVIGATION = ("settings", "setting.svg", "系统设置")
_ICON_ROOT = Path(__file__).resolve().parents[1] / "assets/icons/element-plus"
_BRAND_LOGO = Path(__file__).resolve().parents[1] / "assets/icons/logo.svg"


class _ExpandableNavigationRow(QWidget):
    """One visual navigation row containing a page action and expand action."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "navigationRow")
        self.setProperty("active", False)
        self.setProperty("hovered", False)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self._refresh_style()

    def enterEvent(self, event: QEnterEvent) -> None:
        self.setProperty("hovered", True)
        self._refresh_style()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.setProperty("hovered", False)
        self._refresh_style()
        super().leaveEvent(event)

    def _refresh_style(self) -> None:
        for widget in (self, *self.findChildren(QPushButton)):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()


class NavigationRail(QWidget):
    page_selected = Signal(str)
    history_record_selected = Signal(int)
    workspace_exit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navigationRail")
        self.setFixedWidth(236)
        self._buttons: dict[str, QPushButton] = {}
        self._sub_buttons: dict[str, QPushButton] = {}
        self._expand_buttons: dict[str, QPushButton] = {}
        self._child_containers: dict[str, QWidget] = {}
        self._expandable_rows: dict[str, _ExpandableNavigationRow] = {}
        self._history_records: tuple[ReplayResult, ...] = ()
        self.history_record_list: QListWidget | None = None
        self._icon_paths: dict[str, Path] = {}
        self._theme = ThemeMode.DARK

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(6)
        layout.addLayout(self._brand())
        layout.addSpacing(18)

        navigation_content = QWidget()
        navigation_content.setObjectName("navigationContent")
        navigation_layout = QVBoxLayout(navigation_content)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(6)

        self.workspace_back = QPushButton("←  返回工作区")
        self.workspace_back.setObjectName("workspaceBackButton")
        self.workspace_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.workspace_back.clicked.connect(self.workspace_exit_requested)
        navigation_layout.addWidget(self.workspace_back)
        self.workspace_name = QLabel("尚未选择工作区")
        self.workspace_name.setObjectName("activeWorkspaceName")
        self.workspace_name.setWordWrap(True)
        navigation_layout.addWidget(self.workspace_name)
        navigation_layout.addSpacing(18)

        section = QLabel("控制中心")
        section.setObjectName("sectionLabel")
        navigation_layout.addWidget(section)
        navigation_layout.addSpacing(8)
        for group_name, items in _NAVIGATION_GROUPS:
            group = QLabel(group_name)
            group.setObjectName("navigationGroupLabel")
            navigation_layout.addWidget(group)
            for key, icon, label, child_label in items:
                if child_label is None:
                    navigation_layout.addWidget(self._nav_button(key, icon, label))
                    continue
                navigation_layout.addWidget(self._expandable_nav(key, icon, label, child_label))
            navigation_layout.addSpacing(8)

        navigation_layout.addStretch(1)
        navigation_layout.addWidget(self._nav_button(*_SETTINGS_NAVIGATION))

        divider = QFrame()
        divider.setObjectName("navigationDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        navigation_layout.addWidget(divider)
        version = QLabel("TrafficVerse  ·  v0.1\n核心运行控制台")
        version.setObjectName("brandCaption")
        version.setAlignment(Qt.AlignmentFlag.AlignLeft)
        navigation_layout.addWidget(version)

        navigation_scroll = QScrollArea()
        navigation_scroll.setObjectName("navigationScroll")
        navigation_scroll.setWidgetResizable(True)
        navigation_scroll.setFrameShape(QFrame.Shape.NoFrame)
        navigation_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        navigation_scroll.setWidget(navigation_content)
        layout.addWidget(navigation_scroll, 1)
        self.set_active("live")

    def set_workspace(self, name: str) -> None:
        self.workspace_name.setText(name)

    def set_active(self, key: str) -> None:
        for button_key, button in self._buttons.items():
            button.setProperty("active", button_key == key)
            button.style().unpolish(button)
            button.style().polish(button)
        for button_key, button in self._sub_buttons.items():
            button.setProperty("active", button_key == key)
            button.style().unpolish(button)
            button.style().polish(button)
        for row_key, row in self._expandable_rows.items():
            row.set_active(row_key == key)
        self.refresh_icons()

    def refresh_icons(self, theme: ThemeMode | None = None) -> None:
        if theme is not None:
            self._theme = theme
        colors = load_icon_colors(self._theme)
        for key, button in self._buttons.items():
            color_name = colors["active"] if button.property("active") else colors["normal"]
            color = QColor(color_name)
            button.setIcon(render_element_plus_icon(self._icon_paths[key], color))
            button.setIconSize(ICON_SIZE)

    def _brand(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setPixmap(
            render_svg_pixmap(
                _BRAND_LOGO,
                QSize(40, 40),
            )
        )
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel("TrafficVerse")
        name.setObjectName("brandName")
        caption = QLabel("交通仿真系统")
        caption.setObjectName("brandCaption")
        text.addWidget(name)
        text.addWidget(caption)
        row.addWidget(logo)
        row.addLayout(text)
        row.addStretch(1)
        return row

    def _nav_button(self, key: str, icon_file: str, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setProperty("navKey", key)
        button.setAccessibleName(label)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda checked=False, page=key: self.page_selected.emit(page))
        self._buttons[key] = button
        self._icon_paths[key] = _ICON_ROOT / icon_file
        button.setObjectName(f"nav_{key}")
        button.setProperty("role", "navigation")
        return button

    def _expandable_nav(
        self,
        key: str,
        icon_file: str,
        label: str,
        child_label: str,
    ) -> QWidget:
        container = QWidget()
        container.setObjectName(f"navContainer_{key}")
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        row = _ExpandableNavigationRow()
        row.setObjectName(f"navRow_{key}")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        main_button = self._nav_button(key, icon_file, label)
        main_button.setProperty("role", "navigationRowMain")
        if key == "experiments":
            main_button.clicked.connect(lambda checked=False, page=key: self._show_children(page))
        row_layout.addWidget(main_button, 1)
        expand_button = QPushButton("›")
        expand_button.setObjectName(f"nav_expand_{key}")
        expand_button.setProperty("role", "navigationExpand")
        expand_button.setAccessibleName(f"展开{label}")
        expand_button.setCursor(Qt.CursorShape.PointingHandCursor)
        expand_button.setFixedWidth(32)
        expand_button.clicked.connect(lambda checked=False, page=key: self._toggle_children(page))
        row_layout.addWidget(expand_button)
        column.addWidget(row)

        children = QWidget()
        children.setObjectName(f"nav_children_{key}")
        children_layout = QVBoxLayout(children)
        children_layout.setContentsMargins(0, 0, 0, 0)
        children_layout.setSpacing(0)
        child_button = QPushButton(child_label)
        child_button.setObjectName(f"nav_child_{key}")
        child_button.setProperty("role", "subnavigation")
        child_button.setCursor(Qt.CursorShape.PointingHandCursor)
        child_button.clicked.connect(lambda checked=False, page=key: self.page_selected.emit(page))
        children_layout.addWidget(child_button)
        if key == "experiments":
            history_list = QListWidget()
            history_list.setObjectName("historyReplayList")
            history_list.setFixedHeight(166)
            history_list.setSpacing(1)
            history_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            history_list.setToolTip("按日期选择仿真回放记录")
            history_list.currentRowChanged.connect(self._history_row_changed)
            children_layout.addWidget(history_list)
            self.history_record_list = history_list
        children.hide()
        column.addWidget(children)

        self._expand_buttons[key] = expand_button
        self._child_containers[key] = children
        self._sub_buttons[key] = child_button
        self._expandable_rows[key] = row
        return container

    def set_history_results(self, results: tuple[ReplayResult, ...]) -> None:
        """Refresh the date list shown below the expanded history navigation item."""

        self._history_records = results
        history_list = self.history_record_list
        if history_list is None:
            return
        blocker = QSignalBlocker(history_list)
        history_list.clear()
        for result in results:
            item = QListWidgetItem(result.started_at.strftime("%m-%d %H:%M:%S"))
            item.setData(Qt.ItemDataRole.UserRole, history_list.count())
            item.setSizeHint(QSize(0, 30))
            item.setToolTip(result.scenario_name)
            history_list.addItem(item)
        if history_list.count() > 0:
            history_list.setCurrentRow(0)
        blocker.unblock()

    @Slot(int)
    def _history_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._history_records):
            self.history_record_selected.emit(row)

    def _toggle_children(self, key: str) -> None:
        children = self._child_containers[key]
        expanded = children.isHidden()
        children.setVisible(expanded)
        button = self._expand_buttons[key]
        button.setText("⌄" if expanded else "›")
        label = self._buttons[key].text()
        button.setAccessibleName(f"{'折叠' if expanded else '展开'}{label}")

    def _show_children(self, key: str) -> None:
        """Keep the history records visible when its main navigation label is selected."""

        children = self._child_containers[key]
        if children.isHidden():
            children.show()
            self._expand_buttons[key].setText("⌄")
            self._expand_buttons[key].setAccessibleName(f"折叠{self._buttons[key].text()}")


class _WorkspaceListRow(QWidget):
    delete_requested = Signal(object)

    def __init__(self, workspace: WorkspaceSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceListRow")
        self.setProperty("active", False)
        self.setMinimumHeight(42)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 4, 3)
        layout.setSpacing(6)
        self.name_label = QLabel(workspace.name)
        self.name_label.setObjectName("workspaceListName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.name_label, 1)
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("workspaceListDeleteButton")
        self.delete_button.setAccessibleName(f"删除工作区 {workspace.name}")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setFixedHeight(28)
        self.name_label.installEventFilter(self)
        self.delete_button.installEventFilter(self)
        self.delete_button.clicked.connect(
            lambda checked=False: self.delete_requested.emit(workspace)
        )
        self.delete_button.hide()
        layout.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event: QEnterEvent) -> None:
        self.delete_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        QTimer.singleShot(0, self._hide_delete_when_pointer_left)
        super().leaveEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in {self.name_label, self.delete_button}:
            if event.type() is QEvent.Type.Enter:
                self.delete_button.show()
            elif event.type() is QEvent.Type.Leave:
                QTimer.singleShot(0, self._hide_delete_when_pointer_left)
        return super().eventFilter(watched, event)

    def _hide_delete_when_pointer_left(self) -> None:
        if not self.underMouse() and not self.delete_button.underMouse():
            self.delete_button.hide()


class WorkspaceNavigationRail(QWidget):
    """Workspace browser shown before simulation-specific navigation."""

    workspace_selected = Signal(str)
    workspace_enter_requested = Signal()
    create_requested = Signal()
    delete_requested = Signal(object)
    search_changed = Signal(str)
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceNavigationRail")
        self.setFixedWidth(260)
        self._workspace_ids: set[str] = set()
        self._rows: dict[str, _WorkspaceListRow] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(8)
        layout.addLayout(self._brand())
        layout.addSpacing(24)

        heading = QHBoxLayout()
        title = QLabel("工作区")
        title.setObjectName("workspaceSectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        create = QPushButton("+")
        create.setObjectName("workspaceCreateButton")
        create.setAccessibleName("新建工作区")
        create.setToolTip("新建工作区")
        create.setFixedSize(30, 30)
        create.clicked.connect(self.create_requested)
        heading.addWidget(create)
        layout.addLayout(heading)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("workspaceSearchInput")
        self.search_input.setPlaceholderText("搜索工作区…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.search_changed)
        layout.addWidget(self.search_input)

        self.workspace_list = QListWidget()
        self.workspace_list.setObjectName("workspaceList")
        self.workspace_list.setSpacing(2)
        self.workspace_list.currentItemChanged.connect(self._selection_changed)
        self.workspace_list.itemDoubleClicked.connect(self._workspace_double_clicked)
        layout.addWidget(self.workspace_list, 1)

        settings = QPushButton("⚙  系统设置")
        settings.setObjectName("workspaceSettingsButton")
        settings.setProperty("role", "navigation")
        settings.clicked.connect(self.settings_requested)
        layout.addWidget(settings)

    def set_workspaces(
        self,
        workspaces: tuple[WorkspaceSummary, ...],
        selected_workspace_id: str | None = None,
    ) -> None:
        blocker = QSignalBlocker(self.workspace_list)
        previous_id = selected_workspace_id
        if previous_id is None and self.workspace_list.currentItem() is not None:
            previous_id = str(self.workspace_list.currentItem().data(Qt.ItemDataRole.UserRole))
        self.workspace_list.clear()
        self._workspace_ids = {str(workspace.workspace_id) for workspace in workspaces}
        self._rows.clear()
        selected_item: QListWidgetItem | None = None
        for workspace in workspaces:
            workspace_id = str(workspace.workspace_id)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, workspace_id)
            item.setToolTip(workspace.description or workspace.name)
            item.setSizeHint(QSize(0, 42))
            self.workspace_list.addItem(item)
            row = _WorkspaceListRow(workspace)
            row.delete_requested.connect(self.delete_requested)
            self.workspace_list.setItemWidget(item, row)
            self._rows[workspace_id] = row
            if workspace_id == previous_id:
                selected_item = item
        if selected_item is None and self.workspace_list.count():
            selected_item = self.workspace_list.item(0)
        if selected_item is not None:
            self.workspace_list.setCurrentItem(selected_item)
        blocker.unblock()
        self._refresh_active_rows()

    def set_selected(self, workspace_id: str | None) -> None:
        if workspace_id is None or workspace_id not in self._workspace_ids:
            self.workspace_list.clearSelection()
            return
        for index in range(self.workspace_list.count()):
            item = self.workspace_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole)) == workspace_id:
                self.workspace_list.setCurrentItem(item)
                return

    @Slot(QListWidgetItem, QListWidgetItem)
    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        self._refresh_active_rows()
        if current is not None:
            self.workspace_selected.emit(str(current.data(Qt.ItemDataRole.UserRole)))

    def _refresh_active_rows(self) -> None:
        current = self.workspace_list.currentItem()
        current_id = str(current.data(Qt.ItemDataRole.UserRole)) if current is not None else None
        for workspace_id, row in self._rows.items():
            row.set_active(workspace_id == current_id)

    @Slot(QListWidgetItem)
    def _workspace_double_clicked(self, item: QListWidgetItem) -> None:
        self.workspace_list.setCurrentItem(item)
        self.workspace_enter_requested.emit()

    def _brand(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setPixmap(render_svg_pixmap(_BRAND_LOGO, QSize(40, 40)))
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel("TrafficVerse")
        name.setObjectName("brandName")
        caption = QLabel("交通仿真系统")
        caption.setObjectName("brandCaption")
        text.addWidget(name)
        text.addWidget(caption)
        row.addWidget(logo)
        row.addLayout(text)
        row.addStretch(1)
        return row
