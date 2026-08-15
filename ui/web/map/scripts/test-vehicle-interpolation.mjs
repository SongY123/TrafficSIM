import assert from "node:assert/strict";

import {
  VehicleSnapshotPlayback,
  canInterpolateSnapshots,
  interpolateAngleRad,
  interpolateVehicleSnapshots,
  stabilizeVehicleHeadings
} from "../src/vehicle_interpolation.mjs";

function vehicle(vehicleId, sequence, simulationTimeMs, x, headingRad = 0) {
  return {
    vehicle_id: vehicleId,
    sequence,
    simulation_time_ms: simulationTimeMs,
    position: {x, y: 2, z: 0},
    heading_rad: headingRad,
    speed_mps: 10
  };
}

const previous = [vehicle("vehicle-1", 10, 500, 0)];
const current = [vehicle("vehicle-1", 11, 550, 0.5)];

assert.equal(canInterpolateSnapshots(previous, current), true);
assert.equal(canInterpolateSnapshots(previous, [vehicle("vehicle-1", 12, 600, 1)]), false);
assert.equal(canInterpolateSnapshots(current, previous), false);
assert.equal(canInterpolateSnapshots([], current), false);

const midpoint = interpolateVehicleSnapshots(previous, current, 0.5);
assert.equal(midpoint.length, 1);
assert.deepEqual(midpoint[0].position, {x: 0.25, y: 2, z: 0});
assert.equal(midpoint[0].sequence, 11);
assert.equal(midpoint[0].simulation_time_ms, 550);

assert.equal(interpolateVehicleSnapshots(previous, current, 2)[0].position.x, 0.5);
assert.equal(interpolateVehicleSnapshots(previous, current, -1)[0].position.x, 0);

const teleported = interpolateVehicleSnapshots(
  previous,
  [vehicle("vehicle-1", 11, 550, 100)],
  0.5
);
assert.equal(teleported[0].position.x, 100);

const withNewVehicle = interpolateVehicleSnapshots(
  previous,
  [...current, vehicle("vehicle-2", 11, 550, 40)],
  0.25
);
assert.equal(withNewVehicle[1].position.x, 40);

const slantedAfterLaneChange = vehicle("vehicle-1", 11, 550, 0.3, Math.PI / 6);
const straightened = stabilizeVehicleHeadings(previous, [slantedAfterLaneChange]);
assert.ok(Math.abs(straightened[0].heading_rad) < 1e-9);

const changingLanePrevious = vehicle("vehicle-1", 10, 500, 0, 0);
changingLanePrevious.position.y = 2;
const changingLaneCurrent = vehicle("vehicle-1", 11, 550, 0.3, 0);
changingLaneCurrent.position.y = 2.2;
const changingLane = stabilizeVehicleHeadings(
  [changingLanePrevious],
  [changingLaneCurrent]
);
assert.ok(changingLane[0].heading_rad > 0);

const lowMergePrevious = vehicle("merge_main_L0_lane0.1", 10, 500, 0, 0);
const lowMergeCurrent = vehicle("merge_main_L0_lane0.1", 11, 550, 0.1, Math.PI / 8);
lowMergeCurrent.position.y = 2.2;
const lowMergeChangingLane = stabilizeVehicleHeadings(
  [lowMergePrevious],
  [lowMergeCurrent]
);
assert.equal(lowMergeChangingLane[0].heading_rad, Math.PI / 8);

const teleportedHeading = stabilizeVehicleHeadings(
  previous,
  [vehicle("vehicle-1", 11, 550, 100, 0.75)]
);
assert.equal(teleportedHeading[0].heading_rad, 0.75);

const stoppedVehicleHeading = stabilizeVehicleHeadings(
  previous,
  [vehicle("vehicle-1", 11, 550, 0.001, 0.75)]
);
assert.equal(stoppedVehicleHeading[0].heading_rad, 0.75);

const collisionReboundHeading = stabilizeVehicleHeadings(
  [vehicle("accident_actor_L0_0", 10, 500, 1, 0)],
  [vehicle("accident_actor_L0_0", 11, 550, 0.9, 0)]
);
assert.equal(collisionReboundHeading[0].heading_rad, 0);

const degrees = (radians) => radians * 180 / Math.PI;
const wrappedMidpoint = interpolateAngleRad(179 * Math.PI / 180, -179 * Math.PI / 180, 0.5);
assert.ok(Math.abs(Math.abs(degrees(wrappedMidpoint)) - 180) < 1e-9);

const playback = new VehicleSnapshotPlayback({bufferFrames: 2});
playback.push([vehicle("vehicle-1", 20, 1000, 0)], 0);
playback.push([vehicle("vehicle-1", 21, 1050, 0.5)], 54);
playback.push([vehicle("vehicle-1", 22, 1100, 1)], 101);

const jitteredPositions = [101, 117, 133, 149].map(
  (timestampMs) => playback.sample(timestampMs)[0].position.x
);
playback.push([vehicle("vehicle-1", 23, 1150, 1.5)], 164);
jitteredPositions.push(
  ...[165, 181, 197].map((timestampMs) => playback.sample(timestampMs)[0].position.x)
);
playback.push([vehicle("vehicle-1", 24, 1200, 2)], 207);
jitteredPositions.push(
  ...[213, 229, 245].map((timestampMs) => playback.sample(timestampMs)[0].position.x)
);

const movementPerRenderFrame = jitteredPositions.slice(1).map(
  (position, index) => position - jitteredPositions[index]
);
assert.ok(movementPerRenderFrame.every((distance) => distance > 0.05));
assert.ok(movementPerRenderFrame.every((distance) => distance < 0.3));
assert.equal(playback.sample(1000)[0].position.x, 2);
assert.equal(playback.isActive(), false);

playback.push([vehicle("vehicle-1", 26, 1300, 3)], 1010);
assert.equal(playback.sample(1010)[0].position.x, 3);
assert.equal(playback.isActive(), false);

const oneSecondPlayback = new VehicleSnapshotPlayback({bufferFrames: 2});
oneSecondPlayback.push([vehicle("vehicle-1", 30, 1000, 0)], 0);
oneSecondPlayback.push([vehicle("vehicle-1", 31, 2000, 10)], 1000);
oneSecondPlayback.push([vehicle("vehicle-1", 32, 3000, 20)], 2000);
assert.equal(oneSecondPlayback.sample(2500)[0].position.x, 5);
assert.equal(oneSecondPlayback.isActive(), true);

console.log("vehicle interpolation tests passed");
