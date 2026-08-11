from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from ui.models import ReplayFrame, ReplayWindow
from ui.viewmodels.replay_playback import ReplayPlaybackViewModel

RUN_ID = "2026-08-11-09-08-07"


def _application() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _frame(sequence: int, simulation_time_ms: int) -> ReplayFrame:
    return ReplayFrame(simulation_time_ms=simulation_time_ms, sequence=sequence)


def test_playback_paces_paginated_frames_restarts_and_exits_without_runtime() -> None:
    _application()
    playback = ReplayPlaybackViewModel()
    frames: list[int] = []
    states: list[str] = []
    more: list[tuple[str, int]] = []
    exited: list[str] = []
    playback.frame_changed.connect(lambda frame: frames.append(frame.sequence))
    playback.state_changed.connect(states.append)
    playback.more_requested.connect(lambda run_id, time_ms: more.append((run_id, time_ms)))
    playback.exited.connect(exited.append)

    playback.load_window(
        ReplayWindow(
            run_id=RUN_ID,
            frames=(_frame(1, 0), _frame(2, 1_000)),
            next_time_ms=2_000,
        )
    )
    playback.start()
    playback._advance()

    assert frames == [1, 2]
    assert states[:2] == ["PAUSED", "RUNNING"]
    assert more == [(RUN_ID, 2_000)]
    playback.load_window(
        ReplayWindow(
            run_id=RUN_ID,
            frames=(_frame(2, 1_000), _frame(3, 2_000)),
            next_time_ms=None,
        )
    )
    playback._advance()

    assert frames == [1, 2, 3]
    assert states[-1] == "COMPLETED"
    playback.restart()
    assert frames[-1] == 1
    assert states[-1] == "PAUSED"
    playback.exit()
    assert exited == [RUN_ID]
    assert playback.active is False
