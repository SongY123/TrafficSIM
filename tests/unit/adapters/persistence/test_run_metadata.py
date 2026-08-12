from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from trafficverse.adapters.persistence import (
    InMemoryExperimentRepository,
    RunMetadataExperimentRepository,
)
from trafficverse.domain.enums import ExperimentStatus


def test_run_metadata_mirrors_status_and_preserves_run_identity(tmp_path: Path) -> None:
    experiment_id = UUID("30000000-0000-0000-0000-000000000003")
    directory = tmp_path / "2026-08-11-09-08-07"
    directory.mkdir()
    (directory / "run.json").write_text(
        json.dumps({"run_id": directory.name, "run_kind": "simulation"}),
        encoding="utf-8",
    )
    delegate = InMemoryExperimentRepository()

    async def exercise() -> None:
        await delegate.create(experiment_id)
        repository = RunMetadataExperimentRepository(
            delegate,
            experiment_id=experiment_id,
            run_directory=directory,
        )
        await repository.set_status(experiment_id, ExperimentStatus.RUNNING)
        await repository.set_status(
            experiment_id,
            ExperimentStatus.COMPLETED,
            reason="SIMULATION_DURATION_REACHED",
        )

    asyncio.run(exercise())
    metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))

    assert metadata["run_id"] == directory.name
    assert metadata["run_kind"] == "simulation"
    assert metadata["experiment_id"] == str(experiment_id)
    assert metadata["status"] == "COMPLETED"
    assert metadata["status_reason"] == "SIMULATION_DURATION_REACHED"
    assert metadata["started_at"]
    assert metadata["ended_at"]
    assert not (directory / "run.json.tmp").exists()
