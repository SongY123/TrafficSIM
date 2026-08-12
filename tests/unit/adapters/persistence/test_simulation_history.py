from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest

from trafficverse.adapters.persistence import FileSimulationHistoryStore
from trafficverse.domain.enums import ErrorCode, ExperimentStatus
from trafficverse.domain.errors import TrafficVerseError

RUN_ID = "2026-08-11-09-08-07"
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")


def _write_run(root: Path) -> Path:
    directory = root / RUN_ID
    package = directory / "demo"
    outputs = package / "outputs"
    outputs.mkdir(parents=True)
    (directory / "run.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": RUN_ID,
                "experiment_id": "30000000-0000-0000-0000-000000000003",
                "status": "COMPLETED",
                "created_at": "2026-08-11T09:08:07+08:00",
                "started_at": "2026-08-11T09:08:08+08:00",
                "ended_at": "2026-08-11T09:08:18+08:00",
            }
        ),
        encoding="utf-8",
    )
    (directory / "configuration.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "workspace_id": str(WORKSPACE_ID),
                "scene": {"name": "Morning validation"},
                "map": {"id": "demo", "name": "Demo network"},
                "simulation": {"duration_ms": 10_000},
                "sumo": {"config_file": "demo/demo.sumocfg"},
            }
        ),
        encoding="utf-8",
    )
    (package / "demo.sumocfg").write_text(
        """<configuration>
  <input><net-file value="demo.net.xml"/></input>
  <time><begin value="0"/><end value="10"/><step-length value="1"/></time>
</configuration>
""",
        encoding="utf-8",
    )
    (package / "demo.net.xml").write_text(
        """<net>
  <edge id="edge-a" from="n0" to="n1">
    <lane id="edge-a_0" index="0" speed="13.9" length="100" shape="0,0 100,0"/>
  </edge>
  <junction id="n0" type="priority" shape="-2,-2 2,-2 2,2 -2,2"/>
  <junction id="n1" type="priority" shape="98,-2 102,-2 102,2 98,2"/>
</net>
""",
        encoding="utf-8",
    )
    (outputs / "trafficverse-summary.xml").write_text(
        """<summary>
  <step time="0.00" loaded="2" arrived="0" running="2" halting="1"
        meanWaitingTime="1" meanTravelTime="0" meanSpeed="10"/>
  <step time="10.00" loaded="3" arrived="1" running="2" halting="2"
        meanWaitingTime="3" meanTravelTime="15" meanSpeed="12"/>
</summary>
""",
        encoding="utf-8",
    )
    (outputs / "trafficverse-tripinfo.xml").write_text(
        """<tripinfos>
  <tripinfo id="veh-1" duration="10" waitingTime="2"/>
  <tripinfo id="veh-2" duration="20" waitingTime="4"/>
</tripinfos>
""",
        encoding="utf-8",
    )
    (outputs / "trafficverse-edgeData.xml").write_text(
        """<meandata>
  <interval begin="0" end="10">
    <edge id="edge-a" sampledSeconds="20" speed="10" speedRelative="0.5" flow="720"/>
  </interval>
</meandata>
""",
        encoding="utf-8",
    )
    (outputs / "trafficverse-queue.xml").write_text(
        """<queue-export><data timestep="10"><lanes>
  <lane id="edge-a_0" queueing_length="17.5"/>
</lanes></data></queue-export>
""",
        encoding="utf-8",
    )
    return directory


def test_history_reads_direct_run_folders_and_aligns_result_sources(tmp_path: Path) -> None:
    root = tmp_path / "artifacts/simulations"
    directory = _write_run(root)
    (root / "not-a-run").mkdir()
    (directory / "nested/2026-08-10-01-02-03").mkdir(parents=True)
    store = FileSimulationHistoryStore(root)

    summaries = store.list_runs(WORKSPACE_ID)
    detail = store.get_run(RUN_ID)

    assert [item.run_id for item in summaries] == [RUN_ID]
    assert summaries[0].status is ExperimentStatus.COMPLETED
    assert summaries[0].simulation_time_ms == 10_000
    assert store.list_runs(UUID(int=99)) == ()
    metrics = {metric.key: metric for metric in detail.metrics}
    assert metrics["vehicle_total"].value == 3
    assert metrics["completed_total"].source == "summary.arrived"
    assert metrics["average_speed_mps"].value == 11
    assert metrics["average_travel_time_s"].value == 15
    assert metrics["average_waiting_time_s"].value == 3
    assert metrics["average_queue_length_veh"].value == 1.5
    assert metrics["maximum_queue_length_veh"].value == 2
    assert all(len(trend.samples) == 2 for trend in detail.trends)
    assert detail.road_results[0].edge_id == "edge-a"
    assert detail.road_results[0].average_speed_mps == 10
    assert detail.road_results[0].congestion_ratio == 0.5
    assert detail.road_results[0].traffic_flow_veh_per_hour == 720
    assert detail.road_results[0].queue_length_m == 17.5


def test_history_network_and_export_use_selected_run_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "artifacts/simulations"
    _write_run(root)
    store = FileSimulationHistoryStore(root)

    network = store.get_network(RUN_ID)
    exported = store.export_run(RUN_ID)

    features = network["features"]
    assert isinstance(features, list)
    assert any(feature["properties"].get("sumo_edge_id") == "edge-a" for feature in features)
    assert exported.filename == f"trafficverse-simulation-{RUN_ID}.zip"
    with zipfile.ZipFile(BytesIO(exported.payload)) as archive:
        names = set(archive.namelist())
        assert "demo/demo.net.xml" in names
        assert "export/summary.csv" in names
        assert "export/trends.csv" in names
        assert "export/road_results.csv" in names
        assert "summary.loaded" in archive.read("export/summary.csv").decode("utf-8")


def test_history_rejects_invalid_or_missing_replay_run(tmp_path: Path) -> None:
    root = tmp_path / "artifacts/simulations"
    _write_run(root)
    store = FileSimulationHistoryStore(root)

    with pytest.raises(TrafficVerseError) as invalid:
        store.get_run("../outside")
    with pytest.raises(TrafficVerseError) as unavailable:
        store.get_replay(RUN_ID, from_time_ms=0, limit=10)

    assert invalid.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert unavailable.value.code is ErrorCode.RESOURCE_NOT_FOUND
