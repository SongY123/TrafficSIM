"""Project detail page for workspace information and simulation records."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.models import WorkspaceOverview, WorkspaceSummary
from ui.models.protocol import WorkspaceRecentSimulation
from ui.views.components import PAGE_CONTENT_MARGIN, PANEL_CONTENT_MARGIN, page_header
from ui.views.theme import DEFAULT_THEME, ThemeMode, load_icon_colors

_STATUS_PRESENTATION = {
    "WARNING": ("进行中", "running"),
    "SUCCEEDED": ("完成", "completed"),
    "FAILED": ("失败", "failed"),
}
_ACTION_ICON_SIZE = QSize(18, 18)
_ICON_DEVICE_PIXEL_RATIO = 2


def _render_action_icon(action: str, color: QColor) -> QIcon:
    physical_size = _ACTION_ICON_SIZE * _ICON_DEVICE_PIXEL_RATIO
    pixmap = QPixmap(physical_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(_ICON_DEVICE_PIXEL_RATIO, _ICON_DEVICE_PIXEL_RATIO)
    painter.setPen(
        QPen(
            color,
            1.4,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )

    if action == "view":
        eye = QPainterPath(QPointF(2.0, 9.0))
        eye.cubicTo(5.0, 4.5, 13.0, 4.5, 16.0, 9.0)
        eye.cubicTo(13.0, 13.5, 5.0, 13.5, 2.0, 9.0)
        painter.drawPath(eye)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(9.0, 9.0), 1.8, 1.8)
    elif action in {"pause", "replay"}:
        painter.drawEllipse(QRectF(2.5, 2.5, 13.0, 13.0))
        if action == "pause":
            painter.drawLine(QPointF(7.0, 6.2), QPointF(7.0, 11.8))
            painter.drawLine(QPointF(11.0, 6.2), QPointF(11.0, 11.8))
        else:
            painter.setBrush(color)
            painter.drawPolygon(
                QPolygonF((QPointF(7.4, 5.8), QPointF(12.0, 9.0), QPointF(7.4, 12.2)))
            )
    elif action == "delete":
        painter.drawLine(QPointF(5.0, 5.5), QPointF(13.0, 5.5))
        painter.drawLine(QPointF(7.0, 3.8), QPointF(11.0, 3.8))
        painter.drawRoundedRect(QRectF(5.7, 6.0, 6.6, 8.2), 0.8, 0.8)
        painter.drawLine(QPointF(8.0, 8.0), QPointF(8.0, 12.1))
        painter.drawLine(QPointF(10.0, 8.0), QPointF(10.0, 12.1))
    elif action == "copy":
        painter.drawRoundedRect(QRectF(6.1, 3.0, 7.2, 9.2), 0.8, 0.8)
        painter.drawRoundedRect(QRectF(3.6, 5.8, 7.2, 9.2), 0.8, 0.8)
    elif action == "logs":
        painter.drawRoundedRect(QRectF(2.7, 4.0, 12.6, 10.0), 1.0, 1.0)
        painter.drawLine(QPointF(5.2, 7.1), QPointF(7.2, 9.0))
        painter.drawLine(QPointF(7.2, 9.0), QPointF(5.2, 10.9))
        painter.drawLine(QPointF(9.0, 11.0), QPointF(12.2, 11.0))

    painter.end()
    pixmap.setDevicePixelRatio(_ICON_DEVICE_PIXEL_RATIO)
    return QIcon(pixmap)


class _EditableProjectField(QFrame):
    """Keyboard-accessible project information region."""

    clicked = Signal()

    def __init__(
        self,
        label: str,
        *,
        value_object_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("projectEditableField")
        self.setProperty("editable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"编辑{label}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)
        field_label = QLabel(label)
        field_label.setObjectName("projectFieldLabel")
        layout.addWidget(field_label)
        self.value_label = QLabel()
        self.value_label.setObjectName(value_object_name)
        self.value_label.setWordWrap(True)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(self.value_label)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ProjectDetailPage(QWidget):
    """Show editable project metadata and recent workspace simulations."""

    edit_requested = Signal(str)
    create_simulation_requested = Signal()
    simulation_action_requested = Signal(str, str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectDetailPage")
        self._workspace: WorkspaceSummary | None = None
        self._theme = DEFAULT_THEME

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("项目详情", "项目信息与仿真记录"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(PAGE_CONTENT_MARGIN, 18, PAGE_CONTENT_MARGIN, 24)
        body_layout.setSpacing(14)
        body_layout.addWidget(self._project_information())
        body_layout.addWidget(self._simulation_records(), 1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.set_workspace(None)

    @property
    def workspace(self) -> WorkspaceSummary | None:
        return self._workspace

    def set_workspace(self, workspace: WorkspaceSummary | None) -> None:
        previous_id = self._workspace.workspace_id if self._workspace is not None else None
        self._workspace = workspace
        self.name_field.value_label.setText(
            workspace.name if workspace is not None else "未命名项目"
        )
        description = workspace.description if workspace is not None else ""
        self.description_field.value_label.setText(description or "暂无描述")
        current_id = workspace.workspace_id if workspace is not None else None
        if current_id != previous_id:
            self.simulation_table.setRowCount(0)

    def set_overview(self, overview: WorkspaceOverview | None) -> None:
        if (
            overview is None
            or self._workspace is None
            or overview.workspace_id != self._workspace.workspace_id
        ):
            return
        self._render_simulations(overview.recent_simulations)

    def _project_information(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(PANEL_CONTENT_MARGIN, 12, PANEL_CONTENT_MARGIN, 14)
        layout.setSpacing(10)
        title = QLabel("项目信息")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.name_field = _EditableProjectField(
            "名称",
            value_object_name="projectNameValue",
        )
        self.name_field.clicked.connect(lambda: self.edit_requested.emit("name"))
        layout.addWidget(self.name_field)
        self.description_field = _EditableProjectField(
            "描述",
            value_object_name="projectDescriptionValue",
        )
        self.description_field.clicked.connect(lambda: self.edit_requested.emit("description"))
        layout.addWidget(self.description_field)
        return frame

    def _simulation_records(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(PANEL_CONTENT_MARGIN, 12, PANEL_CONTENT_MARGIN, 14)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        title = QLabel("仿真列表")
        title.setObjectName("panelTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        create = QPushButton("+ 新建仿真")
        create.setObjectName("projectCreateSimulationButton")
        create.setProperty("role", "primaryAction")
        create.setAccessibleName("新建仿真")
        create.clicked.connect(self.create_simulation_requested)
        heading.addWidget(create)
        layout.addLayout(heading)

        table = QTableWidget(0, 5)
        table.setObjectName("projectSimulationTable")
        table.setHorizontalHeaderLabels(
            ("仿真名称", "仿真时间", "仿真参数设置", "仿真状态", "操作")
        )
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.simulation_table = table
        layout.addWidget(table, 1)
        return frame

    def _render_simulations(
        self,
        simulations: tuple[WorkspaceRecentSimulation, ...],
    ) -> None:
        self.simulation_table.setRowCount(len(simulations))
        for row, simulation in enumerate(simulations):
            status_label, status_state = _STATUS_PRESENTATION[simulation.status]
            duration = self._duration_text(simulation.duration_ms)
            values = (
                simulation.name,
                f"{self._time_text(simulation.occurred_at)} · {duration}",
                simulation.automation_summary,
            )
            for column, value in enumerate(values):
                self.simulation_table.setItem(row, column, QTableWidgetItem(value))
            status = QLabel(f"●  {status_label}")
            status.setObjectName("projectSimulationStatus")
            status.setProperty("state", status_state)
            status.setAccessibleName(f"仿真状态：{status_label}")
            status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            status.setContentsMargins(8, 0, 4, 0)
            self.simulation_table.setCellWidget(row, 3, status)
            self.simulation_table.setCellWidget(
                row,
                4,
                self._simulation_actions(
                    simulation.name,
                    status_state,
                    simulation.automation_summary,
                ),
            )
            self.simulation_table.setRowHeight(row, 48)

    def _simulation_actions(
        self,
        simulation_name: str,
        status: str,
        parameter_summary: str,
    ) -> QWidget:
        widget = QWidget()
        widget.setObjectName("projectSimulationActions")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        actions = (
            (("查看", "view"), ("暂停", "pause"), ("复制", "copy"))
            if status == "running"
            else (("回放", "replay"), ("删除", "delete"), ("复制", "copy"))
            if status == "completed"
            else (("查看", "logs"), ("删除", "delete"), ("复制", "copy"))
        )
        for label, action in actions:
            button = QToolButton()
            button.setObjectName("projectSimulationAction")
            button.setProperty("action", action)
            button.setAccessibleName(f"{label}仿真 {simulation_name}")
            button.setToolTip(label)
            button.setIcon(
                _render_action_icon(
                    action,
                    QColor(load_icon_colors(self._theme)["normal"]),
                )
            )
            button.setIconSize(_ACTION_ICON_SIZE)
            button.setFixedSize(24, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

            def request_action(
                checked: bool = False,
                name: str = simulation_name,
                value: str = action,
                parameters: str = parameter_summary,
            ) -> None:
                del checked
                self.simulation_action_requested.emit(name, value, parameters)

            button.clicked.connect(request_action)
            layout.addWidget(button)
        return widget

    def refresh_action_icons(self, theme: ThemeMode) -> None:
        self._theme = theme
        color = QColor(load_icon_colors(theme)["normal"])
        for button in self.findChildren(QToolButton, "projectSimulationAction"):
            action = str(button.property("action"))
            button.setIcon(_render_action_icon(action, color))

    @staticmethod
    def _time_text(value: datetime) -> str:
        return value.astimezone().strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _duration_text(duration_ms: int) -> str:
        total_minutes = duration_ms // 60_000
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
