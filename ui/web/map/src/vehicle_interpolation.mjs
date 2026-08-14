const TWO_PI = Math.PI * 2;
const DEFAULT_BUFFER_FRAMES = 2;
const PLAYBACK_RATE_SMOOTHING = 0.2;
const MAX_RATE_SAMPLE_MULTIPLIER = 4;
const MIN_HEADING_MOVEMENT_M = 0.005;

function clampUnit(value) {
  return Math.max(0, Math.min(1, value));
}

function snapshotVersion(vehicles) {
  const vehicle = vehicles.find(
    (candidate) =>
      Number.isInteger(candidate?.sequence) && Number.isFinite(candidate?.simulation_time_ms)
  );
  if (!vehicle) {
    return null;
  }
  return {
    sequence: vehicle.sequence,
    simulationTimeMs: vehicle.simulation_time_ms
  };
}

export function canInterpolateSnapshots(previous, current) {
  const previousVersion = snapshotVersion(previous);
  const currentVersion = snapshotVersion(current);
  if (!previousVersion || !currentVersion) {
    return false;
  }
  return (
    currentVersion.sequence === previousVersion.sequence + 1 &&
    currentVersion.simulationTimeMs > previousVersion.simulationTimeMs
  );
}

export function interpolateAngleRad(previous, current, progress) {
  const alpha = clampUnit(progress);
  const difference = ((current - previous + Math.PI) % TWO_PI + TWO_PI) % TWO_PI - Math.PI;
  return previous + difference * alpha;
}

function interpolatePosition(previous, current, progress) {
  const alpha = clampUnit(progress);
  return {
    x: previous.x + (current.x - previous.x) * alpha,
    y: previous.y + (current.y - previous.y) * alpha,
    z: previous.z + (current.z - previous.z) * alpha
  };
}

function canInterpolateVehicle(previous, current) {
  const elapsedS = (current.simulation_time_ms - previous.simulation_time_ms) / 1000;
  if (elapsedS <= 0) {
    return false;
  }
  const distanceM = Math.hypot(
    current.position.x - previous.position.x,
    current.position.y - previous.position.y,
    current.position.z - previous.position.z
  );
  const speedMps = Math.max(previous.speed_mps, current.speed_mps);
  const maximumContinuousDistanceM = Math.max(2, speedMps * elapsedS * 3 + 1);
  return distanceM <= maximumContinuousDistanceM;
}

export function stabilizeVehicleHeadings(previous, current) {
  const previousById = new Map(previous.map((vehicle) => [vehicle.vehicle_id, vehicle]));
  return current.map((vehicle) => {
    const previousVehicle = previousById.get(vehicle.vehicle_id);
    if (!previousVehicle || !canInterpolateVehicle(previousVehicle, vehicle)) {
      return vehicle;
    }
    const deltaX = vehicle.position.x - previousVehicle.position.x;
    const deltaY = vehicle.position.y - previousVehicle.position.y;
    if (Math.hypot(deltaX, deltaY) <= MIN_HEADING_MOVEMENT_M) {
      return vehicle;
    }
    const usesMergeBodyHeading =
      vehicle.vehicle_id.startsWith("merge_main_") &&
      Math.abs(deltaY) > MIN_HEADING_MOVEMENT_M &&
      Number.isFinite(vehicle.heading_rad);
    return {
      ...vehicle,
      heading_rad: usesMergeBodyHeading
        ? vehicle.heading_rad
        : Math.atan2(deltaY, deltaX)
    };
  });
}

export function interpolateVehicleSnapshots(previous, current, progress) {
  const previousById = new Map(previous.map((vehicle) => [vehicle.vehicle_id, vehicle]));
  return current.map((vehicle) => {
    const previousVehicle = previousById.get(vehicle.vehicle_id);
    if (!previousVehicle || !canInterpolateVehicle(previousVehicle, vehicle)) {
      return vehicle;
    }
    return {
      ...vehicle,
      position: interpolatePosition(previousVehicle.position, vehicle.position, progress),
      heading_rad: interpolateAngleRad(
        previousVehicle.heading_rad,
        vehicle.heading_rad,
        progress
      )
    };
  });
}

export class VehicleSnapshotPlayback {
  constructor({bufferFrames = DEFAULT_BUFFER_FRAMES} = {}) {
    if (!Number.isInteger(bufferFrames) || bufferFrames < 1) {
      throw new Error("vehicle playback bufferFrames must be a positive integer");
    }
    this.bufferFrames = bufferFrames;
    this.frames = [];
    this.playbackSimulationTimeMs = null;
    this.lastSampleAtMs = null;
    this.wallMsPerSimulationMs = null;
    this.renderedVehicles = [];
  }

