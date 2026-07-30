# Web 3D model assets

This directory contains small, reviewable model inputs for the TrafficVerse Web map prototype.
They are loaded by the MapLibre/deck.gl vehicle visualization.

## `box.glb`

- Purpose: deck.gl `ScenegraphLayer` loading, transform, lighting, and picking smoke tests.
- Format: Binary glTF 2.0 (GLB).
- Size: 1664 bytes.
- SHA-256: `ed52f7192b8311d700ac0ce80644e3852cd01537e4d62241b9acba023da3d54e`.
- Source: [Khronos glTF Sample Assets, Box](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/Box).
- Direct source file: `Models/Box/glTF-Binary/Box.glb` at the upstream `main` branch.
- License: CC BY 4.0 International; original asset credit is Cesium.

The model is a unit box and is intentionally unsuitable as a production vehicle model. Replace it
only through a versioned model catalog that records source, license, axes, scale, checksum, and the
reproducible export command.
