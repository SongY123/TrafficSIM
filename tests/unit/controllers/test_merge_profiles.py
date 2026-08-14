from __future__ import annotations

import pytest

from trafficverse.controllers.merge_profiles import l5_merge_cruise_speed_mps


@pytest.mark.parametrize(
    ("follower_id", "leader_id"),
    (
        ("merge_main_L5_lane1.101", "merge_main_L3_lane1.102"),
        ("merge_main_L4_lane1.104", "merge_main_L5_lane1.105"),
        ("merge_opposing_L5_lane1.101", "merge_opposing_L4_lane1.102"),
        ("merge_opposing_L5_lane1.103", "merge_opposing_L5_lane1.104"),
        ("merge_opposing_L5_lane1.104", "merge_opposing_L5_lane1.105"),
    ),
)
def test_l5_merge_visual_follower_matches_leader_speed(
    follower_id: str,
    leader_id: str,
) -> None:
    assert l5_merge_cruise_speed_mps(follower_id) == pytest.approx(
        l5_merge_cruise_speed_mps(leader_id)
    )
