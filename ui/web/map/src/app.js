import {
  AmbientLight,
  COORDINATE_SYSTEM,
  DirectionalLight,
  LightingEffect
} from "@deck.gl/core";
import {GeoJsonLayer, ScatterplotLayer} from "@deck.gl/layers";
import {MapboxOverlay} from "@deck.gl/mapbox";
import {ScenegraphLayer} from "@deck.gl/mesh-layers";
import maplibregl from "maplibre-gl";

import blankStyle from "../styles/blank-style.json";
import {LAYER_STYLE, MAP_THEMES} from "./style.js";

const EARTH_RADIUS_M = 6378137;
const RAD_TO_DEG = 180 / Math.PI;
const EMPTY_NETWORK = {type: "FeatureCollection", features: []};
const TRUCK_MODEL_URL = new URL(
  "../../assets/models/truck/truck.gltf",
  window.location.href
).href;
const PAGE_MODE = new URLSearchParams(window.location.search).get("mode") ?? "live";
const VIEW_CONFIG = {
  "2d": {pitch: 0, bearing: 0},
  "3d": {pitch: 48, bearing: -18}
};
const FLAT_LAYER_PARAMETERS = {depthCompare: "always", depthWriteEnabled: false};
const SUMO_LANE_ROLES = new Set(["sumo_lane", "sumo_internal_lane"]);
const SUMO_JUNCTION_ROLE = "sumo_junction";

function createLightingEffect(theme) {
  return new LightingEffect({
    ambientLight: new AmbientLight({color: theme.ambientLight, intensity: 1.4}),
    keyLight: new DirectionalLight({
      color: theme.keyLight,
      intensity: 2.2,
      direction: [-3, -5, -8]
    })
  });
}

const state = {
  bridge: null,
  network: EMPTY_NETWORK,
  roadNetwork: EMPTY_NETWORK,
  roadCasings: EMPTY_NETWORK,
  roadGuides: EMPTY_NETWORK,
  junctionSurfaces: EMPTY_NETWORK,
  signalPoints: [],
  trafficLights: new Map(),
  roadResults: new Map(),
  vehicles: [],
  networkBounds: null,
  viewMode: "2d",
  selectedVehicleId: null,
  theme: "dark",
  lightingEffect: createLightingEffect(MAP_THEMES.dark)
};

document.documentElement.dataset.theme = state.theme;
document.body.dataset.mode = PAGE_MODE;

const statusElement = document.getElementById("map-status");
const viewButtons = Array.from(document.querySelectorAll("[data-view-mode]"));

function setStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.dataset.state = isError ? "error" : "ready";
}

let map;
try {
  map = new maplibregl.Map({
    container: "map",
    style: blankStyle,
    center: [0, 0],
    zoom: 15,
    pitch: VIEW_CONFIG[state.viewMode].pitch,
    bearing: VIEW_CONFIG[state.viewMode].bearing,
    maxPitch: 85,
    attributionControl: false,
    antialias: true
  });
} catch (error) {
  setStatus(`地图初始化失败：${error.message}`, true);
  throw error;
}

const overlay = new MapboxOverlay({
  interleaved: true,
  effects: [state.lightingEffect],
  layers: []
});

function activeTheme() {
  return MAP_THEMES[state.theme];
}

function toMapPosition(position) {
  if (!position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) {
    return [0, 0, 0];
  }
  return [position.x, position.y, Number.isFinite(position.z) ? position.z : 0];
}

function phaseColor(signalId, alpha = 245) {
  const phase = state.trafficLights.get(signalId)?.toUpperCase();
  const colors = activeTheme().signal;
  if (phase === "GREEN") {
    return [...colors.green, alpha];
  }
  if (phase === "YELLOW") {
    return [...colors.yellow, alpha];
  }
  if (phase === "RED") {
    return [...colors.red, alpha];
  }
  return [...colors.unknown, alpha];
}

