"""Discover and validate self-contained SUMO scenario packages."""

from __future__ import annotations

import json
import math
import shutil
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from trafficverse.maps.errors import SumoPackageError

_DEFAULT_STEP_S = 1.0
_OUTPUT_ELEMENTS = frozenset(
    {
        "edgeData",
        "inductionLoop",
        "instantInductionLoop",
        "laneAreaDetector",
        "laneData",
        "meanData",
        "multiEntryExit",
        "routeProbe",
        "vTypeProbe",
    }
)


@dataclass(frozen=True, slots=True)
class SumoScenarioPackage:
    """Resolved metadata needed to render and launch one ``.sumocfg`` package."""

    package_id: str
    display_name: str
    traffic_demand_mode: Literal["generated", "scripted"]
    asset_root: Path
    directory: Path
    config_path: Path
    network_path: Path
    input_paths: tuple[Path, ...]
    route_paths: tuple[Path, ...]
    additional_paths: tuple[Path, ...]
    begin_time_ms: int
    end_time_ms: int | None
    step_ms: int
    files: tuple[str, ...]
    output_directories: tuple[Path, ...]


def discover_sumo_packages(
    directory: Path,
    *,
    allowed_root: Path,
) -> tuple[SumoScenarioPackage, ...]:
    """Parse every top-level SUMO configuration in one scenario directory."""

    config_paths = tuple(sorted(directory.glob("*.sumocfg")))
    multiple = len(config_paths) > 1
    return tuple(
        load_sumo_package(
            config_path,
            allowed_root=allowed_root,
            package_id=(
                f"{directory.name}-{config_path.name.removesuffix('.sumocfg')}"
                if multiple
                else directory.name
            ),
        )
        for config_path in config_paths
    )


def load_sumo_package(
    config_path: Path,
    *,
    allowed_root: Path,
    package_id: str | None = None,
) -> SumoScenarioPackage:
    """Load one SUMO configuration and resolve its complete explicit input set safely."""

    resolved_config = config_path.resolve()
    resolved_root = allowed_root.resolve()
    _require_within(resolved_config, resolved_root, "configuration file")
    try:
        root = ElementTree.parse(resolved_config).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise SumoPackageError(f"invalid SUMO configuration {config_path.name}: {error}") from error
    if root.tag != "configuration":
        raise SumoPackageError(
            f"SUMO configuration root must be <configuration>: {config_path.name}"
        )

    input_values = _input_file_values(root)
    network_values = input_values.get("net-file", ())
    if len(network_values) != 1:
        raise SumoPackageError("SUMO configuration must reference exactly one net-file")

    directory = resolved_config.parent
    resolved_inputs: dict[str, tuple[Path, ...]] = {}
    missing: list[str] = []
    for option, values in input_values.items():
        paths = tuple(
            _resolve_input_path(value, directory=directory, allowed_root=resolved_root)
            for value in values
        )
        resolved_inputs[option] = paths
        missing.extend(str(path.relative_to(resolved_root)) for path in paths if not path.is_file())
    if missing:
        raise SumoPackageError("SUMO package references missing input files: " + ", ".join(missing))

    begin_time_ms = _time_ms(root, "begin", default=0.0)
    end_time_ms = _optional_end_time_ms(root)
    step_ms = _time_ms(root, "step-length", default=_DEFAULT_STEP_S)
    if step_ms <= 0:
        raise SumoPackageError("SUMO step-length must be greater than zero")
    if end_time_ms is not None and end_time_ms <= begin_time_ms:
        raise SumoPackageError("SUMO end time must be greater than begin time")

    package_name = package_id or directory.name
    all_input_paths = tuple(
        sorted({path for paths in resolved_inputs.values() for path in paths}, key=str)
    )
    optional_manifest = next(iter(sorted(directory.glob("*.manifest.json"))), None)
    manifest_spec = _manifest_spec(optional_manifest)
    tracked_paths = {resolved_config, *all_input_paths}
    if optional_manifest is not None:
        tracked_paths.add(optional_manifest.resolve())
    files = tuple(
        sorted(path.relative_to(directory).as_posix() for path in tracked_paths if path.is_file())
    )
    return SumoScenarioPackage(
        package_id=package_name,
        display_name=_display_name(manifest_spec, fallback=package_name),
        traffic_demand_mode=_traffic_demand_mode(manifest_spec),
        asset_root=resolved_root,
        directory=directory,
        config_path=resolved_config,
        network_path=resolved_inputs["net-file"][0],
        input_paths=all_input_paths,
        route_paths=resolved_inputs.get("route-files", ()),
        additional_paths=resolved_inputs.get("additional-files", ()),
        begin_time_ms=begin_time_ms,
        end_time_ms=end_time_ms,
        step_ms=step_ms,
        files=files,
        output_directories=_output_directories(root, resolved_inputs.get("additional-files", ())),
    )


