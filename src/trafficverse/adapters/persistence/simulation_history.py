"""Filesystem adapter for formal SUMO simulation history and replay artifacts."""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ElementTree
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from trafficverse.domain.enums import ErrorCode, ExperimentStatus
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    SimulationHistoryDetail,
    SimulationHistorySummary,
    SimulationReplayFrame,
    SimulationReplayWindow,
    SimulationResultExport,
    SimulationResultMetric,
    SimulationResultTrend,
    SimulationRoadResult,
    SimulationTrendSample,
    TrafficLightState,
    VehicleState,
)
from trafficverse.maps.sumo_display import sumo_display_geojson
from trafficverse.maps.sumo_package import load_sumo_package

_RUN_ID = re.compile(r"^\d{4}(?:-\d{2}){5}$")
_ATTRIBUTE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)=\"([^\"]*)\"")
_STEP = re.compile(r"<step\s+([^>]*)/>")
_TERMINAL = frozenset({ExperimentStatus.COMPLETED, ExperimentStatus.FAILED})


class FileSimulationHistoryStore:
    """Read only direct child runs below ``artifacts/simulations``."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def list_runs(self, workspace_id: UUID | None = None) -> tuple[SimulationHistorySummary, ...]:
        if not self._root.is_dir():
            return ()
        summaries: list[SimulationHistorySummary] = []
        for directory in self._root.iterdir():
            if not directory.is_dir() or _RUN_ID.fullmatch(directory.name) is None:
                continue
            try:
                summary = self._summary(directory)
            except (OSError, ValueError, json.JSONDecodeError):
                summary = self._damaged_summary(directory)
            if workspace_id is None or summary.workspace_id in {None, workspace_id}:
                summaries.append(summary)
        return tuple(sorted(summaries, key=lambda item: item.created_at, reverse=True))

    def get_run(self, run_id: str) -> SimulationHistoryDetail:
        directory = self._directory(run_id)
        summary = self._summary(directory)
        steps = self._summary_steps(directory)
        trips = self._trip_rows(directory)
        metrics = self._metrics(steps, trips)
        trends = self._trends(steps)
        road_results = self._road_results(directory)
        return SimulationHistoryDetail(
            **summary.model_dump(),
            metrics=metrics,
            trends=trends,
            road_results=road_results,
        )

    def get_network(self, run_id: str) -> dict[str, object]:
        directory = self._directory(run_id)
        config_path = self._sumo_config_path(directory)
        package = load_sumo_package(config_path, allowed_root=directory)
        return sumo_display_geojson(package.network_path)

    def get_replay(
        self,
        run_id: str,
        *,
        from_time_ms: int,
        limit: int,
    ) -> SimulationReplayWindow:
        directory = self._directory(run_id)
        replay_directory = directory / "replay"
        frames_path = replay_directory / "frames.parquet"
        vehicles_path = replay_directory / "vehicle_states.parquet"
        lights_path = replay_directory / "traffic_light_states.parquet"
        if not self._replay_available(directory):
            raise TrafficVerseError(
                ErrorCode.RESOURCE_NOT_FOUND,
                f"structured replay is unavailable for simulation: {run_id}",
            )
        frames = self._parquet_rows(frames_path)
        vehicle_rows = self._rows_by_sequence(self._parquet_rows(vehicles_path))
        light_rows = self._rows_by_sequence(self._parquet_rows(lights_path))
        if not frames:
            return SimulationReplayWindow(run_id=run_id, frames=())

        frames.sort(key=lambda row: self._int(row["sequence"]))
        start_index = self._snapshot_start_index(frames, from_time_ms)
        vehicles: dict[str, VehicleState] = {}
        lights: dict[str, TrafficLightState] = {}
        output: list[SimulationReplayFrame] = []
        next_time_ms: int | None = None
        for index, frame_row in enumerate(frames[start_index:], start=start_index):
            sequence = self._int(frame_row["sequence"])
            simulation_time_ms = self._int(frame_row["simulation_time_ms"])
            if bool(frame_row["is_snapshot"]):
                vehicles.clear()
                lights.clear()
            self._apply_vehicle_rows(
                vehicles,
                vehicle_rows.get(sequence, ()),
                simulation_time_ms,
                sequence,
            )
            self._apply_light_rows(lights, light_rows.get(sequence, ()), simulation_time_ms)
            if simulation_time_ms < from_time_ms:
                continue
            if len(output) >= limit:
                next_time_ms = simulation_time_ms
                break
            output.append(
                SimulationReplayFrame(
                    simulation_time_ms=simulation_time_ms,
                    sequence=sequence,
                    vehicles=tuple(sorted(vehicles.values(), key=lambda item: item.vehicle_id)),
                    traffic_lights=tuple(sorted(lights.values(), key=lambda item: item.signal_id)),
                    collision_vehicle_ids=self._string_tuple(
                        frame_row.get("collision_vehicle_ids")
                    ),
                )
            )
            if index == len(frames) - 1:
                next_time_ms = None
        return SimulationReplayWindow(
            run_id=run_id,
            frames=tuple(output),
            next_time_ms=next_time_ms,
        )

    def export_run(self, run_id: str) -> SimulationResultExport:
        directory = self._directory(run_id)
        detail = self.get_run(run_id)
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(path for path in directory.rglob("*") if path.is_file()):
                resolved = path.resolve()
                if not resolved.is_relative_to(directory):
                    continue
                archive.write(resolved, resolved.relative_to(directory).as_posix())
            archive.writestr("export/summary.csv", self._summary_csv(detail))
            archive.writestr("export/trends.csv", self._trends_csv(detail.trends))
            archive.writestr("export/road_results.csv", self._roads_csv(detail.road_results))
        return SimulationResultExport(
            filename=f"trafficverse-simulation-{run_id}.zip",
            media_type="application/zip",
            payload=payload.getvalue(),
        )

    def _summary(self, directory: Path) -> SimulationHistorySummary:
        run = self._read_json(directory / "run.json")
        configuration = self._read_json(directory / "configuration.json")
        steps = self._summary_steps(directory)
        status = self._status(run, steps)
        created_at = self._datetime_value(run.get("created_at")) or self._run_id_time(
            directory.name
        )
        scene = self._mapping(configuration.get("scene"))
        map_value = self._mapping(configuration.get("map"))
        simulation = self._mapping(configuration.get("simulation"))
        simulation_time_ms = int(round(self._float(steps[-1].get("time")) * 1_000)) if steps else 0
        ended_at = self._datetime_value(run.get("ended_at"))
        if ended_at is None and status in _TERMINAL:
            ended_at = self._latest_result_time(directory)
        return SimulationHistorySummary(
            run_id=directory.name,
            workspace_id=self._uuid_value(configuration.get("workspace_id")),
            experiment_id=self._uuid_value(run.get("experiment_id")),
            status=status,
            status_reason=self._text(run.get("status_reason")),
            created_at=created_at,
            started_at=self._datetime_value(run.get("started_at")),
            ended_at=ended_at,
            scene_name=self._text(scene.get("name")) or "未命名场景",
            map_id=self._text(map_value.get("id")) or "unknown",
            map_name=self._text(map_value.get("name")) or "未知地图",
            configured_duration_ms=max(0, int(self._float(simulation.get("duration_ms")))),
            simulation_time_ms=max(0, simulation_time_ms),
            replay_available=self._replay_available(directory),
        )

    def _damaged_summary(self, directory: Path) -> SimulationHistorySummary:
        timestamp = self._run_id_time(directory.name)
        return SimulationHistorySummary(
            run_id=directory.name,
            status=ExperimentStatus.FAILED,
            status_reason="simulation artifact metadata is damaged",
            created_at=timestamp,
            ended_at=timestamp,
            scene_name="损坏的仿真记录",
            map_id="unknown",
            map_name="未知地图",
            configured_duration_ms=0,
            simulation_time_ms=0,
            replay_available=False,
        )

    @staticmethod
    def _metrics(
        steps: tuple[dict[str, str], ...], trips: tuple[dict[str, str], ...]
    ) -> tuple[SimulationResultMetric, ...]:
        last = steps[-1] if steps else {}
        speed_samples = [
            (speed, running)
            for row in steps
            if (speed := FileSimulationHistoryStore._optional_non_negative(row.get("meanSpeed")))
            is not None
            and (running := FileSimulationHistoryStore._optional_non_negative(row.get("running")))
            is not None
        ]
        speed_weight = sum(running for _, running in speed_samples)
        average_speed = (
            sum(speed * running for speed, running in speed_samples) / speed_weight
            if speed_weight
            else None
        )
        durations = [
            value
            for row in trips
            if (value := FileSimulationHistoryStore._optional_non_negative(row.get("duration")))
            is not None
        ]
        waiting_times = [
            value
            for row in trips
            if (value := FileSimulationHistoryStore._optional_non_negative(row.get("waitingTime")))
            is not None
        ]
        halting = [
            value
            for row in steps
            if (value := FileSimulationHistoryStore._optional_non_negative(row.get("halting")))
            is not None
        ]
        values: tuple[tuple[str, str, float | None, str, str], ...] = (
            (
                "vehicle_total",
                "车辆总数",
                FileSimulationHistoryStore._optional_non_negative(last.get("loaded")),
                "veh",
                "summary.loaded",
            ),
            (
                "completed_total",
                "完成行程车辆数",
                FileSimulationHistoryStore._optional_non_negative(last.get("arrived")),
                "veh",
                "summary.arrived",
            ),
            ("average_speed_mps", "平均速度", average_speed, "m/s", "summary.meanSpeed"),
            (
                "average_travel_time_s",
                "平均行程时间",
                sum(durations) / len(durations) if durations else None,
                "s",
                "tripinfo.duration",
            ),
            (
                "average_waiting_time_s",
                "平均等待时间",
                sum(waiting_times) / len(waiting_times) if waiting_times else None,
                "s",
                "tripinfo.waitingTime",
            ),
            (
                "average_queue_length_veh",
                "平均排队长度",
                sum(halting) / len(halting) if halting else None,
                "veh",
                "summary.halting",
            ),
            (
                "maximum_queue_length_veh",
                "最大排队长度",
                max(halting, default=None),
                "veh",
                "summary.halting",
            ),
        )
        return tuple(
            SimulationResultMetric(
                key=cast("object", key), label=label, value=value, unit=unit, source=source
            )
            for key, label, value, unit, source in values
        )

    @staticmethod
    def _trends(steps: tuple[dict[str, str], ...]) -> tuple[SimulationResultTrend, ...]:
        definitions = (
            ("vehicle_count", "车辆数量变化", "veh", "running"),
            ("average_speed_mps", "平均速度变化", "m/s", "meanSpeed"),
            ("queue_length_veh", "排队车辆数量变化", "veh", "halting"),
            ("average_waiting_time_s", "平均等待时间变化", "s", "meanWaitingTime"),
            ("completed_total", "完成行程车辆数变化", "veh", "arrived"),
        )
        return tuple(
            SimulationResultTrend(
                key=cast("object", key),
                label=label,
                unit=unit,
                samples=tuple(
                    SimulationTrendSample(
                        simulation_time_ms=max(
                            0,
                            int(round(FileSimulationHistoryStore._float(row.get("time")) * 1_000)),
                        ),
                        value=max(0.0, FileSimulationHistoryStore._float(row.get(attribute))),
                    )
                    for row in steps
                    if "time" in row and attribute in row
                ),
            )
            for key, label, unit, attribute in definitions
        )

    def _road_results(self, directory: Path) -> tuple[SimulationRoadResult, ...]:
        accumulators: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        edge_path = self._result_file(directory, "*edgeData*.xml", "*edge-data*.xml")
        if edge_path is not None:
            root = self._parse_complete_xml(edge_path)
            if root is not None:
                for interval in root.findall("interval"):
                    interval_duration = max(
                        0.0,
                        self._float(interval.attrib.get("end"))
                        - self._float(interval.attrib.get("begin")),
                    )
                    for edge in interval.findall("edge"):
                        edge_id = edge.attrib.get("id")
                        if not edge_id:
                            continue
                        sampled = max(0.0, self._float(edge.attrib.get("sampledSeconds")))
                        bucket = accumulators[edge_id]
                        if sampled and "speed" in edge.attrib:
                            speed = max(0.0, self._float(edge.attrib["speed"]))
                            bucket["speed_sum"] += speed * sampled
                            bucket["speed_sampled"] += sampled
                        if sampled and "speedRelative" in edge.attrib:
                            relative = min(
                                1.0,
                                max(0.0, self._float(edge.attrib["speedRelative"])),
                            )
                            bucket["congestion_sum"] += (1.0 - relative) * sampled
                            bucket["congestion_sampled"] += sampled
                        if interval_duration and "flow" in edge.attrib:
                            bucket["flow_sum"] += (
                                max(0.0, self._float(edge.attrib["flow"])) * interval_duration
                            )
                            bucket["flow_duration"] += interval_duration
        self._append_queue_results(directory, accumulators)
        return tuple(
            SimulationRoadResult(
                edge_id=edge_id,
                average_speed_mps=(
                    bucket["speed_sum"] / bucket["speed_sampled"]
                    if bucket["speed_sampled"]
                    else None
                ),
                congestion_ratio=(
                    bucket["congestion_sum"] / bucket["congestion_sampled"]
                    if bucket["congestion_sampled"]
                    else None
                ),
                traffic_flow_veh_per_hour=(
                    bucket["flow_sum"] / bucket["flow_duration"]
                    if bucket["flow_duration"]
                    else None
                ),
                queue_length_m=bucket.get("queue_max"),
            )
            for edge_id, bucket in sorted(accumulators.items())
        )

    def _append_queue_results(
        self,
        directory: Path,
        accumulators: dict[str, dict[str, float]],
    ) -> None:
        queue_path = self._result_file(directory, "*queue*.xml")
        if queue_path is None:
            return
        root = self._parse_complete_xml(queue_path)
        if root is None:
            return
        package = load_sumo_package(self._sumo_config_path(directory), allowed_root=directory)
        network = ElementTree.parse(package.network_path).getroot()
        lane_edges = {
            lane.attrib["id"]: edge.attrib["id"]
            for edge in network.findall("edge")
            for lane in edge.findall("lane")
            if "id" in lane.attrib and "id" in edge.attrib
        }
        for lane in root.iter("lane"):
            edge_id = lane_edges.get(lane.attrib.get("id", ""))
            if edge_id is None:
                continue
            queue_length = max(
                0.0,
                self._float(
                    lane.attrib.get("queueing_length_experimental")
                    or lane.attrib.get("queueing_length")
                ),
            )
            accumulators[edge_id]["queue_max"] = max(
                accumulators[edge_id].get("queue_max", 0.0), queue_length
            )

    def _summary_steps(self, directory: Path) -> tuple[dict[str, str], ...]:
        path = self._result_file(directory, "*summary*.xml")
        if path is None:
            return ()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ()
        return tuple(dict(_ATTRIBUTE.findall(match.group(1))) for match in _STEP.finditer(text))

    def _trip_rows(self, directory: Path) -> tuple[dict[str, str], ...]:
        path = self._result_file(directory, "*tripinfo*.xml")
        if path is None:
            return ()
        root = self._parse_complete_xml(path)
        return tuple(dict(element.attrib) for element in root.findall("tripinfo")) if root else ()

    def _sumo_config_path(self, directory: Path) -> Path:
        configuration = self._read_json(directory / "configuration.json")
        sumo = self._mapping(configuration.get("sumo"))
        relative = self._text(sumo.get("config_file"))
        if relative is None:
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                f"simulation configuration is missing SUMO input: {directory.name}",
            )
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                f"simulation SUMO input is unavailable: {directory.name}",
            )
        return path

    def _directory(self, run_id: str) -> Path:
        if _RUN_ID.fullmatch(run_id) is None:
            raise TrafficVerseError(ErrorCode.RESOURCE_NOT_FOUND, "simulation run id is invalid")
        directory = (self._root / run_id).resolve()
        if not directory.is_relative_to(self._root) or not directory.is_dir():
            raise TrafficVerseError(
                ErrorCode.RESOURCE_NOT_FOUND, f"simulation run does not exist: {run_id}"
            )
        return directory

    def _replay_available(self, directory: Path) -> bool:
        replay_directory = directory / "replay"
        required = (
            replay_directory / "frames.parquet",
            replay_directory / "vehicle_states.parquet",
            replay_directory / "traffic_light_states.parquet",
        )
        manifest_path = replay_directory / "manifest.json"
        if not manifest_path.is_file() or not all(path.is_file() for path in required):
            return False
        try:
            manifest = self._read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return (
            manifest.get("schema_version") == "1.0"
            and manifest.get("format") == "snapshot-delta-parquet"
            and manifest.get("complete") is True
        )

    @staticmethod
    def _status(run: Mapping[str, object], steps: tuple[dict[str, str], ...]) -> ExperimentStatus:
        value = run.get("status")
        if isinstance(value, str):
            try:
                return ExperimentStatus(value)
            except ValueError:
                return ExperimentStatus.FAILED
        return ExperimentStatus.COMPLETED if steps else ExperimentStatus.CREATED

    @staticmethod
    def _snapshot_start_index(frames: list[dict[str, object]], from_time_ms: int) -> int:
        index = 0
        for candidate, row in enumerate(frames):
            if FileSimulationHistoryStore._int(row["simulation_time_ms"]) > from_time_ms:
                break
            if bool(row["is_snapshot"]):
                index = candidate
        return index

    @staticmethod
    def _rows_by_sequence(
        rows: Iterable[dict[str, object]],
    ) -> dict[int, tuple[dict[str, object], ...]]:
        grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            grouped[FileSimulationHistoryStore._int(row["sequence"])].append(row)
        return {sequence: tuple(values) for sequence, values in grouped.items()}

    @staticmethod
    def _apply_vehicle_rows(
        state: dict[str, VehicleState],
        rows: Iterable[dict[str, object]],
        simulation_time_ms: int,
        sequence: int,
    ) -> None:
        for row in rows:
            vehicle_id = str(row["vehicle_id"])
            if row["record_kind"] == "REMOVE":
                state.pop(vehicle_id, None)
                continue
            state[vehicle_id] = VehicleState.model_validate(
                {
                    "experiment_id": row["experiment_id"],
                    "vehicle_id": vehicle_id,
                    "simulation_time_ms": simulation_time_ms,
                    "sequence": sequence,
                    "automation_level": row["automation_level"],
                    "position": {"x": row["x_m"], "y": row["y_m"], "z": row["z_m"]},
                    "speed_mps": row["speed_mps"],
                    "acceleration_mps2": row["acceleration_mps2"],
                    "heading_rad": row["heading_rad"],
                    "lane_id": row["lane_id"],
                    "target_lane_id": row["target_lane_id"],
                    "controller_id": row["controller_id"],
                    "action": row["action"],
                    "risk_score": row["risk_score"],
                    "route_id": row["route_id"],
                }
            )

    @staticmethod
    def _apply_light_rows(
        state: dict[str, TrafficLightState],
        rows: Iterable[dict[str, object]],
        simulation_time_ms: int,
    ) -> None:
        for row in rows:
            signal_id = str(row["signal_id"])
            if row["record_kind"] == "REMOVE":
                state.pop(signal_id, None)
                continue
            state[signal_id] = TrafficLightState(
                signal_id=signal_id,
                simulation_time_ms=simulation_time_ms,
                phase=str(row["phase"]),
                remaining_ms=(
                    FileSimulationHistoryStore._int(row["remaining_ms"])
                    if row["remaining_ms"] is not None
                    else None
                ),
            )

    @staticmethod
    def _parquet_rows(path: Path) -> list[dict[str, object]]:
        try:
            import pyarrow.parquet as parquet  # type: ignore[import-untyped]
        except ImportError as error:  # pragma: no cover - dependency is required in production
            raise TrafficVerseError(
                ErrorCode.COMPONENT_UNAVAILABLE,
                "Parquet replay support is not installed",
            ) from error
        # ``to_pylist`` is the third-party untyped boundary; rows are narrowed immediately.
        raw_rows = parquet.read_table(path).to_pylist()
        if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
            raise TrafficVerseError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                f"invalid replay parquet rows: {path.name}",
            )
        return [cast("dict[str, object]", row) for row in raw_rows]

    @staticmethod
    def _summary_csv(detail: SimulationHistoryDetail) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("key", "label", "value", "unit", "source"))
        for metric in detail.metrics:
            writer.writerow((metric.key, metric.label, metric.value, metric.unit, metric.source))
        return output.getvalue()

    @staticmethod
    def _trends_csv(trends: tuple[SimulationResultTrend, ...]) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("key", "label", "simulation_time_ms", "value", "unit"))
        for trend in trends:
            for sample in trend.samples:
                writer.writerow(
                    (trend.key, trend.label, sample.simulation_time_ms, sample.value, trend.unit)
                )
        return output.getvalue()

    @staticmethod
    def _roads_csv(roads: tuple[SimulationRoadResult, ...]) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            (
                "edge_id",
                "average_speed_mps",
                "congestion_ratio",
                "traffic_flow_veh_per_hour",
                "queue_length_m",
            )
        )
        for road in roads:
            writer.writerow(
                (
                    road.edge_id,
                    road.average_speed_mps,
                    road.congestion_ratio,
                    road.traffic_flow_veh_per_hour,
                    road.queue_length_m,
                )
            )
        return output.getvalue()

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"JSON document must be an object: {path.name}")
        return cast("dict[str, object]", payload)

    @staticmethod
    def _parse_complete_xml(path: Path) -> ElementTree.Element | None:
        try:
            return ElementTree.parse(path).getroot()
        except (OSError, ElementTree.ParseError):
            return None

    @staticmethod
    def _result_file(directory: Path, *patterns: str) -> Path | None:
        for pattern in patterns:
            matches = sorted(directory.rglob(pattern))
            if matches:
                return matches[0]
        return None

    @staticmethod
    def _latest_result_time(directory: Path) -> datetime:
        files = tuple(path for path in directory.rglob("*") if path.is_file())
        timestamp = max((path.stat().st_mtime for path in files), default=directory.stat().st_mtime)
        return datetime.fromtimestamp(timestamp).astimezone()

    @staticmethod
    def _run_id_time(run_id: str) -> datetime:
        return datetime.strptime(run_id, "%Y-%m-%d-%H-%M-%S").astimezone()

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _string_tuple(value: object) -> tuple[str, ...]:
        return (
            tuple(item for item in value if isinstance(item, str))
            if isinstance(value, list)
            else ()
        )

    @staticmethod
    def _text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _datetime_value(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.astimezone()

    @staticmethod
    def _uuid_value(value: object) -> UUID | None:
        try:
            return UUID(str(value)) if value is not None else None
        except ValueError:
            return None

    @staticmethod
    def _float(value: object) -> float:
        if not isinstance(value, (str, int, float)):
            return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0

    @staticmethod
    def _int(value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, (str, float)):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _optional_non_negative(value: object) -> float | None:
        if not isinstance(value, (str, int, float)):
            return None
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if parsed >= 0.0 else None