  push(vehicles, receivedAtMs) {
    const version = snapshotVersion(vehicles);
    const previousFrame = this.frames.at(-1);
    if (!version || (previousFrame && !canInterpolateSnapshots(previousFrame.vehicles, vehicles))) {
      this.#reset(vehicles, version, receivedAtMs);
      return;
    }

    const caughtUp =
      previousFrame &&
      this.playbackSimulationTimeMs !== null &&
      this.playbackSimulationTimeMs >= previousFrame.simulationTimeMs;
    if (caughtUp) {
      this.frames = [previousFrame];
      this.playbackSimulationTimeMs = null;
      this.lastSampleAtMs = null;
    }

    if (previousFrame) {
      this.#updatePlaybackRate(previousFrame, version, receivedAtMs);
    }
    this.frames.push({
      vehicles,
      sequence: version.sequence,
      simulationTimeMs: version.simulationTimeMs,
      receivedAtMs
    });

    if (
      this.playbackSimulationTimeMs === null &&
      this.frames.length >= this.bufferFrames + 1
    ) {
      this.playbackSimulationTimeMs = this.frames[0].simulationTimeMs;
      this.lastSampleAtMs = receivedAtMs;
      this.renderedVehicles = this.frames[0].vehicles;
    } else if (this.playbackSimulationTimeMs === null && this.frames.length === 1) {
      this.renderedVehicles = vehicles;
    }
  }

  sample(timestampMs) {
    if (
      this.playbackSimulationTimeMs === null ||
      this.lastSampleAtMs === null ||
      this.wallMsPerSimulationMs === null
    ) {
      return this.renderedVehicles;
    }

    const elapsedWallMs = Math.max(0, timestampMs - this.lastSampleAtMs);
    const latestSimulationTimeMs = this.frames.at(-1).simulationTimeMs;
    this.playbackSimulationTimeMs = Math.min(
      latestSimulationTimeMs,
      this.playbackSimulationTimeMs + elapsedWallMs / this.wallMsPerSimulationMs
    );
    this.lastSampleAtMs = timestampMs;
    while (
      this.frames.length > 2 &&
      this.frames[1].simulationTimeMs <= this.playbackSimulationTimeMs
    ) {
      this.frames.shift();
    }

    const previousFrame = this.frames[0];
    const nextFrame = this.frames.find(
      (frame) => frame.simulationTimeMs > this.playbackSimulationTimeMs
    );
    if (!nextFrame) {
      this.renderedVehicles = this.frames.at(-1).vehicles;
      return this.renderedVehicles;
    }
    const progress =
      (this.playbackSimulationTimeMs - previousFrame.simulationTimeMs) /
      (nextFrame.simulationTimeMs - previousFrame.simulationTimeMs);
    this.renderedVehicles = interpolateVehicleSnapshots(
      previousFrame.vehicles,
      nextFrame.vehicles,
      progress
    );
    return this.renderedVehicles;
  }

  isActive() {
    const latestFrame = this.frames.at(-1);
    return (
      latestFrame !== undefined &&
      this.playbackSimulationTimeMs !== null &&
      this.playbackSimulationTimeMs < latestFrame.simulationTimeMs
    );
  }

  #reset(vehicles, version, receivedAtMs) {
    this.frames = version
      ? [
          {
            vehicles,
            sequence: version.sequence,
            simulationTimeMs: version.simulationTimeMs,
            receivedAtMs
          }
        ]
      : [];
    this.playbackSimulationTimeMs = null;
    this.lastSampleAtMs = null;
    this.wallMsPerSimulationMs = null;
    this.renderedVehicles = vehicles;
  }

  #updatePlaybackRate(previousFrame, currentVersion, receivedAtMs) {
    const simulationIntervalMs = currentVersion.simulationTimeMs - previousFrame.simulationTimeMs;
    const receivedIntervalMs = receivedAtMs - previousFrame.receivedAtMs;
    if (receivedIntervalMs <= 0) {
      return;
    }
    const expectedIntervalMs =
      simulationIntervalMs * (this.wallMsPerSimulationMs ?? receivedIntervalMs / simulationIntervalMs);
    if (receivedIntervalMs > expectedIntervalMs * MAX_RATE_SAMPLE_MULTIPLIER) {
      return;
    }
    const observedRate = receivedIntervalMs / simulationIntervalMs;
    this.wallMsPerSimulationMs =
      this.wallMsPerSimulationMs === null
        ? observedRate
        : this.wallMsPerSimulationMs * (1 - PLAYBACK_RATE_SMOOTHING) +
          observedRate * PLAYBACK_RATE_SMOOTHING;
  }
}
