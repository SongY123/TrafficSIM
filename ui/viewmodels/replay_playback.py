"""Wall-clock playback state for reconstructed simulation frames."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ui.models import ReplayFrame, ReplayWindow


class ReplayPlaybackViewModel(QObject):
    """Pace immutable replay frames without touching the simulation runtime."""

    frame_changed = Signal(object)
    state_changed = Signal(str)
    more_requested = Signal(str, int)
    exited = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._run_id: str | None = None
        self._frames: list[ReplayFrame] = []
        self._sequences: set[int] = set()
        self._index = 0
        self._speed = 1.0
        self._next_time_ms: int | None = None
        self._requested_next_time_ms: int | None = None
        self._state = "STOPPED"
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

    @property
    def active(self) -> bool:
        return self._run_id is not None

    @property
    def run_id(self) -> str | None:
        return self._run_id

    def load_window(self, window: ReplayWindow) -> None:
        first_window = self._run_id != window.run_id
        if first_window:
            self._timer.stop()
            self._run_id = window.run_id
            self._frames = []
            self._sequences.clear()
            self._index = 0
            self._state = "PAUSED"
        for frame in window.frames:
            if frame.sequence not in self._sequences:
                self._frames.append(frame)
                self._sequences.add(frame.sequence)
        self._frames.sort(key=lambda frame: frame.sequence)
        self._next_time_ms = window.next_time_ms
        self._requested_next_time_ms = None
        if first_window:
            if self._frames:
                self.frame_changed.emit(self._frames[0])
                self.state_changed.emit("PAUSED")
            else:
                self.state_changed.emit("EMPTY")
        if self._state == "RUNNING":
            self._schedule_next()

    def start(self) -> None:
        if not self._frames or self._run_id is None:
            return
        self._state = "RUNNING"
        self.state_changed.emit(self._state)
        self._schedule_next()

    def pause(self) -> None:
        if self._run_id is None:
            return
        self._timer.stop()
        self._state = "PAUSED"
        self.state_changed.emit(self._state)

    def restart(self) -> None:
        if not self._frames:
            return
        self._timer.stop()
        self._index = 0
        self._state = "PAUSED"
        self.frame_changed.emit(self._frames[0])
        self.state_changed.emit(self._state)

    def exit(self) -> None:
        run_id = self._run_id
        self._timer.stop()
        self._run_id = None
        self._frames = []
        self._sequences.clear()
        self._index = 0
        self._state = "STOPPED"
        if run_id is not None:
            self.exited.emit(run_id)

    def set_speed(self, multiplier: float) -> None:
        if multiplier not in {0.5, 1.0, 2.0}:
            return
        self._speed = multiplier
        if self._state == "RUNNING":
            self._schedule_next()

    def _advance(self) -> None:
        if self._state != "RUNNING":
            return
        if self._index + 1 < len(self._frames):
            self._index += 1
            self.frame_changed.emit(self._frames[self._index])
            self._request_more_if_needed()
            self._schedule_next()
            return
        if self._next_time_ms is not None:
            self._request_more_if_needed(force=True)
            return
        self._state = "COMPLETED"
        self.state_changed.emit(self._state)

    def _schedule_next(self) -> None:
        self._timer.stop()
        if self._index + 1 >= len(self._frames):
            self._advance()
            return
        current = self._frames[self._index].simulation_time_ms
        following = self._frames[self._index + 1].simulation_time_ms
        interval_ms = max(1, round((following - current) / self._speed))
        self._timer.start(interval_ms)

    def _request_more_if_needed(self, *, force: bool = False) -> None:
        if self._run_id is None or self._next_time_ms is None:
            return
        remaining = len(self._frames) - self._index - 1
        if not force and remaining > 100:
            return
        if self._requested_next_time_ms == self._next_time_ms:
            return
        self._requested_next_time_ms = self._next_time_ms
        self.more_requested.emit(self._run_id, self._next_time_ms)
