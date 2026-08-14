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
    lane_prefix: str = "road_fwd",
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
        lane_id=f"{lane_prefix}_{lane_index}",
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


def _occasional_accident_preview() -> tuple[Vehicle, ...]:
    # Display the deterministic final key frame from the scripted SUMO run. These coordinates
    # include the native network offset and keep the two impacts visually distinct.
    vehicles = [
        _preview_vehicle(
            "accident_parked_L0_0",
            "L0",
            6,
            595.989,
            0,
            0.0,
            y_m=158.574,
            heading_rad=0.2812,
            action="PARKED",
            lane_prefix="road_curve",
        ),
        _preview_vehicle(
            "accident_victim_L0_0",
            "L0",
            0,
            569.381,
            1,
            0.0,
            y_m=154.532,
            heading_rad=0.2812,
            action="COLLISION",
            lane_prefix="road_curve",
        ),
        _preview_vehicle(
            "accident_actor_L0_0",
            "L0",
            1,
            567.508,
            0,
            0.0,
            y_m=152.17,
            heading_rad=0.4274,
            action="COLLISION",
            lane_prefix="road_curve",
        ),
        _preview_vehicle(
            "accident_follow_L0_0",
            "L0",
            2,
            562.999,
            1,
            0.0,
            y_m=152.689,
            heading_rad=0.3213,
            action="COLLISION",
            lane_prefix="road_curve",
        ),
        _preview_vehicle(
            "accident_follow_L1_0",
            "L1",
            3,
            554.199,
            1,
            0.0,
            y_m=148.559,
            heading_rad=0.5404,
            action="EMERGENCY_BRAKE",
            lane_prefix="road_curve",
        ),
        _preview_vehicle(
            "accident_follow_L3_0",
            "L3",
            4,
            545.202,
            1,
            0.0,
            y_m=143.161,
            heading_rad=0.5404,
            action="BRAKE",
            lane_prefix="road_curve",
        ),
        _preview_vehicle(
            "accident_follow_L5_0",
            "L5",
            5,
            543.597,
            0,
            12.0,
            y_m=106.842,
            heading_rad=-0.5404,
            action="CHANGE_LANE",
            lane_prefix="right_exit",
        ),
    ]
    straight_specs = (
        ("L0", 0, 538.0, 138.84, 0.5404, 1),
        ("L1", 0, 531.0, 134.64, 0.5404, 1),
        ("L3", 0, 524.0, 130.44, 0.5404, 1),
        ("L0", 1, 556.0, 145.56, 0.5404, 0),
        ("L1", 1, 549.0, 141.36, 0.5404, 0),
        ("L3", 1, 542.0, 137.16, 0.5404, 0),
        ("L3", 2, 535.0, 132.96, 0.5404, 0),
    )
    for sequence, (level, index, x_m, y_m, heading_rad, lane_index) in enumerate(
        straight_specs,
        start=7,
    ):
        vehicles.append(
            _preview_vehicle(
                f"accident_background_{level}_{index}",
                level,
                sequence,
                x_m,
                lane_index,
                0.0,
                y_m=y_m,
                heading_rad=heading_rad,
                action="BRAKE",
                lane_prefix="road_curve",
            )
        )
    right_turn_specs = (
        (570.0, 81.25, -0.8961),
        (590.0, 48.75, -1.0517),
        (615.0, 17.14, -0.8520),
    )
    for index, (x_m, y_m, heading_rad) in enumerate(right_turn_specs):
        vehicles.append(
            _preview_vehicle(
                f"accident_background_L5_{index}",
                "L5",
                14 + index,
                x_m,
                0,
                12.0,
                y_m=y_m,
                heading_rad=heading_rad,
                action="TURN_RIGHT",
                lane_prefix="right_exit",
            )
        )
    return tuple(vehicles)


