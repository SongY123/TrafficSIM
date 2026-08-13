import {
  AmbientLight,
  COORDINATE_SYSTEM,
  DirectionalLight,
  LightingEffect
} from "@deck.gl/core";
import {GeoJsonLayer, IconLayer, PolygonLayer, ScatterplotLayer} from "@deck.gl/layers";
import {MapboxOverlay} from "@deck.gl/mapbox";
import maplibregl from "maplibre-gl";

import blankStyle from "../styles/blank-style.json";
import {LAYER_STYLE, MAP_THEMES} from "./style.js";
import {VehicleSnapshotPlayback} from "./vehicle_interpolation.mjs";
import {
  isAmbulanceVehicle,
  vehicleModelKind,
  vehicleModelSpec
} from "./vehicle_models.mjs";

const EARTH_RADIUS_M = 6378137;
const RAD_TO_DEG = 180 / Math.PI;
const EMPTY_NETWORK = {type: "FeatureCollection", features: []};
const FLAT_LAYER_PARAMETERS = {depthCompare: "always", depthWriteEnabled: false};
const SUMO_LANE_ROLES = new Set(["sumo_lane", "sumo_internal_lane"]);
const SUMO_JUNCTION_ROLE = "sumo_junction";
const COMPACT_AMBULANCE_ICON = Object.freeze({
  url: "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16'%3E%3Crect width='16' height='16' fill='black'/%3E%3C/svg%3E",
  width: 16,
  height: 16,
  anchorX: 8,
  anchorY: 8,
  mask: true
});
function createLightingEffect(theme) {
  return new LightingEffect({
    ambientLight: new AmbientLight({color: theme.ambientLight, intensity: 1.55}),
    keyLight: new DirectionalLight({
      color: theme.keyLight,
      intensity: 2.35,
      direction: [-3, -5, -8]
    })
  });
}

const state = {
  bridge: null,
  network: EMPTY_NETWORK,
  roadNetwork: EMPTY_NETWORK,
  roadCasings: EMPTY_NETWORK,
  laneBoundaries: EMPTY_NETWORK,
  laneMarkings: EMPTY_NETWORK,
  junctionSurfaces: EMPTY_NETWORK,
  signalPoints: [],
  trafficLights: new Map(),
  collisionVehicleIds: new Set(),
  vehicles: [], // Transient render models; authoritative state remains in the latest snapshot.
  authoritativeVehicles: [],
  vehicleAnimationFrame: null,
  vehiclePlayback: new VehicleSnapshotPlayback({bufferFrames: 2}),
  networkBounds: null,
  viewMode: "2d",
  selectedVehicleId: null,
  followScenarioVehicles: true,
  legendVisible: true,
  maximizeEnabled: false,
  maximized: false,
  theme: "light",
  lightingEffect: createLightingEffect(MAP_THEMES.light)
};

document.documentElement.dataset.theme = state.theme;

const statusElement = document.getElementById("map-status");

function setStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.dataset.state = isError ? "error" : "ready";
}

class MapMaximizeControl {
  onAdd() {
    this.container = document.createElement("div");
    this.container.className =
      "maplibregl-ctrl maplibregl-ctrl-group trafficverse-maximize-control";
    this.container.hidden = true;
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.setAttribute("aria-label", "最大化地图");
    this.button.title = "最大化地图";
    this.icon = document.createElement("span");
    this.icon.className = "trafficverse-maximize-icon";
    this.icon.setAttribute("aria-hidden", "true");
    this.button.append(this.icon);
    this.button.addEventListener("click", requestMapMaximizeToggle);
    this.container.append(this.button);
    this.update();
    return this.container;
  }

  onRemove() {
    this.button?.removeEventListener("click", requestMapMaximizeToggle);
    this.container?.remove();
  }

  update() {
    if (!this.container || !this.button) {
      return;
    }
    this.container.hidden = !state.maximizeEnabled;
    const label = state.maximized ? "还原地图" : "最大化地图";
    this.button.setAttribute("aria-label", label);
    this.button.title = label;
    this.button.classList.toggle("is-maximized", state.maximized);
  }
}

