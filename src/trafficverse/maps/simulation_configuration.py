"""Materialize editable UI settings as immutable, runnable SUMO packages."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from trafficverse.domain.enums import AutomationLevel, ErrorCode, SimulationRunKind
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    SimulationConfigurationDraft,
    SimulationConfigurationSnapshot,
    SimulationRunInput,
)
from trafficverse.maps.sumo_package import (
    SumoScenarioPackage,
    load_sumo_package,
    stage_sumo_package,
)

_TIMESTAMP_PATTERN = re.compile(r"^\d{4}(?:-\d{2}){5}$")
_TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S"
_LEVELS = tuple(AutomationLevel(f"L{number}") for number in range(6))
_DEFAULT_VTYPE_ATTRIBUTES: dict[AutomationLevel, dict[str, str]] = {
    AutomationLevel.L0: {"color": "0,114,189", "minGap": "2.5", "sigma": "0.5", "tau": "1"},
    AutomationLevel.L1: {"color": "217,83,25", "minGap": "2", "sigma": "0.4", "tau": "0.95"},
    AutomationLevel.L2: {"color": "237,177,32", "minGap": "1.5", "sigma": "0.3", "tau": "0.9"},
    AutomationLevel.L3: {"color": "46,139,87", "minGap": "1.25", "sigma": "0.2", "tau": "0.8"},
    AutomationLevel.L4: {"color": "126,87,194", "minGap": "0.75", "sigma": "0", "tau": "0.7"},
    AutomationLevel.L5: {"color": "190,63,63", "minGap": "0.5", "sigma": "0", "tau": "0.6"},
}


class SumoSimulationConfigurationStore:
    """Filesystem-backed configuration store constrained to configured roots."""

    def __init__(
        self,
        *,
        package_resolver: Callable[[str], SumoScenarioPackage | None],
        configuration_root: Path,
        simulation_artifact_root: Path,
        test_artifact_root: Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._package_resolver = package_resolver
        self._configuration_root = configuration_root.resolve()
        self._artifact_roots = {
            SimulationRunKind.SIMULATION: simulation_artifact_root.resolve(),
            SimulationRunKind.TEST: test_artifact_root.resolve(),
        }
        self._now = now or (lambda: datetime.now().astimezone())

    def save(self, draft: SimulationConfigurationDraft) -> SimulationConfigurationSnapshot:
        package = self._package_resolver(draft.map_id)
        if package is None:
            raise TrafficVerseError(
                ErrorCode.MAP_ASSET_INVALID,
                f"SUMO scenario package is unavailable: {draft.map_id}",
            )
        saved_at, destination = self._available_timestamp_directory(self._configuration_root)
        destination.mkdir(parents=True)
        try:
            staged_config = stage_sumo_package(package, destination)
            staged_package = load_sumo_package(staged_config, allowed_root=destination)
            generated_route = (
                self._generate_route_file(staged_package, draft)
                if draft.automation_demands
                else None
            )
            self._update_sumo_configuration(
                staged_config,
                generated_route=generated_route,
                begin_time_ms=staged_package.begin_time_ms,
                duration_ms=draft.duration_ms,
                step_ms=staged_package.step_ms,
            )
            self._ensure_result_outputs(staged_config)
            self._write_metadata(
                destination,
                saved_at=saved_at,
                draft=draft,
                package=package,
                staged_config=staged_config,
            )
        except Exception:
            shutil.rmtree(destination)
            raise
        return SimulationConfigurationSnapshot(
            configuration_id=destination.name,
            map_id=package.package_id,
            map_name=package.display_name,
            relative_directory=f"configs/configs/{destination.name}",
        )

    def prepare_run(
        self,
        configuration_id: str,
        run_kind: SimulationRunKind,
        workspace_id: UUID,
        scenario_id: UUID,
        map_id: str | None,
    ) -> SimulationRunInput:
        source = self._configuration_directory(configuration_id)
        metadata = self._read_metadata(source)
        saved_workspace_id = UUID(self._metadata_scalar_text(metadata, "workspace_id"))
        saved_scenario_id = UUID(self._metadata_scalar_text(metadata, "scenario_id"))
        saved_map_id = self._metadata_text(metadata, "map", "id")
        if saved_workspace_id != workspace_id or saved_scenario_id != scenario_id:
            raise TrafficVerseError(
                ErrorCode.RESOURCE_CONFLICT,
                "saved simulation configuration does not belong to the requested context",
            )
        if map_id is not None and saved_map_id != map_id:
            raise TrafficVerseError(
                ErrorCode.RESOURCE_CONFLICT,
                "saved simulation configuration map does not match the request",
            )
        created_at, destination = self._available_timestamp_directory(
            self._artifact_roots[run_kind]
        )
        try:
            shutil.copytree(source, destination)
            config_relative = self._metadata_text(metadata, "sumo", "config_file")
            sumo_config_path = (destination / config_relative).resolve()
            self._require_within(sumo_config_path, destination, "saved SUMO configuration")
            package = load_sumo_package(sumo_config_path, allowed_root=destination)
            for output_directory in package.output_directories:
                (sumo_config_path.parent / output_directory).mkdir(parents=True, exist_ok=True)
            self._write_run_metadata(
                destination,
                created_at=created_at,
                configuration_id=configuration_id,
                run_kind=run_kind,
            )
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            raise
        return SimulationRunInput(
            configuration_id=configuration_id,
            run_id=destination.name,
            run_kind=run_kind,
            workspace_id=saved_workspace_id,
            scenario_id=saved_scenario_id,
            map_id=saved_map_id,
            directory=destination,
            sumo_config_path=sumo_config_path,
        )

    def _generate_route_file(
        self,
        package: SumoScenarioPackage,
        draft: SimulationConfigurationDraft,
    ) -> Path:
        vtypes: dict[str, ElementTree.Element] = {}
        routes: dict[str, ElementTree.Element] = {}
        for route_path in package.route_paths:
            try:
                root = ElementTree.parse(route_path).getroot()
            except (OSError, ElementTree.ParseError) as error:
                raise TrafficVerseError(
                    ErrorCode.SCENARIO_VALIDATION_FAILED,
                    f"cannot generate traffic from invalid route file: {route_path.name}",
                ) from error
            for element in root.findall("vType"):
                identifier = element.attrib.get("id")
                if identifier:
                    vtypes.setdefault(identifier, copy.deepcopy(element))
            for element in root.findall("route"):
                identifier = element.attrib.get("id")
                if identifier:
                    routes.setdefault(identifier, copy.deepcopy(element))

        total_vehicles = sum(item.vehicle_count for item in draft.automation_demands)
        if total_vehicles and not routes:
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                "SUMO route generation requires at least one named route definition",
            )
        generated_root = ElementTree.Element("routes")
        demanded_levels = {item.level for item in draft.automation_demands if item.vehicle_count}
        for level in _LEVELS:
            if level not in demanded_levels and level.value not in vtypes:
                continue
            generated_root.append(vtypes.get(level.value, self._default_vtype(level)))
        for element in routes.values():
            generated_root.append(element)

        route_ids = tuple(routes)
        vehicle_index = 0
        for demand in sorted(draft.automation_demands, key=lambda item: item.level.value):
            for level_index in range(demand.vehicle_count):
                depart_ms = package.begin_time_ms + (
                    vehicle_index * draft.duration_ms // total_vehicles
                )
                ElementTree.SubElement(
                    generated_root,
                    "vehicle",
                    {
                        "id": f"generated_{demand.level.value}_{level_index:06d}",
                        "type": demand.level.value,
                        "route": route_ids[vehicle_index % len(route_ids)],
                        "depart": _seconds_text(depart_ms),
                        "departLane": "best",
                        "departSpeed": "max",
                    },
                )
                vehicle_index += 1

        target = (
            package.route_paths[0]
            if len(package.route_paths) == 1
            else package.config_path.with_name(f"{package.config_path.stem}.generated.rou.xml")
        )
        ElementTree.indent(generated_root, space="  ")
        ElementTree.ElementTree(generated_root).write(
            target,
            encoding="utf-8",
            xml_declaration=True,
        )
        return target

    @staticmethod
    def _default_vtype(level: AutomationLevel) -> ElementTree.Element:
        return ElementTree.Element(
            "vType",
            {
                "id": level.value,
                "vClass": "passenger",
                "length": "5",
                "carFollowModel": "Krauss",
                "guiShape": "passenger",
                "accel": "2.6",
                "decel": "4.5",
                "maxSpeed": "22.22",
                **_DEFAULT_VTYPE_ATTRIBUTES[level],
            },
        )

    @staticmethod
    def _update_sumo_configuration(
        config_path: Path,
        *,
        generated_route: Path | None,
        begin_time_ms: int,
        duration_ms: int,
        step_ms: int,
    ) -> None:
        if duration_ms < step_ms or duration_ms % step_ms:
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                "simulation duration must be a positive multiple of the SUMO step",
            )
        tree = ElementTree.parse(config_path)
        root = tree.getroot()
        if generated_route is not None:
            input_section = root.find("input")
            if input_section is None:
                input_section = ElementTree.SubElement(root, "input")
            route_option = input_section.find("route-files")
            if route_option is None:
                route_option = ElementTree.SubElement(input_section, "route-files")
            route_relative = Path(os.path.relpath(generated_route, config_path.parent)).as_posix()
            route_option.set("value", route_relative)
        time_section = root.find("time")
        if time_section is None:
            time_section = ElementTree.SubElement(root, "time")
        end_option = time_section.find("end")
        if end_option is None:
            end_option = ElementTree.SubElement(time_section, "end")
        end_option.set("value", _seconds_text(begin_time_ms + duration_ms))
        ElementTree.indent(root, space="  ")
        tree.write(config_path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _ensure_result_outputs(config_path: Path) -> None:
        """Add the stable SUMO result set consumed by history and export."""
        tree = ElementTree.parse(config_path)
        root = tree.getroot()
        output = root.find("output")
        if output is None:
            output = ElementTree.SubElement(root, "output")
        for option_name, relative_path in (
            ("summary-output", "outputs/trafficverse-summary.xml"),
            ("tripinfo-output", "outputs/trafficverse-tripinfo.xml"),
            ("queue-output", "outputs/trafficverse-queue.xml"),
        ):
            option = output.find(option_name)
            if option is None:
                option = ElementTree.SubElement(output, option_name)
            option.set("value", relative_path)

        additional_path = config_path.with_name("trafficverse-results.add.xml")
        additional = ElementTree.Element("additional")
        ElementTree.SubElement(
            additional,
            "edgeData",
            {
                "id": "trafficverse_edge_results",
                "file": "outputs/trafficverse-edge-data.xml",
                "period": "10",
                "excludeEmpty": "defaults",
            },
        )
        ElementTree.SubElement(
            additional,
            "laneData",
            {
                "id": "trafficverse_lane_results",
                "file": "outputs/trafficverse-lane-data.xml",
                "period": "10",
                "excludeEmpty": "defaults",
            },
        )
        ElementTree.indent(additional, space="  ")
        ElementTree.ElementTree(additional).write(
            additional_path,
            encoding="utf-8",
            xml_declaration=True,
        )

        input_section = root.find("input")
        if input_section is None:
            input_section = ElementTree.SubElement(root, "input")
        additional_option = input_section.find("additional-files")
        if additional_option is None:
            additional_option = ElementTree.SubElement(input_section, "additional-files")
        values = [
            value.strip()
            for value in additional_option.attrib.get("value", "").split(",")
            if value.strip()
        ]
        relative = additional_path.name
        if relative not in values:
            values.append(relative)
        additional_option.set("value", ",".join(values))
        ElementTree.indent(root, space="  ")
        tree.write(config_path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _write_metadata(
        destination: Path,
        *,
        saved_at: datetime,
        draft: SimulationConfigurationDraft,
        package: SumoScenarioPackage,
        staged_config: Path,
    ) -> None:
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "configuration_id": destination.name,
            "saved_at": saved_at.isoformat(),
            "workspace_id": str(draft.workspace_id),
            "scenario_id": str(draft.scenario_id),
            "scene": {"name": draft.scene_name, "description": draft.description},
            "map": {"id": package.package_id, "name": package.display_name},
            "simulation": {"duration_ms": draft.duration_ms},
            "traffic_demand": [
                {
                    "automation_level": item.level.value,
                    "vehicle_count": item.vehicle_count,
                }
                for item in draft.automation_demands
            ],
            "sumo": {"config_file": staged_config.relative_to(destination).as_posix()},
        }
        _write_json(destination / "configuration.json", payload)

    @staticmethod
    def _write_run_metadata(
        destination: Path,
        *,
        created_at: datetime,
        configuration_id: str,
        run_kind: SimulationRunKind,
    ) -> None:
        _write_json(
            destination / "run.json",
            {
                "schema_version": "1.0",
                "run_id": destination.name,
                "configuration_id": configuration_id,
                "run_kind": run_kind.value,
                "created_at": created_at.isoformat(),
            },
        )

    def _configuration_directory(self, configuration_id: str) -> Path:
        if _TIMESTAMP_PATTERN.fullmatch(configuration_id) is None:
            raise TrafficVerseError(
                ErrorCode.CONFIGURATION_NOT_FOUND,
                "simulation configuration id is invalid",
            )
        directory = (self._configuration_root / configuration_id).resolve()
        self._require_within(directory, self._configuration_root, "simulation configuration")
        if not directory.is_dir():
            raise TrafficVerseError(
                ErrorCode.CONFIGURATION_NOT_FOUND,
                f"simulation configuration does not exist: {configuration_id}",
            )
        return directory

    def _available_timestamp_directory(self, root: Path) -> tuple[datetime, Path]:
        candidate_time = self._now()
        for offset_seconds in range(86_400):
            timestamp = candidate_time + timedelta(seconds=offset_seconds)
            candidate = root / timestamp.strftime(_TIMESTAMP_FORMAT)
            if not candidate.exists():
                return timestamp, candidate
        raise TrafficVerseError(
            ErrorCode.RESOURCE_CONFLICT,
            "no timestamp directory is available for the requested operation",
        )

    @staticmethod
    def _read_metadata(directory: Path) -> dict[str, object]:
        try:
            payload = json.loads((directory / "configuration.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                "saved simulation configuration metadata is invalid",
            ) from error
        if not isinstance(payload, dict):
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                "saved simulation configuration metadata must be an object",
            )
        return payload

    @staticmethod
    def _metadata_text(metadata: dict[str, object], section: str, field: str) -> str:
        section_value = metadata.get(section)
        value = section_value.get(field) if isinstance(section_value, dict) else None
        if not isinstance(value, str) or not value:
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                f"saved simulation configuration is missing {section}.{field}",
            )
        return value

    @staticmethod
    def _metadata_scalar_text(metadata: dict[str, object], field: str) -> str:
        value = metadata.get(field)
        if not isinstance(value, str) or not value:
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                f"saved simulation configuration is missing {field}",
            )
        return value

    @staticmethod
    def _require_within(path: Path, root: Path, description: str) -> None:
        if not path.is_relative_to(root.resolve()):
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                f"{description} escapes its allowed root",
            )


def _seconds_text(value_ms: int) -> str:
    seconds, milliseconds = divmod(value_ms, 1_000)
    return str(seconds) if not milliseconds else f"{seconds}.{milliseconds:03d}".rstrip("0")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
