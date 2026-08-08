"""Pydantic models for runtime, scenario, and map configuration."""

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from trafficverse.domain.enums import AutomationLevel, RequirementMode
from trafficverse.domain.models.common import StrictModel


class ComponentRequirement(StrictModel):
    mode: RequirementMode
    version: str | None = Field(default=None, min_length=1)


class RuntimeProfile(StrictModel):
    operating_system: Literal["Darwin", "Linux", "Windows"]
    architectures: tuple[str, ...] = Field(min_length=1)
    python_version: str = Field(pattern=r"^\d+\.\d+$")
    carla: ComponentRequirement
    sumo: ComponentRequirement
    native_window: ComponentRequirement
    postgres: ComponentRequirement


class RuntimeBaseline(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    default_profile: str = Field(min_length=1)
    profiles: dict[str, RuntimeProfile] = Field(min_length=1)

    @model_validator(mode="after")
    def default_profile_must_exist_or_be_auto(self) -> "RuntimeBaseline":
        if self.default_profile != "auto" and self.default_profile not in self.profiles:
            raise ValueError("default_profile must be 'auto' or name an existing profile")
        return self


class ScenarioIdentityConfig(StrictModel):
    name: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    seed: int = Field(ge=0)


class SimulationConfig(StrictModel):
    start_time_ms: int = Field(default=0, ge=0)
    step_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    speed_multiplier: float = Field(gt=0.0)

    @model_validator(mode="after")
    def duration_must_contain_whole_steps(self) -> "SimulationConfig":
        if self.duration_ms % self.step_ms != 0:
            raise ValueError("duration_ms must be an integer multiple of step_ms")
        return self


class TrafficConfig(StrictModel):
    network: str = Field(min_length=1)
    routes: str = Field(min_length=1)
    signals: str = Field(min_length=1)
    vehicles: int = Field(gt=0)


class SumoConfig(StrictModel):
    """SUMO/TraCI endpoint or managed local process used as the traffic truth source."""

    provider: Literal["sumo"] = "sumo"
    launch_mode: Literal["external", "managed"] = "external"
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8813, ge=1, le=65535)
    step_ms: int = Field(default=50, gt=0)
    begin_time_ms: int = Field(default=0, ge=0)
    tls_manager: Literal["sumo"] = "sumo"
    config_file: str = Field(min_length=1)
    expected_version: str | None = Field(default=None, min_length=1)
    connect_retries: int = Field(default=3, ge=0, le=100)
    binary: str = Field(default="sumo", min_length=1)
    output_directory: str | None = Field(default=None, min_length=1)
    freeze_collisions: bool = False


class CarlaViewConfig(StrictModel):
    mode: Literal["native_window"] = "native_window"
    native_window_id_env: str = Field(
        default="TRAFFICVERSE_CARLA_WINDOW_ID",
        pattern=r"^[A-Z][A-Z0-9_]+$",
    )


class UiConfig(StrictModel):
    api_url: str = Field(default="http://127.0.0.1:8000", min_length=1)
    carla_view: CarlaViewConfig = Field(default_factory=CarlaViewConfig)


class AutomationConfig(StrictModel):
    proportions: dict[AutomationLevel, float]

    @field_validator("proportions")
    @classmethod
    def proportions_must_cover_all_levels_and_sum_to_one(
        cls, value: dict[AutomationLevel, float]
    ) -> dict[AutomationLevel, float]:
        missing = set(AutomationLevel) - set(value)
        if missing:
            names = ", ".join(sorted(level.value for level in missing))
            raise ValueError(f"automation proportions are missing levels: {names}")
        if any(proportion < 0.0 or proportion > 1.0 for proportion in value.values()):
            raise ValueError("automation proportions must be between 0 and 1")
        if not math.isclose(sum(value.values()), 1.0, abs_tol=1e-9):
            raise ValueError("automation proportions must sum to 1.0")
        return value


