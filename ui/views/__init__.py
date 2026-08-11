"""Lazy public UI view exports that keep package import lightweight."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.views.main_window import MainWindow

__all__ = ["MainWindow"]


def __getattr__(name: str) -> object:
    if name == "MainWindow":
        from ui.views.main_window import MainWindow

        return MainWindow
    raise AttributeError(name)
