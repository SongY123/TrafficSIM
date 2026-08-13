from pathlib import Path

import pytest

from trafficverse.maps.errors import SumoPackageError
from trafficverse.maps.sumo_package import (
    discover_sumo_packages,
    load_sumo_package,
    stage_sumo_package,
)


def _write_package(directory: Path, *, config_name: str = "scene.sumocfg") -> Path:
    directory.mkdir(parents=True)
    (directory / "scene.net.xml").write_text("<net/>", encoding="utf-8")
    (directory / "scene.rou.xml").write_text("<routes/>", encoding="utf-8")
    (directory / "scene.add.xml").write_text(
        '<additional><edgeData id="stats" file="outputs/edge.xml"/></additional>',
        encoding="utf-8",
    )
    config = directory / config_name
    config.write_text(
        """<configuration>
  <input>
    <net-file value="scene.net.xml"/>
    <route-files value="scene.rou.xml"/>
    <additional-files value="scene.add.xml"/>
  </input>
  <time><begin value="5"/><end value="15"/><step-length value="0.2"/></time>
  <output><summary-output value="outputs/summary.xml"/></output>
</configuration>
""",
        encoding="utf-8",
    )
    return config


def test_load_sumo_package_resolves_inputs_timing_and_output_directories(tmp_path: Path) -> None:
    config = _write_package(tmp_path / "scene")

    package = load_sumo_package(config, allowed_root=tmp_path)

    assert package.package_id == "scene"
    assert package.traffic_demand_mode == "generated"
    assert package.network_path == (tmp_path / "scene/scene.net.xml").resolve()
    assert package.route_paths == ((tmp_path / "scene/scene.rou.xml").resolve(),)
    assert package.begin_time_ms == 5000
    assert package.end_time_ms == 15000
    assert package.step_ms == 200
    assert package.output_directories == (Path("outputs"),)
    assert package.files == (
        "scene.add.xml",
        "scene.net.xml",
        "scene.rou.xml",
        "scene.sumocfg",
    )


def test_discover_sumo_packages_gives_multiple_configs_stable_ids(tmp_path: Path) -> None:
    directory = tmp_path / "many"
    _write_package(directory, config_name="morning.sumocfg")
    (directory / "evening.sumocfg").write_text(
        (directory / "morning.sumocfg").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    packages = discover_sumo_packages(directory, allowed_root=tmp_path)

    assert [item.package_id for item in packages] == ["many-evening", "many-morning"]


def test_load_sumo_package_rejects_missing_or_escaping_inputs(tmp_path: Path) -> None:
    config = _write_package(tmp_path / "scene")
    config.write_text(
        config.read_text(encoding="utf-8").replace("scene.net.xml", "../../outside.net.xml"),
        encoding="utf-8",
    )

    with pytest.raises(SumoPackageError, match="escapes"):
        load_sumo_package(config, allowed_root=tmp_path)

    config.write_text(
        config.read_text(encoding="utf-8").replace("../../outside.net.xml", "missing.net.xml"),
        encoding="utf-8",
    )
    with pytest.raises(SumoPackageError, match="missing input"):
        load_sumo_package(config, allowed_root=tmp_path)


def test_load_sumo_package_uses_sumo_time_defaults(tmp_path: Path) -> None:
    config = _write_package(tmp_path / "scene")
    config.write_text(
        """<configuration><input>
  <net-file value="scene.net.xml"/><route-files value="scene.rou.xml"/>
</input></configuration>\n""",
        encoding="utf-8",
    )

    package = load_sumo_package(config, allowed_root=tmp_path)

    assert package.begin_time_ms == 0
    assert package.end_time_ms is None
    assert package.step_ms == 1000


def test_load_sumo_package_reads_scripted_traffic_demand_mode(tmp_path: Path) -> None:
    config = _write_package(tmp_path / "scene")
    (config.parent / "scene.manifest.json").write_text(
        '{"spec":{"name":"固定台本","trafficDemandMode":"scripted"}}\n',
        encoding="utf-8",
    )

    package = load_sumo_package(config, allowed_root=tmp_path)

    assert package.display_name == "固定台本"
    assert package.traffic_demand_mode == "scripted"


def test_load_sumo_package_rejects_unknown_traffic_demand_mode(tmp_path: Path) -> None:
    config = _write_package(tmp_path / "scene")
    (config.parent / "scene.manifest.json").write_text(
        '{"spec":{"trafficDemandMode":"typo"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(SumoPackageError, match="trafficDemandMode"):
        load_sumo_package(config, allowed_root=tmp_path)


def test_stage_sumo_package_preserves_inputs_and_excludes_previous_outputs(
    tmp_path: Path,
) -> None:
    config = _write_package(tmp_path / "scene")
    outputs = tmp_path / "scene/outputs"
    outputs.mkdir()
    (outputs / "old.xml").write_text("old", encoding="utf-8")
    package = load_sumo_package(config, allowed_root=tmp_path)

    staged_config = stage_sumo_package(package, tmp_path / "artifacts/package")

    staged_directory = staged_config.parent
    assert staged_config.is_file()
    assert (staged_directory / "scene.net.xml").is_file()
    assert (staged_directory / "outputs").is_dir()
    assert not (staged_directory / "outputs/old.xml").exists()
