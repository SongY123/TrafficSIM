"""Traffic-scene presets exposed by the workspace catalog."""

from dataclasses import dataclass
from uuid import UUID

from ui.models.protocol import Position, Vehicle

_PREVIEW_EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000043")
_FORWARD_LANE_Y_M = (-8.75, -5.25, -1.75)


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
    scene_type: str
    level_behaviors: tuple[tuple[str, str], ...]

    @property
    def description(self) -> str:
        return f"{self.incident}\n{self.behavior_summary}"

    @property
    def vehicle_total(self) -> int:
        return sum(count for _level, count in self.automation_counts)


def _preview_vehicle(
    vehicle_id: str,
    level: str,
    sequence: int,
    x_m: float,
    lane_index: int,
    speed_mps: float,
    *,
    y_m: float | None = None,
    heading_rad: float = 0.0,
    action: str = "KEEP_LANE",
) -> Vehicle:
    return Vehicle(
        experiment_id=_PREVIEW_EXPERIMENT_ID,
        vehicle_id=vehicle_id,
        simulation_time_ms=15_000,
        sequence=sequence,
        position=Position(
            x=x_m,
            y=_FORWARD_LANE_Y_M[lane_index] if y_m is None else y_m,
        ),
        speed_mps=speed_mps,
        acceleration_mps2=0.0,
        heading_rad=heading_rad,
        lane_id=f"road_fwd_{lane_index}",
        target_lane_id=None,
        automation_level=level,
        controller_id="scenario-preview",
        action=action,
        risk_score=0.0,
        route_id="route_fwd",
    )


def _obstacle_preview() -> tuple[Vehicle, ...]:
    levels = ("L2", "L0", "L4", "L1", "L5", "L3") * 2
    vehicles = [
        _preview_vehicle(
            f"target_preview_{level}_{index:02d}",
            level,
            index,
            565.0 + index * 6.4,
            2 if level in {"L4", "L5"} else index % 2,
            5.0 + int(level[1:]) * 2.1,
            action="CHANGE_LANE" if level in {"L4", "L5"} else "BRAKE",
        )
        for index, level in enumerate(levels)
    ]
    vehicles.extend(
        (
            _preview_vehicle("static_obstacle_0", "L0", 90, 650.0, 0, 0.0),
            _preview_vehicle("static_obstacle_1", "L0", 91, 650.0, 1, 0.0),
        )
    )
    return tuple(vehicles)


def _cutin_preview() -> tuple[Vehicle, ...]:
    levels = ("L3", "L0", "L5", "L1", "L4", "L2") * 3
    vehicles = [
        _preview_vehicle(
            f"cutin_target_preview_{level}_{index:02d}",
            level,
            index,
            500.0 + index * 8.5,
            1 + index % 2,
            12.0 + int(level[1:]) * 1.2,
        )
        for index, level in enumerate(levels)
    ]
    vehicles.extend(
        _preview_vehicle(
            f"cutin_actor_preview_{level}_{index:02d}",
            level,
            40 + index,
            530.0 + index * 24.0,
            0,
            14.0 + index,
            y_m=-7.1,
            heading_rad=0.16,
            action="CHANGE_LANE",
        )
        for index, level in enumerate(("L0", "L1", "L2", "L3", "L4", "L5"))
    )
    return tuple(vehicles)


def _emergency_preview() -> tuple[Vehicle, ...]:
    levels = ("L0", "L4", "L1", "L5", "L2", "L3") * 3
    vehicles = [
        _preview_vehicle(
            f"yield_preview_{level}_{index:02d}",
            level,
            index,
            575.0 + index * 9.0,
            0 if level in {"L3", "L5"} else 2 if level == "L4" else 1,
            8.0 + int(level[1:]) * 1.4,
            action="YIELD" if level in {"L3", "L4", "L5"} else "KEEP_LANE",
        )
        for index, level in enumerate(levels)
    ]
    vehicles.append(
        _preview_vehicle("ambulance_L5_0", "L5", 90, 555.0, 1, 27.8, action="EMERGENCY")
    )
    return tuple(vehicles)


def scenario_preview_vehicles(preset: TrafficScenarioPreset) -> tuple[Vehicle, ...]:
    """Return a deterministic, non-authoritative key frame for a scene detail preview."""
    if preset.scenario_id == "mixed-automation-obstacle":
        return _obstacle_preview()
    if preset.scenario_id == "mixed-automation-cutin":
        return _cutin_preview()
    if preset.scenario_id == "mixed-automation-emergency-yield":
        return _emergency_preview()
    return ()


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
        automation_counts=(
            ("L0", 12),
            ("L1", 12),
            ("L2", 12),
            ("L3", 12),
            ("L4", 12),
            ("L5", 12),
        ),
        scene_type="障碍物应急制动",
        level_behaviors=(
            ("L0", "接近障碍物后才开始弱制动，碰撞风险最高。"),
            ("L1", "告警后紧急制动，反应较晚，仍可能发生追尾。"),
            ("L2", "纵向辅助分级制动，减小冲击并降低碰撞数量。"),
            ("L3", "提前感知障碍物，以更平稳的减速度停车。"),
            ("L4", "自主判断安全间隙，优先变道绕过障碍物。"),
            ("L5", "接收路侧障碍信息，提前规划车道与速度。"),
        ),
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
        scene_type="高密度连续加塞",
        level_behaviors=(
            ("L0", "依赖驾驶员临场反应，频繁急刹且碰撞数量较多。"),
            ("L1", "提供危险预警并辅助制动，但应对连续加塞有限。"),
            ("L2", "持续控制纵向间距，降低单次加塞的冲突程度。"),
            ("L3", "识别相邻车辆意图，提前减速形成安全间隙。"),
            ("L4", "自动选择减速或换道，保持更高的通行效率。"),
            ("L5", "利用车车意图信息提前调整间隙与目标车道。"),
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
        scene_type="应急车辆协同让行",
        level_behaviors=(
            ("L0", "救护车贴近后才观察到并执行较晚的人工让行。"),
            ("L1", "通过后方接近预警提醒驾驶员准备变道。"),
            ("L2", "辅助保持安全间距，并在可用间隙内完成让行。"),
            ("L3", "主动识别应急车辆，较早选择相邻车道。"),
            ("L4", "自动规划让行轨迹，救护车通过后恢复行驶。"),
            ("L5", "通过车路协同提前获知路线并率先形成通道。"),
        ),
    ),
)
