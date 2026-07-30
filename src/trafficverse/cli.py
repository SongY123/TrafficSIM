"""TrafficVerse command-line entry point."""

import argparse
import json
import os
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from trafficverse.adapters.sumo import SumoTrafficEngineAdapter
from trafficverse.config.compatibility import (
    default_baseline_path,
    inspect_runtime,
    select_runtime_profile,
)
from trafficverse.config.loader import (
    configuration_hash,
    load_runtime_baseline,
    load_scenario,
    validate_map_manifest,
    validate_scenario_environment,
)
from trafficverse.config.models import ScenarioConfig
from trafficverse.domain.errors import TrafficVerseError
from trafficverse.maps import (
    NETWORK_SCHEMA_VERSION,
    OpenDriveMapCompiler,
    validate_compiled_bundle,
)

SOFTWARE_WEBGL_FLAGS = (
    "--ignore-gpu-blocklist",
    "--enable-unsafe-swiftshader",
    "--disable-gpu-compositing",
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trafficverse")
    subcommands = parser.add_subparsers(dest="command", required=True)

    doctor = subcommands.add_parser("doctor", help="inspect local runtime compatibility")
    doctor.add_argument(
        "--profile",
        default=os.getenv("TRAFFICVERSE_RUNTIME_PROFILE", "auto"),
        help="runtime profile name or auto",
    )
    doctor.add_argument(
        "--baseline",
        type=Path,
        default=default_baseline_path(_repository_root()),
    )

    scenario = subcommands.add_parser("scenario", help="scenario operations")
    scenario_commands = scenario.add_subparsers(dest="scenario_command", required=True)
    validate = scenario_commands.add_parser("validate", help="validate a scenario YAML")
    validate.add_argument("path", type=Path)
    validate.add_argument(
        "--environment",
        action="store_true",
        help="also validate referenced SUMO assets, manifest versions, and checksums",
    )

    map_parser = subcommands.add_parser("map", help="map asset operations")
    map_commands = map_parser.add_subparsers(dest="map_command", required=True)
    map_validate = map_commands.add_parser("validate", help="validate a map manifest")
    map_validate.add_argument("path", type=Path)
    map_validate.add_argument(
        "--profile",
        default=os.getenv("TRAFFICVERSE_RUNTIME_PROFILE", "auto"),
        help="runtime profile whose component versions must match",
    )
    map_validate.add_argument(
        "--baseline",
        type=Path,
        default=default_baseline_path(_repository_root()),
    )
    map_compile = map_commands.add_parser("compile", help="compile OpenDRIVE native map assets")
    map_compile.add_argument("source", type=Path)
    map_compile.add_argument("output", type=Path)
    map_compile.add_argument("--map-id", default="town04-sumo-1.27.1-native-1.0")
    map_compile.add_argument("--sumo-version", default="1.27.1")

    traffic = subcommands.add_parser("traffic", help="SUMO traffic adapter operations")
    traffic_commands = traffic.add_subparsers(dest="traffic_command", required=True)
    smoke = traffic_commands.add_parser("smoke", help="run the external SUMO smoke test")
    smoke.add_argument(
        "--scenario",
        type=Path,
        default=_repository_root() / "configs" / "scenarios" / "core-run-town04.yaml",
    )
    smoke.add_argument("--ticks", type=int, default=2400)

    ui = subcommands.add_parser("ui", help="open the TrafficVerse Core Run desktop UI")
    ui.add_argument(
        "--api-url",
        default=os.getenv("TRAFFICVERSE_API_URL", "http://127.0.0.1:8000"),
    )
    ui.add_argument(
        "--scenario-id",
        type=UUID,
        default=UUID("00000000-0000-0000-0000-000000000042"),
    )
    ui.add_argument(
        "--allow-software-webgl",
        action="store_true",
        help="allow Chromium WebGL on a blocklisted software renderer such as llvmpipe",
    )
    serve = subcommands.add_parser("serve", help="serve the Core Run REST/WebSocket API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--scenario",
        type=Path,
        default=_repository_root() / "configs/scenarios/core-run-town04.yaml",
    )
    serve.add_argument(
        "--artifact-root",
        type=Path,
        default=_repository_root() / "artifacts/maps",
    )
    return parser


def _fail(message: str, *, exit_code: int = 2) -> NoReturn:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def _run_doctor(args: argparse.Namespace) -> int:
    baseline = load_runtime_baseline(args.baseline)
    report = inspect_runtime(baseline, requested_profile=args.profile)
    print(report.model_dump_json(indent=2))
    return 0 if report.ready else 1


def _run_scenario_validate(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.path)
    if args.environment:
        validate_scenario_environment(scenario, repository_root=_repository_root())
    result = {
        "ok": True,
        "scenario": scenario.scenario.name,
        "map_id": scenario.scenario.map_id,
        "configuration_hash": configuration_hash(scenario),
        "environment_checked": bool(args.environment),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_map_validate(args: argparse.Namespace) -> int:
    baseline = load_runtime_baseline(args.baseline)
    profile_name, profile = select_runtime_profile(
        baseline,
        requested_profile=args.profile,
    )
    manifest = validate_map_manifest(
        args.path,
        expected_network_schema_version=NETWORK_SCHEMA_VERSION,
        expected_sumo_version=profile.sumo.version,
    )
    network = validate_compiled_bundle(args.path.parent)
    result = {
        "ok": True,
        "profile": profile_name,
        "map_id": manifest.map_id,
        "validated_files": len(manifest.files),
        "lanes": len(network.lanes),
        "links": len(network.links),
        "signals": len(network.signals),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_map_compile(args: argparse.Namespace) -> int:
    result = OpenDriveMapCompiler().compile(
        args.source,
        args.output,
        map_id=args.map_id,
        sumo_version=args.sumo_version,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "network_schema_version": NETWORK_SCHEMA_VERSION,
                "network": str(result.network_path),
                "geojson": str(result.geojson_path),
                "manifest": str(result.manifest_path),
                "lanes": result.lane_count,
                "links": result.link_count,
                "signals": result.signal_count,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _resolved_sumo_scenario(scenario_path: Path) -> ScenarioConfig:
    scenario = load_scenario(scenario_path)
    config_file = Path(scenario.sumo.config_file)
    if not config_file.is_absolute():
        config_file = _repository_root() / config_file
    return scenario.model_copy(
        update={"sumo": scenario.sumo.model_copy(update={"config_file": str(config_file)})}
    )


def _run_traffic_smoke(args: argparse.Namespace) -> int:
    if args.ticks <= 0:
        raise ValueError("--ticks must be greater than zero")
    scenario = _resolved_sumo_scenario(args.scenario)
    engine = SumoTrafficEngineAdapter(UUID(int=scenario.scenario.seed))
    seen_vehicle_ids: set[str] = set()
    seen_signal_ids: set[str] = set()
    maximum_active_vehicles = 0
    try:
        engine.load(scenario.sumo)
        for sequence in range(1, args.ticks + 1):
            snapshot = engine.step(sequence * scenario.simulation.step_ms)
            seen_vehicle_ids.update(vehicle.vehicle_id for vehicle in snapshot.vehicles)
            seen_signal_ids.update(signal.signal_id for signal in snapshot.traffic_lights)
            maximum_active_vehicles = max(maximum_active_vehicles, len(snapshot.vehicles))
    finally:
        engine.close()

    diagnostics = engine.diagnostics()
    result = {
        "ok": True,
        "ticks": diagnostics.sequence,
        "simulation_time_ms": diagnostics.simulation_time_ms,
        "seen_vehicles": len(seen_vehicle_ids),
        "traffic_lights": len(seen_signal_ids),
        "maximum_active_vehicles": maximum_active_vehicles,
        "departed_vehicle_ids": diagnostics.departed_vehicle_ids,
        "arrived_vehicle_ids": diagnostics.arrived_vehicle_ids,
        "closed": engine.health().status.value == "UNAVAILABLE",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _configure_software_webgl() -> None:
    current_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
    for flag in SOFTWARE_WEBGL_FLAGS:
        if flag not in current_flags:
            current_flags.append(flag)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(current_flags)


def _run_ui(args: argparse.Namespace) -> int:
    if args.allow_software_webgl:
        _configure_software_webgl()
    try:
        from ui.app.main import run
    except ModuleNotFoundError as error:
        if error.name == "PySide6" or (
            error.name is not None and error.name.startswith("PySide6.")
        ):
            _fail("UI dependencies are unavailable; run 'uv sync --extra ui'")
        raise
    return run(args.api_url, args.scenario_id)


def _run_serve(args: argparse.Namespace) -> int:
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(
            "Core Run server only supports loopback binding; use a secured deployment "
            "gateway for remote UI access"
        )
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    import uvicorn

    from trafficverse.bootstrap import build_core_api

    app = build_core_api(
        args.scenario,
        repository_root=_repository_root(),
        artifact_root=args.artifact_root,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "scenario" and args.scenario_command == "validate":
            return _run_scenario_validate(args)
        if args.command == "map" and args.map_command == "validate":
            return _run_map_validate(args)
        if args.command == "map" and args.map_command == "compile":
            return _run_map_compile(args)
        if args.command == "traffic" and args.traffic_command == "smoke":
            return _run_traffic_smoke(args)
        if args.command == "ui":
            return _run_ui(args)
        if args.command == "serve":
            return _run_serve(args)
    except (TrafficVerseError, ValueError) as error:
        _fail(str(error))
    parser.error("unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