function vehicleColor(vehicle, alpha = 245) {
  const color = vehicle.automation_level === "HUMAN"
    ? activeTheme().vehicle.human
    : activeTheme().vehicle.automated;
  return [...color, alpha];
}

function normalizeRoadResultId(rawRoadId) {
  if (rawRoadId === undefined || rawRoadId === null) {
    return "";
  }
  const roadId = String(rawRoadId);
  if (roadId.startsWith("road:")) {
    return roadId.slice("road:".length);
  }
  return roadId.startsWith("-") ? roadId.slice(1) : roadId;
}

function roadResultColor(feature) {
  const properties = feature.properties ?? {};
  const rawRoadId = properties.road_id ?? properties.edge_id ?? properties.sumo_edge_id;
  const roadId = normalizeRoadResultId(rawRoadId);
  const result = roadId ? state.roadResults.get(roadId) : null;
  if (!result) {
    return null;
  }
  const colors = activeTheme().roadResult;
  const colorByLevel = {
    "畅通": colors.free,
    "较快": colors.fast,
    "一般": colors.normal,
    "缓行": colors.slow,
    "拥堵": colors.congested
  };
  return [...(colorByLevel[result.congestion_level] ?? colors.normal), 245];
}

function focusVehicle(vehicleId, duration = 600) {
  const vehicle = state.vehicles.find((candidate) => candidate.vehicle_id === vehicleId);
  if (!vehicle) {
    return;
  }
  state.selectedVehicleId = vehicleId;
  const [x, y] = toMapPosition(vehicle.position);
  const view = VIEW_CONFIG[state.viewMode];
  map.easeTo({
    center: localMetersToLngLat(x, y),
    zoom: 18.5,
    pitch: view.pitch,
    bearing: view.bearing,
    duration
  });
  renderLayers();
}

function selectVehicle({object}) {
  if (object) {
    focusVehicle(object.vehicle_id);
  }
  if (object && state.bridge) {
    state.bridge.selectVehicle(object.vehicle_id);
  }
}

