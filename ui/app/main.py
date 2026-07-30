"""PySide6 application bootstrap; communicates only through API protocols."""

from __future__ import annotations

import argparse
import sys
from uuid import UUID

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ui.api_client import RealtimeClient, RestApiClient
from ui.viewmodels import RunViewModel, WorkspaceViewModel
from ui.views import MainWindow

DEFAULT_SCENARIO_ID = UUID("00000000-0000-0000-0000-000000000042")


def run(api_url: str, scenario_id: UUID = DEFAULT_SCENARIO_ID) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("TrafficVerse")
    rest = RestApiClient(api_url)
    realtime = RealtimeClient(api_url)
    viewmodel = RunViewModel(rest, realtime, scenario_id)
    workspace_viewmodel = WorkspaceViewModel(rest)
    window = MainWindow(viewmodel, workspace_viewmodel)
    window.show()
    QTimer.singleShot(0, viewmodel.initialize)
    QTimer.singleShot(0, workspace_viewmodel.initialize)
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(prog="trafficverse-ui")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scenario-id", type=UUID, default=DEFAULT_SCENARIO_ID)
    args = parser.parse_args()
    return run(args.api_url, args.scenario_id)


if __name__ == "__main__":
    raise SystemExit(main())
