export const MAP_THEMES = {
  dark: {
    background: "#141414",
    roadShadow: [0, 0, 0, 145],
    roadCasing: [37, 40, 43, 255],
    roadSurface: [70, 73, 76, 255],
    roadSurfaceFast: [64, 69, 74, 255],
    junctionSurface: [65, 68, 71, 255],
    laneBoundary: [237, 238, 232, 205],
    laneMarking: [246, 246, 238, 225],
    signal: {
      green: [103, 194, 58],
      yellow: [230, 162, 60],
      red: [245, 108, 108],
      unknown: [144, 147, 153]
    },
    vehicle: {human: [218, 139, 42], automated: [47, 137, 230]},
    vehicleAccent: {human: [250, 187, 82], automated: [105, 190, 255]},
    vehicleGlass: [20, 34, 45, 252],
    vehicleGlassFront: [48, 76, 93, 252],
    vehicleWheel: [10, 12, 14, 255],
    vehicleSensor: [104, 225, 255, 255],
    vehicleShadow: [0, 0, 0, 92],
    vehicleHeadlight: [255, 244, 188, 255],
    vehicleTailLight: [255, 70, 70, 255],
    signalOutline: [29, 30, 31, 255],
    vehicleOutline: [236, 241, 247, 225],
    ambientLight: [229, 234, 243],
    keyLight: [255, 245, 224]
  },
  light: {
    background: "#f2f3f5",
    roadShadow: [37, 42, 47, 72],
    roadCasing: [116, 121, 126, 255],
    roadSurface: [83, 88, 93, 255],
    roadSurfaceFast: [75, 83, 91, 255],
    junctionSurface: [79, 84, 89, 255],
    laneBoundary: [250, 250, 242, 215],
    laneMarking: [255, 255, 247, 235],
    signal: {
      green: [103, 194, 58],
      yellow: [230, 162, 60],
      red: [245, 108, 108],
      unknown: [144, 147, 153]
    },
    vehicle: {human: [213, 127, 28], automated: [36, 123, 216]},
    vehicleAccent: {human: [247, 178, 68], automated: [92, 175, 242]},
    vehicleGlass: [27, 42, 54, 250],
    vehicleGlassFront: [66, 96, 114, 250],
    vehicleWheel: [18, 21, 24, 255],
    vehicleSensor: [45, 190, 224, 255],
    vehicleShadow: [33, 38, 43, 72],
    vehicleHeadlight: [255, 243, 176, 255],
    vehicleTailLight: [238, 58, 58, 255],
    signalOutline: [255, 255, 255, 255],
    vehicleOutline: [48, 49, 51, 235],
    ambientLight: [245, 247, 250],
    keyLight: [255, 245, 224]
  }
};

export const LAYER_STYLE = {
  roadShadowExtraWidthM: 3.2,
  roadCasingExtraWidthM: 1.5,
  roadSurfaceWidthM: 3.8,
  laneBoundaryWidthM: 0.12,
  laneMarkingWidthM: 0.16,
  laneMarkingDashM: 3.2,
  laneMarkingGapM: 4.4,
  signalHaloRadiusM: 6,
  signalRadiusM: 2.2,
  vehicleLengthM: 4.55,
  vehicleWidthM: 1.82,
  vehicleHaloRadiusM: 3.35,
  vehicleHeadlightRadiusM: 0.17
};