class RoiFocusConfig(StrictModel):
    mode: Literal["fixed", "follow_vehicle"]
    x: float | None = None
    y: float | None = None
    vehicle_id: str | None = None

    @model_validator(mode="after")
    def fields_must_match_focus_mode(self) -> "RoiFocusConfig":
        if self.mode == "fixed" and (self.x is None or self.y is None):
            raise ValueError("fixed ROI focus requires x and y")
        if self.mode == "follow_vehicle" and not self.vehicle_id:
            raise ValueError("follow_vehicle ROI focus requires vehicle_id")
        return self


class RoiConfig(StrictModel):
    radius_m: float = Field(gt=0.0)
    buffer_m: float = Field(gt=0.0)
    max_actors: int = Field(default=200, gt=0)
    focus: RoiFocusConfig


class CarlaConfig(StrictModel):
    mode: RequirementMode
    endpoint_mode: Literal["local_server"] = "local_server"
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    timeout_s: float = Field(gt=0.0)
    expected_version: str = Field(min_length=1)
    step_ms: int = Field(default=50, gt=0)
    worker_threads: int = Field(default=0, ge=0)
    blueprint_filter: str = Field(default="vehicle.*", min_length=1)
    fallback_blueprints: tuple[str, ...] = Field(
        default=("vehicle.tesla.model3", "vehicle.audi.tt"),
        min_length=1,
    )
    spawn_retries: int = Field(default=2, ge=0, le=10)

    @field_validator("fallback_blueprints")
    @classmethod
    def fallback_blueprints_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not blueprint for blueprint in value):
            raise ValueError("fallback blueprint IDs must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("fallback blueprint IDs must be unique")
        return value


class WeatherConfig(StrictModel):
    preset: str = Field(min_length=1)


class MapRegistrationConfig(StrictModel):
    manifest: str = Field(min_length=1)


class LoggingConfig(StrictModel):
    trajectory_hz: int = Field(gt=0)
    parquet_batch_rows: int = Field(gt=0)


class ReplayConfig(StrictModel):
    snapshot_interval_ms: int = Field(gt=0)


class ScenarioConfig(StrictModel):
    schema_version: Literal["1.2"] = "1.2"
    scenario: ScenarioIdentityConfig
    simulation: SimulationConfig
    traffic: TrafficConfig
    sumo: SumoConfig
    automation: AutomationConfig
    roi: RoiConfig
    carla: CarlaConfig
    weather: WeatherConfig
    map_registration: MapRegistrationConfig
    logging: LoggingConfig
    replay: ReplayConfig
    ui: UiConfig = Field(default_factory=UiConfig)

    @model_validator(mode="after")
    def duplicated_engine_values_must_match(self) -> "ScenarioConfig":
        mismatches = []
        if self.simulation.step_ms != self.sumo.step_ms:
            mismatches.append("sumo.step_ms")
        if self.simulation.start_time_ms != self.sumo.begin_time_ms:
            mismatches.append("sumo.begin_time_ms")
        if (
            self.carla.mode is not RequirementMode.DISABLED
            and self.simulation.step_ms != self.carla.step_ms
        ):
            mismatches.append("carla.step_ms")
        if mismatches:
            raise ValueError("simulation step values must match: " + ", ".join(mismatches))
        return self


class MapManifest(StrictModel):
    schema_version: Literal["1.1"] = "1.1"
    map_id: str = Field(min_length=1)
    carla_map: str = Field(min_length=1)
    carla_version: str = Field(min_length=1)
    sumo_version: str = Field(min_length=1)
    network_schema_version: Literal["traffic-network/1.0"]
    compiler_version: str = Field(min_length=1)
    source_repository: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    sumo_generation_command: str = Field(min_length=1)
    validated: bool
    max_registration_error_m: float = Field(gt=0.0)
    strict_signal_mapping: bool
    files: dict[str, str] = Field(min_length=1)

    @field_validator("files")
    @classmethod
    def checksums_must_use_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        for path, checksum in value.items():
            if not path or not checksum.startswith("sha256:") or len(checksum) != 71:
                raise ValueError("map files must use sha256:<64 lowercase hex characters>")
            digest = checksum.removeprefix("sha256:")
            if any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("map checksums must be lowercase hexadecimal")
        return value