def _dense_merge_preview(*, l5_only: bool) -> tuple[Vehicle, ...]:
    low_levels = ("L0", "L1", "L2", "L3")
    vehicles: list[Vehicle] = []
    sequence = 0
    main_positions_m = (
        (65.0, 48.0, 31.0, 14.0) if l5_only else (104.0, 86.0, 68.0, 50.0, 32.0, 14.0)
    )
    for lane_index, y_m in enumerate((11.25, 14.75, 18.25)):
        for index, x_m in enumerate(main_positions_m):
            level = "L5" if l5_only else low_levels[(lane_index + index) % len(low_levels)]
            if l5_only:
                speed_mps = 8.0 if lane_index == 0 and index == 2 else 20.0
            else:
                speed_mps = (5.0, 8.5, 12.5)[lane_index] if x_m >= 50.0 else 15.0
            vehicles.append(
                _preview_vehicle(
                    f"merge_preview_main_{level}_{sequence}",
                    level,
                    sequence,
                    x_m,
                    lane_index,
                    speed_mps,
                    y_m=y_m,
                    action=(
                        "YIELD"
                        if l5_only and speed_mps == 8.0
                        else "LANE_CHANGE_LEFT"
                        if not l5_only
                        and ((lane_index == 0 and x_m == 86.0) or (lane_index == 1 and x_m == 68.0))
                        else "BRAKE"
                        if not l5_only and x_m >= 50.0
                        else "CRUISE"
                    ),
                    lane_prefix="main_before",
                )
            )
            sequence += 1
    ramp_points = (
        ((75.0, 1.0), (88.0, 3.0), (100.0, 7.0), (111.0, 13.0))
        if l5_only
        else (
            (10.0, 0.0),
            (25.0, 0.0),
            (40.0, 0.0),
            (55.0, 0.0),
            (70.0, 0.0),
            (83.0, 1.5),
            (95.0, 4.8),
        )
    )
    for index, (x_m, y_m) in enumerate(ramp_points):
        level = "L5" if l5_only else low_levels[index % len(low_levels)]
        vehicles.append(
            _preview_vehicle(
                f"merge_preview_ramp_{level}_{index}",
                level,
                sequence,
                x_m,
                0,
                19.0 if l5_only else (3.2 if x_m >= 80.0 else 14.0),
                y_m=y_m,
                heading_rad=0.0 if x_m <= 70.0 else 0.3948,
                action="MERGE",
                lane_prefix="merge_ramp",
            )
        )
        sequence += 1
    opposing_positions_by_lane_m = (
        ((180.0, 210.0, 240.0, 270.0),) * 3
        if l5_only
        else (
            (
                314.0,
                293.0,
                272.0,
                251.0,
                229.0,
                207.0,
                184.0,
                161.0,
                138.0,
                115.0,
                95.54,
                84.04,
                71.34,
                59.54,
                46.04,
                34.54,
                20.34,
                6.54,
            ),
            (
                312.0,
                291.0,
                269.0,
                247.0,
                226.0,
                204.0,
                181.0,
                159.0,
                136.0,
                117.0,
                96.74,
                84.84,
                72.04,
                58.34,
                47.14,
                32.64,
                21.44,
                5.34,
            ),
            (
                315.5,
                295.0,
                274.0,
                252.0,
                230.0,
                209.0,
                186.0,
                163.0,
                140.0,
                116.0,
                94.34,
                81.64,
                69.44,
                57.54,
                42.94,
                31.54,
                17.04,
                4.34,
            ),
        )
    )
    for lane_index, (y_m, opposing_positions_m) in enumerate(
        zip((28.75, 25.25, 21.75), opposing_positions_by_lane_m, strict=True)
    ):
        for index, x_m in enumerate(opposing_positions_m):
            level = "L5" if l5_only else low_levels[(lane_index + index + 2) % len(low_levels)]
            vehicles.append(
                _preview_vehicle(
                    f"merge_preview_opposing_{level}_{lane_index}_{index}",
                    level,
                    sequence,
                    x_m,
                    lane_index,
                    20.0 if l5_only else 13.4 + index * 0.035 + lane_index * 0.05,
                    y_m=y_m,
                    heading_rad=3.1416,
                    lane_prefix=("opposing_before" if l5_only or index < 10 else "opposing_after"),
                )
            )
            sequence += 1
    return tuple(vehicles)


