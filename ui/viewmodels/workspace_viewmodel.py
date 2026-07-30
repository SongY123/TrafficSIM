"""Workspace list and search state, independent from concrete widgets."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ui.api_client import RestApiClient
from ui.models import WorkspacePage, WorkspaceSummary


class WorkspaceViewModel(QObject):
    workspaces_changed = Signal(object)
    selection_changed = Signal(object)
    loading_changed = Signal(bool)
    notification = Signal(str, str)

    def __init__(self, rest: RestApiClient, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rest = rest
        self._workspaces: tuple[WorkspaceSummary, ...] = ()
        self._selected_id: UUID | None = None
        self._query: str | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh)
        rest.request_succeeded.connect(self.handle_rest_success)
        rest.request_failed.connect(self.handle_rest_failure)

    def initialize(self) -> None:
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        self.loading_changed.emit(True)
        self._rest.list_workspaces(self._query)

    @Slot(str)
    def set_search_query(self, value: str) -> None:
        query = value.strip() or None
        if query == self._query:
            return
        self._query = query
        self._search_timer.start()

    @Slot(str)
    def select(self, workspace_id: str) -> None:
        try:
            identifier = UUID(workspace_id)
        except ValueError:
            return
        workspace = next(
            (item for item in self._workspaces if item.workspace_id == identifier),
            None,
        )
        if workspace is None:
            return
        self._selected_id = identifier
        self.selection_changed.emit(workspace)

    @Slot(str, object)
    def handle_rest_success(self, operation: str, payload: object) -> None:
        if operation != "workspaces.list":
            return
        page = WorkspacePage.model_validate(payload)
        self._workspaces = page.items
        self.loading_changed.emit(False)
        self.workspaces_changed.emit(page)
        selected = next(
            (item for item in page.items if item.workspace_id == self._selected_id),
            page.items[0] if page.items else None,
        )
        self._selected_id = selected.workspace_id if selected is not None else None
        self.selection_changed.emit(selected)

    @Slot(str, str)
    def handle_rest_failure(self, operation: str, message: str) -> None:
        if operation != "workspaces.list":
            return
        self.loading_changed.emit(False)
        self.notification.emit("error", f"工作台加载失败：{message}")
