from __future__ import annotations

import json
from uuid import UUID

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from ui.api_client.websocket_client import RealtimeClient

FIRST_EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
SECOND_EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000002")


class FakeWebSocket(QObject):
    connected = Signal()
    disconnected = Signal()
    textMessageReceived = Signal(str)
    errorOccurred = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._state = QAbstractSocket.SocketState.UnconnectedState
        self.opened_urls: list[str] = []
        self.sent_messages: list[dict[str, object]] = []
        self.close_calls = 0

    def state(self) -> QAbstractSocket.SocketState:
        return self._state

    def open(self, url: QUrl) -> None:
        self.opened_urls.append(url.toString())
        self._state = QAbstractSocket.SocketState.ConnectingState

    def close(self) -> None:
        self.close_calls += 1
        if self._state is not QAbstractSocket.SocketState.UnconnectedState:
            self._state = QAbstractSocket.SocketState.ClosingState

    def sendTextMessage(self, raw: str) -> int:
        self.sent_messages.append(json.loads(raw))
        return len(raw)

    def errorString(self) -> str:
        return "fake socket error"

    def finish_connecting(self) -> None:
        self._state = QAbstractSocket.SocketState.ConnectedState
        self.connected.emit()

    def finish_disconnecting(self) -> None:
        self._state = QAbstractSocket.SocketState.UnconnectedState
        self.disconnected.emit()


def _client(socket: FakeWebSocket) -> RealtimeClient:
    return RealtimeClient(
        "http://127.0.0.1:8000",
        socket=socket,  # type: ignore[arg-type]
    )


def test_switch_waits_for_old_socket_to_disconnect_before_opening_new_experiment() -> None:
    socket = FakeWebSocket()
    client = _client(socket)
    client.connect_to_experiment(FIRST_EXPERIMENT_ID)
    socket.finish_connecting()

    client.connect_to_experiment(SECOND_EXPERIMENT_ID)

    assert socket.close_calls == 1
    assert len(socket.opened_urls) == 1
    assert client.experiment_id is None

    socket.finish_disconnecting()

    assert len(socket.opened_urls) == 2
    assert f"experiment_id={SECOND_EXPERIMENT_ID}" in socket.opened_urls[-1]
    assert client.experiment_id == SECOND_EXPERIMENT_ID


def test_switch_resets_sequence_before_subscribing_to_new_experiment() -> None:
    socket = FakeWebSocket()
    client = _client(socket)
    client.connect_to_experiment(FIRST_EXPERIMENT_ID)
    socket.finish_connecting()
    socket.textMessageReceived.emit(json.dumps({"type": "event", "sequence": 27}))

    client.connect_to_experiment(SECOND_EXPERIMENT_ID)
    socket.finish_disconnecting()
    socket.finish_connecting()

    subscribe = socket.sent_messages[-1]
    assert subscribe["type"] == "subscribe"
    assert subscribe["experiment_id"] == str(SECOND_EXPERIMENT_ID)
    assert subscribe["sequence"] == 0
    subscribe_payload = subscribe["payload"]
    assert isinstance(subscribe_payload, dict)
    assert subscribe_payload["max_hz"] == 20


def test_manual_close_cancels_pending_experiment_switch() -> None:
    socket = FakeWebSocket()
    client = _client(socket)
    client.connect_to_experiment(FIRST_EXPERIMENT_ID)
    socket.finish_connecting()
    client.connect_to_experiment(SECOND_EXPERIMENT_ID)

    client.close()
    socket.finish_disconnecting()

    assert len(socket.opened_urls) == 1
    assert client.experiment_id is None