def scenario_preview_vehicles(preset: TrafficScenarioPreset) -> tuple[Vehicle, ...]:
    """Return a deterministic, non-authoritative key frame for a scene detail preview."""
    if preset.scenario_id == "mixed-automation-obstacle":
        return _obstacle_preview()
    if preset.scenario_id == "mixed-automation-cutin":
        return _cutin_preview()
    if preset.scenario_id == "mixed-automation-emergency-yield":
        return _emergency_preview()
    if preset.scenario_id == "mixed-automation-occasional-accident":
        return _occasional_accident_preview()
    if preset.scenario_id == "mixed-automation-low-level-merge":
        return _dense_merge_preview(l5_only=False)
    if preset.scenario_id == "mixed-automation-l5-merge":
        return _dense_merge_preview(l5_only=True)
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
    TrafficScenarioPreset(
        scenario_id="mixed-automation-occasional-accident",
        name="偶发事故",
        incident=(
            "普通城市或园区道路，无雨雪、雾、积水和外界复杂干扰。道路为单向双车道，"
            "前方经过轻微弯道。右侧车道前方停靠一辆L0车辆，后方L0为避让停车车辆向左"
            "变道，却在横跨车道线时与左侧正常行驶的L0车辆发生侧碰；两车随即停止，"
            "车身分别占据左右车道并封死全部通行空间。"
        ),
        behavior_summary=(
            "两次碰撞共涉及3辆行驶中的L0。首次碰撞发生时，后方车辆仍继续前进；第三辆L0"
            "与前方事故车组的初始距离缩短至原来的约1/3，反应过晚并追尾，碰撞后立即"
            "停车。两次碰撞间隔同步缩短至原来的约1/3。第三辆L0后方各车的连续初始间距"
            "保持为原布局的40%；L1先紧急制动，L3检测到L1真实急刹后缓慢制动，最终均"
            "留出约一个车长且未发生碰撞。L5从继续前移30米后的上方车道出发，先静止3秒，"
            "随后以翻倍后的恒定速度接近路口，首次碰撞发生后向下方车道变道并右转绕行。"
            "双车道另加入10辆保持安全间距的背景车：L0、L1、L3直行并在两条车道交替"
            "形成停车队列，3辆新增L5均从右转支路绕行；原有7辆场景车的状态和时序保持不变。"
        ),
        map_id="mixed-automation-occasional-accident",
        duration_s=60,
        automation_counts=(("L0", 6), ("L1", 3), ("L3", 4), ("L5", 4)),
        scene_type="偶发事故",
        level_behaviors=(
            (
                "L0",
                "停车车辆诱发前车变道碰撞；后方L0发现过晚并追尾，新增L0保持直行并正常制动。",
            ),
            ("L1", "原有L1先轻微减速再紧急制动，新增L1保持直行并正常制动。"),
            ("L2", "本场景未配置该等级车辆。"),
            ("L3", "原有L3检测到L1急刹后缓慢制动，新增L3保持直行并正常制动。"),
            ("L4", "本场景未配置该等级车辆。"),
            (
                "L5",
                "原有L5维持既定变道时序，另3辆L5保持安全间距并以12m/s恒速右转绕行。",
            ),
        ),
    ),
    TrafficScenarioPreset(
        scenario_id="mixed-automation-low-level-merge",
        name="低智驾等级会车（L0-L3）",
        incident=(
            "双向城市快速路的正向道路包含3条主车道，右侧另有1条汇入车道；对向道路"
            "包含3条行驶车道。L0-L3混合车流从主路、支路和对向道路连续进入。"
        ),
        behavior_summary=(
            "第0秒时画面最上方3条对向车道已经由随机错位、不同初速度的车流铺满整段"
            "道路；后续车辆从地图最右端按1～3辆的非固定批次持续进入，不再每次同步"
            "刷新三条车道。下方3条"
            "主路和支路需求保持不变。10～22秒支路汇入使D1首先减速，扰动随后向D2、"
            "D3扩大，22秒后主路逐步恢复。"
        ),
        map_id="mixed-automation-low-level-merge",
        duration_s=30,
        automation_counts=(("L0", 40), ("L1", 41), ("L2", 39), ("L3", 35)),
        scene_type="低智驾被动汇流",
        level_behaviors=(
            ("L0", "依赖基础跟车和临近冲突反应，只在汇入口附近减速或被动变道。"),
            ("L1", "具备基础辅助能力，但不会远距离协同规划，仍受D1汇流扰动影响。"),
            ("L2", "能够较稳定地纵向跟车，但对相邻车道插入仍表现出滞后减速。"),
            ("L3", "保持基本稳定跟车，不参与车队协同，受到的外溢扰动相对较小。"),
            ("L4", "本场景未配置该等级车辆。"),
            ("L5", "本场景未配置该等级车辆。"),
        ),
    ),
    TrafficScenarioPreset(
        scenario_id="mixed-automation-l5-merge",
        name="L5会车",
        incident=(
            "使用与低智驾场景完全相同的正向3车道、单汇入车道和对向3车道路网，"
            "全部车辆均为具备协同汇流能力的L5。"
        ),
        behavior_summary=(
            "主路车辆提前识别汇入需求，选择车辆短时协调降速并主动形成可用车隙。"
            "汇入车辆有序插入后恢复巡航，中间与最外侧车道速度保持稳定，整体通过率明显提高。"
        ),
        map_id="mixed-automation-l5-merge",
        duration_s=20,
        automation_counts=(("L5", 70),),
        scene_type="L5协同密集汇入",
        level_behaviors=(
            ("L0", "本场景未配置该等级车辆。"),
            ("L1", "本场景未配置该等级车辆。"),
            ("L2", "本场景未配置该等级车辆。"),
            ("L3", "本场景未配置该等级车辆。"),
            ("L4", "本场景未配置该等级车辆。"),
            ("L5", "通过车车协同提前预留汇入间隙，减少制动波并保持三条主车道稳定通行。"),
        ),
    ),
)