def stage_sumo_package(package: SumoScenarioPackage, destination: Path) -> Path:
    """Copy immutable inputs into an experiment artifact tree and return its config path."""

    destination.mkdir(parents=True, exist_ok=True)
    sources = {
        path
        for path in package.directory.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(package.directory).parts)
    }
    sources.update(package.input_paths)
    sources.add(package.config_path)
    for source in sorted(sources, key=str):
        if source.is_relative_to(package.directory):
            package_relative = source.relative_to(package.directory)
            if any(
                package_relative.is_relative_to(output_directory)
                for output_directory in package.output_directories
            ):
                continue
        relative = source.relative_to(package.asset_root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    staged_config = destination / package.config_path.relative_to(package.asset_root)
    for output_directory in package.output_directories:
        (staged_config.parent / output_directory).mkdir(parents=True, exist_ok=True)
    return staged_config


def _input_file_values(root: ElementTree.Element) -> dict[str, tuple[str, ...]]:
    input_section = root.find("input")
    if input_section is None:
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for option in input_section:
        if not (option.tag.endswith("-file") or option.tag.endswith("-files")):
            continue
        value = option.attrib.get("value", "").strip()
        if value:
            result[option.tag] = tuple(item.strip() for item in value.split(",") if item.strip())
    return result


def _resolve_input_path(value: str, *, directory: Path, allowed_root: Path) -> Path:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (directory / candidate).resolve()
    _require_within(resolved, allowed_root, "SUMO input file")
    return resolved


def _require_within(path: Path, root: Path, description: str) -> None:
    if not path.is_relative_to(root):
        raise SumoPackageError(f"{description} escapes the configured SUMO package root")


def _time_ms(root: ElementTree.Element, name: str, *, default: float) -> int:
    option = root.find(f"time/{name}")
    raw = option.attrib.get("value") if option is not None else None
    try:
        value_s = default if raw is None else float(raw)
    except ValueError as error:
        raise SumoPackageError(f"invalid SUMO {name} value: {raw}") from error
    value_ms = value_s * 1000.0
    rounded = round(value_ms)
    if not math.isclose(value_ms, rounded, abs_tol=1e-6):
        raise SumoPackageError(f"SUMO {name} must resolve to a whole number of milliseconds")
    return rounded


def _optional_end_time_ms(root: ElementTree.Element) -> int | None:
    option = root.find("time/end")
    if option is None or "value" not in option.attrib:
        return None
    value = _time_ms(root, "end", default=-1.0)
    return value if value >= 0 else None


def _manifest_spec(manifest_path: Path | None) -> dict[str, object]:
    if manifest_path is None:
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SumoPackageError(f"invalid SUMO package manifest: {manifest_path.name}") from error
    if not isinstance(payload, dict):
        raise SumoPackageError("SUMO package manifest must be a JSON object")
    spec = payload.get("spec")
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise SumoPackageError("SUMO package manifest spec must be a JSON object")
    return spec


def _display_name(spec: dict[str, object], *, fallback: str) -> str:
    name = spec.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else fallback


def _traffic_demand_mode(
    spec: dict[str, object],
) -> Literal["generated", "scripted"]:
    value = spec.get("trafficDemandMode", "generated")
    if value == "generated":
        return "generated"
    if value == "scripted":
        return "scripted"
    raise SumoPackageError("SUMO package manifest trafficDemandMode must be generated or scripted")


def _output_directories(
    root: ElementTree.Element,
    additional_paths: tuple[Path, ...],
) -> tuple[Path, ...]:
    output_paths: set[Path] = set()
    output_section = root.find("output")
    if output_section is not None:
        for option in output_section:
            value = option.attrib.get("value", "").strip()
            if value:
                output_paths.add(Path(value))
    for path in additional_paths:
        try:
            additional = ElementTree.parse(path).getroot()
        except (OSError, ElementTree.ParseError):
            continue
        for element in additional.iter():
            if element.tag not in _OUTPUT_ELEMENTS:
                continue
            value = element.attrib.get("file", "").strip()
            if value:
                output_paths.add(Path(value))
    unsafe = tuple(path for path in output_paths if path.is_absolute() or ".." in path.parts)
    if unsafe:
        raise SumoPackageError("SUMO output paths must remain relative to the scenario package")
    directories = {path.parent for path in output_paths if path.parent != Path(".")}
    return tuple(sorted(directories, key=str))
