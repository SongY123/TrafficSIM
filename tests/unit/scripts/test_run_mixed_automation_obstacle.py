from __future__ import annotations

from scripts.dev.run_mixed_automation_obstacle import _collision_counts_by_level


def test_collision_counts_group_unique_target_vehicles_by_level() -> None:
    counts = _collision_counts_by_level(
        {
            "target_L0_000",
            "target_L0_019",
            "target_L5_015",
            "obstacle_right_0",
            "opposing_L2_000",
        }
    )

    assert counts == {"0": 2, "1": 0, "2": 0, "3": 0, "4": 0, "5": 1}
