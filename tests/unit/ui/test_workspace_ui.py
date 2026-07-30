from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget

from ui.models import WorkspacePage, WorkspaceSummary
from ui.viewmodels import WorkspaceViewModel
from ui.views.workspace_page import WorkspacePageWidget


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000101")


class _Rest(QObject):
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.queries: list[str | None] = []

    def list_workspaces(self, query: str | None = None) -> None:
        self.queries.append(query)


def _workspace() -> WorkspaceSummary:
    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    return WorkspaceSummary(
        workspace_id=WORKSPACE_ID,
        name="北京亦庄交通仿真",
        description="城市道路与信号控制实验",
        created_at=now,
        updated_at=now,
    )


def test_workspace_viewmodel_loads_searches_and_selects() -> None:
    app = QApplication.instance() or QApplication([])
    rest = _Rest()
    viewmodel = WorkspaceViewModel(rest)  # type: ignore[arg-type]
    pages: list[WorkspacePage] = []
    selections: list[WorkspaceSummary | None] = []
    viewmodel.workspaces_changed.connect(pages.append)
    viewmodel.selection_changed.connect(selections.append)

    viewmodel.initialize()
    assert rest.queries == [None]

    page = WorkspacePage(items=(_workspace(),), total=1, offset=0, limit=50)
    rest.request_succeeded.emit("workspaces.list", page.model_dump(mode="json"))
    assert pages == [page]
    assert selections[-1] == _workspace()

    viewmodel.set_search_query("  亦庄  ")
    QTest.qWait(300)
    app.processEvents()
    assert rest.queries[-1] == "亦庄"

    viewmodel.select(str(WORKSPACE_ID))
    assert selections[-1] == _workspace()


def test_workspace_page_renders_results_and_emits_search() -> None:
    app = QApplication.instance() or QApplication([])
    page_widget = WorkspacePageWidget()
    searches: list[str] = []
    selections: list[str] = []
    page_widget.search_changed.connect(searches.append)
    page_widget.workspace_selected.connect(selections.append)

    page_widget.set_workspaces(
        WorkspacePage(items=(_workspace(),), total=1, offset=0, limit=50)
    )
    workspace_list = page_widget.findChild(QListWidget, "workspaceList")
    assert workspace_list is not None
    assert workspace_list.count() == 1
    workspace_list.setCurrentRow(0)
    assert selections == [str(WORKSPACE_ID)]

    page_widget.set_selection(_workspace())
    assert page_widget.workspace_name.text() == "北京亦庄交通仿真"
    descriptions = {
        label.text() for label in page_widget.findChildren(QLabel)
    }
    assert "城市道路与信号控制实验" in descriptions

    search = page_widget.findChild(QLineEdit, "workspaceSearchInput")
    assert search is not None
    search.setText("信号")
    app.processEvents()
    assert searches[-1] == "信号"
