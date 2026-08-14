"""Shared deterministic motion profiles for merge demonstrations."""

from __future__ import annotations

import re

_MERGE_VEHICLE_PATTERN = re.compile(
    r"^merge_(main|ramp|opposing)_L([0-5])(?:_lane([0-2]))?\.(\d+)$"
)
_L5_ZIPPER_SPEEDS_MPS = (15.8, 15.9, 16.0, 16.1, 16.2)
_L5_FREE_FLOW_SPEEDS_MPS = (15.2, 15.45, 15.7, 15.95, 16.2, 16.45, 16.7)
_STREAM_OFFSETS = {"main": 0, "ramp": 2, "opposing": 4}
# Keep selected followers aligned with slower leaders whose rendered body is longer than SUMO's.
_L5_VISUAL_FOLLOWER_SPEED_OVERRIDES_MPS = {
    "merge_main_L5_lane1.101": 15.45,
    "merge_main_L4_lane1.104": 15.95,
    "merge_opposing_L5_lane1.101": 15.45,
    "merge_opposing_L5_lane1.103": 15.2,
    "merge_opposing_L5_lane1.104": 15.2,
}


def l5_merge_cruise_speed_mps(vehicle_id: str) -> float:
    """Return a stable per-vehicle speed while keeping zipper streams tightly grouped."""
    speed_override_mps = _L5_VISUAL_FOLLOWER_SPEED_OVERRIDES_MPS.get(vehicle_id)
    if speed_override_mps is not None:
        return speed_override_mps
    match = _MERGE_VEHICLE_PATTERN.match(vehicle_id)
    if match is None:
        raise ValueError(f"unsupported merge vehicle id: {vehicle_id}")
    stream, level_text, lane_text, sequence_text = match.groups()
    lane_index = int(lane_text or 0)
    level = int(level_text)
    sequence = int(sequence_text)
    speed_profile = (
        _L5_ZIPPER_SPEEDS_MPS
        if stream == "ramp" or (stream == "main" and lane_index == 0)
        else _L5_FREE_FLOW_SPEEDS_MPS
    )
    profile_index = (level * 3 + lane_index * 2 + sequence + _STREAM_OFFSETS[stream]) % len(
        speed_profile
    )
    return speed_profile[profile_index]
