import assert from "node:assert/strict";

import {
  ORDINARY_VEHICLE_MODEL_KINDS,
  VEHICLE_MODEL_KINDS,
  VEHICLE_MODEL_SPECS,
  isAmbulanceVehicle,
  vehicleModelKind,
  vehicleModelSpec
} from "../src/vehicle_models.mjs";

assert.deepEqual(VEHICLE_MODEL_KINDS, ["sedan", "truck", "trailer", "ambulance"]);
assert.deepEqual(ORDINARY_VEHICLE_MODEL_KINDS, ["sedan", "truck", "trailer"]);

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
assert.equal(isAmbulanceVehicle({vehicle_id: "ambulance_L0_0"}), true);
assert.equal(isAmbulanceVehicle({vehicle_id: "truck_L0_0"}), false);

const distributedKinds = new Set(
  Array.from({length: 30}, (_, index) =>
    vehicleModelKind({vehicle_id: `vehicle_L3_${index}`})
  )
);
assert.deepEqual(distributedKinds, new Set(ORDINARY_VEHICLE_MODEL_KINDS));
assert.equal(
  vehicleModelKind({vehicle_id: "stable_L4_9"}),
  vehicleModelKind({vehicle_id: "stable_L4_9"})
);
assert.equal(vehicleModelSpec({vehicle_id: "fleet_trailer_2"}).lengthM, 12);

console.log("vehicle model tests passed");
