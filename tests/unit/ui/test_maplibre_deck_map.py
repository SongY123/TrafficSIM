from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from trafficverse.cli import SOFTWARE_WEBGL_FLAGS, _build_parser, _configure_software_webgl

MAP_WEB_ROOT = Path(__file__).resolve().parents[3] / "ui/web/map"


def test_map_page_uses_offline_maplibre_deck_bundle() -> None:
    html = (MAP_WEB_ROOT / "index.html").read_text(encoding="utf-8")
    blank_style = json.loads((MAP_WEB_ROOT / "styles/blank-style.json").read_text(encoding="utf-8"))

    assert "https://" not in html
    assert "http://" not in html
    assert 'href="bundle/maplibre-gl.css"' in html
    assert 'src="bundle/map.js"' in html
    assert '<html lang="zh-CN" data-theme="light">' in html
    assert (MAP_WEB_ROOT / "bundle/maplibre-gl.css").is_file()
    assert (MAP_WEB_ROOT / "bundle/map.js").is_file()
    assert (MAP_WEB_ROOT / "bundle/map.js.LEGAL.txt").is_file()
    assert blank_style["sources"] == {}
    assert blank_style["layers"] == [
        {
            "id": "background",
            "type": "background",
            "paint": {"background-color": "#f1f3f9"},
        }
    ]


