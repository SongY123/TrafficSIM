from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from trafficverse.domain.enums import AutomationLevel, ErrorCode, SimulationRunKind
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.domain.models import AutomationDemand, SimulationConfigurationDraft
from trafficverse.maps.simulation_configuration import SumoSimulationConfigurationStore
from trafficverse.maps.sumo_package import load_sumo_package

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ACCIDENT_PACKAGE_ID = "mixed-automation-occasional-accident"


def _package(maps_root: Path, *, include_route: bool = True) -> Path:
    package = maps_root / "demo"
    package.mkdir(parents=True)
    (package / "demo.net.xml").write_text("<net/>\n", encoding="utf-8")
    route = '<route id="route-east" edges="edge-a" />' if include_route else ""
    (package / "demo.rou.xml").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<routes>
  <vType id="L0" color="0,0,255" />
  {route}
  <flow id="source-flow" type="L0" route="route-east" begin="0" end="120"/>
</routes>
""",
        encoding="utf-8",
    )
    (package / "demo.sumocfg").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <input>
    <net-file value="demo.net.xml"/>
    <route-files value="demo.rou.xml"/>
  </input>
  <time>
    <begin value="0"/>
    <end value="120"/>
    <step-length value="1"/>
  </time>
  <output>
    <summary-output value="outputs/summary.xml"/>
  </output>
</configuration>
""",
        encoding="utf-8",
    )
    return package / "demo.sumocfg"


def _draft() -> SimulationConfigurationDraft:
    return SimulationConfigurationDraft(
        workspace_id=UUID("10000000-0000-0000-0000-000000000001"),
        scenario_id=UUID("20000000-0000-0000-0000-000000000002"),
        scene_name="Morning exact-count run",
        description="Generated from the configuration page.",
        map_id="demo",
        duration_ms=60_000,
        automation_demands=(
            AutomationDemand(level=AutomationLevel.L0, vehicle_count=2),
            AutomationDemand(level=AutomationLevel.L3, vehicle_count=1),
            AutomationDemand(level=AutomationLevel.L5, vehicle_count=0),
        ),
    )


def _store(tmp_path: Path, *, include_route: bool = True) -> SumoSimulationConfigurationStore:
    maps_root = tmp_path / "configs/maps"
    config_path = _package(maps_root, include_route=include_route)
    package = load_sumo_package(config_path, allowed_root=maps_root)
    return SumoSimulationConfigurationStore(
        package_resolver=lambda map_id: package if map_id == "demo" else None,
        configuration_root=tmp_path / "configs/configs",
        simulation_artifact_root=tmp_path / "artifacts/simulations",
        test_artifact_root=tmp_path / "artifacts/tests",
        now=lambda: datetime(2026, 8, 11, 9, 8, 7, tzinfo=timezone.utc),
    )


def test_save_copies_package_and_generates_exact_automation_counts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source_route = tmp_path / "configs/maps/demo/demo.rou.xml"
    original_route = source_route.read_text(encoding="utf-8")

    snapshot = store.save(_draft())

    assert snapshot.configuration_id == "2026-08-11-09-08-07"
    root = tmp_path / snapshot.relative_directory
    assert root == tmp_path / "configs/configs/2026-08-11-09-08-07"
    assert source_route.read_text(encoding="utf-8") == original_route

    metadata = json.loads((root / "configuration.json").read_text(encoding="utf-8"))
    assert metadata["scene"]["name"] == "Morning exact-count run"
    assert metadata["map"] == {"id": "demo", "name": "demo"}
    assert metadata["simulation"]["duration_ms"] == 60_000
    assert metadata["traffic_demand"] == [
        {"automation_level": "L0", "vehicle_count": 2},
        {"automation_level": "L3", "vehicle_count": 1},
        {"automation_level": "L5", "vehicle_count": 0},
    ]

    routes = ElementTree.parse(root / "demo/demo.rou.xml").getroot()
    vehicles = routes.findall("vehicle")
    assert [vehicle.attrib["type"] for vehicle in vehicles].count("L0") == 2
    assert [vehicle.attrib["type"] for vehicle in vehicles].count("L3") == 1
    assert {vehicle.attrib["depart"] for vehicle in vehicles} == {"0"}
    assert routes.find("flow") is None
    assert routes.find("route[@id='route-east']") is not None
    assert routes.find("vType[@id='L3']") is not None

    config = ElementTree.parse(root / "demo/demo.sumocfg").getroot()
    end_option = config.find("time/end")
    route_option = config.find("input/route-files")
    assert end_option is not None
    assert route_option is not None
    assert end_option.attrib["value"] == "60"
    assert route_option.attrib["value"] == "demo.rou.xml"
    output = config.find("output")
    assert output is not None
    summary_output = output.find("summary-output")
    tripinfo_output = output.find("tripinfo-output")
    queue_output = output.find("queue-output")
    assert summary_output is not None
    assert tripinfo_output is not None
    assert queue_output is not None
    assert summary_output.attrib["value"] == "outputs/trafficverse-summary.xml"
    assert tripinfo_output.attrib["value"] == "outputs/trafficverse-tripinfo.xml"
    assert queue_output.attrib["value"] == "outputs/trafficverse-queue.xml"
    additional = config.find("input/additional-files")
    assert additional is not None
    assert additional.attrib["value"] == "trafficverse-results.add.xml"
    result_root = ElementTree.parse(root / "demo/trafficverse-results.add.xml").getroot()
    edge_data = result_root.find("edgeData")
    lane_data = result_root.find("laneData")
    assert edge_data is not None
    assert lane_data is not None
    assert edge_data.attrib["file"] == "outputs/trafficverse-edge-data.xml"
    assert lane_data.attrib["file"] == "outputs/trafficverse-lane-data.xml"


