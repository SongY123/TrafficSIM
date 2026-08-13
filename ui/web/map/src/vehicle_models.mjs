export const ORDINARY_VEHICLE_MODEL_KINDS = Object.freeze(["sedan", "truck", "trailer"]);

export const VEHICLE_MODEL_KINDS = Object.freeze([
  ...ORDINARY_VEHICLE_MODEL_KINDS,
  "ambulance"
]);

const MODEL_ALIASES = Object.freeze({
  ambulance: "ambulance",
  emergency: "ambulance",
  rescue: "ambulance",
  sedan: "sedan",
  car: "sedan",
  passenger: "sedan",
  truck: "truck",
  lorry: "truck",
  trailer: "trailer",
  semi: "trailer"
});

export const VEHICLE_MODEL_SPECS = Object.freeze({
  sedan: Object.freeze({
    lengthM: 4.55,
    widthM: 1.82,
    outline: Object.freeze([
      [2.275, -0.53], [2.275, 0.53], [1.94, 0.91], [-1.99, 0.91],
      [-2.275, 0.64], [-2.275, -0.64], [-1.99, -0.91], [1.94, -0.91]
    ]),
    parts: Object.freeze([
      {kind: "roof", points: [[1, -0.54], [1, 0.54], [0.68, 0.66], [-0.92, 0.66], [-1.16, 0.5], [-1.16, -0.5], [-0.92, -0.66], [0.68, -0.66]]},
      {kind: "front-glass", points: [[0.96, -0.51], [0.96, 0.51], [0.58, 0.62], [0.58, -0.62]]},
      {kind: "rear-glass", points: [[-0.69, -0.62], [-0.69, 0.62], [-1.1, 0.47], [-1.1, -0.47]]},
      {kind: "hood-highlight", points: [[2.03, -0.3], [2.03, 0.3], [1.28, 0.42], [1.28, -0.42]]}
    ]),
    wheelAxlesM: Object.freeze([1.08, -1.24]),
    sensorForwardM: 0,
    lightLateralM: 0.62
  }),
  truck: Object.freeze({
    lengthM: 7.2,
    widthM: 2.35,
    outline: Object.freeze([
      [3.6, -0.76], [3.6, 0.76], [3.2, 1.175], [-3.6, 1.175],
      [-3.6, -1.175], [3.2, -1.175]
    ]),
    parts: Object.freeze([
      {kind: "cargo-panel", points: [[0.72, -1.01], [0.72, 1.01], [-3.3, 1.01], [-3.3, -1.01]]},
      {kind: "roof", points: [[3.08, -0.78], [3.08, 0.78], [2.52, 0.94], [0.94, 0.94], [0.94, -0.94], [2.52, -0.94]]},
      {kind: "front-glass", points: [[2.95, -0.7], [2.95, 0.7], [2.5, 0.83], [2.5, -0.83]]},
      {kind: "body-seam", points: [[0.84, -1.06], [0.84, 1.06], [0.7, 1.06], [0.7, -1.06]]}
    ]),
    wheelAxlesM: Object.freeze([2.12, -1.72, -2.72]),
    sensorForwardM: 1.7,
    lightLateralM: 0.8
  }),
  trailer: Object.freeze({
    lengthM: 12,
    widthM: 2.5,
    outline: Object.freeze([
      [6, -0.78], [6, 0.78], [5.55, 1.12], [3.15, 1.12],
      [2.9, 1.25], [-6, 1.25], [-6, -1.25], [2.9, -1.25], [3.15, -1.12], [5.55, -1.12]
    ]),
    parts: Object.freeze([
      {kind: "trailer-panel", points: [[2.68, -1.08], [2.68, 1.08], [-5.68, 1.08], [-5.68, -1.08]]},
      {kind: "roof", points: [[5.48, -0.76], [5.48, 0.76], [4.95, 0.96], [3.24, 0.96], [3.24, -0.96], [4.95, -0.96]]},
      {kind: "front-glass", points: [[5.38, -0.69], [5.38, 0.69], [4.9, 0.84], [4.9, -0.84]]},
      {kind: "body-seam", points: [[3.06, -1.12], [3.06, 1.12], [2.86, 1.2], [2.86, -1.2]]}
    ]),
    wheelAxlesM: Object.freeze([4.25, -3.72, -4.72]),
    sensorForwardM: 4.05,
    lightLateralM: 0.82
  }),
  ambulance: Object.freeze({
    lengthM: 5.8,
    widthM: 2.15,
    outline: Object.freeze([
      [2.9, -0.68], [2.9, 0.68], [2.5, 1.075], [-2.9, 1.075],
      [-2.9, -1.075], [2.5, -1.075]
    ]),
    parts: Object.freeze([
      {kind: "medical-roof", points: [[1.52, -0.9], [1.52, 0.9], [-2.58, 0.9], [-2.58, -0.9]]},
      {kind: "front-glass", points: [[2.54, -0.67], [2.54, 0.67], [2.08, 0.84], [2.08, -0.84]]},
      {kind: "emergency-cross-horizontal", points: [[0.18, -0.52], [0.18, 0.52], [-0.2, 0.52], [-0.2, -0.52]]},
      {kind: "emergency-cross-vertical", points: [[0.52, -0.19], [0.52, 0.19], [-0.54, 0.19], [-0.54, -0.19]]}
    ]),
    wheelAxlesM: Object.freeze([1.72, -1.82]),
    sensorForwardM: 0.78,
    lightLateralM: 0.72
  })
});

function normalizedModelAlias(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  return MODEL_ALIASES[normalized] ?? null;
}

function stableStringHash(value) {
  let hash = 2166136261;
  for (const character of value) {
    hash ^= character.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function isAmbulanceVehicle(vehicle) {
  const explicitKind = normalizedModelAlias(
    vehicle?.visual_type ?? vehicle?.vehicle_type ?? vehicle?.type_id
  );
  if (explicitKind === "ambulance") {
    return true;
  }
  return /(^|[_-])(ambulance|emergency|rescue)([_-]|$)/i.test(vehicle?.vehicle_id ?? "");
}

export function vehicleModelKind(vehicle) {
  if (isAmbulanceVehicle(vehicle)) {
    return "ambulance";
  }
  const explicitKind = normalizedModelAlias(
    vehicle?.visual_type ?? vehicle?.vehicle_type ?? vehicle?.type_id
  );
  if (explicitKind && explicitKind !== "ambulance") {
    return explicitKind;
  }
  const vehicleId = String(vehicle?.vehicle_id ?? "vehicle");
  const idKind = Object.entries(MODEL_ALIASES).find(
    ([alias, kind]) => kind !== "ambulance" && new RegExp(`(^|[_-])${alias}([_-]|$)`, "i").test(vehicleId)
  )?.[1];
  if (idKind) {
    return idKind;
  }
  return ORDINARY_VEHICLE_MODEL_KINDS[
    stableStringHash(vehicleId) % ORDINARY_VEHICLE_MODEL_KINDS.length
  ];
}

export function vehicleModelSpec(vehicle) {
  return VEHICLE_MODEL_SPECS[vehicleModelKind(vehicle)];
}
