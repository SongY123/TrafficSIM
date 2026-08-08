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
    assert (MAP_WEB_ROOT / "bundle/maplibre-gl.css").is_file()
    assert (MAP_WEB_ROOT / "bundle/map.js").is_file()
    assert (MAP_WEB_ROOT / "bundle/map.js.LEGAL.txt").is_file()
    assert blank_style["sources"] == {}
    assert blank_style["layers"] == [
        {
            "id": "background",
            "type": "background",
            "paint": {"background-color": "#141414"},
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


def test_map_source_uses_interleaved_meter_offset_layers_without_polling() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")

    assert "new MapboxOverlay" in source
    assert "interleaved: true" in source
    assert "COORDINATE_SYSTEM.METER_OFFSETS" in source
    assert "lineCapRounded: true" in source
    assert "lineJointRounded: true" in source
    assert source.count("new GeoJsonLayer") == 6
    assert source.count("new ScatterplotLayer") == 4
    assert source.count("new PolygonLayer") == 3
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
    assert "requestAnimationFrame" not in source


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
    assert "automated: [47, 137, 230]" in style
    assert "roadSurface:" in style
    assert "laneBoundary:" in style
    assert "vehicleGlass:" in style
    assert ':root[data-theme="light"]' in css
    assert "setTheme" in bundle
    assert "#f2f3f5" in bundle


def test_map_derives_clear_lane_boundaries_and_dashed_markings_from_lane_geometry() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    style = (MAP_WEB_ROOT / "src/style.js").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert "function offsetLaneBoundary(feature, side)" in source
    assert "function dashedLaneMarkings(feature)" in source
    assert 'id: "trafficverse-road-shadow"' in source
    assert 'id: "trafficverse-lane-boundaries"' in source
    assert 'id: "trafficverse-lane-markings"' in source
    assert "state.laneBoundaries" in source
    assert "state.laneMarkings" in source
    assert "laneBoundaryWidthM" in style
    assert "laneMarkingDashM" in style
    assert "trafficverse-lane-boundaries" in bundle
    assert "trafficverse-lane-markings" in bundle


def test_map_renders_oriented_top_down_cars_without_sideways_truck_overlay() -> None:
    source = (MAP_WEB_ROOT / "src/app.js").read_text(encoding="utf-8")
    bundle = (MAP_WEB_ROOT / "bundle/map.js").read_text(encoding="utf-8")

    assert "function orientedVehiclePoint(vehicle, forwardM, lateralM" in source
    assert "function vehicleBodyPolygon(vehicle" in source
    assert "function vehicleCabinPolygon(vehicle" in source
    assert "function vehicleDetailParts()" in source
    assert "function vehiclePartColor(part)" in source
    assert 'id: "trafficverse-vehicle-shadows"' in source
    assert 'id: "trafficverse-vehicle-bodies"' in source
    assert 'id: "trafficverse-vehicle-details"' in source
    assert 'id: "trafficverse-vehicle-headlights"' in source
    assert 'id: "trafficverse-vehicle-models"' not in source
    assert "new ScenegraphLayer" not in source
    assert "vehicle.heading_rad" in source
    assert "LAYER_STYLE.vehicleLengthM * 0.5" in source
    assert "LAYER_STYLE.vehicleWidthM * 0.5" in source
    assert "trafficverse-vehicle-bodies" in bundle
    assert "trafficverse-vehicle-details" in bundle
    assert "trafficverse-vehicle-headlights" in bundle
    assert "trafficverse-vehicle-models" not in bundle


def test_map_hud_has_a_safe_inset_from_the_webview_edge() -> None:
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    hud_rules = css.split("#map-hud {", maxsplit=1)[1].split("}", maxsplit=1)[0]

    assert "left: 18px;" in hud_rules
    assert "padding: 10px 12px;" in hud_rules
    assert "padding-left: 0;" not in hud_rules
    assert "border-left: 0;" not in hud_rules


def test_map_hud_only_shows_the_three_requested_icon_legends() -> None:
    html = (MAP_WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (MAP_WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'aria-label="地图图例"' in html
    assert html.count('class="legend-item"') == 3
    assert all(label in html for label in ("人工智能", "自动驾驶", "交通信号"))
    assert all(
        icon in html for icon in ("legend-icon ai", "legend-icon automated", "legend-icon signal")
    )
    assert "map-eyebrow" not in html
    assert "map-title" not in html
    assert 'id="map-status" hidden' in html
    assert ".legend-icon.ai" in css
    assert ".legend-icon.automated" in css
    assert ".legend-icon.signal" in css


def test_truck_model_is_local_and_checksum_documented() -> None:
    model_root = MAP_WEB_ROOT.parents[1] / "assets/models/truck"
    notice = (model_root / "README.md").read_text(encoding="utf-8")

    assert (model_root / "truck.gltf").stat().st_size == 58_706
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
