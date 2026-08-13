"""Load external Qt stylesheets for the desktop theme."""

from __future__ import annotations

import json
import platform
from enum import Enum
from pathlib import Path
from typing import TypedDict, cast

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


class ThemeMode(str, Enum):
    DARK = "dark"
    LIGHT = "light"


DEFAULT_THEME = ThemeMode.LIGHT


_STYLE_ROOT = Path(__file__).with_name("styles")


class IconColors(TypedDict):
    normal: str
    active: str


class FontFamilies(TypedDict):
    ui: str
    mono: str


def configure_application_font() -> None:
    """Set a concrete platform font before Qt resolves its generic aliases."""
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        raise RuntimeError("QApplication must exist before configuring the interface font")
    application.setFont(QFont(_load_platform_fonts()["ui"]))


def load_stylesheet(theme: ThemeMode) -> str:
    """Return the complete external QSS document for a supported theme."""
    stylesheet = (_STYLE_ROOT / f"{theme.value}.qss").read_text(encoding="utf-8")
    fonts = _load_platform_fonts()
    return stylesheet.replace("__TRAFFICVERSE_UI_FONT__", fonts["ui"]).replace(
        "__TRAFFICVERSE_MONO_FONT__", fonts["mono"]
    )


def load_icon_colors(theme: ThemeMode) -> IconColors:
    """Return navigation icon colors from the external theme configuration."""
    payload = json.loads((_STYLE_ROOT / "icon-colors.json").read_text(encoding="utf-8"))
    colors = payload[theme.value]
    return IconColors(normal=str(colors["normal"]), active=str(colors["active"]))


def _load_platform_fonts() -> FontFamilies:
    """Load standard installed fonts without forcing Qt to scan missing aliases."""
    payload = json.loads((_STYLE_ROOT / "font-families.json").read_text(encoding="utf-8"))
    platform_key = _font_platform_key()
    return cast(FontFamilies, payload.get(platform_key, payload["default"]))


def _font_platform_key() -> str:
    system_name = platform.system()
    if system_name == "Darwin":
        return "macos"
    if system_name == "Windows":
        return "windows"
    if system_name == "Linux":
        return "linux"
    return "default"
