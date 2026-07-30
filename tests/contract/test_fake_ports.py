from pathlib import Path
from uuid import uuid4

from tests.fakes import (
    FakeDataLogger,
    FakeEventPublisher,
    FakeExperimentRepository,
    FakeTrafficEnginePort,
)

from trafficverse.bootstrap import AppContainer
from trafficverse.config.loader import load_scenario
from trafficverse.domain.enums import ComponentStatus, ExperimentStatus

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_fake_ports_drive_minimal_external_free_tick() -> None:
    experiment_id = uuid4()
    scenario = load_scenario(
        REPOSITORY_ROOT / "configs" / "scenarios" / "core-run-town04.yaml",
        apply_environment=False,
    )
    traffic = FakeTrafficEnginePort(experiment_id)
    repository = FakeExperimentRepository()
    container = AppContainer(
        traffic=traffic,
        experiments=repository,
        events=FakeEventPublisher(),
        data_logger=FakeDataLogger(),
    )

    container.traffic.load(scenario.sumo)
    snapshot = container.traffic.step(50)

    assert snapshot.simulation_time_ms == 50
    assert container.traffic.health().status is ComponentStatus.HEALTHY

    container.traffic.close()
    assert container.traffic.health().status is ComponentStatus.UNAVAILABLE
    assert ExperimentStatus.CREATED.value == "CREATED"
