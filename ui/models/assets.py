"""Reusable presentation models for directory-based UI asset catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ui.models.protocol import MapManifest, MapSummary

_KNOWN_SUFFIXES = (
    ".tileset.json",
    ".net.xml",
    ".rou.xml",
    ".add.xml",
    ".sumocfg",
    ".geojson",
    ".xodr",
    ".fbx",
    ".b3dm",
    ".glb",
    ".gltf",
    ".bin",
    ".yaml",
    ".yml",
    ".json",
    ".xml",
)


@dataclass(frozen=True, slots=True)
class AssetFileEntry:
    """One file shown beneath an asset directory."""

    name: str
    format_suffix: str
    compatibility: tuple[str, ...] = ()
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class AssetDirectoryEntry:
    """One reusable asset package and its manifest-tracked files."""

    asset_id: str
    name: str
    validated: bool
    compatibility: tuple[str, ...]
    files: tuple[AssetFileEntry, ...] = ()


def map_asset_entry(summary: MapSummary, manifest: MapManifest | None) -> AssetDirectoryEntry:
    """Combine REST summary and optional manifest into a directory entry."""

    files = (
        tuple(
            AssetFileEntry(
                name=name,
                format_suffix=asset_file_suffix(name),
                compatibility=asset_file_compatibility(name),
                checksum=checksum,
            )
            for name, checksum in sorted(manifest.files.items())
        )
        if manifest is not None
        else ()
    )
    compatibility = tuple(
        platform
        for platform in (
            "OpenDRIVE",
            "SUMO 编译源",
            "SUMO",
            "deck.gl",
            "MapLibre",
            "3D 模型源",
        )
        if any(platform in file.compatibility for file in files)
    )
    return AssetDirectoryEntry(
        asset_id=summary.map_id,
        name=summary.map_id,
        validated=summary.validated,
        compatibility=compatibility,
        files=files,
    )


def asset_file_suffix(name: str) -> str:
    """Return a user-facing suffix while preserving compound simulator extensions."""

    normalized = name.lower()
    for suffix in _KNOWN_SUFFIXES:
        if normalized.endswith(suffix):
            return suffix
    return PurePosixPath(name).suffix.lower() or "文件"


def asset_file_compatibility(name: str) -> tuple[str, ...]:
    """Describe consumers that can use a manifest-tracked file."""

    suffix = asset_file_suffix(name)
    if suffix in {".net.xml", ".rou.xml", ".add.xml", ".sumocfg"}:
        return ("SUMO",)
    if suffix == ".xodr":
        return ("OpenDRIVE", "SUMO 编译源")
    if suffix == ".fbx":
        return ("3D 模型源",)
    if suffix in {".geojson", ".json", ".tileset.json"}:
        return ("deck.gl", "MapLibre")
    if suffix in {".glb", ".gltf", ".bin", ".b3dm"}:
        return ("deck.gl",)
    return ()