def test_map_dependencies_and_server_build_engines_are_pinned() -> None:
    package = json.loads((MAP_WEB_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((MAP_WEB_ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert package["engines"] == {"node": ">=16.20.2 <17", "npm": ">=8.19.4 <9"}
    assert package["dependencies"] == {
        "@deck.gl/core": "9.3.7",
        "@deck.gl/layers": "9.3.7",
        "@deck.gl/mapbox": "9.3.7",
        "@deck.gl/mesh-layers": "9.3.7",
        "maplibre-gl": "5.12.0",
    }
    assert package["overrides"] == {"@mapbox/jsonlint-lines-primitives": "2.0.2"}
    assert lock["lockfileVersion"] == 2


def test_map_source_uses_interleaved_meter_offset_layers_with_snapshot_interpolation() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")

    assert "new MapboxOverlay" in source
    assert "interleaved: true" in source
    assert "COORDINATE_SYSTEM.METER_OFFSETS" in source
    assert "lineCapRounded: true" in source
    assert "lineJointRounded: true" in source
    assert source.count("new GeoJsonLayer") == 6
    assert source.count("new ScatterplotLayer") == 6
    assert source.count("new PolygonLayer") == 5
    assert "new ScenegraphLayer" not in source
    assert "new LightingEffect" in source
    assert "../../assets/models/truck/truck.gltf" not in source
    assert "setNetwork(network)" in source
    assert "setVehicles(vehicles)" in source
    assert "setTrafficLights(trafficLights)" in source
    assert 'new Set(["sumo_lane", "sumo_internal_lane"])' in source
    assert 'const SUMO_JUNCTION_ROLE = "sumo_junction";' in source
    assert "state.roadCasings = externalLanes" in source
    assert "focusVehicle(vehicleId)" in source
    assert "setInterval" not in source
    assert "requestAnimationFrame" in source
    assert "VehicleSnapshotPlayback" in source
    assert "bufferFrames: 2" in source
    assert "cancelAnimationFrame" in source
    assert "function isAmbulance(vehicle)" in source
    assert "function isStaticObstacle(vehicle)" in source
    assert "trafficverse-obstacle-bodies" in source
    legend_html = (MAP_WEB_ROOT / "index.html").read_text(encoding="utf-8")
    assert "救护车" not in legend_html
    assert "障碍物" not in legend_html


def test_signal_layers_remain_legible_and_render_above_vehicles() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    signal_source = source.split("function signalLayers", maxsplit=1)[1].split(
        "function vehicleLayers", maxsplit=1
    )[0]

    assert "radiusMinPixels: 8" in signal_source
    assert "radiusMinPixels: 5" in signal_source
    assert "radiusMaxPixels" not in signal_source
    assert "lineWidthMinPixels: 2" in signal_source
    assert (
        "const showSignalHalo = map.getZoom() < LAYER_STYLE.detailedVehicleMinZoom" in signal_source
    )
    assert "data: showSignalHalo ? state.signalPoints : []" in signal_source
    assert "layers: [...cachedRoadLayers, ...vehicleLayers(), ...cachedSignalLayers]" in source


def test_flat_map_layers_disable_depth_test_to_prevent_zoom_z_fighting() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert (
        'const FLAT_LAYER_PARAMETERS = {depthCompare: "always", depthWriteEnabled: false};'
        in source
    )
    assert source.count("parameters: FLAT_LAYER_PARAMETERS") >= 8
    assert 'depthCompare:"always",depthWriteEnabled:!1' in bundle


def test_map_supports_command_drag_bearing_rotation_without_leaving_2d() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert "function enableCommandDragRotation()" in source
    assert "event.metaKey" in source
    assert 'addEventListener("mousedown", startRotation, true)' in source
    assert "map.jumpTo({bearing})" in source
    assert "maxPitch: 0" in source
    assert "pitchWithRotate: false" in source
    assert "enableCommandDragRotation();" in source
    assert "metaKey" in bundle


def test_map_is_fixed_to_2d_and_view_mode_is_not_exposed_to_the_qt_host() -> None:
    html = (MAP_WEB_ROOT / "index.html").read_text(encoding="utf-8")
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    host = (MAP_WEB_ROOT.parents[1] / "widgets/maplibre_deck_map.py").read_text(encoding="utf-8")

    assert 'data-view-mode="2d"' not in html
    assert 'data-view-mode="3d"' not in html
    assert ">2D</button>" not in html
    assert ">3D</button>" not in html
    assert 'id="reset-view"' in html
    assert 'viewMode: "2d"' in source
    assert '"3d":' not in source
    assert "function setViewMode" not in source
    assert "setViewMode(viewMode) {\n    setViewMode(viewMode);\n  }" not in source
    assert "def set_view_mode(self, view_mode: str)" not in host
    assert 'self._dispatch("setViewMode", view_mode)' not in host


def test_map_reset_uses_one_camera_transition_for_bounds_and_orientation() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")
    reset_view = source.split("function resetView", maxsplit=1)[1].split(
        "function enableCommandDragRotation", maxsplit=1
    )[0]

    assert "map.fitBounds(state.networkBounds" in reset_view
    assert "pitch: 0" in reset_view
    assert "bearing: 0" in reset_view
    assert "map.easeTo" not in reset_view
    assert "maxZoom:18,pitch:0,bearing:0" in bundle


def test_live_map_exposes_a_maximize_control_above_navigation_and_resizes_in_place() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")
    host = (MAP_WEB_ROOT.parents[1] / "widgets/maplibre_deck_map.py").read_text(encoding="utf-8")

    assert "class MapMaximizeControl" in source
    assert 'aria-label", "最大化地图"' in source
    assert 'title = "最大化地图"' in source
    assert "state.bridge.toggleMapMaximize()" in source
    assert "setMaximizeEnabled(enabled)" in source
    assert "setMaximized(maximized)" in source
    assert "map.resize();" in source
    maximize_control = source.index('map.addControl(maximizeControl, "top-right")')
    navigation_control = source.index(
        'map.addControl(new maplibregl.NavigationControl({visualizePitch: false}), "top-right")'
    )
    assert maximize_control < navigation_control
    assert ".trafficverse-maximize-control" in css
    assert ".trafficverse-maximize-icon::before" in css
    assert ".trafficverse-maximize-icon::after" in css
    assert "\\u6700\\u5927\\u5316\\u5730\\u56FE" in bundle
    assert "\\u8FD8\\u539F\\u5730\\u56FE" in bundle
    assert "maximize_requested = Signal()" in host
    assert "show_maximize: bool = False" in host
    assert 'self._dispatch("setMaximizeEnabled", show_maximize)' in host
    assert "def set_maximized(self, maximized: bool)" in host


def test_scenario_camera_fit_runs_only_once_after_vehicle_bounds_are_available() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    scenario_fit = source.split("function fitScenarioVehicles", maxsplit=1)[1].split(
        "function enableCommandDragRotation", maxsplit=1
    )[0]

    disable_follow = scenario_fit.index("state.followScenarioVehicles = false;")
    fit_bounds = scenario_fit.index("map.fitBounds(bounds")
    assert disable_follow < fit_bounds
    assert "performance.now()" not in scenario_fit


def test_map_visuals_are_externalized_and_support_light_theme() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    style = (MAP_WEB_ROOT / "src/style.js").read_text(encoding="utf-8")
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert 'from "./style.js"' in source
    assert "setTheme(themeName)" in source
    assert "dark: {" in style
    assert "light: {" in style
    assert 'background: "#141414"' in style
    assert "laneBoundary: [237, 238, 232, 205]" in style
    assert 'background: "#f1f3f9"' in style
    assert "roadCasing: [255, 255, 255, 255]" in style
    assert "roadSurface: [255, 255, 255, 255]" in style
    assert "roadSurfaceFast: [255, 255, 255, 255]" in style
    assert "junctionSurface: [255, 255, 255, 255]" in style
    assert "laneBoundary: [252, 234, 135, 255]" in style
    assert style.count("showLaneMarkings: false") == 2
    assert "showLaneMarkings: true" not in style
    assert 'theme: "light"' in source
    assert "createLightingEffect(MAP_THEMES.light)" in source
    assert "automated: [47, 137, 230]" in style
    assert "roadSurface:" in style
    assert "laneBoundary:" in style
    assert "vehicleGlass:" in style
    assert ':root[data-theme="light"]' in css
    assert "--map-background: #141414;" in css
    assert "--map-background: #f1f3f9;" in css
    assert "setTheme" in bundle
    assert "#f1f3f9" in bundle


def test_map_derives_clear_lane_boundaries_and_dashed_markings_from_lane_geometry() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    style = (MAP_WEB_ROOT / "src/style.js").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert "function offsetLaneBoundary(feature, side)" in source
    assert "function dashedLaneMarkings(feature)" in source
    assert 'id: "trafficverse-road-shadow"' in source
    assert 'id: "trafficverse-lane-boundaries"' in source
    assert 'id: "trafficverse-lane-markings"' in source
    assert "data: theme.showLaneMarkings ? state.laneMarkings : EMPTY_NETWORK" in source
    assert "state.laneBoundaries" in source
    assert "state.laneMarkings" in source
    assert "laneBoundaryWidthM" in style
    assert "laneMarkingDashM" in style
    assert "trafficverse-lane-boundaries" in bundle
    assert "trafficverse-lane-markings" in bundle


def test_map_renders_automation_colored_vehicle_models_with_zoom_lod() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    models = (MAP_WEB_ROOT / "src/vehicle_models.mjs").read_text(encoding="utf-8")
    style = (MAP_WEB_ROOT / "src/style.js").read_text(encoding="utf-8")
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert "function orientedVehiclePoint(vehicle, forwardM, lateralM" in source
    assert "function vehicleBodyPolygon(vehicle" in source
    assert "function vehicleDetailParts(vehicles)" in source
    assert "function vehiclePartColor(part)" in source
    assert 'id: "trafficverse-vehicle-shadows"' in source
    assert 'id: "trafficverse-vehicle-dots"' in source
    assert 'id: "trafficverse-compact-ambulances"' in source
    assert 'id: "trafficverse-vehicle-bodies"' in source
    assert 'id: "trafficverse-vehicle-details"' in source
    assert 'id: "trafficverse-vehicle-headlights"' in source
    assert 'id: "trafficverse-emergency-highlight"' in source
    assert "new ScenegraphLayer" not in source
    assert "vehicle.heading_rad" in source
    assert "map.getZoom() >= LAYER_STYLE.detailedVehicleMinZoom" in source
    assert "const detailedVehicles = showDetailedVehicles ? vehicles : []" in source
    assert "const compactVehicles = showDetailedVehicles ? [] : vehicles" in source
    assert "const compactAmbulances = compactVehicles.filter(isAmbulance)" in source
    assert "new IconLayer" in source
    assert "COMPACT_AMBULANCE_ICON" in source
    assert 'kind: "rear-marker"' in source
    assert "vehicleTailLight" not in source
    assert 'map.on("zoomend", renderLayers)' in source
    assert "getFillColor: vehicleColor" in source
    assert all(f'"{kind}"' in models for kind in ("sedan", "truck", "trailer", "ambulance"))
    assert "isAmbulanceVehicle" in models
    assert "stableStringHash" in models
    level_colors = {
        "L0": ("85, 183, 233", "#55b7e9"),
        "L1": ("54, 157, 214", "#369dd6"),
        "L2": ("37, 129, 196", "#2581c4"),
        "L3": ("56, 104, 183", "#3868b7"),
        "L4": ("85, 79, 167", "#554fa7"),
        "L5": ("116, 55, 143", "#74378f"),
    }
    for level, (rgb, hex_color) in level_colors.items():
        assert style.count(f"{level}: [{rgb}]") == 4
        assert css.count(f"--{level.lower()}: {hex_color}") == 2
        assert f"{level}:[{rgb.replace(' ', '')}]" in bundle
    assert 'vehicle.automation_level === "L5" ? theme.vehicleOutline' in source
    assert "vehicleTailLight" not in style
    assert "emergencyVehicle: [239, 68, 68]" in style
    assert "emergencyVehicle: [220, 38, 38]" in style
    assert "trafficverse-vehicle-bodies" in bundle
    assert "trafficverse-vehicle-dots" in bundle
    assert "trafficverse-compact-ambulances" in bundle
    assert "trafficverse-vehicle-details" in bundle
    assert "trafficverse-vehicle-headlights" in bundle
    assert "trafficverse-emergency-highlight" in bundle


def test_map_fits_the_complete_occasional_accident_vehicle_group() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert '(vehicle?.vehicle_id ?? "").startsWith("accident_")' in source
    assert '.startsWith("accident_")' in source
    assert "accident_" in bundle


def test_map_hud_has_a_safe_inset_from_the_webview_edge() -> None:
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    hud_rules = css.split("#map-hud {", maxsplit=1)[1].split("}", maxsplit=1)[0]

    assert "left: 18px;" in hud_rules
    assert "padding: 10px 12px;" in hud_rules
    assert "padding-left: 0;" not in hud_rules
    assert "border-left: 0;" not in hud_rules


def test_map_hud_shows_large_automation_and_signal_legends_only() -> None:
    html = (MAP_WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'aria-label="地图图例"' in html
    assert html.count('class="legend-item"') == 7
    assert all(label in html for label in ("L0", "L1", "L2", "L3", "L4", "L5", "交通信号"))
    assert "救护车" not in html
    assert "障碍物" not in html
    assert all(
        f"legend-icon {icon}" in html for icon in ("l0", "l1", "l2", "l3", "l4", "l5", "signal")
    )
    assert "legend-icon emergency" not in html
    assert "legend-icon obstacle" not in html
    legend_rules = css.split(".map-legend {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "font-size: 20px;" in legend_rules
    assert "map-eyebrow" not in html
    assert "map-title" not in html
    assert 'id="map-status" hidden' in html
    assert ".legend-icon.ai" in css
    assert ".legend-icon.automated" in css
    assert ".legend-icon.signal" in css


def test_map_legend_visibility_can_be_controlled_by_the_qt_host() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")
    host = (MAP_WEB_ROOT.parents[1] / "widgets/maplibre_deck_map.py").read_text(encoding="utf-8")

    assert "setLegendVisible(visible)" in source
    assert 'document.getElementById("map-hud").hidden = !visible;' in source
    assert "#map-hud[hidden]" in css
    assert "setLegendVisible" in bundle
    assert "show_legend: bool = True" in host
    assert 'self._dispatch("setLegendVisible", show_legend)' in host


def test_legend_free_preview_uses_symmetric_padding_to_center_the_network() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")

    assert "legendVisible: true" in source
    assert "const verticalPaddingPx = state.legendVisible ? 100 : 46" in source
    assert "top: verticalPaddingPx" in source
    assert "bottom: 46" in source


def test_map_renders_scripted_accident_zone_without_moving_the_collision_keyframe() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    host = (MAP_WEB_ROOT.parents[1] / "widgets/maplibre_deck_map.py").read_text(encoding="utf-8")
    collision_handler = source.split("setCollisionVehicleIds(vehicleIds) {", maxsplit=1)[1].split(
        "setTrafficLights(trafficLights)", maxsplit=1
    )[0]

    assert "collisionVehicleIds: new Set()" in source
    assert "function isScriptedAccidentVehicle(vehicle)" in source
    assert 'vehicleId.startsWith("accident_")' in source
    assert "function collisionZonePolygon(vehicles)" in source
    assert "vehicles.flatMap((vehicle) => vehicleBodyPolygon(vehicle))" in source
    assert "collisionZonePaddingM" in source
    assert "Math.max(9" not in source
    assert "Math.max(5.5" not in source
    assert 'id: "trafficverse-collision-zone"' in source
    assert "data: collisionZonePolygon(collisionVehicles)" in source
    assert "isScriptedAccidentVehicle(vehicle)" in source
    assert "trafficverse-collision-halos" not in source
    assert "trafficverse-collision-markers" not in source
    assert "setCollisionVehicleIds(vehicleIds)" in source
    assert "state.collisionVehicleIds = new Set" in collision_handler
    assert "renderVehicleLayers();" in collision_handler
    assert "updateMapStatus();" in collision_handler
    assert "fitScenarioVehicles" not in collision_handler
    assert "fitBounds" not in collision_handler
    assert "easeTo" not in collision_handler
    assert "jumpTo" not in collision_handler
    assert "followScenarioVehicles" not in collision_handler
    assert "def set_collision_vehicle_ids" in host
    assert 'self._dispatch("setCollisionVehicleIds", payload)' in host


def test_truck_model_is_local_and_checksum_documented() -> None:
    model_root = MAP_WEB_ROOT.parents[1] / "assets/models/truck"
    notice = (model_root / "README.md").read_text(encoding="utf-8")
    gltf_bytes = (model_root / "truck.gltf").read_bytes().replace(b"\r\n", b"\n")

    assert len(gltf_bytes) == 58_706
    assert (model_root / "truck.bin").stat().st_size == 198_096
    assert "CC BY 4.0" in notice
    assert "fbd30d52ebef8079203e5e24bd963a75ffd060beb64bc1535cc2a05dd9e04da7" in notice


def test_ui_software_webgl_is_explicit_and_preserves_existing_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _build_parser().parse_args(["ui", "--allow-software-webgl"])
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--remote-debugging-port=0")

    _configure_software_webgl()

    assert args.allow_software_webgl is True
    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split() == [
        "--remote-debugging-port=0",
        "--ignore-gpu-blocklist",
        "--enable-unsafe-swiftshader",
        "--disable-gpu-compositing",
    ]
    assert len(SOFTWARE_WEBGL_FLAGS) == 3