function roadLayers() {
  const theme = activeTheme();
  const common = {
    data: state.roadNetwork,
    coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
    coordinateOrigin: [0, 0, 0],
    filled: false,
    stroked: true,
    lineCapRounded: true,
    lineJointRounded: true,
    pickable: false,
    parameters: FLAT_LAYER_PARAMETERS
  };
  return [
    new GeoJsonLayer({
      id: "trafficverse-junction-surfaces",
      data: state.junctionSurfaces,
      coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
      coordinateOrigin: [0, 0, 0],
      filled: true,
      stroked: false,
      pickable: false,
      getFillColor: theme.junctionSurface,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new GeoJsonLayer({
      ...common,
      id: "trafficverse-road-casing",
      data: state.roadCasings,
      lineWidthUnits: "meters",
      getLineWidth: (feature) =>
        (feature.properties?.width_m ?? LAYER_STYLE.roadSurfaceWidthM) +
        LAYER_STYLE.roadCasingExtraWidthM,
      lineWidthMinPixels: 3,
      getLineColor: theme.roadCasing
    }),
    new GeoJsonLayer({
      ...common,
      id: "trafficverse-road-surface",
      lineWidthUnits: "meters",
      getLineWidth: (feature) =>
        (feature.properties?.width_m ?? LAYER_STYLE.roadSurfaceWidthM) +
        (PAGE_MODE === "replay" ? 0.8 : 0),
      lineWidthMinPixels: PAGE_MODE === "replay" ? 4 : 2,
      getLineColor: (feature) =>
        roadResultColor(feature) ?? (
          feature.properties?.speed_limit_mps >= 20
            ? theme.roadFast
            : theme.roadRegular
        ),
    }),
    new GeoJsonLayer({
      ...common,
      id: "trafficverse-lane-guides",
      data: PAGE_MODE === "replay" ? EMPTY_NETWORK : state.roadGuides,
      lineWidthUnits: "pixels",
      getLineWidth: LAYER_STYLE.laneGuideWidthPx,
      getLineColor: theme.laneGuide
    })
  ];
}

function signalLayers(phaseTrigger) {
  const theme = activeTheme();
  const common = {
    data: state.signalPoints,
    coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
    coordinateOrigin: [0, 0, 0],
    getPosition: (signal) => signal.position,
    radiusUnits: "meters",
    pickable: false,
    parameters: FLAT_LAYER_PARAMETERS,
    updateTriggers: {getFillColor: phaseTrigger}
  };
  return [
    new ScatterplotLayer({
      ...common,
      id: "trafficverse-signal-halo",
      getFillColor: (signal) => phaseColor(signal.signalId, 45),
      getRadius: LAYER_STYLE.signalHaloRadiusM,
      radiusMinPixels: 5,
      radiusMaxPixels: 12
    }),
    new ScatterplotLayer({
      ...common,
      id: "trafficverse-signals",
      getFillColor: (signal) => phaseColor(signal.signalId),
      getRadius: LAYER_STYLE.signalRadiusM,
      radiusMinPixels: 3,
      radiusMaxPixels: 7,
      stroked: true,
      getLineColor: theme.signalOutline,
      lineWidthMinPixels: 1
    })
  ];
}

function vehicleLayers() {
  const theme = activeTheme();
  const common = {
    data: state.vehicles,
    coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
    coordinateOrigin: [0, 0, 0],
    getPosition: (vehicle) => toMapPosition(vehicle.position),
    pickable: true,
    onClick: selectVehicle
  };
  const layers = [
    new ScatterplotLayer({
      ...common,
      id: "trafficverse-vehicle-halo",
      getFillColor: (vehicle) => vehicleColor(vehicle, 55),
      getRadius: (vehicle) =>
        vehicle.vehicle_id === state.selectedVehicleId
          ? 7
          : state.viewMode === "3d"
            ? 4.6
            : 3.6,
      radiusUnits: "meters",
      radiusMinPixels: 5,
      parameters: FLAT_LAYER_PARAMETERS,
      updateTriggers: {getFillColor: state.theme}
    })
  ];
  if (state.viewMode === "3d") {
    layers.push(
      new ScenegraphLayer({
        ...common,
        id: "trafficverse-vehicle-models",
        scenegraph: TRUCK_MODEL_URL,
        sizeScale: LAYER_STYLE.vehicleModelScale,
        sizeMinPixels: 18,
        sizeMaxPixels: 80,
        getTranslation: [0, 0, 0.45],
        getColor: (vehicle) => vehicleColor(vehicle),
        getOrientation: (vehicle) => [
          0,
          180 - (Number.isFinite(vehicle.heading_rad) ? vehicle.heading_rad * RAD_TO_DEG : 0),
          90
        ],
        _lighting: "pbr",
        updateTriggers: {getColor: state.theme},
        onError: (error) => setStatus(`三维车辆模型加载失败：${error.message}`, true)
      })
    );
  } else {
    layers.push(
      new ScatterplotLayer({
        ...common,
        id: "trafficverse-vehicle-markers",
        getFillColor: vehicleColor,
        getRadius: LAYER_STYLE.vehicleMarkerRadiusM,
        radiusUnits: "meters",
        radiusMinPixels: 4,
        stroked: true,
        getLineColor: theme.vehicleOutline,
        lineWidthMinPixels: 1,
        parameters: FLAT_LAYER_PARAMETERS,
        updateTriggers: {getFillColor: state.theme, getLineColor: state.theme}
      })
    );
  }
  return layers;
}

function renderLayers() {
  const phaseTrigger = [state.theme, ...Array.from(state.trafficLights.entries()).flat()];
  overlay.setProps({
    effects: [state.lightingEffect],
    layers: [...roadLayers(), ...signalLayers(phaseTrigger), ...vehicleLayers()]
  });
  setStatus(
    `车道 ${state.roadNetwork.features.length} · 信号 ${state.signalPoints.length} · 车辆 ${state.vehicles.length}`
  );
}

function signalPointFromFeature(feature) {
  const coordinates = feature?.geometry?.coordinates;
  const signalId = feature?.properties?.signal_id;
  if (
    feature?.geometry?.type !== "Point" ||
    !signalId ||
    !Array.isArray(coordinates) ||
    !Number.isFinite(coordinates[0]) ||
    !Number.isFinite(coordinates[1])
  ) {
    return null;
  }
  return {
    signalId,
    position: [coordinates[0], coordinates[1], coordinates[2] ?? 0]
  };
}

function localMetersToLngLat(x, y) {
  return [x * RAD_TO_DEG / EARTH_RADIUS_M, y * RAD_TO_DEG / EARTH_RADIUS_M];
}

function visitCoordinates(coordinates, visitor) {
  if (!Array.isArray(coordinates)) {
    return;
  }
  if (Number.isFinite(coordinates[0]) && Number.isFinite(coordinates[1])) {
    visitor(coordinates[0], coordinates[1]);
    return;
  }
  for (const child of coordinates) {
    visitCoordinates(child, visitor);
  }
}

function resetView(duration = 500) {
  if (!state.networkBounds || state.networkBounds.isEmpty()) {
    return;
  }
  map.fitBounds(state.networkBounds, {
    padding: {top: 100, right: 46, bottom: 46, left: 46},
    duration,
    maxZoom: 18
  });
  const view = VIEW_CONFIG[state.viewMode];
  map.easeTo({pitch: view.pitch, bearing: view.bearing, duration});
}

function enableCommandDragRotation() {
  const container = map.getCanvasContainer();
  let dragStart = null;

  function startRotation(event) {
    if (event.button !== 0 || !event.metaKey) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    dragStart = {
      x: event.clientX,
      y: event.clientY,
      bearing: map.getBearing(),
      pitch: map.getPitch()
    };
    container.style.cursor = "grabbing";
  }

  function rotate(event) {
    if (!dragStart) {
      return;
    }
    event.preventDefault();
    const bearing = dragStart.bearing + (event.clientX - dragStart.x) * 0.35;
    const pitch = Math.max(
      0,
      Math.min(85, dragStart.pitch - (event.clientY - dragStart.y) * 0.3)
    );
    map.jumpTo({bearing, pitch});
  }

  function stopRotation() {
    if (!dragStart) {
      return;
    }
    dragStart = null;
    container.style.cursor = "";
  }

  container.addEventListener("mousedown", startRotation, true);
  window.addEventListener("mousemove", rotate, true);
  window.addEventListener("mouseup", stopRotation, true);
  window.addEventListener("blur", stopRotation);
  map.once("remove", () => {
    container.removeEventListener("mousedown", startRotation, true);
    window.removeEventListener("mousemove", rotate, true);
    window.removeEventListener("mouseup", stopRotation, true);
    window.removeEventListener("blur", stopRotation);
  });
}

function applyTheme(themeName) {
  if (!(themeName in MAP_THEMES)) {
    return;
  }
  state.theme = themeName;
  const theme = activeTheme();
  state.lightingEffect = createLightingEffect(theme);
  document.documentElement.dataset.theme = themeName;
  if (map.isStyleLoaded()) {
    map.setPaintProperty("background", "background-color", theme.background);
    renderLayers();
  }
}

function fitNetwork(network) {
  const bounds = new maplibregl.LngLatBounds();
  for (const feature of network.features ?? []) {
    visitCoordinates(feature?.geometry?.coordinates, (x, y) => {
      bounds.extend(localMetersToLngLat(x, y));
    });
  }
  state.networkBounds = bounds;
  resetView(0);
}

function setViewMode(viewMode) {
  if (!(viewMode in VIEW_CONFIG)) {
    return;
  }
  state.viewMode = viewMode;
  for (const button of viewButtons) {
    button.classList.toggle("active", button.dataset.viewMode === viewMode);
  }
  const view = VIEW_CONFIG[viewMode];
  map.easeTo({pitch: view.pitch, bearing: view.bearing, duration: 500});
  renderLayers();
}

for (const button of viewButtons) {
  button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
}
document.getElementById("reset-view").addEventListener("click", () => resetView());

window.TrafficVerseMap = {
  setNetwork(network) {
    state.network = network?.type === "FeatureCollection" ? network : EMPTY_NETWORK;
    const lineFeatures = state.network.features.filter(
      (feature) => feature.geometry?.type === "LineString"
    );
    const sumoLineFeatures = lineFeatures.filter((feature) =>
      SUMO_LANE_ROLES.has(feature.properties?.trafficverse_role)
    );
    const replayRoadFeatures = lineFeatures.filter((feature) => {
      const properties = feature.properties ?? {};
      const rawRoadId = properties.road_id ?? properties.edge_id ?? properties.sumo_edge_id;
      const roadId = normalizeRoadResultId(rawRoadId);
      return roadId !== "" && !roadId.startsWith(":") && (
        properties.trafficverse_role === undefined ||
        properties.trafficverse_role === null ||
        properties.trafficverse_role === "sumo_lane"
      );
    });
    const roadFeatures = PAGE_MODE === "replay"
      ? replayRoadFeatures
      : sumoLineFeatures.length > 0
        ? sumoLineFeatures
        : lineFeatures;
    state.roadNetwork = {
      type: "FeatureCollection",
      features: roadFeatures
    };
    state.roadGuides = {
      type: "FeatureCollection",
      features: roadFeatures.filter(
        (feature) => feature.properties?.trafficverse_role !== "sumo_internal_lane"
      )
    };
    state.roadCasings = state.roadGuides;
    state.junctionSurfaces = {
      type: "FeatureCollection",
      features: state.network.features.filter(
        (feature) => feature.properties?.trafficverse_role === SUMO_JUNCTION_ROLE
      )
    };
    state.signalPoints = state.network.features
      .map(signalPointFromFeature)
      .filter((point) => point !== null);
    fitNetwork(state.network);
    renderLayers();
  },
  setVehicles(vehicles) {
    state.vehicles = Array.isArray(vehicles) ? vehicles : [];
    renderLayers();
  },
  setTrafficLights(trafficLights) {
    state.trafficLights = new Map(
      (Array.isArray(trafficLights) ? trafficLights : []).map((light) => [
        light.signal_id,
        light.phase
      ])
    );
    renderLayers();
  },
  setRoadResults(results) {
    state.roadResults = new Map(
      (Array.isArray(results) ? results : []).map((result) => [
        normalizeRoadResultId(result.road_id),
        result
      ])
    );
    renderLayers();
  },
  focusVehicle(vehicleId) {
    focusVehicle(vehicleId);
  },
  setTheme(themeName) {
    applyTheme(themeName);
  }
};

function connectQtBridge() {
  if (!window.qt || !window.QWebChannel) {
    setStatus("地图已就绪 · 浏览器预览模式");
    return;
  }
  new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
    state.bridge = channel.objects.trafficVerseBridge;
    state.bridge.mapReady();
    setStatus("地图已就绪");
  });
}

map.once("load", () => {
  map.addControl(overlay);
  map.addControl(new maplibregl.NavigationControl({visualizePitch: true}), "top-right");
  enableCommandDragRotation();
  applyTheme(state.theme);
  setViewMode(state.viewMode);
  connectQtBridge();
});
map.on("error", (event) => {
  const message = event?.error?.message ?? "未知错误";
  setStatus(`地图资源加载失败：${message}`, true);
});