let map;
try {
  map = new maplibregl.Map({
    container: "map",
    style: blankStyle,
    center: [0, 0],
    zoom: 15,
    pitch: 0,
    bearing: 0,
    maxPitch: 0,
    pitchWithRotate: false,
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
  layers: [],
  getTooltip: ({object}) => vehicleTooltip(object)
});
const maximizeControl = new MapMaximizeControl();
let cachedRoadLayers = [];
let cachedSignalLayers = [];

function activeTheme() {
  return MAP_THEMES[state.theme];
}

function featureCollection(features) {
  return {type: "FeatureCollection", features};
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
  if (isAmbulance(vehicle)) {
    return [...activeTheme().emergencyVehicle, alpha];
  }
  const color = activeTheme().vehicle[vehicle.automation_level] ?? activeTheme().vehicle.HUMAN;
  return [...color, alpha];
}

function vehicleAccentColor(vehicle, alpha = 245) {
  if (isAmbulance(vehicle)) {
    return [...activeTheme().emergencyVehicleAccent, alpha];
  }
  const color =
    activeTheme().vehicleAccent[vehicle.automation_level] ?? activeTheme().vehicleAccent.HUMAN;
  return [...color, alpha];
}

function isAmbulance(vehicle) {
  return isAmbulanceVehicle(vehicle);
}

function isStaticObstacle(vehicle) {
  return (vehicle?.vehicle_id ?? "").startsWith("static_obstacle_");
}

function isScriptedAccidentVehicle(vehicle) {
  return (vehicle?.vehicle_id ?? "").startsWith("accident_");
}

function vehicleTooltip(vehicle) {
  if (!vehicle?.vehicle_id) {
    return null;
  }
  if (isStaticObstacle(vehicle)) {
    return `${vehicle.vehicle_id}\n固定道路障碍物`;
  }
  const speedKmh = Number.isFinite(vehicle.speed_mps) ? vehicle.speed_mps * 3.6 : 0;
  const identity = isAmbulance(vehicle) ? "救护车" : `等级 ${vehicle.automation_level}`;
  return `${vehicle.vehicle_id}\n${identity} · ${speedKmh.toFixed(1)} km/h\n车道 ${vehicle.lane_id}`;
}

function laneWidthM(feature) {
  const widthM = feature?.properties?.width_m;
  return Number.isFinite(widthM) && widthM > 0
    ? widthM
    : LAYER_STYLE.roadSurfaceWidthM;
}

function normalizedLaneCoordinates(feature) {
  if (feature?.geometry?.type !== "LineString") {
    return [];
  }
  return feature.geometry.coordinates.filter(
    (coordinate) =>
      Array.isArray(coordinate) &&
      Number.isFinite(coordinate[0]) &&
      Number.isFinite(coordinate[1])
  );
}

function offsetLaneBoundary(feature, side) {
  const coordinates = normalizedLaneCoordinates(feature);
  if (coordinates.length < 2 || (side !== -1 && side !== 1)) {
    return null;
  }
  const offsetM = laneWidthM(feature) * 0.5 * side;
  const boundaryCoordinates = coordinates.map((coordinate, index) => {
    const previous = coordinates[Math.max(index - 1, 0)];
    const next = coordinates[Math.min(index + 1, coordinates.length - 1)];
    const deltaX = next[0] - previous[0];
    const deltaY = next[1] - previous[1];
    const lengthM = Math.hypot(deltaX, deltaY);
    if (lengthM <= Number.EPSILON) {
      return [...coordinate];
    }
    const normalX = -deltaY / lengthM;
    const normalY = deltaX / lengthM;
    return [
      coordinate[0] + normalX * offsetM,
      coordinate[1] + normalY * offsetM,
      coordinate[2] ?? 0
    ];
  });
  return {
    type: "Feature",
    properties: {
      ...feature.properties,
      trafficverse_role: "derived_lane_boundary",
      boundary_side: side
    },
    geometry: {type: "LineString", coordinates: boundaryCoordinates}
  };
}

function coordinateAtDistance(coordinates, distanceM) {
  let remainingM = Math.max(0, distanceM);
  for (let index = 1; index < coordinates.length; index += 1) {
    const start = coordinates[index - 1];
    const end = coordinates[index];
    const segmentLengthM = Math.hypot(end[0] - start[0], end[1] - start[1]);
    if (segmentLengthM <= Number.EPSILON) {
      continue;
    }
    if (remainingM <= segmentLengthM) {
      const ratio = remainingM / segmentLengthM;
      return [
        start[0] + (end[0] - start[0]) * ratio,
        start[1] + (end[1] - start[1]) * ratio,
        (start[2] ?? 0) + ((end[2] ?? 0) - (start[2] ?? 0)) * ratio
      ];
    }
    remainingM -= segmentLengthM;
  }
  return [...coordinates[coordinates.length - 1]];
}

function laneLengthM(coordinates) {
  let lengthM = 0;
  for (let index = 1; index < coordinates.length; index += 1) {
    lengthM += Math.hypot(
      coordinates[index][0] - coordinates[index - 1][0],
      coordinates[index][1] - coordinates[index - 1][1]
    );
  }
  return lengthM;
}

function dashedLaneMarkings(feature) {
  const coordinates = normalizedLaneCoordinates(feature);
  if (coordinates.length < 2) {
    return [];
  }
  const totalLengthM = laneLengthM(coordinates);
  const intervalM = LAYER_STYLE.laneMarkingDashM + LAYER_STYLE.laneMarkingGapM;
  const markings = [];
  for (
    let startM = LAYER_STYLE.laneMarkingGapM * 0.5;
    startM < totalLengthM;
    startM += intervalM
  ) {
    const endM = Math.min(startM + LAYER_STYLE.laneMarkingDashM, totalLengthM);
    if (endM - startM < 0.5) {
      continue;
    }
    markings.push({
      type: "Feature",
      properties: {
        ...feature.properties,
        trafficverse_role: "derived_lane_marking"
      },
      geometry: {
        type: "LineString",
        coordinates: [
          coordinateAtDistance(coordinates, startM),
          coordinateAtDistance(coordinates, endM)
        ]
      }
    });
  }
  return markings;
}

function orientedVehiclePoint(vehicle, forwardM, lateralM, elevationM = 0) {
  const [x, y, z] = toMapPosition(vehicle.position);
  // TrafficVerse headings use mathematical radians: zero points along +x and CCW is positive.
  const headingRad = Number.isFinite(vehicle.heading_rad) ? vehicle.heading_rad : 0;
  const cosHeading = Math.cos(headingRad);
  const sinHeading = Math.sin(headingRad);
  return [
    x + cosHeading * forwardM - sinHeading * lateralM,
    y + sinHeading * forwardM + cosHeading * lateralM,
    z + elevationM
  ];
}

function vehicleBodyPolygon(vehicle, forwardOffsetM = 0, lateralOffsetM = 0) {
  return vehicleModelSpec(vehicle).outline.map(([forwardM, lateralM]) =>
    orientedVehiclePoint(
      vehicle,
      forwardM + forwardOffsetM,
      lateralM + lateralOffsetM
    )
  );
}

function orientedVehiclePolygon(vehicle, points, elevationM = 0.04) {
  return points.map(([forwardM, lateralM]) =>
    orientedVehiclePoint(vehicle, forwardM, lateralM, elevationM)
  );
}

function vehicleDetailParts(vehicles) {
  return vehicles.flatMap((vehicle) => {
    const modelKind = vehicleModelKind(vehicle);
    const model = vehicleModelSpec(vehicle);
    const wheelLateralM = model.widthM * 0.5 * 0.96;
    const wheelHalfLengthM = modelKind === "sedan" ? 0.31 : 0.39;
    const wheelHalfWidthM = modelKind === "sedan" ? 0.11 : 0.14;
    const parts = [
      ...model.parts.map((part) => ({
        vehicle,
        kind: part.kind,
        polygon: orientedVehiclePolygon(vehicle, part.points, 0.07)
      })),
      ...model.wheelAxlesM.flatMap((forwardM) =>
        [-wheelLateralM, wheelLateralM].map((lateralM) => ({
          vehicle,
          kind: "wheel",
          polygon: orientedVehiclePolygon(vehicle, [
            [forwardM + wheelHalfLengthM, lateralM - wheelHalfWidthM],
            [forwardM + wheelHalfLengthM, lateralM + wheelHalfWidthM],
            [forwardM - wheelHalfLengthM, lateralM + wheelHalfWidthM],
            [forwardM - wheelHalfLengthM, lateralM - wheelHalfWidthM]
          ], 0.09)
        }))
      )
    ];
    if (vehicle.automation_level !== "HUMAN") {
      parts.push({
        vehicle,
        kind: "sensor",
        polygon: orientedVehiclePolygon(vehicle, [
          [model.sensorForwardM + 0.14, -0.13],
          [model.sensorForwardM + 0.14, 0.13],
          [model.sensorForwardM - 0.14, 0.13],
          [model.sensorForwardM - 0.14, -0.13]
        ], 0.1)
      });
    }
    return parts;
  });
}

function vehiclePartColor(part) {
  const theme = activeTheme();
  if (part.kind === "wheel") {
    return theme.vehicleWheel;
  }
  if (part.kind === "front-glass") {
    return theme.vehicleGlassFront;
  }
  if (part.kind === "rear-glass" || part.kind === "side-glass" || part.kind === "body-seam") {
    return theme.vehicleGlass;
  }
  if (part.kind === "sensor") {
    return theme.vehicleSensor;
  }
  if (part.kind.startsWith("emergency-cross")) {
    return theme.emergencyVehicleMark;
  }
  if (
    part.kind === "hood-highlight" ||
    part.kind === "cargo-panel" ||
    part.kind === "trailer-panel" ||
    part.kind === "medical-roof"
  ) {
    return vehicleAccentColor(part.vehicle, 190);
  }
  return vehicleAccentColor(part.vehicle);
}

function vehicleLightPoints(vehicles) {
  return vehicles.flatMap((vehicle) => {
    const model = vehicleModelSpec(vehicle);
    const halfLengthM = model.lengthM * 0.5;
    return [
      {vehicle, forwardM: halfLengthM - 0.12, lateralM: -model.lightLateralM, kind: "headlight"},
      {vehicle, forwardM: halfLengthM - 0.12, lateralM: model.lightLateralM, kind: "headlight"},
      {vehicle, forwardM: -halfLengthM + 0.1, lateralM: -model.lightLateralM, kind: "rear-marker"},
      {vehicle, forwardM: -halfLengthM + 0.1, lateralM: model.lightLateralM, kind: "rear-marker"}
    ];
  });
}

function focusVehicle(vehicleId, duration = 600) {
  const vehicle = state.vehicles.find((candidate) => candidate.vehicle_id === vehicleId);
  if (!vehicle) {
    return;
  }
  state.selectedVehicleId = vehicleId;
  const [x, y] = toMapPosition(vehicle.position);
  map.easeTo({
    center: localMetersToLngLat(x, y),
    zoom: 18.5,
    pitch: 0,
    bearing: map.getBearing(),
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
      id: "trafficverse-road-shadow",
      data: state.roadCasings,
      lineWidthUnits: "meters",
      getLineWidth: (feature) => laneWidthM(feature) + LAYER_STYLE.roadShadowExtraWidthM,
      lineWidthMinPixels: 4,
      getLineColor: theme.roadShadow,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new GeoJsonLayer({
      ...common,
      id: "trafficverse-road-casing",
      data: state.roadCasings,
      lineWidthUnits: "meters",
      getLineWidth: (feature) => laneWidthM(feature) + LAYER_STYLE.roadCasingExtraWidthM,
      lineWidthMinPixels: 3,
      getLineColor: theme.roadCasing,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new GeoJsonLayer({
      ...common,
      id: "trafficverse-road-surface",
      lineWidthUnits: "meters",
      getLineWidth: laneWidthM,
      lineWidthMinPixels: 2,
      getLineColor: (feature) =>
        feature.properties?.speed_limit_mps >= 20
          ? theme.roadSurfaceFast
          : theme.roadSurface,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new GeoJsonLayer({
      ...common,
      id: "trafficverse-lane-boundaries",
      data: state.laneBoundaries,
      lineWidthUnits: "meters",
      getLineWidth: LAYER_STYLE.laneBoundaryWidthM,
      lineWidthMinPixels: 0.65,
      lineWidthMaxPixels: 2,
      getLineColor: theme.laneBoundary,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new GeoJsonLayer({
      ...common,
      id: "trafficverse-lane-markings",
      data: theme.showLaneMarkings ? state.laneMarkings : EMPTY_NETWORK,
      lineWidthUnits: "meters",
      getLineWidth: LAYER_STYLE.laneMarkingWidthM,
      lineWidthMinPixels: 0.8,
      lineWidthMaxPixels: 2.4,
      getLineColor: theme.laneMarking,
      parameters: FLAT_LAYER_PARAMETERS
    })
  ];
}

function signalLayers(phaseTrigger) {
  const theme = activeTheme();
  const showSignalHalo = map.getZoom() < LAYER_STYLE.detailedVehicleMinZoom;
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
      data: showSignalHalo ? state.signalPoints : [],
      getFillColor: (signal) => phaseColor(signal.signalId, 45),
      getRadius: LAYER_STYLE.signalHaloRadiusM,
      radiusMinPixels: 8
    }),
    new ScatterplotLayer({
      ...common,
      id: "trafficverse-signals",
      getFillColor: (signal) => phaseColor(signal.signalId),
      getRadius: LAYER_STYLE.signalRadiusM,
      radiusMinPixels: 5,
      stroked: true,
      getLineColor: theme.signalOutline,
      lineWidthMinPixels: 2
    })
  ];
}

function collisionZonePolygon(vehicles) {
  if (vehicles.length === 0) {
    return [];
  }
  const bodyPoints = vehicles.flatMap((vehicle) => vehicleBodyPolygon(vehicle));
  const xValues = bodyPoints.map((position) => position[0]);
  const yValues = bodyPoints.map((position) => position[1]);
  const minX = Math.min(...xValues) - LAYER_STYLE.collisionZonePaddingM;
  const maxX = Math.max(...xValues) + LAYER_STYLE.collisionZonePaddingM;
  const minY = Math.min(...yValues) - LAYER_STYLE.collisionZonePaddingM;
  const maxY = Math.max(...yValues) + LAYER_STYLE.collisionZonePaddingM;
  return [{
    polygon: [
      [minX, minY, 0.04],
      [maxX, minY, 0.04],
      [maxX, maxY, 0.04],
      [minX, maxY, 0.04]
    ]
  }];
}

function vehicleLayers() {
  const theme = activeTheme();
  const vehicles = state.vehicles.filter((vehicle) => !isStaticObstacle(vehicle));
  const obstacles = state.vehicles.filter(isStaticObstacle);
  const ambulances = vehicles.filter(isAmbulance);
  const showDetailedVehicles = map.getZoom() >= LAYER_STYLE.detailedVehicleMinZoom;
  const detailedVehicles = showDetailedVehicles ? vehicles : [];
  const compactVehicles = showDetailedVehicles ? [] : vehicles;
  const collisionVehicles = vehicles.filter(
    (vehicle) =>
      isScriptedAccidentVehicle(vehicle) &&
      state.collisionVehicleIds.has(vehicle.vehicle_id)
  );
  const compactAmbulances = compactVehicles.filter(isAmbulance);
  const compactOrdinaryVehicles = compactVehicles.filter((vehicle) => !isAmbulance(vehicle));
  const common = {
    data: detailedVehicles,
    coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
    coordinateOrigin: [0, 0, 0],
    pickable: true,
    onClick: selectVehicle
  };
  return [
    new PolygonLayer({
      id: "trafficverse-collision-zone",
      data: collisionZonePolygon(collisionVehicles),
      coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
      coordinateOrigin: [0, 0, 0],
      getPolygon: (zone) => zone.polygon,
      getFillColor: [249, 115, 22, 42],
      getLineColor: [194, 65, 12, 245],
      stroked: true,
      getLineWidth: 2.5,
      lineWidthUnits: "pixels",
      pickable: false,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new ScatterplotLayer({
      id: "trafficverse-obstacle-halo",
      data: obstacles,
      coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
      coordinateOrigin: [0, 0, 0],
      getPosition: (vehicle) => toMapPosition(vehicle.position),
      getFillColor: [...theme.obstacle, 70],
      getLineColor: theme.obstacle,
      getRadius: 4.2,
      radiusUnits: "meters",
      radiusMinPixels: 6,
      radiusMaxPixels: 14,
      stroked: true,
      lineWidthMinPixels: 2,
      pickable: false,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new PolygonLayer({
      id: "trafficverse-obstacle-bodies",
      data: obstacles,
      coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
      coordinateOrigin: [0, 0, 0],
      getPolygon: (vehicle) => orientedVehiclePolygon(vehicle, [
        [3.0, -1.45], [3.0, 1.45], [-3.0, 1.45], [-3.0, -1.45]
      ]),
      getFillColor: theme.obstacle,
      getLineColor: theme.obstacleOutline,
      getLineWidth: 2,
      lineWidthUnits: "pixels",
      stroked: true,
      pickable: true,
      onClick: selectVehicle,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new ScatterplotLayer({
      id: "trafficverse-emergency-highlight",
      data: showDetailedVehicles ? ambulances : [],
      coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
      coordinateOrigin: [0, 0, 0],
      getPosition: (vehicle) => toMapPosition(vehicle.position),
      getFillColor: [...theme.emergencyVehicle, 85],
      getLineColor: theme.emergencyVehicleAccent,
      getRadius: 5.4,
      radiusUnits: "meters",
      radiusMinPixels: 9,
      radiusMaxPixels: 18,
      stroked: true,
      lineWidthMinPixels: 2.5,
      pickable: false,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new PolygonLayer({
      ...common,
      id: "trafficverse-vehicle-shadows",
      getPolygon: (vehicle) => vehicleBodyPolygon(vehicle, -0.1, -0.12),
      getFillColor: theme.vehicleShadow,
      stroked: false,
      pickable: false,
      parameters: FLAT_LAYER_PARAMETERS
    }),
    new ScatterplotLayer({
      ...common,
      id: "trafficverse-vehicle-dots",
      data: compactOrdinaryVehicles,
      getPosition: (vehicle) => toMapPosition(vehicle.position),
      getFillColor: (vehicle) =>
        vehicle.vehicle_id === state.selectedVehicleId
          ? vehicleColor(vehicle)
          : vehicleColor(vehicle, 235),
      getLineColor: (vehicle) =>
        vehicle.automation_level === "L5" ? theme.vehicleOutline : vehicleColor(vehicle),
      getRadius: (vehicle) =>
        vehicle.vehicle_id === state.selectedVehicleId
          ? LAYER_STYLE.compactVehicleSelectedRadiusPx
          : LAYER_STYLE.compactVehicleRadiusPx,
      radiusUnits: "pixels",
      stroked: true,
      lineWidthMinPixels: 1.25,
      parameters: FLAT_LAYER_PARAMETERS,
      updateTriggers: {
        getFillColor: [state.theme, state.selectedVehicleId],
        getLineColor: state.theme,
        getRadius: state.selectedVehicleId
      }
    }),
    new IconLayer({
      ...common,
      id: "trafficverse-compact-ambulances",
      data: compactAmbulances,
      getPosition: (vehicle) => toMapPosition(vehicle.position),
      getIcon: () => COMPACT_AMBULANCE_ICON,
      getColor: (vehicle) => vehicleColor(vehicle),
      getSize: (vehicle) =>
        vehicle.vehicle_id === state.selectedVehicleId
          ? LAYER_STYLE.compactVehicleSelectedRadiusPx * 2
          : LAYER_STYLE.compactVehicleRadiusPx * 2,
      sizeUnits: "pixels",
      parameters: FLAT_LAYER_PARAMETERS,
      updateTriggers: {
        getColor: state.theme,
        getSize: state.selectedVehicleId
      }
    }),
    new PolygonLayer({
      ...common,
      id: "trafficverse-vehicle-bodies",
      getPolygon: vehicleBodyPolygon,
      getFillColor: vehicleColor,
      getLineColor: theme.vehicleOutline,
      getLineWidth: (vehicle) =>
        vehicle.vehicle_id === state.selectedVehicleId ? 2.2 : 1.05,
      lineWidthUnits: "pixels",
      stroked: true,
      parameters: FLAT_LAYER_PARAMETERS,
      updateTriggers: {
        getFillColor: state.theme,
        getLineColor: state.theme,
        getLineWidth: state.selectedVehicleId
      }
    }),
    new PolygonLayer({
      ...common,
      id: "trafficverse-vehicle-details",
      data: vehicleDetailParts(detailedVehicles),
      getPolygon: (part) => part.polygon,
      getFillColor: vehiclePartColor,
      stroked: false,
      pickable: false,
      parameters: FLAT_LAYER_PARAMETERS,
      updateTriggers: {getFillColor: state.theme}
    }),
    new ScatterplotLayer({
      ...common,
      id: "trafficverse-vehicle-headlights",
      data: vehicleLightPoints(detailedVehicles),
      getPosition: (light) =>
        orientedVehiclePoint(light.vehicle, light.forwardM, light.lateralM, 0.12),
      getFillColor: (light) =>
        light.kind === "headlight"
          ? theme.vehicleHeadlight
          : vehicleAccentColor(light.vehicle, 225),
      getRadius: (light) =>
        light.kind === "headlight"
          ? LAYER_STYLE.vehicleHeadlightRadiusM
          : LAYER_STYLE.vehicleHeadlightRadiusM * 0.78,
      radiusUnits: "meters",
      radiusMinPixels: 1.2,
      radiusMaxPixels: 3,
      pickable: false,
      parameters: FLAT_LAYER_PARAMETERS,
      updateTriggers: {getFillColor: state.theme}
    })
  ];
}

function refreshStaticLayers() {
  const phaseTrigger = [state.theme, ...Array.from(state.trafficLights.entries()).flat()];
  cachedRoadLayers = roadLayers();
  cachedSignalLayers = signalLayers(phaseTrigger);
}

function renderVehicleLayers() {
  if (cachedRoadLayers.length === 0) {
    refreshStaticLayers();
  }
  overlay.setProps({
    effects: [state.lightingEffect],
    layers: [...cachedRoadLayers, ...vehicleLayers(), ...cachedSignalLayers]
  });
}

function updateMapStatus() {
  const roadCount = state.roadNetwork.features.length;
  const signalCount = state.signalPoints.length;
  const vehicleCount = state.authoritativeVehicles.length;
  const collisionCount = state.collisionVehicleIds.size;
  setStatus(
    `车道 ${roadCount} · 信号 ${signalCount} · 车辆 ${vehicleCount} · 碰撞 ${collisionCount}`
  );
}

function renderLayers() {
  refreshStaticLayers();
  renderVehicleLayers();
  updateMapStatus();
}

function cancelVehicleAnimation() {
  if (state.vehicleAnimationFrame !== null) {
    cancelAnimationFrame(state.vehicleAnimationFrame);
    state.vehicleAnimationFrame = null;
  }
}

function animateVehicles(timestampMs) {
  state.vehicles = state.vehiclePlayback.sample(timestampMs);
  renderVehicleLayers();
  if (state.vehiclePlayback.isActive()) {
    state.vehicleAnimationFrame = requestAnimationFrame(animateVehicles);
    return;
  }
  state.vehicleAnimationFrame = null;
}

function setVehicleSnapshot(vehicles) {
  const receivedAtMs = performance.now();
  state.authoritativeVehicles = vehicles;
  state.vehiclePlayback.push(vehicles, receivedAtMs);
  state.vehicles = state.vehiclePlayback.sample(receivedAtMs);
  renderVehicleLayers();
  if (state.vehiclePlayback.isActive() && state.vehicleAnimationFrame === null) {
    state.vehicleAnimationFrame = requestAnimationFrame(animateVehicles);
  }
  updateMapStatus();
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
  state.followScenarioVehicles = false;
  if (!state.networkBounds || state.networkBounds.isEmpty()) {
    return;
  }
  const verticalPaddingPx = state.legendVisible ? 100 : 46;
  map.fitBounds(state.networkBounds, {
    padding: {top: verticalPaddingPx, right: 46, bottom: 46, left: 46},
    duration,
    maxZoom: 18,
    pitch: 0,
    bearing: 0
  });
}

function resizeMapAfterLayout() {
  requestAnimationFrame(() => {
    map.resize();
    renderLayers();
  });
}

function requestMapMaximizeToggle() {
  if (state.bridge?.toggleMapMaximize) {
    state.bridge.toggleMapMaximize();
  }
}

function scenarioVehicles() {
  const ids = state.vehicles.map((vehicle) => vehicle.vehicle_id ?? "");
  if (ids.some((vehicleId) => vehicleId.startsWith("static_obstacle_"))) {
    return state.vehicles.filter((vehicle) =>
      /^(target_|static_obstacle_)/.test(vehicle.vehicle_id ?? "")
    );
  }
  if (ids.some((vehicleId) => vehicleId.startsWith("cutin_"))) {
    return state.vehicles.filter((vehicle) => (vehicle.vehicle_id ?? "").startsWith("cutin_"));
  }
  if (ids.some((vehicleId) => vehicleId === "ambulance_L5_0")) {
    return state.vehicles.filter((vehicle) => /^(yield_|ambulance_)/.test(vehicle.vehicle_id ?? ""));
  }
  if (ids.some((vehicleId) => vehicleId.startsWith("accident_"))) {
    return state.vehicles.filter((vehicle) =>
      (vehicle.vehicle_id ?? "").startsWith("accident_")
    );
  }
  return [];
}

function fitScenarioVehicles() {
  if (!state.followScenarioVehicles) {
    return;
  }
  const vehicles = scenarioVehicles();
  if (vehicles.length < 2) {
    return;
  }
  const bounds = new maplibregl.LngLatBounds();
  for (const vehicle of vehicles) {
    const [x, y] = toMapPosition(vehicle.position);
    bounds.extend(localMetersToLngLat(x, y));
  }
  if (bounds.isEmpty()) {
    return;
  }
  state.followScenarioVehicles = false;
  map.fitBounds(bounds, {
    padding: {top: 60, right: 50, bottom: 45, left: 50},
    duration: 180,
    maxZoom: 18
  });
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
      bearing: map.getBearing()
    };
    container.style.cursor = "grabbing";
  }

  function rotate(event) {
    if (!dragStart) {
      return;
    }
    event.preventDefault();
    const bearing = dragStart.bearing + (event.clientX - dragStart.x) * 0.35;
    map.jumpTo({bearing});
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
  state.followScenarioVehicles = true;
  resetView(0);
  state.followScenarioVehicles = true;
}

document.getElementById("reset-view").addEventListener("click", () => resetView());

window.TrafficVerseMap = {
  setLegendVisible(visible) {
    state.legendVisible = Boolean(visible);
    document.getElementById("map-hud").hidden = !visible;
  },
  setMaximizeEnabled(enabled) {
    state.maximizeEnabled = Boolean(enabled);
    maximizeControl.update();
  },
  setMaximized(maximized) {
    state.maximized = Boolean(maximized);
    maximizeControl.update();
    resizeMapAfterLayout();
  },
  setNetwork(network) {
    state.network = network?.type === "FeatureCollection" ? network : EMPTY_NETWORK;
    const lineFeatures = state.network.features.filter(
      (feature) => feature.geometry?.type === "LineString"
    );
    const sumoLineFeatures = lineFeatures.filter((feature) =>
      SUMO_LANE_ROLES.has(feature.properties?.trafficverse_role)
    );
    const roadFeatures = sumoLineFeatures.length > 0 ? sumoLineFeatures : lineFeatures;
    const externalLanes = featureCollection(
      roadFeatures.filter(
        (feature) => feature.properties?.trafficverse_role !== "sumo_internal_lane"
      )
    );
    state.roadNetwork = featureCollection(roadFeatures);
    state.roadCasings = externalLanes;
    state.laneBoundaries = featureCollection(
      externalLanes.features.flatMap((feature) => [
        offsetLaneBoundary(feature, -1),
        offsetLaneBoundary(feature, 1)
      ]).filter((feature) => feature !== null)
    );
    state.laneMarkings = featureCollection(
      externalLanes.features.flatMap((feature) => dashedLaneMarkings(feature))
    );
    state.junctionSurfaces = featureCollection(
      state.network.features.filter(
        (feature) => feature.properties?.trafficverse_role === SUMO_JUNCTION_ROLE
      )
    );
    state.signalPoints = state.network.features
      .map(signalPointFromFeature)
      .filter((point) => point !== null);
    fitNetwork(state.network);
    renderLayers();
  },
  setVehicles(vehicles) {
    setVehicleSnapshot(Array.isArray(vehicles) ? vehicles : []);
    fitScenarioVehicles();
  },
  setCollisionVehicleIds(vehicleIds) {
    state.collisionVehicleIds = new Set(
      (Array.isArray(vehicleIds) ? vehicleIds : []).filter((vehicleId) =>
        typeof vehicleId === "string"
      )
    );
    renderVehicleLayers();
    updateMapStatus();
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
  map.addControl(maximizeControl, "top-right");
  map.addControl(new maplibregl.NavigationControl({visualizePitch: false}), "top-right");
  enableCommandDragRotation();
  applyTheme(state.theme);
  connectQtBridge();
  map.on("movestart", (event) => {
    if (event.originalEvent) {
      state.followScenarioVehicles = false;
    }
  });
  map.on("zoomend", renderLayers);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.maximized) {
    requestMapMaximizeToggle();
  }
});
map.on("error", (event) => {
  const message = event?.error?.message ?? "未知错误";
  setStatus(`地图资源加载失败：${message}`, true);
});
map.once("remove", cancelVehicleAnimation);
