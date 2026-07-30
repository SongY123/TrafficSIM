"""Safe YAML loading, environment overrides, hashing, and asset validation."""

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar, cast

import yaml
from pydantic import BaseModel, ValidationError

from trafficverse.config.models import (
    MapManifest,
    RuntimeBaseline,
    ScenarioConfig,
    SumoConfig,
)
from trafficverse.domain.enums import ErrorCode
from trafficverse.domain.errors import ConfigurationError

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_yaml_model(path: Path, model_type: type[ModelT]) -> ModelT:
    if not path.is_file():
        raise ConfigurationError(
            ErrorCode.CONFIGURATION_NOT_FOUND,
            f"configuration file does not exist: {path}",
            details={"path": str(path)},
        )
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigurationError(
            ErrorCode.SCENARIO_VALIDATION_FAILED,
            f"invalid YAML in {path}",
            details={"path": str(path), "reason": str(error)},
        ) from error
    if not isinstance(raw, Mapping):
        raise ConfigurationError(
            ErrorCode.SCENARIO_VALIDATION_FAILED,
            f"configuration root must be a mapping: {path}",
            details={"path": str(path)},
        )
    try:
        return model_type.model_validate(cast("Mapping[str, object]", raw))
    except ValidationError as error:
        raise ConfigurationError(
            ErrorCode.SCENARIO_VALIDATION_FAILED,
            f"configuration validation failed: {path}",
            details={"path": str(path), "reason": str(error)},
        ) from error


def load_runtime_baseline(path: Path) -> RuntimeBaseline:
    return _load_yaml_model(path, RuntimeBaseline)


def load_scenario(path: Path, *, apply_environment: bool = True) -> ScenarioConfig:
    scenario = _load_yaml_model(path, ScenarioConfig)
    if not apply_environment:
        return scenario

    sumo_host = os.getenv("TRAFFICVERSE_SUMO_HOST")
    sumo_port_value = os.getenv("TRAFFICVERSE_SUMO_PORT")
    sumo_updates: dict[str, object] = {}
    if sumo_host:
        sumo_updates["host"] = sumo_host
    if sumo_port_value:
        try:
            sumo_updates["port"] = int(sumo_port_value)
        except ValueError as error:
            raise ConfigurationError(
                ErrorCode.SCENARIO_VALIDATION_FAILED,
                "TRAFFICVERSE_SUMO_PORT must be an integer",
                details={"variable": "TRAFFICVERSE_SUMO_PORT"},
            ) from error

    if not sumo_updates:
        return scenario
    try:
        sumo = SumoConfig.model_validate(
            {**scenario.sumo.model_dump(mode="python"), **sumo_updates}
        )
    except ValidationError as error:
        raise ConfigurationError(
            ErrorCode.SCENARIO_VALIDATION_FAILED,
            "SUMO environment overrides are invalid",
            details={"reason": str(error)},
        ) from error
    return scenario.model_copy(update={"sumo": sumo})


def load_map_manifest(path: Path) -> MapManifest:
    return _load_yaml_model(path, MapManifest)


def configuration_hash(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_scenario_environment(scenario: ScenarioConfig, *, repository_root: Path) -> None:
    missing: dict[str, str] = {}
    sumo_config = _repository_path(repository_root, scenario.sumo.config_file)
    if not sumo_config.is_file():
        missing["sumo.config_file"] = str(sumo_config)
    traffic_assets: dict[str, Path] = {}
    for field in ("network", "routes", "signals"):
        asset = _repository_path(repository_root, str(getattr(scenario.traffic, field)))
        traffic_assets[field] = asset
        if not asset.is_file():
            missing[f"traffic.{field}"] = str(asset)
    manifest_candidates = (
        traffic_assets["network"].parent / "manifest.yaml",
        sumo_config.parent / "manifest.yaml",
    )
    manifest_path = next((path for path in manifest_candidates if path.is_file()), None)
    if manifest_path is None:
        missing["map.manifest"] = str(manifest_candidates[0])
    if missing:
        raise ConfigurationError(
            ErrorCode.CONFIGURATION_NOT_FOUND,
            "scenario references missing runtime assets",
            details=missing,
        )
    assert manifest_path is not None
    validate_map_manifest(
        manifest_path,
        expected_map_id=scenario.scenario.map_id,
        expected_sumo_version=scenario.sumo.expected_version,
    )


def _repository_path(repository_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repository_root / path


def validate_map_manifest(
    manifest_path: Path,
    *,
    expected_map_id: str | None = None,
    expected_network_schema_version: str = "traffic-network/1.0",
    expected_sumo_version: str | None = None,
) -> MapManifest:
    manifest = load_map_manifest(manifest_path)
    if not manifest.validated:
        raise ConfigurationError(
            ErrorCode.MAP_ASSET_INVALID,
            "map manifest is not marked as validated",
            details={"path": str(manifest_path)},
        )
    version_mismatches: dict[str, str] = {}
    if expected_map_id is not None and manifest.map_id != expected_map_id:
        version_mismatches["map"] = f"expected {expected_map_id}, found {manifest.map_id}"
    if manifest.network_schema_version != expected_network_schema_version:
        version_mismatches["traffic-network"] = (
            f"expected {expected_network_schema_version}, found {manifest.network_schema_version}"
        )
    if expected_sumo_version is not None and manifest.sumo_version != expected_sumo_version:
        version_mismatches["sumo"] = (
            f"expected {expected_sumo_version}, found {manifest.sumo_version}"
        )
    if version_mismatches:
        raise ConfigurationError(
            ErrorCode.VERSION_MISMATCH,
            "map manifest versions do not match the runtime baseline",
            details=version_mismatches,
        )

    checksum_errors: dict[str, str] = {}
    for relative_path, expected in manifest.files.items():
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            checksum_errors[relative_path] = "unsafe relative path"
            continue
        asset_path = manifest_path.parent / relative_path
        if not asset_path.is_file():
            checksum_errors[relative_path] = "missing"
            continue
        actual = f"sha256:{hashlib.sha256(asset_path.read_bytes()).hexdigest()}"
        if actual != expected:
            checksum_errors[relative_path] = f"expected {expected}, found {actual}"
    if checksum_errors:
        raise ConfigurationError(
            ErrorCode.MAP_ASSET_INVALID,
            "map asset checksum validation failed",
            details=checksum_errors,
        )
    return manifest
