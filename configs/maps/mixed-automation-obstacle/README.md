# Bidirectional mixed-automation obstacle scenario

This package models a straight bidirectional road with three lanes in each
direction. Forward traffic uses `road_fwd`; opposing traffic uses `road_rev`.
The forward direction's right lanes 0 and 1 are blocked by two red trucks
already positioned at 650 m when the simulation starts. Lane 2 remains open as
the bypass lane.

The generated route file contains 24 forward and 36 opposing vehicles. Event
vehicles keep the positions required by the obstacle demonstration. The open
forward lane interleaves L1-L5 background vehicles, while every opposing lane
repeats a mixed L0-L5 sequence instead of forming large level-specific bands.
Colors identify automation levels. Each vehicle receives a deterministic
normally distributed sample around the supplied Krauss parameters, so vehicles
of the same level are not identical. The generator seed is recorded in the XML
comment.

Opening the `.sumocfg` directly shows the two physical blockers and SUMO's
native response. For the level-specific demonstration, run the TraCI
controller from the repository root:

```bash
open -a XQuartz
uv run python scripts/dev/run_mixed_automation_obstacle.py --delay-ms 200
```

The controller behavior is:

- L0 blocked vehicle: late detection and weak braking without an escape lane;
  selected vehicles cannot stop in time, and collisions are frozen/highlighted
  for observation.
- L1-L3 blocked vehicles: progressively earlier braking while staying in
  their blocked lane. A vehicle that has successfully stopped waits briefly,
  then gradually merges into lane 2 and leaves the blocked area.
- L4-L5 blocked vehicles: controlled change to the free lane 2.
- Vehicles already in lane 2 and all opposing vehicles continue normally.

At the end of a controlled run, the JSON summary includes
`collision_counts_by_level`. It counts unique target vehicles that collided,
so a frozen vehicle is not counted again on every later simulation step.

Regenerate the route asset after changing vehicle counts or the sampling model:

```bash
uv run python scripts/dev/generate_mixed_automation_obstacle_routes.py
```

Use `--no-l0-crash` to restore safe native L0 following. Use
`--delay-ms 500` or `--delay-ms 1000` when you need a slower GUI. The
configuration's default GUI delay is 500 ms. The `--obstacle-time-s` option is
kept for compatibility, but the default is now `0`, because the blockers are
present from the beginning.

Regenerate the network after changing the node, edge, or type sources:

```bash
netconvert \
  --node-files mixed-automation-obstacle.nod.xml \
  --edge-files mixed-automation-obstacle.edg.xml \
  --type-files mixed-automation-obstacle.typ.xml \
  --output-file mixed-automation-obstacle.net.xml
```
