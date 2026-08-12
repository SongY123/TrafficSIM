"""Versioned Qt WebSocket client with bounded reconnect and snapshot recovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket


class RealtimeClient(QObject):
    connection_changed = Signal(str)
    envelope_received = Signal(object)
    protocol_error = Signal(str)

    def __init__(
        self,
        base_url: str,
        parent: QObject | None = None,
        *,
        socket: QWebSocket | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_url = base_url.rstrip("/")
        self._socket = socket if socket is not None else QWebSocket(parent=self)
        self._socket.connected.connect(self._connected)
        self._socket.disconnected.connect(self._disconnected)
        self._socket.textMessageReceived.connect(self._receive_text)
        self._socket.errorOccurred.connect(self._socket_error)
        self._reconnect = QTimer(self)
        self._reconnect.setSingleShot(True)
        self._reconnect.timeout.connect(self._open)
        self._experiment_id: UUID | None = None
        self._pending_experiment_id: UUID | None = None
        self._manual_close = False
        self._attempt = 0
        self._last_sequence = 0

    @property
    def experiment_id(self) -> UUID | None:
        return self._experiment_id

    def connect_to_experiment(self, experiment_id: UUID) -> None:
        state = self._socket.state()
        if self._pending_experiment_id == experiment_id:
            return
        if self._experiment_id == experiment_id and state in {
            QAbstractSocket.SocketState.ConnectingState,
            QAbstractSocket.SocketState.ConnectedState,
        }:
            return
        self._reconnect.stop()
        self._pending_experiment_id = experiment_id
        self._experiment_id = None
        self._manual_close = False
        self._attempt = 0
        self._last_sequence = 0
        if state is QAbstractSocket.SocketState.UnconnectedState:
            self._open_pending_experiment()
            return
        self.connection_changed.emit("CONNECTING")
        self._socket.close()

    def close(self) -> None:
        self._manual_close = True
        self._reconnect.stop()
        self._pending_experiment_id = None
        self._experiment_id = None
        self._attempt = 0
        self._last_sequence = 0
        self._socket.close()

    def subscribe(self) -> str:
        return self.send_command(
            "subscribe",
            {
                "topics": ["vehicles", "traffic_lights", "health", "events"],
                "max_hz": 20,
            },
        )

    def request_snapshot(self) -> str:
        return self.send_command("world.snapshot.request", {})

    def send_command(self, message_type: str, payload: dict[str, object]) -> str:
        if self._experiment_id is None:
            raise RuntimeError("an experiment must be selected before sending commands")
        if self._socket.state() is not QAbstractSocket.SocketState.ConnectedState:
            raise RuntimeError("the real-time connection is not connected")
        message_id = str(uuid4())
        message = {
            "schema_version": "1.0",
            "type": message_type,
            "message_id": message_id,
            "correlation_id": None,
            "experiment_id": str(self._experiment_id),
            "simulation_time_ms": 0,
            "sequence": self._last_sequence,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self._socket.sendTextMessage(json.dumps(message, separators=(",", ":")))
        return message_id

    def _open(self) -> None:
        if self._experiment_id is None or self._manual_close:
            return
        self.connection_changed.emit("CONNECTING")
        self._socket.open(QUrl(self._websocket_url(self._experiment_id)))

    def _connected(self) -> None:
        if self._experiment_id is None:
            # The previous connection can finish its handshake while a switch is closing it.
            self._socket.close()
            return
        self._attempt = 0
        self.connection_changed.emit("CONNECTED")
        self.subscribe()

    def _disconnected(self) -> None:
        if self._pending_experiment_id is not None:
            self._open_pending_experiment()
            return
        if self._manual_close:
            self.connection_changed.emit("DISCONNECTED")
            return
        if self._experiment_id is None:
            self.connection_changed.emit("DISCONNECTED")
            return
        self.connection_changed.emit("RECONNECTING")
        delay_ms = min(10_000, 500 * (2**self._attempt))
        self._attempt = min(self._attempt + 1, 5)
        self._reconnect.start(delay_ms)

    def _open_pending_experiment(self) -> None:
        experiment_id = self._pending_experiment_id
        if experiment_id is None:
            return
        self._pending_experiment_id = None
        self._experiment_id = experiment_id
        self._open()

    def _receive_text(self, raw: str) -> None:
        if self._experiment_id is None:
            return
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("WebSocket message must be an object")
            sequence = payload.get("sequence")
            if isinstance(sequence, int):
                self._last_sequence = max(self._last_sequence, sequence)
            if payload.get("type") == "heartbeat.ping":
                self.send_command("heartbeat.pong", {})
                return
            self.envelope_received.emit(payload)
        except (json.JSONDecodeError, ValueError, RuntimeError) as error:
            self.protocol_error.emit(str(error))

    def _socket_error(self, error: QAbstractSocket.SocketError) -> None:
        del error
        if self._manual_close or self._pending_experiment_id is not None:
            return
        self.protocol_error.emit(self._socket.errorString())

    def _websocket_url(self, experiment_id: UUID) -> str:
        parts = urlsplit(self._base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit(
            (scheme, parts.netloc, "/api/v1/ws", f"experiment_id={experiment_id}", "")
        )