def test_save_with_empty_automation_demand_preserves_original_route_file(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_route = tmp_path / "configs/maps/demo/demo.rou.xml"
    original_route = source_route.read_bytes()
    draft = _draft().model_copy(update={"automation_demands": ()})

    snapshot = store.save(draft)

    root = tmp_path / snapshot.relative_directory
    assert (root / "demo/demo.rou.xml").read_bytes() == original_route
    metadata = json.loads((root / "configuration.json").read_text(encoding="utf-8"))
    assert metadata["traffic_demand"] == []
    config = ElementTree.parse(root / "demo/demo.sumocfg").getroot()
    end_option = config.find("time/end")
    route_option = config.find("input/route-files")
    assert end_option is not None
    assert route_option is not None
    assert end_option.attrib["value"] == "60"
    assert route_option.attrib["value"] == "demo.rou.xml"


def test_save_preserves_scripted_accident_vehicles_when_demands_are_present(
    tmp_path: Path,
) -> None:
    maps_root = REPOSITORY_ROOT / "configs/maps"
    package = load_sumo_package(
        maps_root / ACCIDENT_PACKAGE_ID / f"{ACCIDENT_PACKAGE_ID}.sumocfg",
        allowed_root=maps_root,
    )
    store = SumoSimulationConfigurationStore(
        package_resolver=lambda map_id: package if map_id == ACCIDENT_PACKAGE_ID else None,
        configuration_root=tmp_path / "configs/configs",
        simulation_artifact_root=tmp_path / "artifacts/simulations",
        test_artifact_root=tmp_path / "artifacts/tests",
        now=lambda: datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc),
    )
    draft = SimulationConfigurationDraft(
        workspace_id=UUID("10000000-0000-0000-0000-000000000001"),
        scenario_id=UUID("20000000-0000-0000-0000-000000000002"),
        scene_name="偶发事故",
        description="固定事故台本",
        map_id=ACCIDENT_PACKAGE_ID,
        duration_ms=60_000,
        automation_demands=(
            AutomationDemand(level=AutomationLevel.L0, vehicle_count=6),
            AutomationDemand(level=AutomationLevel.L1, vehicle_count=3),
            AutomationDemand(level=AutomationLevel.L3, vehicle_count=4),
            AutomationDemand(level=AutomationLevel.L5, vehicle_count=4),
        ),
    )

    snapshot = store.save(draft)

    route_path = (
        tmp_path
        / "configs/configs"
        / snapshot.configuration_id
        / ACCIDENT_PACKAGE_ID
        / f"{ACCIDENT_PACKAGE_ID}.rou.xml"
    )
    route_root = ElementTree.parse(route_path).getroot()
    vehicle_ids = {vehicle.attrib["id"] for vehicle in route_root.findall("vehicle")}
    assert vehicle_ids == {
        "accident_parked_L0_0",
        "accident_actor_L0_0",
        "accident_victim_L0_0",
        "accident_follow_L0_0",
        "accident_follow_L1_0",
        "accident_follow_L3_0",
        "accident_follow_L5_0",
        "accident_background_L0_0",
        "accident_background_L0_1",
        "accident_background_L1_0",
        "accident_background_L1_1",
        "accident_background_L3_0",
        "accident_background_L3_1",
        "accident_background_L3_2",
        "accident_background_L5_0",
        "accident_background_L5_1",
        "accident_background_L5_2",
    }


@pytest.mark.parametrize(
    ("kind", "relative_root"),
    [
        (SimulationRunKind.SIMULATION, "artifacts/simulations"),
        (SimulationRunKind.TEST, "artifacts/tests"),
    ],
)
def test_prepare_run_copies_saved_configuration_to_isolated_artifact(
    tmp_path: Path,
    kind: SimulationRunKind,
    relative_root: str,
) -> None:
    store = _store(tmp_path)
    saved = store.save(_draft())

    draft = _draft()
    prepared = store.prepare_run(
        saved.configuration_id,
        kind,
        draft.workspace_id,
        draft.scenario_id,
        draft.map_id,
    )

    assert prepared.run_id == "2026-08-11-09-08-07"
    assert prepared.run_kind is kind
    assert prepared.directory == tmp_path / relative_root / prepared.run_id
    assert prepared.sumo_config_path == prepared.directory / "demo/demo.sumocfg"
    assert (prepared.directory / "configuration.json").is_file()
    assert (prepared.directory / "demo/outputs").is_dir()


def test_save_without_a_route_definition_rejects_generated_traffic(tmp_path: Path) -> None:
    store = _store(tmp_path, include_route=False)

    with pytest.raises(TrafficVerseError) as caught:
        store.save(_draft())

    assert caught.value.code is ErrorCode.SCENARIO_VALIDATION_FAILED
    assert "route definition" in caught.value.message
    assert not (tmp_path / "configs/configs/2026-08-11-09-08-07").exists()
