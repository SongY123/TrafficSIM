"""Pydantic models for runtime, scenario, and map configuration."""

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from trafficverse.domain.enums import AutomationLevel, RequirementMode
from trafficverse.domain.models.common import StrictModel


class ComponentRequirement(StrictModel):
    mode: RequirementMode
    version: str = Field(min_length=1)


class RuntimeProfile(StrictModel):
    operating_system: Literal["Darwin", "Linux", "Windows"]
    architectures: tuple[str, ...] = Field(min_length=1)
    python_version: str = Field(pattern=r"^\d+\.\d+$")
    sumo: ComponentRequirement
    postgres: ComponentRequirement


class RuntimeBaseline(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
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
    """External SUMO/TraCI endpoint used as the production traffic truth source."""

    provider: Literal["sumo"] = "sumo"
    launch_mode: Literal["external"] = "external"
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8813, ge=1, le=65535)
    step_ms: int = Field(default=50, gt=0)
    tls_manager: Literal["sumo"] = "sumo"
    config_file: str = Field(min_length=1)
    expected_version: str = Field(default="1.27.1", min_length=1)
    connect_retries: int = Field(default=3, ge=0, le=100)


class UiConfig(StrictModel):
    api_url: str = Field(default="http://127.0.0.1:8000", min_length=1)


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


class TrafficBehaviorConfig(StrictModel):
    max_acceleration_mps2: float = Field(default=2.5, gt=0.0)
    comfortable_deceleration_mps2: float = Field(default=4.0, gt=0.0)
    emergency_deceleration_mps2: float = Field(default=8.0, gt=0.0)
    minimum_gap_m: float = Field(default=2.5, gt=0.0)
    time_headway_s: float = Field(default=1.2, gt=0.0)
    vehicle_length_m: float = Field(default=4.5, gt=0.0)
    lane_change_front_gap_m: float = Field(default=10.0, gt=0.0)
    lane_change_rear_gap_m: float = Field(default=8.0, gt=0.0)


class TrafficEngineConfig(StrictModel):
    network_schema_version: Literal["traffic-network/1.0"] = "traffic-network/1.0"
    network_path: str = Field(min_length=1)
    routes_path: str = Field(min_length=1)
    signals_path: str = Field(min_length=1)
    step_ms: int = Field(default=50, gt=0)
    seed: int = Field(default=0, ge=0)
    behavior: TrafficBehaviorConfig = Field(default_factory=TrafficBehaviorConfig)


class LoggingConfig(StrictModel):
    trajectory_hz: int = Field(gt=0)
    parquet_batch_rows: int = Field(gt=0)


class ReplayConfig(StrictModel):
    snapshot_interval_ms: int = Field(gt=0)


class ScenarioConfig(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    scenario: ScenarioIdentityConfig
    simulation: SimulationConfig
    traffic: TrafficConfig
    sumo: SumoConfig
    automation: AutomationConfig
    logging: LoggingConfig
    replay: ReplayConfig
    ui: UiConfig = Field(default_factory=UiConfig)

    @model_validator(mode="after")
    def simulation_and_sumo_steps_must_match(self) -> "ScenarioConfig":
        if self.simulation.step_ms != self.sumo.step_ms:
            raise ValueError("simulation.step_ms must match sumo.step_ms")
        return self


class MapManifest(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    map_id: str = Field(min_length=1)
    sumo_version: str = Field(min_length=1)
    network_schema_version: Literal["traffic-network/1.0"]
    compiler_version: str = Field(min_length=1)
    source_repository: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    sumo_generation_command: str = Field(min_length=1)
    validated: bool
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
