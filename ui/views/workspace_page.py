"""Workspace overview and management dialogs."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.models import TRAFFIC_SCENARIO_PRESETS, MapSummary, WorkspaceOverview, WorkspaceSummary
from ui.views.components import PAGE_CONTENT_MARGIN, empty_state, metric_card, panel
from ui.widgets import MapLibreDeckMapWidget


class WorkspaceEditDialog(QDialog):
    """Create or edit a workspace without exposing persistence details."""

    def __init__(
        self,
        *,
        title: str,
        workspace: WorkspaceSummary | None = None,
        entity_label: str = "工作区",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceEditDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)

        name_label = QLabel(f"{entity_label}名称")
        name_label.setObjectName("fieldLabel")
        layout.addWidget(name_label)
        self.name_input = QLineEdit(workspace.name if workspace is not None else "")
        self.name_input.setObjectName("workspaceNameInput")
        self.name_input.setPlaceholderText(f"请输入{entity_label}名称")
        self.name_input.setMaxLength(200)
        self.name_input.textChanged.connect(self._refresh_acceptance)
        layout.addWidget(self.name_input)

        description_label = QLabel("描述")
        description_label.setObjectName("fieldLabel")
        layout.addWidget(description_label)
        self.description_input = QTextEdit()
        self.description_input.setObjectName("workspaceDescriptionInput")
        self.description_input.setPlaceholderText(f"请输入{entity_label}描述…")
        self.description_input.setFixedHeight(110)
        if workspace is not None:
            self.description_input.setPlainText(workspace.description)
        layout.addWidget(self.description_input)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh_acceptance()

    def values(self) -> tuple[str, str]:
        return (
            self.name_input.text().strip(),
            self.description_input.toPlainText().strip(),
        )

    def _refresh_acceptance(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(self.name_input.text().strip())
        )


class WorkspaceDeleteDialog(QDialog):
    """Destructive confirmation requiring the exact workspace name."""

    def __init__(self, workspace: WorkspaceSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceDeleteDialog")
        self.setWindowTitle("删除工作区")
        self.setModal(True)
        self.setMinimumWidth(500)
        self._workspace_name = workspace.name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        heading = QLabel("删除工作区")
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        message = QLabel(f"确定要删除“{workspace.name}”工作区吗？此操作无法撤销。")
        message.setWordWrap(True)
        layout.addWidget(message)
        self.error_label = QLabel()
        self.error_label.setObjectName("workspaceDeleteError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.confirm_input = QLineEdit()
        self.confirm_input.setObjectName("workspaceDeleteConfirmInput")
        self.confirm_input.setPlaceholderText("请输入工作区名称以确认删除")
        self.confirm_input.textChanged.connect(self.error_label.hide)
        layout.addWidget(self.confirm_input)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        delete = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        delete.setText("删除")
        delete.setObjectName("dangerButton")
        delete.clicked.connect(self._attempt_delete)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _attempt_delete(self) -> None:
        if self.confirm_input.text() == self._workspace_name:
            self.accept()
            return
        self.error_label.setText(f"工作区名称不匹配，请输入完整名称“{self._workspace_name}”。")
        self.error_label.show()
        self.confirm_input.setFocus()
        self.confirm_input.selectAll()


class WorkspaceOverviewPage(QWidget):
    enter_requested = Signal()
    rename_requested = Signal()
    delete_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        load_web_map: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceOverviewPage")
        self._load_web_map = load_web_map
        self._workspace: WorkspaceSummary | None = None
        self._metric_values: dict[str, QLabel] = {}
        self._automation_values: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())

        self.body_stack = QStackedWidget()
        self.body_stack.setObjectName("workspaceBodyStack")
        self.empty = empty_state(
            "还没有工作区",
            "点击左侧“+”创建工作区。进入工作区后才能配置并运行仿真。",
            "▦",
        )
        self.content = self._overview_content()
        self.body_stack.addWidget(self.empty)
        self.body_stack.addWidget(self.content)
        root.addWidget(self.body_stack, 1)
        self.set_workspace(None)

    @property
    def workspace(self) -> WorkspaceSummary | None:
        return self._workspace

    def set_workspace(self, workspace: WorkspaceSummary | None) -> None:
        self._workspace = workspace
        available = workspace is not None
        self.title.setText(workspace.name if workspace is not None else "工作区")
        self.description.setText(
            workspace.description
            if workspace is not None and workspace.description
            else "选择一个工作区查看总览"
        )
        self.enter_button.setEnabled(available)
        self.rename_button.setEnabled(available)
        self.delete_button.setEnabled(available)
        self.body_stack.setCurrentWidget(self.content if available else self.empty)
        if available:
            self._reset_overview()

    def set_overview(self, overview: WorkspaceOverview | None) -> None:
        if (
            overview is None
            or self._workspace is None
            or overview.workspace_id != self._workspace.workspace_id
        ):
            return
        values = {
            "map_count": f"{overview.map_count:,}",
            "agent_count": f"{overview.agent_count:,}",
            "scenario_count": f"{len(TRAFFIC_SCENARIO_PRESETS):,}",
            "simulation_count": f"{overview.simulation_count:,}",
            "total": f"{overview.simulation_count:,}",
            "succeeded": f"{overview.succeeded_simulations:,}",
            "failed": f"{overview.failed_simulations:,}",
            "runtime": f"{overview.runtime_hours:,.1f} h",
        }
        for key, value in values.items():
            self._metric_values[key].setText(value)
        for label in self._automation_values.values():
            label.setText("0")
        for item in overview.automation_counts:
            automation_label = self._automation_values.get(item.level)
            if automation_label is not None:
                automation_label.setText(f"{item.count:,}")
        self.preview_title.setText(f"区域预览 · {overview.preview_region}")
        self.activity_table.setRowCount(len(overview.activity))
        maximum = max((sample.simulations for sample in overview.activity), default=1)
        for row, sample in enumerate(overview.activity):
            self.activity_table.setItem(row, 0, QTableWidgetItem(str(sample.day)[5:]))
            progress = QProgressBar()
            progress.setRange(0, maximum)
            progress.setValue(sample.simulations)
            progress.setFormat(f"{sample.simulations} 次")
            self.activity_table.setCellWidget(row, 1, progress)
        self.recent_table.setRowCount(len(overview.recent_simulations))
        status_labels = {"SUCCEEDED": "成功", "WARNING": "警告", "FAILED": "失败"}
        for row, simulation in enumerate(overview.recent_simulations):
            duration_minutes = simulation.duration_ms // 60_000
            row_values = (
                simulation.name,
                status_labels[simulation.status],
                f"{duration_minutes // 60:02d}:{duration_minutes % 60:02d}",
                simulation.automation_summary,
            )
            for column, value in enumerate(row_values):
                self.recent_table.setItem(row, column, QTableWidgetItem(value))

    def _header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(30, 16, PAGE_CONTENT_MARGIN, 16)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.title = QLabel("工作区")
        self.title.setObjectName("pageTitle")
        self.description = QLabel("选择一个工作区查看总览")
        self.description.setObjectName("pageSubtitle")
        self.description.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.description)
        layout.addLayout(text, 1)

        self.rename_button = QPushButton("重命名")
        self.rename_button.setObjectName("workspaceRenameButton")
        self.rename_button.clicked.connect(self.rename_requested)
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self.delete_requested)
        self.enter_button = QPushButton("进入工作区  →")
        self.enter_button.setObjectName("workspaceEnterButton")
        self.enter_button.setProperty("role", "primaryAction")
        self.enter_button.clicked.connect(self.enter_requested)
        for button in (self.rename_button, self.delete_button, self.enter_button):
            button.setFixedSize(112, 36)
        layout.addWidget(self.rename_button)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.enter_button)
        return frame

    def _overview_content(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 18, PAGE_CONTENT_MARGIN, 24)
        layout.setSpacing(12)

        metrics = QGridLayout()
        metrics.setSpacing(12)
        definitions = (
            ("map_count", "地图数量", "工作区地图资产"),
            ("agent_count", "智能体数量", "当前工作区车辆规模"),
            ("scenario_count", "场景个数", "实际可运行场景"),
            ("simulation_count", "仿真次数", "累计运行记录"),
        )
        for column, (key, label, detail) in enumerate(definitions):
            card = metric_card(label, "—", detail)
            self._metric_values[key] = self._card_value(card)
            metrics.addWidget(card, 0, column)
        layout.addLayout(metrics)

        automation = QHBoxLayout()
        automation.setSpacing(10)
        for level in ("L0", "L1", "L2", "L3", "L4", "L5", "其他交通参与方"):
            card = metric_card(level, "—")
            self._automation_values[level] = self._card_value(card)
            automation.addWidget(card)
        layout.addLayout(automation)

        outcomes = QHBoxLayout()
        outcomes.setSpacing(12)
        for key, label in (
            ("total", "总仿真次数"),
            ("succeeded", "成功次数"),
            ("failed", "失败次数"),
            ("runtime", "累计仿真时间"),
        ):
            card = metric_card(label, "—")
            self._metric_values[key] = self._card_value(card)
            outcomes.addWidget(card)
        layout.addLayout(outcomes)

        details = QHBoxLayout()
        details.setSpacing(12)
        preview = QFrame()
        preview.setObjectName("workspacePreview")
        preview_layout = QVBoxLayout(preview)
        self.preview_title = QLabel("区域预览")
        self.preview_title.setObjectName("panelTitle")
        preview_layout.addWidget(self.preview_title)
        self.preview_map = MapLibreDeckMapWidget(
            load_page=self._load_web_map,
            show_legend=False,
        )
        self.preview_map.setObjectName("workspacePreviewMap")
        self.preview_map.setMinimumHeight(520)
        preview_layout.addWidget(self.preview_map, 1)
        self.preview_status = QLabel("正在加载标准路网预览……")
        self.preview_status.setObjectName("workspacePreviewStatus")
        preview_layout.addWidget(self.preview_status)
        details.addWidget(preview, 3)
        details.addWidget(self._activity_panel(), 2)
        layout.addLayout(details, 1)
        layout.addWidget(self._recent_panel())
        scroll.setWidget(body)
        return scroll

    def set_preview_network(self, network: object) -> None:
        """Render the selected standard network in the workspace region preview."""
        self.preview_map.set_network(network)
        self.preview_status.setText("已加载标准路网预览")

    def set_maps(self, maps: tuple[MapSummary, ...]) -> None:
        """Explain whether a validated SUMO network is available for preview."""
        has_preview = any(item.kind == "sumo" and item.validated for item in maps)
        self.preview_status.setText(
            "正在加载标准路网预览……" if has_preview else "暂无可预览的SUMO路网"
        )

    def _activity_panel(self) -> QFrame:
        self.activity_table = QTableWidget(0, 2)
        self.activity_table.setObjectName("workspaceActivityTable")
        self.activity_table.setHorizontalHeaderLabels(("日期", "活动趋势（7 天）"))
        self.activity_table.horizontalHeader().setStretchLastSection(True)
        self.activity_table.verticalHeader().hide()
        self.activity_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return panel("活动趋势（7 天）", self.activity_table, kicker="近期运行")

    def _recent_panel(self) -> QFrame:
        self.recent_table = QTableWidget(0, 4)
        self.recent_table.setObjectName("workspaceRecentTable")
        self.recent_table.setHorizontalHeaderLabels(("仿真名称", "状态", "时长", "智能体构成"))
        self.recent_table.horizontalHeader().setStretchLastSection(True)
        self.recent_table.verticalHeader().hide()
        self.recent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return panel("近期仿真", self.recent_table, kicker="近期运行记录")

    def _reset_overview(self) -> None:
        for label in (*self._metric_values.values(), *self._automation_values.values()):
            label.setText("—")
        self.preview_title.setText("区域预览")
        self.activity_table.setRowCount(0)
        self.recent_table.setRowCount(0)

    @staticmethod
    def _card_value(card: QFrame) -> QLabel:
        labels = card.findChildren(QLabel, "metricValue")
        if not labels:
            raise RuntimeError("metric card does not contain a value label")
        return labels[0]


def run_workspace_dialog(
    dialog: WorkspaceEditDialog,
    submit: Callable[[str, str], None],
) -> None:
    if dialog.exec() == QDialog.DialogCode.Accepted:
        submit(*dialog.values())
