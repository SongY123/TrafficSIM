import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from trafficverse.adapters.persistence.postgres import (
    PostgresRepository,
    create_postgres_engine,
)
from trafficverse.application.scenario_service import ScenarioDraft, ScenarioService
from trafficverse.application.workspace_service import WorkspaceService
from trafficverse.config.loader import load_scenario
from trafficverse.domain.enums import ErrorCode, EventSeverity, ExperimentStatus
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import (
    ArtifactCreate,
    DomainEvent,
    ExperimentCreate,
    MapAssetRegistration,
    MetricSample,
    ScenarioListQuery,
    WorkspaceListQuery,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_PATH = REPOSITORY_ROOT / "configs/scenarios/core-run-town04.yaml"
ALEMBIC_CONFIG = REPOSITORY_ROOT / "migrations/alembic.ini"


def database_url() -> str:
    value = os.getenv("TRAFFICVERSE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("TRAFFICVERSE_TEST_DATABASE_URL is not configured")
    return value


def migrate(revision: str) -> None:
    config = Config(str(ALEMBIC_CONFIG))
    config.set_main_option("sqlalchemy.url", database_url())
    command.upgrade(config, revision) if revision == "head" else command.downgrade(config, revision)


@pytest.mark.integration
@pytest.mark.postgres
def test_migration_round_trip_and_schema_contract() -> None:
    url = database_url()
    migrate("base")
    migrate("head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) >= {
            "map_asset",
            "scenario",
            "scenario_version",
            "experiment",
            "experiment_state_change",
            "event",
            "metric_sample",
            "artifact",
            "workspace",
        }
        unique_names = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("scenario_version")
        }
        assert "uq_scenario_version_scenario_version" in unique_names
        map_unique_names = {
            constraint["name"] for constraint in inspector.get_unique_constraints("map_asset")
        }
        assert map_unique_names >= {
            "uq_map_asset_map_id",
            "uq_map_asset_source_checksum",
        }
        foreign_keys = {
            key["name"] or tuple(key["constrained_columns"])
            for table in ("scenario_version", "experiment", "event", "metric_sample", "artifact")
            for key in inspector.get_foreign_keys(table)
        }
        assert len(foreign_keys) == 6
        index_names = {
            index["name"]
            for table in (
                "scenario_version",
                "experiment",
                "experiment_state_change",
                "event",
                "metric_sample",
                "artifact",
                "workspace",
            )
            for index in inspector.get_indexes(table)
        }
        assert index_names >= {
            "ix_event_experiment_time",
            "ix_metric_experiment_name_time",
            "ix_artifact_experiment_kind",
            "ix_state_change_experiment_occurred",
            "ix_workspace_active_updated_id",
            "ix_workspace_active_lower_name",
            "ix_workspace_active_lower_description",
        }
    finally:
        engine.dispose()

    migrate("base")
    migrate("head")


@pytest.mark.integration
@pytest.mark.postgres
def test_repository_contract_crud_conflict_rollback_and_metadata() -> None:
    url = database_url()
    migrate("base")
    migrate("head")

    async def exercise() -> None:
        engine = create_postgres_engine(url)
        repository = PostgresRepository(engine)
        service = ScenarioService(repository)
        map_asset_id = uuid4()
        config = load_scenario(SCENARIO_PATH, apply_environment=False)
        await repository.register_map_asset(
            MapAssetRegistration(
                map_asset_id=map_asset_id,
                map_id=config.scenario.map_id,
                name="Town04",
                source_checksum=f"sha256:{'a' * 64}",
                network_schema_version="traffic-network/1.0",
                manifest_uri="configs/maps/town04/manifest.yaml",
            )
        )
        draft = ScenarioDraft(
            name="Town04 baseline",
            description="integration",
            map_asset_id=map_asset_id,
            config=config,
        )
        created = await service.create(draft)
        cloned = await service.clone(created.scenario_id, name="Town04 clone")
        assert cloned.current_version.version == 1
        assert (await service.list(ScenarioListQuery(limit=1))).total == 2

        updates = await asyncio.gather(
            service.update(
                created.scenario_id,
                draft.model_copy(update={"description": "client-a"}),
                expected_version=1,
            ),
            service.update(
                created.scenario_id,
                draft.model_copy(update={"description": "client-b"}),
                expected_version=1,
            ),
            return_exceptions=True,
        )
        successes = [value for value in updates if not isinstance(value, BaseException)]
        conflicts = [
            value
            for value in updates
            if isinstance(value, TrafficVerseError)
            and value.code is ErrorCode.CONCURRENT_MODIFICATION
        ]
        assert len(successes) == len(conflicts) == 1
        current = await service.get(created.scenario_id)
        assert current.current_version.version == 2

        experiment_id = uuid4()
        experiment = await repository.create_experiment(
            ExperimentCreate(
                experiment_id=experiment_id,
                scenario_version_id=current.current_version.scenario_version_id,
                seed=config.scenario.seed,
                step_ms=config.simulation.step_ms,
                duration_ms=config.simulation.duration_ms,
            )
        )
        assert experiment.status is ExperimentStatus.CREATED
        with pytest.raises(TrafficVerseError) as invalid:
            await repository.transition_status(
                experiment_id,
                ExperimentStatus.RUNNING,
                simulation_time_ms=0,
            )
        assert invalid.value.code is ErrorCode.INVALID_STATE_TRANSITION
        assert await repository.list_state_changes(experiment_id) == ()
        assert await repository.get_status(experiment_id) is ExperimentStatus.CREATED

        await repository.transition_status(
            experiment_id,
            ExperimentStatus.PREPARING,
            simulation_time_ms=0,
            reason="assets validated",
        )
        history = await repository.list_state_changes(experiment_id)
        assert len(history) == 1
        assert history[0].from_status is ExperimentStatus.CREATED
        assert history[0].to_status is ExperimentStatus.PREPARING

        await repository.append_event(
            DomainEvent(
                event_id=uuid4(),
                experiment_id=experiment_id,
                event_type="experiment.preparing",
                severity=EventSeverity.INFO,
                simulation_time_ms=0,
                payload={"source": "test"},
            )
        )
        await repository.append_metric(
            MetricSample(
                experiment_id=experiment_id,
                metric_name="active_vehicles",
                value=0.0,
                unit="vehicles",
                simulation_time_ms=0,
                dimensions={"map": "Town04"},
            )
        )
        artifact = await repository.append_artifact(
            ArtifactCreate(
                artifact_id=uuid4(),
                experiment_id=experiment_id,
                kind="manifest",
                uri="artifacts/experiments/test/manifest.json",
                format="json",
                checksum=f"sha256:{'b' * 64}",
                size_bytes=128,
                metadata={"schema_version": "1.0"},
            )
        )
        assert artifact.size_bytes == 128
        assert len(await repository.list_events(experiment_id)) == 1
        assert len(await repository.list_metrics(experiment_id, metric_name="active_vehicles")) == 1
        assert await repository.list_metrics(experiment_id, metric_name="missing") == ()
        assert (await repository.list_artifacts(experiment_id))[0] == artifact

        await service.delete(created.scenario_id)
        with pytest.raises(TrafficVerseError) as hidden:
            await service.get(created.scenario_id)
        assert hidden.value.code is ErrorCode.RESOURCE_NOT_FOUND
        assert (await service.list(ScenarioListQuery())).total == 1
        assert (await service.get(created.scenario_id, include_deleted=True)).deleted_at
        assert (await repository.get_experiment(experiment_id)).scenario_version_id == (
            current.current_version.scenario_version_id
        )

        async with engine.connect() as connection:
            counts = {
                table: int(
                    (await connection.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar_one()
                )
                for table in ("event", "metric_sample", "artifact")
            }
        assert counts == {"event": 1, "metric_sample": 1, "artifact": 1}
        await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.integration
@pytest.mark.postgres
def test_workspace_repository_search_pagination_and_soft_delete() -> None:
    url = database_url()
    migrate("base")
    migrate("head")

    async def exercise() -> None:
        engine = create_postgres_engine(url)
        repository = PostgresRepository(engine)
        service = WorkspaceService(repository)
        now = datetime.now(timezone.utc)
        ids = [uuid4() for _ in range(4)]
        rows = (
            (ids[0], "Traffic baseline", "morning commute", now, None),
            (ids[1], "Percent % study", "literal_underbar", now + timedelta(minutes=1), None),
            (ids[2], "Description match", "traffic analysis", now + timedelta(minutes=2), None),
            (ids[3], "Deleted traffic", "hidden", now + timedelta(minutes=3), now),
        )
        async with engine.begin() as connection:
            for workspace_id, name, description, updated_at, deleted_at in rows:
                await connection.execute(
                    text(
                        """
                        INSERT INTO workspace
                            (id, name, description, created_at, updated_at, deleted_at)
                        VALUES
                            (:id, :name, :description, :created_at, :updated_at, :deleted_at)
                        """
                    ),
                    {
                        "id": workspace_id,
                        "name": name,
                        "description": description,
                        "created_at": now,
                        "updated_at": updated_at,
                        "deleted_at": deleted_at,
                    },
                )

        page = await service.list(WorkspaceListQuery(limit=1))
        assert page.total == 3
        assert page.items[0].workspace_id == ids[2]
        assert (await service.list(WorkspaceListQuery(q="baseline"))).items[0].workspace_id == ids[0]
        assert (await service.list(WorkspaceListQuery(q="analysis"))).items[0].workspace_id == ids[2]
        assert (await service.list(WorkspaceListQuery(q="%"))).items[0].workspace_id == ids[1]
        assert (await service.list(WorkspaceListQuery(q="_"))).items[0].workspace_id == ids[1]
        assert (await service.list(WorkspaceListQuery(q="missing"))).total == 0
        assert (await service.get(ids[1])).name == "Percent % study"
        with pytest.raises(TrafficVerseError) as deleted:
            await service.get(ids[3])
        assert deleted.value.code is ErrorCode.RESOURCE_NOT_FOUND
        await engine.dispose()

    asyncio.run(exercise())
