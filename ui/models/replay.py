"""Presentation-only models and sample data for the replay prototype."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplayMetric:
    """One aggregate result displayed in the replay summary."""

    label: str
    value: str
    unit: str
    tone: str = "default"


@dataclass(frozen=True, slots=True)
class ReplayTrend:
    """One normalized trend series rendered by the desktop client."""

    title: str
    values: tuple[float, ...]
    color_index: int


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    """UI-facing replay record used until the history API is connected."""

    record_id: str
    occurred_at: str
    map_name: str
    scenario_name: str
    started_at: str
    ended_at: str
    duration: str
    status: str
    metrics: tuple[ReplayMetric, ...]
    trends: tuple[ReplayTrend, ...]


def _record(
    *,
    record_id: str,
    occurred_at: str,
    started_at: str,
    scenario_name: str,
    vehicle_total: int,
    completed_total: int,
    average_speed_kmh: float,
    average_travel_time_min: float,
    average_wait_time_s: float,
    average_queue_length_veh: float,
    maximum_queue_length_veh: int,
) -> ReplayRecord:
    return ReplayRecord(
        record_id=record_id,
        occurred_at=occurred_at,
        map_name="Town04",
        scenario_name=scenario_name,
        started_at=started_at,
        ended_at=occurred_at,
        duration="00:40:00",
        status="正常结束",
        metrics=(
            ReplayMetric("车辆总数", str(vehicle_total), "veh"),
            ReplayMetric("完成行程车辆数", str(completed_total), "veh"),
            ReplayMetric("平均速度", f"{average_speed_kmh:.1f}", "km/h", "primary"),
            ReplayMetric("平均行程时间", f"{average_travel_time_min:.1f}", "min"),
            ReplayMetric("平均等待时间", f"{average_wait_time_s:.1f}", "s"),
            ReplayMetric("平均排队长度", f"{average_queue_length_veh:.1f}", "veh"),
            ReplayMetric("最大排队长度", str(maximum_queue_length_veh), "veh", "warning"),
        ),
        trends=(
            ReplayTrend(
                "车辆数量变化",
                (0.20, 0.31, 0.46, 0.61, 0.70, 0.78, 0.86, 0.91, 0.84, 0.72),
                0,
            ),
            ReplayTrend(
                "平均速度变化",
                (0.45, 0.51, 0.61, 0.70, 0.66, 0.58, 0.62, 0.75, 0.80, 0.80),
                1,
            ),
            ReplayTrend(
                "排队车辆数量变化",
                (0.12, 0.20, 0.34, 0.51, 0.62, 0.70, 0.72, 0.68, 0.75, 0.88),
                2,
            ),
            ReplayTrend(
                "平均等待时间变化",
                (0.71, 0.67, 0.58, 0.46, 0.39, 0.42, 0.54, 0.56, 0.45, 0.43, 0.52),
                3,
            ),
        ),
    )


MOCK_REPLAY_RECORDS: tuple[ReplayRecord, ...] = (
    _record(
        record_id="replay-20260722-220010",
        occurred_at="2026-07-22 22:00:10",
        started_at="2026-07-22 21:20:10",
        scenario_name="高速公路_10km_仿真",
        vehicle_total=2457,
        completed_total=2318,
        average_speed_kmh=68.5,
        average_travel_time_min=14.8,
        average_wait_time_s=36.2,
        average_queue_length_veh=8.6,
        maximum_queue_length_veh=24,
    ),
    _record(
        record_id="replay-20260722-213005",
        occurred_at="2026-07-22 21:30:05",
        started_at="2026-07-22 20:50:05",
        scenario_name="晚高峰匝道汇流",
        vehicle_total=2216,
        completed_total=2104,
        average_speed_kmh=64.2,
        average_travel_time_min=15.6,
        average_wait_time_s=41.8,
        average_queue_length_veh=10.1,
        maximum_queue_length_veh=29,
    ),
    _record(
        record_id="replay-20260722-201545",
        occurred_at="2026-07-22 20:15:45",
        started_at="2026-07-22 19:35:45",
        scenario_name="自动驾驶混合交通",
        vehicle_total=1982,
        completed_total=1906,
        average_speed_kmh=72.1,
        average_travel_time_min=13.2,
        average_wait_time_s=28.6,
        average_queue_length_veh=6.4,
        maximum_queue_length_veh=18,
    ),
    _record(
        record_id="replay-20260722-190000",
        occurred_at="2026-07-22 19:00:00",
        started_at="2026-07-22 18:20:00",
        scenario_name="主线通行能力测试",
        vehicle_total=2640,
        completed_total=2478,
        average_speed_kmh=61.7,
        average_travel_time_min=16.4,
        average_wait_time_s=45.3,
        average_queue_length_veh=11.7,
        maximum_queue_length_veh=32,
    ),
    _record(
        record_id="replay-20260722-184512",
        occurred_at="2026-07-22 18:45:12",
        started_at="2026-07-22 18:05:12",
        scenario_name="常规流量基线",
        vehicle_total=1768,
        completed_total=1702,
        average_speed_kmh=75.4,
        average_travel_time_min=12.5,
        average_wait_time_s=24.9,
        average_queue_length_veh=5.8,
        maximum_queue_length_veh=16,
    ),
)
