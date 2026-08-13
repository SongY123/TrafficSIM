"""Workspace-scoped API agent asset configuration."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.models import AgentApiSummary
from ui.views.components import PAGE_CONTENT_MARGIN, page_header, panel

_MOCK_WORKSPACE_ID = UUID("00000000-0000-0000-0000-0000000000a0")
_AUTOMATION_LEVEL_PATTERN = re.compile(r"(?<![A-Z0-9])L([0-5])(?![A-Z0-9])", re.IGNORECASE)


def _mock_agent_api_summaries() -> tuple[AgentApiSummary, ...]:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    definitions = (
        ("L0人工驾驶智能体", "trafficverse-l0-driver", "人工驾驶基础行为模型"),
        ("L1辅助驾驶智能体", "trafficverse-l1-assist", "碰撞预警与紧急制动模型"),
        ("L2部分自动驾驶智能体", "trafficverse-l2-partial", "组合驾驶辅助模型"),
        ("L3条件自动驾驶智能体", "trafficverse-l3-conditional", "条件自动驾驶决策模型"),
        ("L4高度自动驾驶智能体", "trafficverse-l4-high", "限定区域高度自动驾驶模型"),
        ("L5完全自动驾驶智能体", "trafficverse-l5-full", "完全自动驾驶决策模型"),
    )
    return tuple(
        AgentApiSummary(
            agent_api_id=UUID(f"00000000-0000-0000-0000-0000000000a{index}"),
            workspace_id=_MOCK_WORKSPACE_ID,
            name=name,
            api_base_url=f"https://mock-agents.trafficverse.local/v1/l{index - 1}",
            model_id=model_id,
            credential_env_var=f"TRAFFICVERSE_L{index - 1}_AGENT_API_KEY",
            description=description,
            created_at=created_at,
            updated_at=created_at,
        )
        for index, (name, model_id, description) in enumerate(definitions, start=1)
    )


def _automation_level(agent: AgentApiSummary) -> str:
    match = _AUTOMATION_LEVEL_PATTERN.search(f"{agent.name} {agent.model_id}")
    return f"L{match.group(1)}" if match is not None else "自定义"


class AgentAssetPage(QWidget):
    """Configure remote intelligent agents without storing API secrets."""

    configure_requested = Signal(str, str, str, str, str)
    delete_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("agentAssetPage")
        self._agents: tuple[AgentApiSummary, ...] = ()
        self._using_mock_agents = True
        self._editing_agent_id: UUID | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(
            page_header(
                "智能体",
                "通过 API 配置接入可复用的驾驶与交通智能体",
            )
        )

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(PAGE_CONTENT_MARGIN, 16, PAGE_CONTENT_MARGIN, 18)
        layout.setSpacing(12)
        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self._configuration_panel(), 2)
        columns.addWidget(self._catalog_panel(), 3)
        layout.addLayout(columns, 1)
        root.addWidget(body, 1)
        self.set_agents(())

    def _configuration_panel(self) -> QFrame:
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(11)
        self.name_input = QLineEdit()
        self.name_input.setObjectName("agentNameInput")
        self.name_input.setPlaceholderText("例如：城市驾驶智能体")
        self.api_input = QLineEdit()
        self.api_input.setObjectName("agentApiUrlInput")
        self.api_input.setPlaceholderText("https://agents.example.com/v1")
        self.model_input = QLineEdit()
        self.model_input.setObjectName("agentModelInput")
        self.model_input.setPlaceholderText("模型或智能体 ID")
        self.credential_input = QLineEdit("TRAFFICVERSE_AGENT_API_KEY")
        self.credential_input.setObjectName("agentCredentialEnvInput")
        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("用途说明（可选）")
        form.addRow("名称", self.name_input)
        form.addRow("API 地址", self.api_input)
        form.addRow("模型 ID", self.model_input)
        form.addRow("凭证环境变量", self.credential_input)
        form.addRow("说明", self.description_input)
        note = QLabel("这里只保存环境变量名称，不保存 API Key；凭证由部署环境注入。")
        note.setObjectName("caption")
        note.setWordWrap(True)
        form.addRow("", note)
        self.save_button = QPushButton("添加 API 智能体")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._emit_configuration)
        form.addRow("", self.save_button)
        return panel("API 配置", content, kicker="智能体接入")

    def _catalog_panel(self) -> QFrame:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("agentAssetTable")
        self.table.setHorizontalHeaderLabels(
            ("智驾等级", "智能体名称", "模型 ID", "API 地址", "操作")
        )
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 126)
        layout.addWidget(self.table, 1)
        return panel("已配置智能体", content, kicker="工作区资源")

    def set_agents(self, agents: tuple[AgentApiSummary, ...]) -> None:
        self._using_mock_agents = not agents
        self._agents = agents or _mock_agent_api_summaries()
        self._editing_agent_id = None
        self._reset_editor()
        self._render_agents()

    def _render_agents(self) -> None:
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._agents))
        for row, agent in enumerate(self._agents):
            values = (
                _automation_level(agent),
                agent.name,
                agent.model_id,
                agent.api_base_url,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            self.table.setCellWidget(row, 4, self._row_actions(agent.agent_api_id))
            self.table.setRowHeight(row, 42)

    def _row_actions(self, agent_id: UUID) -> QWidget:
        actions = QWidget()
        actions.setObjectName("agentRowActions")
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        edit_button = QPushButton("编辑")
        edit_button.setObjectName("agentRowEditButton")
        edit_button.clicked.connect(
            lambda _checked=False, selected_id=agent_id: self._begin_edit(selected_id)
        )
        delete_button = QPushButton("删除")
        delete_button.setObjectName("agentRowDeleteButton")
        delete_button.clicked.connect(
            lambda _checked=False, selected_id=agent_id: self._delete_agent(selected_id)
        )
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        return actions

    def _begin_edit(self, agent_id: UUID) -> None:
        agent = next((item for item in self._agents if item.agent_api_id == agent_id), None)
        if agent is None:
            return
        self._editing_agent_id = agent_id
        self.name_input.setText(agent.name)
        self.api_input.setText(agent.api_base_url)
        self.model_input.setText(agent.model_id)
        self.credential_input.setText(agent.credential_env_var)
        self.description_input.setText(agent.description)
        self.save_button.setText("保存修改")

    def _emit_configuration(self) -> None:
        if self._editing_agent_id is not None:
            self._save_local_edit()
            return
        self.configure_requested.emit(
            self.name_input.text().strip(),
            self.api_input.text().strip(),
            self.model_input.text().strip(),
            self.credential_input.text().strip(),
            self.description_input.text().strip(),
        )

    def _save_local_edit(self) -> None:
        updated_at = datetime.now(timezone.utc)
        self._agents = tuple(
            agent.model_copy(
                update={
                    "name": self.name_input.text().strip(),
                    "api_base_url": self.api_input.text().strip(),
                    "model_id": self.model_input.text().strip(),
                    "credential_env_var": self.credential_input.text().strip(),
                    "description": self.description_input.text().strip(),
                    "updated_at": updated_at,
                }
            )
            if agent.agent_api_id == self._editing_agent_id
            else agent
            for agent in self._agents
        )
        self._editing_agent_id = None
        self._render_agents()
        self._reset_editor()

    def _delete_agent(self, agent_id: UUID) -> None:
        if not self._using_mock_agents:
            self.delete_requested.emit(agent_id)
            return
        self._agents = tuple(agent for agent in self._agents if agent.agent_api_id != agent_id)
        if self._editing_agent_id == agent_id:
            self._editing_agent_id = None
            self._reset_editor()
        self._render_agents()

    def _reset_editor(self) -> None:
        self.name_input.clear()
        self.api_input.clear()
        self.model_input.clear()
        self.credential_input.setText("TRAFFICVERSE_AGENT_API_KEY")
        self.description_input.clear()
        self.save_button.setText("添加 API 智能体")
