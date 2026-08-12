"""Lazy view-model exports that do not require every Qt transport at import time."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.viewmodels.replay_playback import ReplayPlaybackViewModel
    from ui.viewmodels.run_viewmodel import RunViewModel

__all__ = ["ReplayPlaybackViewModel", "RunViewModel"]


def __getattr__(name: str) -> object:
    if name == "ReplayPlaybackViewModel":
        from ui.viewmodels.replay_playback import ReplayPlaybackViewModel

        return ReplayPlaybackViewModel
    if name == "RunViewModel":
        from ui.viewmodels.run_viewmodel import RunViewModel

        return RunViewModel
    raise AttributeError(name)
