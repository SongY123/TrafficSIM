"""Small presentation components shared by TrafficVerse pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

PAGE_CONTENT_MARGIN = 18
PANEL_CONTENT_MARGIN = 14
PANEL_BORDER_WIDTH = 1
PAGE_TEXT_MARGIN = PAGE_CONTENT_MARGIN + PANEL_BORDER_WIDTH + PANEL_CONTENT_MARGIN


def panel(title: str, content: QWidget, *, kicker: str | None = None) -> QFrame:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(PANEL_CONTENT_MARGIN, 12, PANEL_CONTENT_MARGIN, 14)
    layout.setSpacing(10)
    if kicker is not None:
        kicker_label = QLabel(kicker.upper())
        kicker_label.setObjectName("panelKicker")
        layout.addWidget(kicker_label)
    title_label = QLabel(title)
    title_label.setObjectName("panelTitle")
    layout.addWidget(title_label)
    layout.addWidget(content, 1)
    return frame


def page_header(title: str, subtitle: str, actions: QWidget | None = None) -> QFrame:
    frame = QFrame()
    frame.setObjectName("topBar")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(PAGE_TEXT_MARGIN, 14, PAGE_CONTENT_MARGIN, 14)
    title_stack = QVBoxLayout()
    title_stack.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    title_stack.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        title_stack.addWidget(subtitle_label)
    layout.addLayout(title_stack)
    layout.addStretch(1)
    if actions is not None:
        layout.addWidget(actions)
    return frame


def metric_card(label: str, value: str, detail: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("metricCard")
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(PANEL_CONTENT_MARGIN, 12, PANEL_CONTENT_MARGIN, 12)
    layout.setSpacing(4)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    name = QLabel(label)
    name.setObjectName("metricLabel")
    number = QLabel(value)
    number.setObjectName("metricValue")
    layout.addWidget(name)
    layout.addWidget(number)
    if detail:
        caption = QLabel(detail)
        caption.setObjectName("caption")
        layout.addWidget(caption)
    return frame


def empty_state(title: str, description: str, symbol: str = "◇") -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(30, 30, 30, 30)
    layout.addStretch(1)
    icon = QLabel(symbol)
    icon.setObjectName("emptyIcon")
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    heading = QLabel(title)
    heading.setObjectName("emptyTitle")
    heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
    body = QLabel(description)
    body.setObjectName("caption")
    body.setAlignment(Qt.AlignmentFlag.AlignCenter)
    body.setWordWrap(True)
    layout.addWidget(icon)
    layout.addWidget(heading)
    layout.addWidget(body)
    layout.addStretch(1)
    return widget
