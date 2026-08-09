"""Traffic-scene presets exposed by the workspace catalog."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrafficScenarioPreset:
    """UI-owned preset that binds a documented scene to a runnable SUMO package."""

    scenario_id: str
    name: str
    incident: str
    behavior_summary: str
    map_id: str
    duration_s: int
    automation_counts: tuple[tuple[str, int], ...]

    @property
    def description(self) -> str:
        return f"{self.incident}\n{self.behavior_summary}"


TRAFFIC_SCENARIO_PRESETS = (
    TrafficScenarioPreset(
        scenario_id="mixed-automation-obstacle",
        name="直道后出现障碍物",
        incident="直道路段发生事故，两条车道被障碍物占用，混合智驾车队需要制动或绕行。",
        behavior_summary=(
            "L0 可能因反应过晚发生碰撞；L1-L3 依次更早、更平稳地制动；"
            "L4 自动变道；L5 利用车路协同信息提前规划绕行。"
        ),
        map_id="mixed-automation-obstacle",
        duration_s=90,
        automation_counts=(("L0", 12), ("L1", 12), ("L2", 12), ("L3", 12), ("L4", 12), ("L5", 12)),
    ),
    TrafficScenarioPreset(
        scenario_id="mixed-automation-cutin",
        name="高速公路车辆突然加塞",
        incident="密集交通中多辆相邻车道车辆连续切入主车道，检验不同智驾等级的应对差异。",
        behavior_summary=(
            "L0-L1 依赖驾驶员反应或预警；L2-L3 提前减速并保持车道；"
            "L4 自动选择减速或换道；L5 根据车车通信意图提前形成安全间隙。"
        ),
        map_id="mixed-automation-cutin",
        duration_s=60,
        automation_counts=(
            ("L0", 16),
            ("L1", 16),
            ("L2", 16),
            ("L3", 16),
            ("L4", 16),
            ("L5", 16),
        ),
    ),
    TrafficScenarioPreset(
        scenario_id="mixed-automation-emergency-yield",
        name="救护车接近与应急让行",
        incident="救护车从混合车队后方高速接近，车辆需要及时形成应急通道并在通过后恢复。",
        behavior_summary=(
            "L0-L2 的发现和让行逐级改善；L3-L4 主动识别并形成通道；"
            "L5 通过车路协同提前获知救护车路线并率先组织让行。"
        ),
        map_id="mixed-automation-emergency-yield",
        duration_s=60,
        automation_counts=(
            ("L0", 12),
            ("L1", 12),
            ("L2", 12),
            ("L3", 12),
            ("L4", 12),
            ("L5", 13),
        ),
    ),
)
