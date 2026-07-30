"""SQLAlchemy models private to the PostgreSQL adapter."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MapAssetRow(Base):
    __tablename__ = "map_asset"
    __table_args__ = (
        UniqueConstraint("map_id", name="uq_map_asset_map_id"),
        UniqueConstraint("source_checksum", name="uq_map_asset_source_checksum"),
        CheckConstraint("status = 'VALIDATED'", name="ck_map_asset_status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    map_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_format: Mapped[str] = mapped_column(String(50), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(71), nullable=False)
    network_schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    manifest_uri: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScenarioRow(Base):
    __tablename__ = "scenario"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceRow(Base):
    __tablename__ = "workspace"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "ix_workspace_active_updated_id",
            updated_at.desc(),
            id,
            postgresql_where=deleted_at.is_(None),
        ),
        Index(
            "ix_workspace_active_lower_name",
            func.lower(name),
            postgresql_where=deleted_at.is_(None),
        ),
        Index(
            "ix_workspace_active_lower_description",
            func.lower(description),
            postgresql_where=deleted_at.is_(None),
        ),
    )


class ScenarioVersionRow(Base):
    __tablename__ = "scenario_version"
    __table_args__ = (
        UniqueConstraint("scenario_id", "version", name="uq_scenario_version_scenario_version"),
        CheckConstraint("version >= 1", name="ck_scenario_version_positive"),
        Index("ix_scenario_version_map_asset_id", "map_asset_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("scenario.id", ondelete="RESTRICT"),
        nullable=False,
    )
    map_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("map_asset.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


_EXPERIMENT_STATUSES = (
    "CREATED",
    "PREPARING",
    "READY",
    "RUNNING",
    "PAUSED",
    "STOPPING",
    "COMPLETED",
    "FAILED",
)
_STATUS_SQL = ", ".join(f"'{status}'" for status in _EXPERIMENT_STATUSES)


class ExperimentRow(Base):
    __tablename__ = "experiment"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="ck_experiment_status"),
        CheckConstraint("seed >= 0", name="ck_experiment_seed"),
        CheckConstraint("step_ms > 0", name="ck_experiment_step_ms"),
        CheckConstraint("duration_ms > 0", name="ck_experiment_duration_ms"),
        CheckConstraint("current_time_ms >= 0", name="ck_experiment_current_time_ms"),
        Index("ix_experiment_scenario_version_id", "scenario_version_id"),
        Index("ix_experiment_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    scenario_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("scenario_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExperimentStateChangeRow(Base):
    __tablename__ = "experiment_state_change"
    __table_args__ = (
        CheckConstraint(f"from_status IN ({_STATUS_SQL})", name="ck_state_from_status"),
        CheckConstraint(f"to_status IN ({_STATUS_SQL})", name="ck_state_to_status"),
        CheckConstraint("simulation_time_ms >= 0", name="ck_state_simulation_time_ms"),
        Index(
            "ix_state_change_experiment_occurred",
            "experiment_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("experiment.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    simulation_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventRow(Base):
    __tablename__ = "event"
    __table_args__ = (
        CheckConstraint("simulation_time_ms >= 0", name="ck_event_simulation_time_ms"),
        Index("ix_event_experiment_time", "experiment_id", "simulation_time_ms"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    experiment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("experiment.id", ondelete="RESTRICT"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    simulation_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[object] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MetricSampleRow(Base):
    __tablename__ = "metric_sample"
    __table_args__ = (
        CheckConstraint("simulation_time_ms >= 0", name="ck_metric_simulation_time_ms"),
        Index(
            "ix_metric_experiment_name_time",
            "experiment_id",
            "metric_name",
            "simulation_time_ms",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("experiment.id", ondelete="RESTRICT"),
        nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    simulation_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dimensions: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)


class ArtifactRow(Base):
    __tablename__ = "artifact"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_artifact_size_bytes"),
        Index("ix_artifact_experiment_kind", "experiment_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    experiment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("experiment.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    checksum: Mapped[str] = mapped_column(String(71), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
