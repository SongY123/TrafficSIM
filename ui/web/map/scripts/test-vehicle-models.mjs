import assert from "node:assert/strict";

import {MAP_THEMES} from "../src/style.js";

import {
  ORDINARY_VEHICLE_MODEL_PERCENTAGES,
  ORDINARY_VEHICLE_MODEL_KINDS,
  VEHICLE_MODEL_KINDS,
  VEHICLE_MODEL_SPECS,
  isAmbulanceVehicle,
  vehicleModelKind,
  vehicleModelSpec
} from "../src/vehicle_models.mjs";

assert.deepEqual(VEHICLE_MODEL_KINDS, ["sedan", "truck", "trailer", "ambulance"]);
assert.deepEqual(ORDINARY_VEHICLE_MODEL_KINDS, ["sedan", "truck", "trailer"]);
assert.deepEqual(ORDINARY_VEHICLE_MODEL_PERCENTAGES, {sedan: 85, truck: 10, trailer: 5});

for (const kind of VEHICLE_MODEL_KINDS) {
  const spec = VEHICLE_MODEL_SPECS[kind];
  assert.ok(spec.lengthM > 4);
  assert.ok(spec.widthM > 1.5);
  assert.ok(spec.outline.length >= 6);
  assert.ok(spec.wheelAxlesM.length >= 2);
}

assert.equal(vehicleModelKind({vehicle_id: "ambulance_L5_0"}), "ambulance");
assert.equal(vehicleModelKind({vehicle_id: "rescue-L0-7"}), "ambulance");
assert.equal(vehicleModelKind({vehicle_id: "ordinary", visual_type: "emergency"}), "ambulance");
assert.equal(vehicleModelKind({vehicle_id: "fleet_truck_1"}), "truck");
assert.equal(vehicleModelKind({vehicle_id: "fleet-semi-1"}), "trailer");
assert.equal(vehicleModelKind({vehicle_id: "passenger_L3_1"}), "sedan");
assert.equal(vehicleModelKind({vehicle_id: "accident_follow_L1_0"}), "sedan");
assert.equal(vehicleModelKind({vehicle_id: "accident_follow_L3_0"}), "sedan");
assert.equal(isAmbulanceVehicle({vehicle_id: "ambulance_L0_0"}), true);
assert.equal(isAmbulanceVehicle({vehicle_id: "truck_L0_0"}), false);

const distributedModels = Array.from({length: 5000}, (_, index) =>
  vehicleModelKind({vehicle_id: `vehicle_L3_${index}`})
);
const distributedKinds = new Set(distributedModels);
assert.deepEqual(distributedKinds, new Set(ORDINARY_VEHICLE_MODEL_KINDS));
const sedanCount = distributedModels.filter((kind) => kind === "sedan").length;
const truckCount = distributedModels.filter((kind) => kind === "truck").length;
assert.ok(truckCount <= sedanCount * 0.2);
assert.equal(
  vehicleModelKind({vehicle_id: "stable_L4_9"}),
  vehicleModelKind({vehicle_id: "stable_L4_9"})
);
assert.equal(vehicleModelSpec({vehicle_id: "fleet_trailer_2"}).lengthM, 12);

const automationLevels = ["L0", "L1", "L2", "L3", "L4", "L5"];
assert.deepEqual(MAP_THEMES.dark.vehicle.L0, [231, 229, 228]);
assert.deepEqual(MAP_THEMES.light.vehicle.L0, [168, 162, 158]);
assert.deepEqual(MAP_THEMES.dark.vehicle.L5, [0, 0, 0]);
assert.deepEqual(MAP_THEMES.light.vehicle.L5, [0, 0, 0]);
for (const theme of Object.values(MAP_THEMES)) {
  const automationColors = automationLevels.map((level) => theme.vehicle[level]);
  const signalColors = [theme.signal.red, theme.signal.yellow, theme.signal.green];
  assert.equal(new Set(automationColors.map((color) => color.join(","))).size, 6);
  for (const automationColor of automationColors) {
    for (const signalColor of signalColors) {
      const distance = Math.hypot(
        ...automationColor.map((channel, index) => channel - signalColor[index])
      );
      assert.ok(distance > 75);
    }
  }
  assert.equal("vehicleTailLight" in theme, false);
}

console.log("vehicle model tests passed");
