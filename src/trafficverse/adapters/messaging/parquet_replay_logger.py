"""Parquet snapshot/delta logger for deterministic simulation replay."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as parquet  # type: ignore[import-untyped]

from trafficverse.domain.models import DomainEvent, SimulationFrame, TrafficLightState, VehicleState

_FRAME_SCHEMA = pa.schema(
    (
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("experiment_id", pa.string(), nullable=False),
        pa.field("simulation_time_ms", pa.int64(), nullable=False),
        pa.field("sequence", pa.int64(), nullable=False),
        pa.field("is_snapshot", pa.bool_(), nullable=False),
        pa.field("vehicle_count", pa.int32(), nullable=False),
        pa.field("average_speed_mps", pa.float64(), nullable=False),
        pa.field("halting_vehicle_count", pa.int32(), nullable=False),
        pa.field("collision_vehicle_ids", pa.list_(pa.string()), nullable=False),
    )
)
_VEHICLE_SCHEMA = pa.schema(
    (
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("record_kind", pa.string(), nullable=False),
        pa.field("experiment_id", pa.string(), nullable=False),
        pa.field("simulation_time_ms", pa.int64(), nullable=False),
        pa.field("sequence", pa.int64(), nullable=False),
        pa.field("vehicle_id", pa.string(), nullable=False),
        pa.field("automation_level", pa.string()),
        pa.field("x_m", pa.float64()),
        pa.field("y_m", pa.float64()),
        pa.field("z_m", pa.float64()),
        pa.field("speed_mps", pa.float64()),
        pa.field("acceleration_mps2", pa.float64()),
        pa.field("heading_rad", pa.float64()),
        pa.field("lane_id", pa.string()),
        pa.field("target_lane_id", pa.string()),
        pa.field("controller_id", pa.string()),
        pa.field("action", pa.string()),
        pa.field("risk_score", pa.float64()),
        pa.field("route_id", pa.string()),
    )
)
_LIGHT_SCHEMA = pa.schema(
    (
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("record_kind", pa.string(), nullable=False),
        pa.field("simulation_time_ms", pa.int64(), nullable=False),
        pa.field("sequence", pa.int64(), nullable=False),
        pa.field("signal_id", pa.string(), nullable=False),
        pa.field("phase", pa.string()),
        pa.field("remaining_ms", pa.int64()),
    )
)


class ParquetReplayDataLogger:
    """Record bounded-frequency snapshots and deltas under one run directory."""

    def __init__(
        self,
        run_directory: Path,
        *,
        trajectory_hz: int,
        parquet_batch_rows: int,
        snapshot_interval_ms: int,
    ) -> None:
        if trajectory_hz <= 0 or parquet_batch_rows <= 0 or snapshot_interval_ms <= 0:
            raise ValueError("replay logger intervals and batch size must be positive")
        self._directory = run_directory.resolve() / "replay"
        self._directory.mkdir(parents=True, exist_ok=True)
        self._sample_interval_ms = max(1, round(1_000 / trajectory_hz))
        self._batch_rows = parquet_batch_rows
        self._snapshot_interval_ms = snapshot_interval_ms
        self._next_sample_ms: int | None = None
        self._next_snapshot_ms: int | None = None
        self._previous_vehicles: dict[str, dict[str, object]] = {}
        self._previous_lights: dict[str, dict[str, object]] = {}
        self._frame_rows: list[dict[str, object]] = []
        self._vehicle_rows: list[dict[str, object]] = []
        self._light_rows: list[dict[str, object]] = []
        # PyArrow does not publish typing metadata; Any stays at this adapter boundary.
        self._writers: dict[str, Any] = {}
        self._flushed = False
        self._frame_count = 0

    async def record_frame(self, frame: SimulationFrame) -> None:
        if self._flushed:
            raise RuntimeError("cannot append replay frames after the logger was flushed")
        snapshot = frame.traffic
        simulation_time_ms = snapshot.simulation_time_ms
        if self._next_sample_ms is not None and simulation_time_ms < self._next_sample_ms:
            return
        self._next_sample_ms = simulation_time_ms + self._sample_interval_ms
        is_snapshot = self._next_snapshot_ms is None or simulation_time_ms >= self._next_snapshot_ms
        if is_snapshot:
            self._next_snapshot_ms = simulation_time_ms + self._snapshot_interval_ms
        vehicles = {
            vehicle.vehicle_id: self._vehicle_payload(vehicle) for vehicle in snapshot.vehicles
        }
        lights = {light.signal_id: self._light_payload(light) for light in snapshot.traffic_lights}
        speeds = tuple(vehicle.speed_mps for vehicle in snapshot.vehicles)
        self._frame_rows.append(
            {
                "schema_version": "1.0",
                "experiment_id": str(snapshot.experiment_id),
                "simulation_time_ms": simulation_time_ms,
                "sequence": snapshot.sequence,
                "is_snapshot": is_snapshot,
                "vehicle_count": len(vehicles),
                "average_speed_mps": sum(speeds) / len(speeds) if speeds else 0.0,
                "halting_vehicle_count": sum(speed < 0.1 for speed in speeds),
                "collision_vehicle_ids": sorted(snapshot.collision_vehicle_ids),
            }
        )
        self._append_vehicle_records(frame, vehicles, is_snapshot)
        self._append_light_records(frame, lights, is_snapshot)
        self._previous_vehicles = vehicles
        self._previous_lights = lights
        self._frame_count += 1
        if self._has_full_buffer():
            await asyncio.to_thread(self._flush_full_buffers)

    async def record_event(self, event: DomainEvent) -> None:
        if self._flushed:
            raise RuntimeError("cannot append replay events after the logger was flushed")
        await asyncio.to_thread(self._append_event, event)

    def _append_event(self, event: DomainEvent) -> None:
        path = self._directory / "events.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.model_dump_json() + "\n")

    async def flush(self) -> None:
        if self._flushed:
            return
        await asyncio.to_thread(self._flush_sync)

    def _flush_sync(self) -> None:
        self._write_rows("frames.parquet", _FRAME_SCHEMA, self._frame_rows)
        self._write_rows("vehicle_states.parquet", _VEHICLE_SCHEMA, self._vehicle_rows)
        self._write_rows("traffic_light_states.parquet", _LIGHT_SCHEMA, self._light_rows)
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()
        self._flushed = True
        self._write_manifest()

    def _has_full_buffer(self) -> bool:
        return any(
            len(rows) >= self._batch_rows
            for rows in (self._frame_rows, self._vehicle_rows, self._light_rows)
        )

    def _append_vehicle_records(
        self,
        frame: SimulationFrame,
        vehicles: dict[str, dict[str, object]],
        is_snapshot: bool,
    ) -> None:
        snapshot = frame.traffic
        selected = (
            vehicles
            if is_snapshot
            else {
                vehicle_id: payload
                for vehicle_id, payload in vehicles.items()
                if self._previous_vehicles.get(vehicle_id) != payload
            }
        )
        for vehicle_id, payload in selected.items():
            self._vehicle_rows.append(
                {
                    "schema_version": "1.0",
                    "record_kind": "SNAPSHOT" if is_snapshot else "UPSERT",
                    "experiment_id": str(snapshot.experiment_id),
                    "simulation_time_ms": snapshot.simulation_time_ms,
                    "sequence": snapshot.sequence,
                    "vehicle_id": vehicle_id,
                    **payload,
                }
            )
        if not is_snapshot:
            for vehicle_id in sorted(self._previous_vehicles.keys() - vehicles.keys()):
                self._vehicle_rows.append(
                    self._vehicle_removal_row(
                        experiment_id=str(snapshot.experiment_id),
                        simulation_time_ms=snapshot.simulation_time_ms,
                        sequence=snapshot.sequence,
                        vehicle_id=vehicle_id,
                    )
                )

    def _append_light_records(
        self,
        frame: SimulationFrame,
        lights: dict[str, dict[str, object]],
        is_snapshot: bool,
    ) -> None:
        snapshot = frame.traffic
        selected = (
            lights
            if is_snapshot
            else {
                signal_id: payload
                for signal_id, payload in lights.items()
                if self._previous_lights.get(signal_id) != payload
            }
        )
        for signal_id, payload in selected.items():
            self._light_rows.append(
                {
                    "schema_version": "1.0",
                    "record_kind": "SNAPSHOT" if is_snapshot else "UPSERT",
                    "simulation_time_ms": snapshot.simulation_time_ms,
                    "sequence": snapshot.sequence,
                    "signal_id": signal_id,
                    **payload,
                }
            )
        if not is_snapshot:
            for signal_id in sorted(self._previous_lights.keys() - lights.keys()):
                self._light_rows.append(
                    {
                        "schema_version": "1.0",
                        "record_kind": "REMOVE",
                        "simulation_time_ms": snapshot.simulation_time_ms,
                        "sequence": snapshot.sequence,
                        "signal_id": signal_id,
                        "phase": None,
                        "remaining_ms": None,
                    }
                )

    def _flush_full_buffers(self) -> None:
        buffers = (
            ("frames.parquet", _FRAME_SCHEMA, self._frame_rows),
            ("vehicle_states.parquet", _VEHICLE_SCHEMA, self._vehicle_rows),
            ("traffic_light_states.parquet", _LIGHT_SCHEMA, self._light_rows),
        )
        for filename, schema, rows in buffers:
            if len(rows) >= self._batch_rows:
                self._write_rows(filename, schema, rows)

    def _write_rows(
        self,
        filename: str,
        schema: Any,
        rows: list[dict[str, object]],
    ) -> None:
        if not rows:
            if filename not in self._writers:
                writer = parquet.ParquetWriter(self._directory / filename, schema)
                self._writers[filename] = writer
            return
        writer = self._writers.get(filename)
        if writer is None:
            writer = parquet.ParquetWriter(self._directory / filename, schema)
            self._writers[filename] = writer
        writer.write_table(pa.Table.from_pylist(rows, schema=schema))
        rows.clear()

    def _write_manifest(self) -> None:
        files = tuple(
            name
            for name in (
                "frames.parquet",
                "vehicle_states.parquet",
                "traffic_light_states.parquet",
                "events.jsonl",
            )
            if (self._directory / name).is_file()
        )
        payload = {
            "schema_version": "1.0",
            "format": "snapshot-delta-parquet",
            "complete": True,
            "frame_count": self._frame_count,
            "sample_interval_ms": self._sample_interval_ms,
            "snapshot_interval_ms": self._snapshot_interval_ms,
            "files": {name: self._checksum(self._directory / name) for name in files},
        }
        manifest = self._directory / "manifest.json"
        temporary = manifest.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(manifest)

    @staticmethod
    def _vehicle_payload(vehicle: VehicleState) -> dict[str, object]:
        return {
            "automation_level": vehicle.automation_level.value,
            "x_m": vehicle.position.x,
            "y_m": vehicle.position.y,
            "z_m": vehicle.position.z,
            "speed_mps": vehicle.speed_mps,
            "acceleration_mps2": vehicle.acceleration_mps2,
            "heading_rad": vehicle.heading_rad,
            "lane_id": vehicle.lane_id,
            "target_lane_id": vehicle.target_lane_id,
            "controller_id": vehicle.controller_id,
            "action": vehicle.action.value,
            "risk_score": vehicle.risk_score,
            "route_id": vehicle.route_id,
        }

    @staticmethod
    def _light_payload(light: TrafficLightState) -> dict[str, object]:
        return {"phase": light.phase, "remaining_ms": light.remaining_ms}

    @staticmethod
    def _vehicle_removal_row(
        *,
        experiment_id: str,
        simulation_time_ms: int,
        sequence: int,
        vehicle_id: str,
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "record_kind": "REMOVE",
            "experiment_id": experiment_id,
            "simulation_time_ms": simulation_time_ms,
            "sequence": sequence,
            "vehicle_id": vehicle_id,
            "automation_level": None,
            "x_m": None,
            "y_m": None,
            "z_m": None,
            "speed_mps": None,
            "acceleration_mps2": None,
            "heading_rad": None,
            "lane_id": None,
            "target_lane_id": None,
            "controller_id": None,
            "action": None,
            "risk_score": None,
            "route_id": None,
        }

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"
