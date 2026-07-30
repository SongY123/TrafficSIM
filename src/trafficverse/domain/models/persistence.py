"""Technology-neutral records crossing the persistence Port boundary."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator

from trafficverse.domain.enums import ExperimentStatus
from trafficverse.domain.models.common import StrictModel


class MapAssetRegistration(StrictModel):
    map_asset_id: UUID
    map_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_format: Literal["OpenDRIVE"] = "OpenDRIVE"
    source_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    network_schema_version: str = Field(min_length=1)
    manifest_uri: str = Field(min_length=1)
    status: Literal["VALIDATED"] = "VALIDATED"


class ScenarioWrite(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    map_asset_id: UUID
    config: dict[str, JsonValue]
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ScenarioVersionRecord(StrictModel):
    scenario_version_id: UUID
    scenario_id: UUID
    map_asset_id: UUID
    version: int = Field(ge=1)
    config: dict[str, JsonValue]
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class ScenarioRecord(StrictModel):
    scenario_id: UUID
    name: str
    description: str
    current_version: ScenarioVersionRecord
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class ScenarioListQuery(StrictModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    include_deleted: bool = False


class ScenarioPage(StrictModel):
    items: tuple[ScenarioRecord, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class WorkspaceRecord(StrictModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class WorkspaceListQuery(StrictModel):
    q: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("q", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class WorkspacePage(StrictModel):
    items: tuple[WorkspaceRecord, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class ExperimentCreate(StrictModel):
    experiment_id: UUID
    scenario_version_id: UUID
    seed: int = Field(ge=0)
    step_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)


class ExperimentRecord(StrictModel):
    experiment_id: UUID
    scenario_version_id: UUID
    status: ExperimentStatus
    seed: int = Field(ge=0)
    step_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    current_time_ms: int = Field(ge=0)
    failure_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExperimentStateChangeRecord(StrictModel):
    state_change_id: int = Field(ge=1)
    experiment_id: UUID
    from_status: ExperimentStatus
    to_status: ExperimentStatus
    reason: str | None = None
    simulation_time_ms: int = Field(ge=0)
    occurred_at: datetime


class ArtifactCreate(StrictModel):
    artifact_id: UUID
    experiment_id: UUID
    kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    format: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ArtifactRecord(ArtifactCreate):
    created_at: datetime
